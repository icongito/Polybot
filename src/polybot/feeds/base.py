"""Reconnecting websocket feed adapter base.

Every adapter:
* reconnects with capped exponential backoff + jitter (bounded retry budget
  per hour — never unlimited hot-looping),
* stamps each message with a nanosecond local receive time,
* tracks health (last message age, connection state, sequence gaps),
* publishes normalized events onto the shared EventBus.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from abc import ABC, abstractmethod
from typing import Any

import websockets

from polybot.bus import EventBus
from polybot.models.core import FeedSource
from polybot.observability import metrics

logger = logging.getLogger(__name__)

MAX_RECONNECTS_PER_HOUR = 120


class FeedHealth:
    def __init__(self, source: FeedSource) -> None:
        self.source = source
        self.connected = False
        self.last_message_ns: int | None = None
        self.messages = 0
        self.reconnects = 0
        self.sequence_gaps = 0

    def touch(self, now_ns: int) -> None:
        self.last_message_ns = now_ns
        self.messages += 1

    def age_seconds(self, now_ns: int | None = None) -> float:
        if self.last_message_ns is None:
            return float("inf")
        return max(0.0, ((now_ns or time.time_ns()) - self.last_message_ns) / 1e9)

    def is_fresh(self, max_age_s: float) -> bool:
        return self.connected and self.age_seconds() <= max_age_s


class WebSocketFeed(ABC):
    source: FeedSource

    def __init__(
        self,
        bus: EventBus,
        *,
        reconnect_initial_delay_s: float = 0.5,
        reconnect_max_delay_s: float = 30.0,
        heartbeat_timeout_s: float = 20.0,
    ) -> None:
        self.bus = bus
        self.health = FeedHealth(self.source)
        self._reconnect_initial = reconnect_initial_delay_s
        self._reconnect_max = reconnect_max_delay_s
        self._heartbeat_timeout = heartbeat_timeout_s
        self._task: asyncio.Task[None] | None = None
        self._reconnect_times: list[float] = []

    # ------------------------------------------------------------ subclass API

    @abstractmethod
    def url(self) -> str: ...

    @abstractmethod
    async def on_connect(self, ws: websockets.ClientConnection) -> None:
        """Send subscription messages after (re)connecting."""

    @abstractmethod
    def handle_message(self, raw: str | bytes, local_recv_ns: int) -> None:
        """Parse one frame and publish normalized events. Must not raise."""

    async def keepalive(self, ws: websockets.ClientConnection) -> None:
        """Optional app-level ping loop; default sends nothing."""
        return None

    # ------------------------------------------------------------------ runner

    async def _run(self) -> None:
        delay = self._reconnect_initial
        while True:
            if not self._reconnect_budget_ok():
                logger.error("%s: reconnect budget exhausted; backing off 5 minutes", self.source)
                await asyncio.sleep(300)
                self._reconnect_times.clear()
            try:
                async with websockets.connect(
                    self.url(),
                    max_size=2**23,
                    open_timeout=10,
                    ping_interval=15,
                    ping_timeout=10,
                ) as ws:
                    self.health.connected = True
                    delay = self._reconnect_initial
                    logger.info("%s connected", self.source)
                    await self.on_connect(ws)
                    keepalive = asyncio.create_task(self.keepalive(ws))
                    try:
                        await self._read_loop(ws)
                    finally:
                        keepalive.cancel()
            except asyncio.CancelledError:
                self.health.connected = False
                raise
            except Exception as exc:
                logger.warning("%s disconnected: %r", self.source, exc)
            self.health.connected = False
            self.health.reconnects += 1
            self._reconnect_times.append(time.monotonic())
            metrics.FEED_RECONNECTS.labels(source=self.source.value).inc()
            await asyncio.sleep(delay * (1 + random.random() * 0.25))
            delay = min(delay * 2, self._reconnect_max)

    async def _read_loop(self, ws: websockets.ClientConnection) -> None:
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=self._heartbeat_timeout)
            local_recv_ns = time.time_ns()
            self.health.touch(local_recv_ns)
            metrics.FEED_MESSAGES.labels(source=self.source.value).inc()
            try:
                self.handle_message(raw, local_recv_ns)
            except Exception:
                logger.exception("%s: failed handling frame", self.source)

    def _reconnect_budget_ok(self) -> bool:
        cutoff = time.monotonic() - 3600
        self._reconnect_times = [t for t in self._reconnect_times if t > cutoff]
        return len(self._reconnect_times) < MAX_RECONNECTS_PER_HOUR

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name=f"feed-{self.source.value}")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


def parse_json(raw: str | bytes) -> Any:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    return json.loads(raw)


def observe_latency(source: FeedSource, provider_ts: float, local_recv_ns: int) -> None:
    latency = local_recv_ns / 1e9 - provider_ts
    if 0 <= latency < 60:
        metrics.FEED_LATENCY.labels(source=source.value).observe(latency)
