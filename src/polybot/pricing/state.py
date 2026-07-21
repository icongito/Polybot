"""Live price/market state maintained from bus events.

One :class:`AssetState` per asset (feeds, vol, momentum, chainlink cadence)
plus one :class:`MarketView` per active 5-minute market (opening price, books,
per-interval counters).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from itertools import pairwise

from polybot.models.core import (
    Asset,
    BookSnapshot,
    FeedSource,
    MarketInfo,
    OpeningPrice,
    Side,
    Tick,
)
from polybot.pricing.vol import RealizedVol

EXCHANGE_SOURCES = (
    FeedSource.BINANCE_SPOT,
    FeedSource.BINANCE_FUTURES,
    FeedSource.COINBASE,
    FeedSource.OKX,
)


@dataclass
class MomentumTracker:
    """EWMA of signed per-second log returns; positive = upward pressure."""

    halflife_s: float = 10.0
    value: float = 0.0
    _last_price: float | None = None
    _last_ts: float | None = None

    def update(self, price: float, ts: float) -> None:
        if self._last_price is not None and self._last_ts is not None:
            dt = ts - self._last_ts
            if dt > 0:
                rate = math.log(price / self._last_price) / dt
                alpha = 1 - math.exp(-math.log(2) * dt / self.halflife_s)
                self.value += alpha * (rate - self.value)
        self._last_price, self._last_ts = price, ts


class AssetState:
    def __init__(self, asset: Asset, vol: RealizedVol) -> None:
        self.asset = asset
        self.chainlink: Tick | None = None
        self.exchange_ticks: dict[FeedSource, Tick] = {}
        self.vol = vol
        self.momentum = MomentumTracker()
        self.chainlink_update_ts: deque[float] = deque(maxlen=100)
        self.trade_times: deque[float] = deque(maxlen=200)

    def on_tick(self, tick: Tick) -> None:
        if tick.source.is_settlement:
            if self.chainlink is None or tick.provider_ts >= self.chainlink.provider_ts:
                if self.chainlink is None or tick.price != self.chainlink.price:
                    self.chainlink_update_ts.append(tick.provider_ts)
                self.chainlink = tick
        elif tick.source in EXCHANGE_SOURCES:
            mid = tick.mid
            if mid is not None:
                previous = self.exchange_ticks.get(tick.source)
                if previous is None or tick.provider_ts >= previous.provider_ts:
                    self.exchange_ticks[tick.source] = tick
                self.vol.update(mid, tick.provider_ts)
                self.momentum.update(mid, tick.provider_ts)
            if tick.last is not None and tick.bid is None:
                self.trade_times.append(tick.provider_ts)

    # ----------------------------------------------------------- derived state

    def exchange_midpoints(self, now_ns: int, max_age_s: float) -> dict[FeedSource, float]:
        result: dict[FeedSource, float] = {}
        for source, tick in self.exchange_ticks.items():
            mid = tick.mid
            if mid is not None and tick.age_seconds(now_ns) <= max_age_s:
                result[source] = mid
        return result

    def consensus_exchange_price(self, now_ns: int, max_age_s: float) -> float | None:
        mids = list(self.exchange_midpoints(now_ns, max_age_s).values())
        if not mids:
            return None
        mids.sort()
        n = len(mids)
        return mids[n // 2] if n % 2 == 1 else (mids[n // 2 - 1] + mids[n // 2]) / 2

    def cross_exchange_dispersion(self, now_ns: int, max_age_s: float) -> float | None:
        mids = list(self.exchange_midpoints(now_ns, max_age_s).values())
        if len(mids) < 2:
            return None
        center = sum(mids) / len(mids)
        if center == 0:
            return None
        return (max(mids) - min(mids)) / center

    def chainlink_update_interval_s(self) -> float | None:
        if len(self.chainlink_update_ts) < 3:
            return None
        ts = list(self.chainlink_update_ts)
        gaps = [b - a for a, b in pairwise(ts) if b > a]
        if not gaps:
            return None
        gaps.sort()
        return gaps[len(gaps) // 2]

    def trade_intensity_per_s(self, now_s: float, window_s: float = 30.0) -> float:
        recent = [t for t in self.trade_times if now_s - t <= window_s]
        return len(recent) / window_s


@dataclass
class MarketView:
    market: MarketInfo
    opening: OpeningPrice | None = None
    books: dict[Side, BookSnapshot] = field(default_factory=dict)
    orders_submitted: int = 0
    stake_usd: float = 0.0

    def book(self, side: Side) -> BookSnapshot | None:
        return self.books.get(side)

    def seconds_remaining(self, now_s: float) -> float:
        return max(0.0, self.market.end_ts - now_s)


class PriceStateTracker:
    """Consumes bus events; the single source of truth for live state."""

    def __init__(
        self,
        assets: list[Asset],
        vol_factory: type[RealizedVol] | None = None,
        *,
        vol_halflife_s: float = 60.0,
        vol_floor: float = 1e-6,
        vol_min_ticks: int = 20,
    ) -> None:
        self.assets = {
            asset: AssetState(asset, RealizedVol(vol_halflife_s, vol_floor, vol_min_ticks))
            for asset in assets
        }
        self.markets: dict[str, MarketView] = {}
        self._token_to_market: dict[str, tuple[str, Side]] = {}

    def on_tick(self, tick: Tick) -> None:
        state = self.assets.get(tick.asset)
        if state is not None:
            state.on_tick(tick)

    def on_market(self, market: MarketInfo) -> None:
        self.markets[market.slug] = MarketView(market=market)
        if market.up_token_id:
            self._token_to_market[market.up_token_id] = (market.slug, Side.UP)
        if market.down_token_id:
            self._token_to_market[market.down_token_id] = (market.slug, Side.DOWN)
        # Drop views for markets two intervals old to bound memory.
        cutoff = market.start_ts - 2 * (market.end_ts - market.start_ts)
        for slug in [s for s, v in self.markets.items() if v.market.end_ts < cutoff]:
            old = self.markets.pop(slug)
            self._token_to_market.pop(old.market.up_token_id, None)
            self._token_to_market.pop(old.market.down_token_id, None)

    def on_opening(self, opening: OpeningPrice) -> None:
        view = self.markets.get(opening.market_slug)
        if view is not None:
            view.opening = opening

    def on_book(self, snapshot: BookSnapshot) -> None:
        ref = self._token_to_market.get(snapshot.token_id)
        if ref is None:
            return
        slug, side = ref
        view = self.markets.get(slug)
        if view is not None:
            view.books[side] = snapshot

    def token_meta(self, token_id: str) -> tuple[str, Asset, Side] | None:
        ref = self._token_to_market.get(token_id)
        if ref is None:
            return None
        slug, side = ref
        view = self.markets.get(slug)
        if view is None:
            return None
        return slug, view.market.asset, side

    def active_view(self, asset: Asset, now_s: float) -> MarketView | None:
        for view in self.markets.values():
            if view.market.asset is asset and view.market.start_ts <= now_s < view.market.end_ts:
                return view
        return None
