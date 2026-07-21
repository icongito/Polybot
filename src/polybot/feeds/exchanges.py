"""Exchange leading-indicator feeds: Binance spot/futures, Coinbase, OKX.

These prices are never settlement prices — they lead the next Chainlink print
only. Each adapter normalizes to :class:`Tick` with best bid/ask and last
trade where the venue provides them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any

import websockets

from polybot.bus import EventBus
from polybot.feeds.base import WebSocketFeed, observe_latency, parse_json
from polybot.models.core import Asset, FeedSource, Tick

logger = logging.getLogger(__name__)


class BinanceFeed(WebSocketFeed):
    """Binance combined stream: bookTicker + trade per symbol."""

    source = FeedSource.BINANCE_SPOT

    def __init__(
        self,
        bus: EventBus,
        ws_base: str,
        symbols: dict[Asset, str],
        source: FeedSource = FeedSource.BINANCE_SPOT,
        **kwargs: Any,
    ) -> None:
        self.source = source
        super().__init__(bus, **kwargs)
        self._ws_base = ws_base
        self._symbols = {symbol.lower(): asset for asset, symbol in symbols.items()}

    def url(self) -> str:
        streams = "/".join(
            f"{symbol}@{channel}" for symbol in self._symbols for channel in ("bookTicker", "trade")
        )
        return f"{self._ws_base}?streams={streams}"

    async def on_connect(self, ws: websockets.ClientConnection) -> None:
        return None

    def handle_message(self, raw: str | bytes, local_recv_ns: int) -> None:
        start_ns = time.time_ns()
        message = parse_json(raw)
        data = message.get("data") if isinstance(message, dict) else None
        if not isinstance(data, dict):
            return
        symbol = str(data.get("s", "")).lower()
        asset = self._symbols.get(symbol)
        if asset is None:
            return
        event_ts = data.get("E")
        trade_ts = data.get("T")
        provider_ts = (
            float(event_ts) / 1000.0
            if event_ts is not None
            else float(trade_ts) / 1000.0
            if trade_ts is not None
            else local_recv_ns / 1e9
        )
        exchange_ts = float(trade_ts) / 1000.0 if trade_ts is not None else None
        if "b" in data and "a" in data:  # bookTicker
            tick = Tick(
                source=self.source,
                asset=asset,
                symbol=symbol,
                provider_ts=provider_ts,
                exchange_ts=exchange_ts,
                local_recv_ns=local_recv_ns,
                seq=int(data["u"]) if "u" in data else None,
                bid=float(data["b"]),
                ask=float(data["a"]),
                processing_latency_ns=time.time_ns() - start_ns,
            )
        elif "p" in data:  # trade
            tick = Tick(
                source=self.source,
                asset=asset,
                symbol=symbol,
                provider_ts=provider_ts,
                exchange_ts=exchange_ts,
                local_recv_ns=local_recv_ns,
                seq=int(data["t"]) if "t" in data else None,
                last=float(data["p"]),
                processing_latency_ns=time.time_ns() - start_ns,
            )
        else:
            return
        if event_ts is not None or trade_ts is not None:
            observe_latency(self.source, provider_ts, local_recv_ns)
        self.bus.publish(tick)


class CoinbaseFeed(WebSocketFeed):
    source = FeedSource.COINBASE

    def __init__(
        self, bus: EventBus, ws_url: str, symbols: dict[Asset, str], **kwargs: Any
    ) -> None:
        super().__init__(bus, **kwargs)
        self._ws_url = ws_url
        self._symbols = {symbol: asset for asset, symbol in symbols.items()}

    def url(self) -> str:
        return self._ws_url

    async def on_connect(self, ws: websockets.ClientConnection) -> None:
        await ws.send(
            json.dumps(
                {
                    "type": "subscribe",
                    "product_ids": list(self._symbols),
                    "channels": ["ticker", "heartbeat"],
                }
            )
        )

    def handle_message(self, raw: str | bytes, local_recv_ns: int) -> None:
        start_ns = time.time_ns()
        message = parse_json(raw)
        if not isinstance(message, dict) or message.get("type") != "ticker":
            return
        asset = self._symbols.get(str(message.get("product_id", "")))
        if asset is None:
            return
        provider_ts = _parse_iso_ts(message.get("time")) or local_recv_ns / 1e9
        tick = Tick(
            source=self.source,
            asset=asset,
            symbol=str(message.get("product_id")),
            provider_ts=provider_ts,
            exchange_ts=provider_ts,
            local_recv_ns=local_recv_ns,
            seq=int(message["sequence"]) if "sequence" in message else None,
            bid=_opt_float(message.get("best_bid")),
            ask=_opt_float(message.get("best_ask")),
            last=_opt_float(message.get("price")),
            processing_latency_ns=time.time_ns() - start_ns,
        )
        observe_latency(self.source, provider_ts, local_recv_ns)
        self.bus.publish(tick)


class OkxFeed(WebSocketFeed):
    source = FeedSource.OKX

    def __init__(
        self, bus: EventBus, ws_url: str, symbols: dict[Asset, str], **kwargs: Any
    ) -> None:
        super().__init__(bus, **kwargs)
        self._ws_url = ws_url
        self._symbols = {symbol: asset for asset, symbol in symbols.items()}

    def url(self) -> str:
        return self._ws_url

    async def on_connect(self, ws: websockets.ClientConnection) -> None:
        args = [{"channel": "tickers", "instId": inst} for inst in self._symbols]
        await ws.send(json.dumps({"op": "subscribe", "args": args}))

    async def keepalive(self, ws: websockets.ClientConnection) -> None:
        while True:
            await asyncio.sleep(20.0)
            await ws.send("ping")

    def handle_message(self, raw: str | bytes, local_recv_ns: int) -> None:
        if raw in ("pong", b"pong"):
            return
        start_ns = time.time_ns()
        message = parse_json(raw)
        if not isinstance(message, dict):
            return
        for entry in message.get("data") or []:
            asset = self._symbols.get(str(entry.get("instId", "")))
            if asset is None:
                continue
            provider_ts = float(entry.get("ts", 0)) / 1000.0 or local_recv_ns / 1e9
            tick = Tick(
                source=self.source,
                asset=asset,
                symbol=str(entry.get("instId")),
                provider_ts=provider_ts,
                exchange_ts=provider_ts,
                local_recv_ns=local_recv_ns,
                bid=_opt_float(entry.get("bidPx")),
                ask=_opt_float(entry.get("askPx")),
                last=_opt_float(entry.get("last")),
                processing_latency_ns=time.time_ns() - start_ns,
            )
            observe_latency(self.source, provider_ts, local_recv_ns)
            self.bus.publish(tick)


def _opt_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso_ts(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
