"""Polymarket Gamma API market discovery.

Five-minute Up/Down market slugs are deterministic:
``{asset}-updown-5m-{window_ts}`` where ``window_ts`` is the unix start of the
window, aligned to 300 seconds. One ``GET /events?slug=...`` resolves the
market. A tag-based search fallback covers slug-scheme changes; every result
is validated field by field before use.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from polybot.config import DiscoveryConfig
from polybot.discovery.validation import validate_resolution_rules
from polybot.models.core import Asset, MarketInfo, ResolutionRules

logger = logging.getLogger(__name__)


def window_start_ts(now_s: float, interval_s: int = 300) -> int:
    return int(now_s) - (int(now_s) % interval_s)


def slug_for(asset: Asset, window_ts: int, template: str = "{asset}-updown-5m-{window_ts}") -> str:
    return template.format(asset=asset.value.lower(), window_ts=window_ts)


class GammaDiscovery:
    def __init__(self, config: DiscoveryConfig, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self._client = client or httpx.AsyncClient(
            base_url=config.gamma_base_url, timeout=config.request_timeout_s
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch_market(self, asset: Asset, window_ts: int) -> MarketInfo | None:
        """Fetch and validate the market for one asset/window; None if absent."""
        slug = slug_for(asset, window_ts, self.config.slug_template)
        try:
            response = await self._client.get("/events", params={"slug": slug})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("gamma request failed for %s: %s", slug, exc)
            return None
        payload = response.json()
        events = payload if isinstance(payload, list) else payload.get("data", [])
        if not events:
            logger.info("no gamma event for slug %s", slug)
            return None
        return self._parse_event(events[0], asset, slug, window_ts)

    def _parse_event(
        self, event: dict[str, Any], asset: Asset, slug: str, window_ts: int
    ) -> MarketInfo | None:
        markets = event.get("markets") or []
        if not markets:
            logger.warning("gamma event %s has no markets", slug)
            return None
        market = markets[0]

        token_ids = _parse_json_field(market.get("clobTokenIds"))
        outcomes = [str(o).lower() for o in _parse_json_field(market.get("outcomes"))]
        if len(token_ids) != 2 or len(outcomes) != 2:
            logger.warning("market %s: malformed outcomes/token ids", slug)
            return None
        try:
            up_index = outcomes.index("up")
            down_index = outcomes.index("down")
        except ValueError:
            logger.warning("market %s: outcomes %s are not Up/Down", slug, outcomes)
            return None

        start_ts = float(window_ts)
        end_ts = start_ts + self.config.interval_seconds
        description = str(market.get("description") or event.get("description") or "")
        resolution_source = str(market.get("resolutionSource") or "")
        rules = validate_resolution_rules(description, resolution_source, start_ts, end_ts)
        if not rules.valid:
            logger.warning("market %s failed rule validation: %s", slug, rules.problems)

        tick_size = _first_float(
            market.get("orderPriceMinTickSize"), market.get("tickSize"), default=0.01
        )
        taker_fee_bps = _first_float(market.get("takerBaseFee"), market.get("fee"), default=0.0)

        return MarketInfo(
            slug=slug,
            asset=asset,
            condition_id=str(market.get("conditionId", "")),
            question_id=str(market.get("questionID")) if market.get("questionID") else None,
            up_token_id=str(token_ids[up_index]),
            down_token_id=str(token_ids[down_index]),
            start_ts=start_ts,
            end_ts=end_ts,
            tick_size=tick_size,
            neg_risk=bool(market.get("negRisk", False)),
            taker_fee_bps=taker_fee_bps,
            maker_fee_bps=_first_float(market.get("makerBaseFee"), default=0.0),
            order_book_enabled=bool(market.get("enableOrderBook", True)),
            accepting_orders=bool(market.get("acceptingOrders", True)),
            rules=rules,
            discovered_at_ns=time.time_ns(),
            raw={"event_slug": str(event.get("slug", "")), "market": market},
        )


def build_untradable_market(asset: Asset, slug: str, window_ts: int, reason: str) -> MarketInfo:
    """Placeholder used when discovery fails but recording must continue."""
    rules = ResolutionRules(
        raw_description="",
        resolution_source="",
        references_chainlink=False,
        up_wins_on_equal=False,
        interval_start_ts=float(window_ts),
        interval_end_ts=float(window_ts + 300),
        valid=False,
        problems=(reason,),
    )
    return MarketInfo(
        slug=slug,
        asset=asset,
        condition_id="",
        up_token_id="",
        down_token_id="",
        start_ts=float(window_ts),
        end_ts=float(window_ts + 300),
        tick_size=0.01,
        order_book_enabled=False,
        accepting_orders=False,
        rules=rules,
        discovered_at_ns=time.time_ns(),
    )


def _parse_json_field(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _first_float(*values: Any, default: float = 0.0) -> float:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default
