"""Polymarket Real-Time Data Socket adapter for the Chainlink settlement feed.

RTDS relays the exact Chainlink Data Streams prices Polymarket resolves
against (topic ``crypto_prices_chainlink``), no authentication required. This
is the default settlement-price source; the direct Chainlink Streams adapter
(:mod:`polybot.feeds.chainlink_streams`) can replace it when API credentials
are configured. The parser is deliberately tolerant of payload-shape drift and
drops anything it cannot interpret rather than guessing.
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
from polybot.models.core import Asset, FeedSource, Tick

logger = logging.getLogger(__name__)

TOPIC = "crypto_prices_chainlink"


def rtds_symbol(asset: Asset) -> str:
    return f"{asset.value.lower()}/usd"


class RtdsChainlinkFeed(WebSocketFeed):
    source = FeedSource.RTDS_CHAINLINK

    def __init__(self, bus: EventBus, ws_url: str, assets: list[Asset], **kwargs: Any) -> None:
        super().__init__(bus, **kwargs)
        self._ws_url = ws_url
        self._assets = assets
        self._symbol_to_asset = {rtds_symbol(a): a for a in assets}

    def url(self) -> str:
        return self._ws_url

    async def on_connect(self, ws: websockets.ClientConnection) -> None:
        message = {
            "action": "subscribe",
            "subscriptions": [
                {"topic": TOPIC, "type": "*", "filters": symbol} for symbol in self._symbol_to_asset
            ],
        }
        await ws.send(json.dumps(message))

    async def keepalive(self, ws: websockets.ClientConnection) -> None:
        while True:
            await ws.send(json.dumps({"action": "ping"}))
            await asyncio.sleep(10.0)

    def handle_message(self, raw: str | bytes, local_recv_ns: int) -> None:
        start_ns = time.time_ns()
        try:
            message = parse_json(raw)
        except json.JSONDecodeError:
            return
        for item in message if isinstance(message, list) else [message]:
            if not isinstance(item, dict):
                continue
            if item.get("topic") not in (TOPIC, None):
                continue
            payload = item.get("payload", item)
            entries = payload if isinstance(payload, list) else [payload]
            for entry in entries:
                if isinstance(entry, dict):
                    self._publish_entry(entry, item, local_recv_ns, start_ns)

    def _publish_entry(
        self, entry: dict[str, Any], envelope: dict[str, Any], local_recv_ns: int, start_ns: int
    ) -> None:
        symbol = str(entry.get("symbol") or entry.get("pair") or "").lower()
        asset = self._symbol_to_asset.get(symbol)
        if asset is None:
            return
        value = entry.get("value", entry.get("price"))
        if value is None:
            return
        provider_ts = _to_seconds(
            entry.get("timestamp") or envelope.get("timestamp") or time.time()
        )
        tick = Tick(
            source=self.source,
            asset=asset,
            symbol=symbol,
            provider_ts=provider_ts,
            exchange_ts=provider_ts,
            local_recv_ns=local_recv_ns,
            last=float(value),
            processing_latency_ns=time.time_ns() - start_ns,
        )
        observe_latency(self.source, provider_ts, local_recv_ns)
        self.bus.publish(tick)


def _to_seconds(value: Any) -> float:
    ts = float(value)
    # Millisecond timestamps are ~1e12; second timestamps ~1e9.
    if ts > 1e11:
        ts /= 1000.0
    return ts
