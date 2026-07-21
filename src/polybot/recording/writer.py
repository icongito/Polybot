"""Append-only NDJSON(.gz) capture writer, one file per asset per interval.

Subscribes to the event bus with a lossless queue (the recorder must never
drop an event) and drains it into per-market files named
``<capture_dir>/<asset>/<slug>.ndjson.gz``. Ticks are not market-scoped by
themselves, so the writer asks a resolver for the set of currently-open
market slugs for a tick's asset and fans the tick into all of them — this
keeps each interval's capture file self-contained for replay while the
mapping logic itself lives in :class:`~polybot.pricing.state.PriceStateTracker`
(the single source of truth for "which markets are open"), not here.
"""

from __future__ import annotations

import asyncio
import gzip
import logging
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any, cast

from polybot.bus import EventBus, Subscription
from polybot.models.core import (
    Asset,
    BookSnapshot,
    Fill,
    MarketInfo,
    MarketResult,
    OpeningPrice,
    OrderRecord,
    Signal,
    Tick,
)
from polybot.recording.schema import CaptureEnvelope, EventTag

logger = logging.getLogger(__name__)

# asset -> open market slugs; token_id -> (slug, asset)
OpenSlugsResolver = Callable[[Asset], list[str]]
TokenResolver = Callable[[str], tuple[str, Asset] | None]


def capture_path(capture_dir: str, asset: str, slug: str, *, compress: bool) -> Path:
    ext = "ndjson.gz" if compress else "ndjson"
    return Path(capture_dir) / asset / f"{slug}.{ext}"


class _MarketFile:
    def __init__(self, path: Path, compress: bool) -> None:
        self.path = path
        self.compress = compress
        self.events = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        # gzip.GzipFile and a plain buffered file object aren't unified under
        # IO[bytes] in typeshed, though both implement write/flush/close.
        self._handle: IO[bytes] = cast(
            "IO[bytes]", gzip.open(path, "ab") if compress else open(path, "ab")
        )

    def write(self, envelope: CaptureEnvelope) -> None:
        line = envelope.model_dump_json().encode("utf-8") + b"\n"
        self._handle.write(line)
        self.events += 1

    def close(self) -> None:
        self._handle.flush()
        self._handle.close()


class CaptureWriter:
    def __init__(
        self,
        bus: EventBus,
        capture_dir: str,
        *,
        resolve_open_slugs: OpenSlugsResolver,
        resolve_token: TokenResolver,
        compress: bool = True,
    ) -> None:
        self.bus = bus
        self.capture_dir = capture_dir
        self.compress = compress
        self._resolve_open_slugs = resolve_open_slugs
        self._resolve_token = resolve_token
        self._sub: Subscription | None = None
        self._task: asyncio.Task[None] | None = None
        self._files: dict[str, _MarketFile] = {}

    def _file_for(self, asset: str, slug: str) -> _MarketFile:
        file = self._files.get(slug)
        if file is None:
            path = capture_path(self.capture_dir, asset, slug, compress=self.compress)
            file = _MarketFile(path, self.compress)
            self._files[slug] = file
        return file

    def _record(
        self, tag: EventTag, asset: str, slug: str, recv_ns: int, data: dict[str, Any]
    ) -> None:
        envelope = CaptureEnvelope(t=tag, recv_ns=recv_ns, data=data)
        self._file_for(asset, slug).write(envelope)

    def on_event(self, event: Any) -> None:
        if isinstance(event, Tick):
            for slug in self._resolve_open_slugs(event.asset):
                self._record(
                    "tick",
                    event.asset.value,
                    slug,
                    event.local_recv_ns,
                    event.model_dump(mode="json"),
                )
            return
        if isinstance(event, BookSnapshot):
            ref = self._resolve_token(event.token_id)
            if ref is not None:
                slug, asset = ref
                self._record(
                    "book", asset.value, slug, event.local_recv_ns, event.model_dump(mode="json")
                )
            return
        if isinstance(event, MarketInfo):
            self._record(
                "market",
                event.asset.value,
                event.slug,
                event.discovered_at_ns,
                event.model_dump(mode="json"),
            )
            return
        if isinstance(event, OpeningPrice):
            self._record(
                "opening",
                event.asset.value,
                event.market_slug,
                event.local_recv_ns,
                event.model_dump(mode="json"),
            )
            return
        if isinstance(event, Signal):
            self._record(
                "signal",
                event.asset.value,
                event.market_slug,
                event.created_ns,
                event.model_dump(mode="json"),
            )
            return
        if isinstance(event, Fill):
            self._record(
                "fill",
                event.asset.value,
                event.market_slug,
                event.local_recv_ns,
                event.model_dump(mode="json"),
            )
            return

    def on_order(self, record: OrderRecord) -> None:
        recv_ns = record.acknowledged_ns or record.submitted_ns or record.intent.created_ns
        self._record(
            "order",
            record.intent.asset.value,
            record.intent.market_slug,
            recv_ns,
            record.model_dump(mode="json"),
        )

    def on_result(self, result: MarketResult) -> None:
        self._record(
            "result",
            result.asset.value,
            result.market_slug,
            result.resolved_at_ns,
            result.model_dump(mode="json"),
        )

    def close_market(self, slug: str) -> tuple[str, int] | None:
        """Flush and close a finished interval's file; returns (path, events)."""
        file = self._files.pop(slug, None)
        if file is None:
            return None
        file.close()
        return str(file.path), file.events

    async def _run(self) -> None:
        assert self._sub is not None
        async for event in self._sub:
            try:
                self.on_event(event)
            except Exception:
                logger.exception("capture writer failed to record event")

    def start(self) -> None:
        if self._task is None:
            self._sub = self.bus.subscribe("capture-writer", lossless=True)
            self._task = asyncio.create_task(self._run(), name="capture-writer")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        for file in self._files.values():
            file.close()
        self._files.clear()
