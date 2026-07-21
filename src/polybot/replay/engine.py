"""Deterministic replay engine.

Merges one or more capture files in strict local-receive-time order onto a
:class:`~polybot.clock.SimClock`, replays ticks/books/market/opening events
into a fresh :class:`PriceStateTracker`, and periodically evaluates the same
:class:`StrategyEngine` used live. Trade signals are executed against
:class:`PaperExecutor`, whose fill model is allowed to consult the recorded
future book state (see :mod:`polybot.replay.fill_model`) but the strategy
itself is never shown anything past the current simulated instant.

Operational-only risk gates (clock drift, kill switch, geo eligibility) are
not part of historical market data, so replay runs with permissive stand-ins
for those three checks; every market-derived risk check (edges, ages,
spreads, stakes) still runs for real against the replayed state.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from polybot.bus import EventBus
from polybot.clock import DriftMonitor, SimClock
from polybot.config import AppConfig
from polybot.execution.delay import DelayTracker
from polybot.execution.paper import PaperExecutor, PaperFillParams
from polybot.execution.precheck import pre_submission_check
from polybot.feeds.health import HealthReport
from polybot.models.core import (
    Asset,
    BookSnapshot,
    Fill,
    MarketInfo,
    MarketResult,
    OpeningPrice,
    OrderRecord,
    OrderStatus,
    Signal,
    SignalDecision,
    Tick,
    TradingMode,
)
from polybot.pricing.baseline import BaselineModel
from polybot.pricing.empirical import EmpiricalModel
from polybot.pricing.ensemble import ConservativeEnsemble
from polybot.pricing.state import PriceStateTracker
from polybot.recording.reader import open_capture
from polybot.recording.schema import CaptureEnvelope
from polybot.replay.fill_model import BookHistory
from polybot.risk.engine import GeoGate, KillSwitch, RiskEngine
from polybot.strategy.engine import StrategyEngine

logger = logging.getLogger(__name__)

EVAL_INTERVAL_S = 0.25


@dataclass
class ReplayResult:
    signals: list[Signal] = field(default_factory=list)
    orders: list[OrderRecord] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    results: list[MarketResult] = field(default_factory=list)


def _load_sorted(paths: Iterable[Path]) -> list[CaptureEnvelope]:
    envelopes: list[CaptureEnvelope] = []
    for path in paths:
        envelopes.extend(open_capture(path))
    envelopes.sort(key=lambda e: e.recv_ns)
    return envelopes


class ReplayEngine:
    def __init__(self, config: AppConfig, assets: list[Asset]) -> None:
        self.config = config
        self.assets = assets
        self.clock = SimClock()
        self.tracker = PriceStateTracker(
            assets,
            vol_halflife_s=config.model.vol_ewma_halflife_s,
            vol_floor=config.model.vol_floor_per_sqrt_s,
            vol_min_ticks=config.model.vol_sample_min_ticks,
        )
        empirical = EmpiricalModel.load(
            config.model.empirical_model_path,
            min_samples=config.model.empirical_min_training_samples,
        )
        ensemble = ConservativeEnsemble(config.model, BaselineModel(config.model), empirical)

        drift = DriftMonitor(config.risk.max_clock_drift_s)
        drift.last_offset_s = 0.0  # replay: clock drift is not a historical fact to reconstruct
        risk = RiskEngine(
            config=config.risk,
            drift=drift,
            kill_switch=KillSwitch(file_path="/dev/null"),
            geo=GeoGate(eligible=True, attestation="replay"),
        )
        self.risk = risk
        self._bus = EventBus()
        self.strategy = StrategyEngine(
            self.tracker,
            ensemble,
            risk,
            self._bus,
            risk_config=config.risk,
            endgame=config.endgame,
            model_config=config.model,
            mode=TradingMode.PAPER,
        )
        self._book_history = BookHistory()
        self._delay_tracker = DelayTracker()
        params = PaperFillParams(fee_rate=config.risk.taker_fee_rate)
        self._executor = PaperExecutor(
            self._bus,
            params,
            book_at=lambda intent, ts_s: self._book_history.at(intent.token_id, int(ts_s * 1e9)),
            market_end_ts=lambda intent: self.tracker.markets[intent.market_slug].market.end_ts,
            now_s=self.clock.now_s,
        )
        self._fill_sub = self._bus.subscribe("replay-fills", lossless=True)
        self.result = ReplayResult()
        self._last_eval_s: dict[Asset, float] = dict.fromkeys(assets, float("-inf"))

    async def run(self, paths: list[str | Path]) -> ReplayResult:
        envelopes = _load_sorted(Path(p) for p in paths)
        if not envelopes:
            return self.result

        # Pre-index the full book history up front — this is the one place
        # replay is allowed to see "the future" (see fill_model docstring).
        for env in envelopes:
            if env.t == "book":
                self._book_history.add(BookSnapshot.model_validate(env.data))
        self._book_history.finalize()

        for env in envelopes:
            self.clock.advance_to_ns(env.recv_ns)
            await self._apply(env)
            await self._maybe_evaluate()

        return self.result

    async def _apply(self, env: CaptureEnvelope) -> None:
        if env.t == "tick":
            self.tracker.on_tick(Tick.model_validate(env.data))
        elif env.t == "book":
            self.tracker.on_book(BookSnapshot.model_validate(env.data))
        elif env.t == "market":
            self.tracker.on_market(MarketInfo.model_validate(env.data))
        elif env.t == "opening":
            self.tracker.on_opening(OpeningPrice.model_validate(env.data))
        elif env.t == "result":
            self.result.results.append(MarketResult.model_validate(env.data))
        # "signal"/"order"/"fill" envelopes are the historical live/paper
        # record and are intentionally not replayed as inputs — replay
        # regenerates its own signals/orders from the raw market data above.

    async def _maybe_evaluate(self) -> None:
        now_s = self.clock.now_s()
        now_ns = self.clock.now_ns()
        health = HealthReport(healthy=True)  # feed health is a live-only concern in replay
        for asset in self.assets:
            if now_s - self._last_eval_s[asset] < EVAL_INTERVAL_S:
                continue
            self._last_eval_s[asset] = now_s
            outcome = self.strategy.evaluate_asset(asset, now_s=now_s, now_ns=now_ns, health=health)
            if outcome is None:
                continue
            signal, intent = outcome
            self.result.signals.append(signal)
            if signal.decision is not SignalDecision.TRADE or intent is None:
                continue
            view = self.tracker.markets.get(signal.market_slug)
            state = self.tracker.assets.get(asset)
            if view is None or state is None:
                continue
            precheck = pre_submission_check(
                intent,
                signal,
                view,
                state,
                now_s=now_s,
                now_ns=now_ns,
                exec_config=self.config.execution,
                risk_config=self.config.risk,
                fresh_probability=signal.probability,
            )
            if not precheck.ok:
                logger.debug("replay precheck abort %s: %s", signal.id, precheck.problems)
                self.result.orders.append(
                    OrderRecord(
                        intent=intent,
                        status=OrderStatus.ABORTED_PRECHECK,
                        detail="; ".join(precheck.problems),
                    )
                )
                continue
            view.orders_submitted += 1
            record = await self._executor.submit(intent)
            self.result.orders.append(record)
            while not self._fill_sub.queue.empty():
                fill = self._fill_sub.queue.get_nowait()
                if isinstance(fill, Fill):
                    self.result.fills.append(fill)
            if record.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
                view.stake_usd += intent.max_notional
                self.risk.record_fill(intent.max_notional)
