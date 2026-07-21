"""Polymarket CLOB user-channel websocket (authenticated).

Streams the bot's own order acknowledgements and fills. Used to persist real
fills and to *measure* the actual taker delay (submission -> ack -> fill),
which feeds the execution-delay buffer and the paper fill model.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any

import websockets

from polybot.bus import EventBus
from polybot.feeds.base import WebSocketFeed, parse_json
from polybot.models.core import Asset, FeedSource, Fill, Side

logger = logging.getLogger(__name__)


class ClobUserFeed(WebSocketFeed):
    source = FeedSource.CLOB_USER

    def __init__(
        self,
        bus: EventBus,
        ws_base_url: str,
        api_key: str,
        api_secret: str,
        api_passphrase: str,
        *,
        token_meta: Callable[[str], tuple[str, Asset, Side] | None],
        on_order_ack: Callable[[str, int], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(bus, **kwargs)
        self._ws_base_url = ws_base_url.rstrip("/")
        self._auth = {"apiKey": api_key, "secret": api_secret, "passphrase": api_passphrase}
        self._markets: list[str] = []
        self._token_meta = token_meta
        self._on_order_ack = on_order_ack

    def url(self) -> str:
        return f"{self._ws_base_url}/user"

    def set_markets(self, condition_ids: list[str]) -> None:
        self._markets = condition_ids

    async def on_connect(self, ws: websockets.ClientConnection) -> None:
        await ws.send(json.dumps({"type": "user", "auth": self._auth, "markets": self._markets}))

    def handle_message(self, raw: str | bytes, local_recv_ns: int) -> None:
        message = parse_json(raw)
        events = message if isinstance(message, list) else [message]
        for event in events:
            if not isinstance(event, dict):
                continue
            event_type = event.get("event_type")
            if event_type == "order":
                self._handle_order(event, local_recv_ns)
            elif event_type == "trade":
                self._handle_trade(event, local_recv_ns)

    def _handle_order(self, event: dict[str, Any], local_recv_ns: int) -> None:
        order_id = str(event.get("id", ""))
        if order_id and self._on_order_ack is not None:
            self._on_order_ack(order_id, local_recv_ns)
        logger.info(
            "order update %s status=%s",
            order_id,
            event.get("status"),
            extra={"ctx": {"order_event": event}},
        )

    def _handle_trade(self, event: dict[str, Any], local_recv_ns: int) -> None:
        token_id = str(event.get("asset_id", ""))
        meta = self._token_meta(token_id)
        if meta is None:
            logger.warning("trade for unknown token %s", token_id)
            return
        market_slug, asset, side = meta
        try:
            fill = Fill(
                order_id=str(event.get("taker_order_id") or event.get("id", "")),
                signal_id=str(event.get("taker_order_id") or ""),
                market_slug=market_slug,
                asset=asset,
                side=side,
                token_id=token_id,
                price=float(event.get("price", 0)),
                size=float(event.get("size", 0)),
                fee=float(event.get("fee_rate_bps", 0)) / 10_000 * float(event.get("size", 0)),
                fill_ts=_ms_to_s(event.get("match_time") or event.get("timestamp"), local_recv_ns),
                local_recv_ns=local_recv_ns,
                simulated=False,
            )
        except (TypeError, ValueError):
            logger.exception("malformed trade event")
            return
        self.bus.publish(fill)


def _ms_to_s(value: Any, fallback_ns: int) -> float:
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return fallback_ns / 1e9
    if ts > 1e11:
        ts /= 1000.0
    return ts


def now_ns() -> int:
    return time.time_ns()
