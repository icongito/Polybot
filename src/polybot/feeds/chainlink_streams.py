"""Direct Chainlink Data Streams websocket adapter (credential-gated).

Connects to the Data Streams aggregation network websocket with HMAC
authentication and decodes V3 report blobs to benchmark prices. Enabled only
when API credentials are configured; otherwise the RTDS relay is the
settlement source.

Report blob (ABI-encoded static tuple, 32-byte words):
``(feedId, validFromTimestamp, observationsTimestamp, nativeFee, linkFee,
expiresAt, price, bid, ask)`` with prices as int192 scaled by 1e18.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any
from urllib.parse import urlsplit

import websockets

from polybot.bus import EventBus
from polybot.feeds.base import WebSocketFeed, observe_latency, parse_json
from polybot.models.core import Asset, FeedSource, Tick

logger = logging.getLogger(__name__)

WS_PATH = "/api/v1/ws"
PRICE_SCALE = 10**18
_INT192_SIGN_BIT = 1 << 191
_INT192_MODULUS = 1 << 192


def decode_full_report(full_report_hex: str) -> dict[str, Any]:
    """Decode the outer report envelope + V3 report blob."""
    blob = bytes.fromhex(full_report_hex.removeprefix("0x"))
    # Outer envelope: (bytes32[3] reportContext, bytes reportData, ...signatures).
    # reportData is a dynamic bytes field whose offset is at word 3.
    words = [blob[i : i + 32] for i in range(0, len(blob), 32)]
    report_data_offset = int.from_bytes(words[3], "big")
    length = int.from_bytes(blob[report_data_offset : report_data_offset + 32], "big")
    report = blob[report_data_offset + 32 : report_data_offset + 32 + length]
    rwords = [report[i : i + 32] for i in range(0, len(report), 32)]
    if len(rwords) < 7:
        raise ValueError("report blob too short for V3 schema")
    return {
        "feed_id": "0x" + rwords[0].hex(),
        "valid_from_ts": int.from_bytes(rwords[1], "big"),
        "observations_ts": int.from_bytes(rwords[2], "big"),
        "price": _decode_int192(rwords[6]) / PRICE_SCALE,
        "bid": _decode_int192(rwords[7]) / PRICE_SCALE if len(rwords) > 7 else None,
        "ask": _decode_int192(rwords[8]) / PRICE_SCALE if len(rwords) > 8 else None,
    }


def _decode_int192(word: bytes) -> int:
    value = int.from_bytes(word[-24:], "big")
    if value & _INT192_SIGN_BIT:
        value -= _INT192_MODULUS
    return value


def hmac_headers(
    api_key: str, api_secret: str, method: str, full_path: str, body: bytes = b""
) -> dict[str, str]:
    timestamp_ms = int(time.time() * 1000)
    body_hash = hashlib.sha256(body).hexdigest()
    payload = f"{method} {full_path} {body_hash} {api_key} {timestamp_ms}"
    signature = hmac.new(api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return {
        "Authorization": api_key,
        "X-Authorization-Timestamp": str(timestamp_ms),
        "X-Authorization-Signature-SHA256": signature,
    }


class ChainlinkStreamsFeed(WebSocketFeed):
    source = FeedSource.CHAINLINK_STREAMS

    def __init__(
        self,
        bus: EventBus,
        ws_base_url: str,
        api_key: str,
        api_secret: str,
        feed_ids: dict[Asset, str],
        **kwargs: Any,
    ) -> None:
        super().__init__(bus, **kwargs)
        self._ws_base_url = ws_base_url.rstrip("/")
        self._api_key = api_key
        self._api_secret = api_secret
        self._feed_id_to_asset = {fid.lower(): asset for asset, fid in feed_ids.items()}
        self._query = "feedIDs=" + ",".join(feed_ids.values())

    def url(self) -> str:
        return f"{self._ws_base_url}{WS_PATH}?{self._query}"

    async def _run(self) -> None:  # override to inject auth headers per attempt
        import asyncio
        import random

        delay = self._reconnect_initial
        while True:
            full_path = f"{WS_PATH}?{self._query}"
            headers = hmac_headers(self._api_key, self._api_secret, "GET", full_path)
            try:
                async with websockets.connect(
                    self.url(),
                    additional_headers=headers,
                    max_size=2**23,
                    open_timeout=10,
                    ping_interval=15,
                    ping_timeout=10,
                ) as ws:
                    self.health.connected = True
                    delay = self._reconnect_initial
                    logger.info("chainlink streams connected")
                    await self._read_loop(ws)
            except asyncio.CancelledError:
                self.health.connected = False
                raise
            except Exception as exc:
                logger.warning("chainlink streams disconnected: %r", exc)
            self.health.connected = False
            self.health.reconnects += 1
            await asyncio.sleep(delay * (1 + random.random() * 0.25))
            delay = min(delay * 2, self._reconnect_max)

    async def on_connect(self, ws: websockets.ClientConnection) -> None:
        return None

    def handle_message(self, raw: str | bytes, local_recv_ns: int) -> None:
        start_ns = time.time_ns()
        message = parse_json(raw)
        report = message.get("report") if isinstance(message, dict) else None
        if not isinstance(report, dict):
            return
        full_report = report.get("fullReport")
        feed_id = str(report.get("feedID", "")).lower()
        asset = self._feed_id_to_asset.get(feed_id)
        if asset is None or not isinstance(full_report, str):
            return
        try:
            decoded = decode_full_report(full_report)
        except (ValueError, IndexError) as exc:
            logger.warning("failed to decode chainlink report: %r", exc)
            return
        provider_ts = float(report.get("observationsTimestamp") or decoded["observations_ts"])
        tick = Tick(
            source=self.source,
            asset=asset,
            symbol=feed_id,
            provider_ts=provider_ts,
            exchange_ts=provider_ts,
            local_recv_ns=local_recv_ns,
            bid=decoded["bid"],
            ask=decoded["ask"],
            last=decoded["price"],
            processing_latency_ns=time.time_ns() - start_ns,
        )
        observe_latency(self.source, provider_ts, local_recv_ns)
        self.bus.publish(tick)


def ws_host(url: str) -> str:
    return urlsplit(url).netloc
