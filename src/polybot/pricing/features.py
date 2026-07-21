"""Feature extraction shared by the empirical model and signal records."""

from __future__ import annotations

import math
from dataclasses import dataclass

from polybot.models.core import Side
from polybot.pricing.state import AssetState, MarketView

FEATURE_NAMES = (
    "z_distance",  # chainlink distance from open, in remaining-move stdevs
    "sqrt_tau",  # sqrt(seconds remaining)
    "sigma",  # realized vol per sqrt-second (scaled)
    "exchange_gap",  # (exchange consensus - chainlink) / chainlink, in stdevs of 1s move
    "momentum",  # EWMA per-second log-return rate (scaled)
    "dispersion",  # cross-exchange dispersion (relative)
    "book_imbalance",  # up-book bid depth vs ask depth in top levels
    "spread",  # up-token spread
    "trade_intensity",  # polymarket trades per second
    "update_cadence",  # expected further chainlink updates before expiry (log1p)
)


@dataclass(frozen=True)
class FeatureVector:
    z_distance: float
    sqrt_tau: float
    sigma: float
    exchange_gap: float
    momentum: float
    dispersion: float
    book_imbalance: float
    spread: float
    trade_intensity: float
    update_cadence: float

    def as_list(self) -> list[float]:
        return [getattr(self, name) for name in FEATURE_NAMES]


def top_depth(view: MarketView, side: Side, levels: int = 3) -> tuple[float, float]:
    book = view.book(side)
    if book is None:
        return 0.0, 0.0
    bid_depth = sum(level.size for level in book.bids[:levels])
    ask_depth = sum(level.size for level in book.asks[:levels])
    return bid_depth, ask_depth


def extract_features(
    state: AssetState,
    view: MarketView,
    *,
    now_s: float,
    now_ns: int,
    max_exchange_age_s: float,
) -> FeatureVector | None:
    if state.chainlink is None or view.opening is None:
        return None
    opening = view.opening.price
    chainlink = state.chainlink.price
    if opening <= 0 or chainlink <= 0:
        return None

    tau = view.seconds_remaining(now_s)
    stdev_remaining = state.vol.remaining_move_stdev(tau)
    log_distance = math.log(chainlink / opening)
    z_distance = log_distance / stdev_remaining if stdev_remaining > 0 else 0.0
    z_distance = _clamp(z_distance, -10.0, 10.0)

    consensus = state.consensus_exchange_price(now_ns, max_exchange_age_s)
    sigma_1s = state.vol.sigma_per_sqrt_s()
    if consensus is not None and sigma_1s > 0:
        exchange_gap = _clamp(math.log(consensus / chainlink) / sigma_1s, -10.0, 10.0)
    else:
        exchange_gap = 0.0

    dispersion = state.cross_exchange_dispersion(now_ns, max_exchange_age_s) or 0.0

    up_bids, up_asks = top_depth(view, Side.UP)
    total = up_bids + up_asks
    book_imbalance = (up_bids - up_asks) / total if total > 0 else 0.0

    up_book = view.book(Side.UP)
    spread = up_book.spread if up_book is not None and up_book.spread is not None else 1.0

    cadence = state.chainlink_update_interval_s()
    expected_updates = tau / cadence if cadence and cadence > 0 else tau
    update_cadence = math.log1p(max(0.0, expected_updates))

    return FeatureVector(
        z_distance=z_distance,
        sqrt_tau=math.sqrt(max(0.0, tau)),
        sigma=sigma_1s * 1e4,
        exchange_gap=exchange_gap,
        momentum=_clamp(state.momentum.value * 1e4, -50.0, 50.0),
        dispersion=_clamp(dispersion * 1e4, 0.0, 100.0),
        book_imbalance=book_imbalance,
        spread=spread,
        trade_intensity=state.trade_intensity_per_s(now_s),
        update_cadence=update_cadence,
    )


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
