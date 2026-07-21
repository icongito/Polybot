"""Risk engine: every configured limit is checked before any order intent
leaves the strategy. Checks return the full list of violations (never
short-circuiting) so rejected signals record every reason.

Structural bans: there is no leverage, no martingale sizing, no averaging
down, and no unbounded retry anywhere in this codebase — position size comes
only from the fixed per-trade/per-market caps below.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from polybot.clock import DriftMonitor
from polybot.config import RiskConfig
from polybot.feeds.health import HealthReport
from polybot.models.core import BookSnapshot, Tick
from polybot.observability import metrics
from polybot.pricing.state import AssetState, MarketView


@dataclass
class RiskCheckInput:
    view: MarketView
    state: AssetState
    book: BookSnapshot
    probability: float
    executable_vwap: float
    executable_notional: float
    net_edge: float
    expected_profit_usd: float
    signal_created_ns: int
    seconds_remaining: float
    health: HealthReport
    now_ns: int


@dataclass
class DailyRiskState:
    day: str = ""
    realized_loss_usd: float = 0.0
    open_exposure_usd: float = 0.0

    def roll(self, now_s: float) -> None:
        day = time.strftime("%Y-%m-%d", time.gmtime(now_s))
        if day != self.day:
            self.day = day
            self.realized_loss_usd = 0.0


@dataclass
class KillSwitch:
    file_path: str
    engaged_reason: str | None = None

    def engage(self, reason: str) -> None:
        self.engaged_reason = reason
        metrics.KILL_SWITCH.set(1)

    @property
    def engaged(self) -> bool:
        if self.engaged_reason is not None:
            return True
        if Path(self.file_path).exists():
            self.engaged_reason = f"kill file present: {self.file_path}"
            metrics.KILL_SWITCH.set(1)
            return True
        return False


@dataclass
class GeoGate:
    eligible: bool
    attestation: str

    @property
    def passes(self) -> bool:
        return self.eligible and bool(self.attestation.strip())


@dataclass
class RiskEngine:
    config: RiskConfig
    drift: DriftMonitor
    kill_switch: KillSwitch
    geo: GeoGate
    daily: DailyRiskState = field(default_factory=DailyRiskState)
    external_kill: bool = False  # mirrored from redis by the app loop

    def check(self, inp: RiskCheckInput) -> list[str]:
        cfg = self.config
        problems: list[str] = []
        self.daily.roll(inp.now_ns / 1e9)

        if self.kill_switch.engaged or self.external_kill:
            problems.append("kill switch engaged")
        if not self.geo.passes:
            problems.append("geographic eligibility not confirmed")
        if not self.drift.trading_allowed:
            problems.append("clock drift unknown or above limit")
        if not inp.health.healthy:
            problems.extend(f"feed health: {p}" for p in inp.health.problems)

        market = inp.view.market
        if not market.tradable:
            problems.append("market not tradable (rules/book status)")
        if inp.view.opening is None or not inp.view.opening.verified:
            problems.append("opening price unverified")
        if inp.seconds_remaining <= 0:
            problems.append("market closed")

        if inp.net_edge < cfg.min_net_edge:
            problems.append(f"net edge {inp.net_edge:.4f} < min {cfg.min_net_edge}")
        if inp.expected_profit_usd < cfg.min_expected_profit_usd:
            problems.append(
                f"expected profit ${inp.expected_profit_usd:.2f} < min ${cfg.min_expected_profit_usd}"
            )
        if inp.executable_vwap > cfg.max_entry_price:
            problems.append(f"entry price {inp.executable_vwap:.3f} > max {cfg.max_entry_price}")

        spread = inp.book.spread
        if spread is None or spread > cfg.max_spread:
            problems.append(f"spread {spread} > max {cfg.max_spread}")

        # Ages.
        chainlink = inp.state.chainlink
        if chainlink is None or chainlink.age_seconds(inp.now_ns) > cfg.max_chainlink_age_s:
            problems.append("chainlink feed stale")
        if not _any_fresh_exchange(inp.state, inp.now_ns, cfg.max_exchange_age_s):
            problems.append("all exchange feeds stale")
        if inp.book.age_seconds(inp.now_ns) > cfg.max_book_age_s:
            problems.append("polymarket book stale")
        signal_age = (inp.now_ns - inp.signal_created_ns) / 1e9
        if signal_age > cfg.max_signal_age_s:
            problems.append(f"signal age {signal_age:.3f}s > max {cfg.max_signal_age_s}s")

        # Source divergence: exchange consensus vs chainlink.
        consensus = inp.state.consensus_exchange_price(inp.now_ns, cfg.max_exchange_age_s)
        if consensus is not None and chainlink is not None and chainlink.price > 0:
            divergence = abs(consensus - chainlink.price) / chainlink.price
            if divergence > cfg.max_source_divergence:
                problems.append(
                    f"source divergence {divergence:.5f} > max {cfg.max_source_divergence}"
                )

        # Stakes and counts.
        if inp.executable_notional > cfg.max_stake_per_trade_usd:
            problems.append("stake per trade exceeded")
        if inp.view.stake_usd + inp.executable_notional > cfg.max_stake_per_market_usd:
            problems.append("stake per market exceeded")
        if self.daily.realized_loss_usd >= cfg.max_daily_loss_usd:
            problems.append("max daily loss reached")
        if (
            self.daily.open_exposure_usd + inp.executable_notional
            > cfg.max_simultaneous_exposure_usd
        ):
            problems.append("max simultaneous exposure exceeded")
        if inp.view.orders_submitted >= cfg.max_orders_per_interval:
            problems.append("max orders per interval reached")

        return problems

    def record_fill(self, notional: float) -> None:
        self.daily.open_exposure_usd += notional
        metrics.EXPOSURE.set(self.daily.open_exposure_usd)

    def record_settlement(self, pnl_usd: float, released_notional: float) -> None:
        self.daily.open_exposure_usd = max(0.0, self.daily.open_exposure_usd - released_notional)
        if pnl_usd < 0:
            self.daily.realized_loss_usd += -pnl_usd
        metrics.EXPOSURE.set(self.daily.open_exposure_usd)


def _any_fresh_exchange(state: AssetState, now_ns: int, max_age_s: float) -> bool:
    tick: Tick
    for tick in state.exchange_ticks.values():
        if tick.age_seconds(now_ns) <= max_age_s:
            return True
    return False
