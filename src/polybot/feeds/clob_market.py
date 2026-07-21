"""Polymarket CLOB market-channel websocket: maintains L2 books for the
active Up/Down outcome tokens and publishes a BookSnapshot on every change.

The CLOB websocket takes its asset list at subscription time; when the
active markets roll to a new interval the adapter reconnects with the new
token set (``set_tokens``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import websockets

from polybot.bus import EventBus
from polybot.feeds.base import WebSocketFeed, observe_latency, parse_json
from polybot.models.core import Asset, BookLevel, BookSnapshot, FeedSource, Side, Tick

logger = logging.getLogger(__name__)


class TokenRef:
    def __init__(self, token_id: str, asset: Asset, side: Side, tick_size: float) -> None:
        self.token_id = token_id
        self.asset = asset
        self.side = side
        self.tick_size = tick_size
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self.seq = 0


class ClobMarketFeed(WebSocketFeed):
    source = FeedSource.CLOB_MARKET

    def __init__(self, bus: EventBus, ws_base_url: str, **kwargs: Any) -> None:
        super().__init__(bus, **kwargs)
        self._ws_base_url = ws_base_url.rstrip("/")
        self._tokens: dict[str, TokenRef] = {}
        self._ws: websockets.ClientConnection | None = None
        self._background_tasks: set[asyncio.Task[None]] = set()

    def url(self) -> str:
        return f"{self._ws_base_url}/market"

    def set_tokens(self, refs: list[TokenRef]) -> None:
        """Replace the subscribed token set; forces a resubscribe."""
        new_ids = {ref.token_id for ref in refs}
        if new_ids == set(self._tokens):
            return
        self._tokens = {ref.token_id: ref for ref in refs}
        ws = self._ws
        if ws is not None:
            # Close the socket; the runner reconnects and resubscribes with
            # the new token set. The task reference is retained so it can't
            # be garbage-collected mid-close.
            task = asyncio.create_task(ws.close())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def on_connect(self, ws: websockets.ClientConnection) -> None:
        self._ws = ws
        if not self._tokens:
            return
        await ws.send(json.dumps({"type": "market", "assets_ids": list(self._tokens)}))

    def handle_message(self, raw: str | bytes, local_recv_ns: int) -> None:
        start_ns = time.time_ns()
        message = parse_json(raw)
        events = message if isinstance(message, list) else [message]
        for event in events:
            if isinstance(event, dict):
                self._handle_event(event, local_recv_ns, start_ns)

    def _handle_event(self, event: dict[str, Any], local_recv_ns: int, start_ns: int) -> None:
        event_type = event.get("event_type")
        token_id = str(event.get("asset_id", ""))
        ref = self._tokens.get(token_id)
        if ref is None:
            return
        provider_ts = _ms_to_s(event.get("timestamp"), local_recv_ns)

        if event_type == "book":
            ref.bids = _parse_levels(event.get("bids") or event.get("buys") or [])
            ref.asks = _parse_levels(event.get("asks") or event.get("sells") or [])
        elif event_type == "price_change":
            for change in event.get("changes") or []:
                price = float(change.get("price", 0))
                size = float(change.get("size", 0))
                book = ref.bids if str(change.get("side", "")).upper() == "BUY" else ref.asks
                if size <= 0:
                    book.pop(price, None)
                else:
                    book[price] = size
        elif event_type == "tick_size_change":
            new_tick = event.get("new_tick_size")
            if new_tick is not None:
                ref.tick_size = float(new_tick)
            return
        elif event_type == "last_trade_price":
            trade_price = event.get("price")
            if trade_price is not None:
                self.bus.publish(
                    Tick(
                        source=self.source,
                        asset=ref.asset,
                        symbol=f"{ref.asset.value}:{ref.side.value}",
                        provider_ts=provider_ts,
                        local_recv_ns=local_recv_ns,
                        last=float(trade_price),
                        processing_latency_ns=time.time_ns() - start_ns,
                    )
                )
            return
        else:
            return

        ref.seq += 1
        snapshot = BookSnapshot(
            token_id=token_id,
            asset=ref.asset,
            side=ref.side,
            bids=tuple(
                BookLevel(price=p, size=s)
                for p, s in sorted(ref.bids.items(), key=lambda kv: -kv[0])
            ),
            asks=tuple(
                BookLevel(price=p, size=s)
                for p, s in sorted(ref.asks.items(), key=lambda kv: kv[0])
            ),
            provider_ts=provider_ts,
            local_recv_ns=local_recv_ns,
            seq=ref.seq,
            tick_size=ref.tick_size,
        )
        observe_latency(self.source, provider_ts, local_recv_ns)
        self.bus.publish(snapshot)


def _parse_levels(levels: list[Any]) -> dict[float, float]:
    parsed: dict[float, float] = {}
    for level in levels:
        if isinstance(level, dict):
            try:
                price = float(level["price"])
                size = float(level["size"])
            except (KeyError, TypeError, ValueError):
                continue
            if size > 0:
                parsed[price] = size
    return parsed


def _ms_to_s(value: Any, fallback_ns: int) -> float:
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return fallback_ns / 1e9
    if ts > 1e11:
        ts /= 1000.0
    return ts
