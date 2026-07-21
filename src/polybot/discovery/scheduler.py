"""Interval scheduler: rolls 5-minute windows per asset, preloads the next
market, captures/verifies the Chainlink opening print, and emits results.

Opening-price capture rule: the opening value is the first settlement-feed
observation whose provider timestamp is >= the window start. It is *verified*
only when the last observation before the boundary agrees with it within
``open_verify_tolerance`` (relative) and both sit close to the boundary.
Unverified openings disable trading for the interval (recording continues).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from polybot.bus import EventBus
from polybot.clock import Clock
from polybot.config import DiscoveryConfig
from polybot.discovery.gamma import GammaDiscovery, slug_for, window_start_ts
from polybot.models.core import Asset, MarketInfo, MarketResult, OpeningPrice, Side, Tick

logger = logging.getLogger(__name__)

OPEN_VERIFY_TOLERANCE = 0.0005  # relative gap allowed between pre/post boundary prints
OPEN_MAX_DELAY_S = 10.0  # opening print must arrive within this many seconds of start
CLOSE_GRACE_S = 15.0  # keep accepting closing prints this long after the boundary


@dataclass
class IntervalState:
    market: MarketInfo
    opening: OpeningPrice | None = None
    last_before_open: Tick | None = None
    first_at_or_after_open: Tick | None = None
    last_at_or_before_close: Tick | None = None
    closed: bool = False
    extra: dict[str, float] = field(default_factory=dict)


class MarketScheduler:
    """Owns the market lifecycle for every configured asset."""

    def __init__(
        self,
        config: DiscoveryConfig,
        discovery: GammaDiscovery,
        bus: EventBus,
        clock: Clock,
        assets: list[Asset],
        on_result: Callable[[MarketResult, IntervalState], Awaitable[None]] | None = None,
    ) -> None:
        self.config = config
        self.discovery = discovery
        self.bus = bus
        self.clock = clock
        self.assets = assets
        self.on_result = on_result
        self.current: dict[Asset, IntervalState] = {}
        self.next_market: dict[Asset, MarketInfo] = {}
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------ ticks

    def on_settlement_tick(self, tick: Tick) -> None:
        """Feed every settlement-source tick here (called from the bus consumer)."""
        state = self.current.get(tick.asset)
        if state is None:
            return
        market = state.market
        if tick.provider_ts < market.start_ts:
            state.last_before_open = tick
            return
        if state.first_at_or_after_open is None:
            state.first_at_or_after_open = tick
            state.opening = self._build_opening(state, tick)
            self.bus.publish(state.opening)
        if tick.provider_ts <= market.end_ts:
            state.last_at_or_before_close = tick

    def _build_opening(self, state: IntervalState, tick: Tick) -> OpeningPrice:
        market = state.market
        price = tick.price
        verified = True
        notes: list[str] = []
        delay = tick.provider_ts - market.start_ts
        if delay > OPEN_MAX_DELAY_S:
            verified = False
            notes.append(f"opening print arrived {delay:.1f}s after start")
        prev = state.last_before_open
        if prev is not None:
            gap = abs(price - prev.price) / max(price, 1e-12)
            if gap > OPEN_VERIFY_TOLERANCE:
                verified = False
                notes.append(f"pre/post boundary prints diverge by {gap:.5f}")
        else:
            verified = False
            notes.append("no settlement print observed before the boundary")
        return OpeningPrice(
            asset=market.asset,
            market_slug=market.slug,
            price=price,
            source=tick.source,
            provider_ts=tick.provider_ts,
            local_recv_ns=tick.local_recv_ns,
            verified=verified,
            verification_note="; ".join(notes),
        )

    # ------------------------------------------------------------------ loop

    async def run_once(self) -> None:
        now_s = self.clock.now_s()
        interval = self.config.interval_seconds
        current_ts = window_start_ts(now_s, interval)
        next_ts = current_ts + interval

        for asset in self.assets:
            state = self.current.get(asset)

            # Roll over a finished interval.
            if (
                state is not None
                and now_s >= state.market.end_ts + CLOSE_GRACE_S
                and not state.closed
            ):
                await self._finalize(state)
                state.closed = True

            # Activate the current window (from preload if available).
            if state is None or state.market.start_ts != float(current_ts):
                market = self.next_market.pop(asset, None)
                if market is None or market.start_ts != float(current_ts):
                    market = await self.discovery.fetch_market(asset, current_ts)
                if market is not None:
                    carry = self.current.get(asset)
                    new_state = IntervalState(market=market)
                    # Chainlink prints observed in the previous interval remain the
                    # freshest pre-boundary evidence for opening verification.
                    if carry is not None and carry.last_at_or_before_close is not None:
                        new_state.last_before_open = carry.last_at_or_before_close
                    if carry is not None and not carry.closed:
                        await self._finalize(carry)
                        carry.closed = True
                    self.current[asset] = new_state
                    self.bus.publish(market)
                    logger.info(
                        "active market %s (%s) tradable=%s",
                        market.slug,
                        asset.value,
                        market.tradable,
                    )

            # Preload next window shortly before the boundary.
            if asset not in self.next_market and next_ts - now_s <= self.config.preload_lead_s:
                market = await self.discovery.fetch_market(asset, next_ts)
                if market is not None:
                    self.next_market[asset] = market
                    logger.info("preloaded next market %s", market.slug)
                else:
                    logger.debug(
                        "next market %s not yet listed",
                        slug_for(asset, next_ts, self.config.slug_template),
                    )

    async def _finalize(self, state: IntervalState) -> None:
        market = state.market
        opening = state.opening
        closing_tick = state.last_at_or_before_close
        closing = closing_tick.price if closing_tick is not None else None
        winner: Side | None = None
        if opening is not None and opening.verified and closing is not None:
            winner = Side.UP if closing >= opening.price else Side.DOWN
        result = MarketResult(
            market_slug=market.slug,
            asset=market.asset,
            start_ts=market.start_ts,
            end_ts=market.end_ts,
            opening_price=opening.price if opening else None,
            closing_price=closing,
            winner=winner,
            opening_verified=bool(opening and opening.verified),
            resolved_at_ns=self.clock.now_ns(),
        )
        logger.info(
            "interval finished %s open=%s close=%s winner=%s verified=%s",
            market.slug,
            result.opening_price,
            result.closing_price,
            winner.value if winner else None,
            result.opening_verified,
        )
        if self.on_result is not None:
            await self.on_result(result, state)

    async def _run(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                logger.exception("scheduler iteration failed")
            await asyncio.sleep(self.config.poll_interval_s)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="market-scheduler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


def _now_ns() -> int:
    return time.time_ns()
