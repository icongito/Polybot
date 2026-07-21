"""Strategy engine: turns live state into signals, and signals into order
intents inside the endgame window.

Signals are computed and recorded throughout the whole interval (spec:
continuous evaluation). Order intents are gated by the endgame window, the
endgame quality conditions, and the risk engine.
"""

from __future__ import annotations

import logging
import uuid

from polybot.bus import EventBus
from polybot.config import EndgameConfig, ModelConfig, RiskConfig
from polybot.models.core import (
    Asset,
    OrderIntent,
    Side,
    Signal,
    SignalDecision,
    TradingMode,
)
from polybot.observability import metrics
from polybot.pricing.ensemble import ConservativeEnsemble, EnsembleResult
from polybot.pricing.features import extract_features
from polybot.pricing.state import AssetState, PriceStateTracker
from polybot.risk.engine import RiskCheckInput, RiskEngine
from polybot.strategy.edge import (
    build_cost_stack,
    expected_profit_usd,
    net_edge,
    walk_asks,
)

logger = logging.getLogger(__name__)


class StrategyEngine:
    def __init__(
        self,
        tracker: PriceStateTracker,
        ensemble: ConservativeEnsemble,
        risk: RiskEngine,
        bus: EventBus,
        *,
        risk_config: RiskConfig,
        endgame: EndgameConfig,
        model_config: ModelConfig,
        mode: TradingMode,
        health_provider: object = None,
        measured_delay_buffer: float | None = None,
    ) -> None:
        self.tracker = tracker
        self.ensemble = ensemble
        self.risk = risk
        self.bus = bus
        self.risk_config = risk_config
        self.endgame = endgame
        self.model_config = model_config
        self.mode = mode
        self.measured_delay_buffer = measured_delay_buffer

    def evaluate_asset(
        self, asset: Asset, *, now_s: float, now_ns: int, health: object
    ) -> tuple[Signal, OrderIntent | None] | None:
        """Evaluate the active market for one asset. Returns (signal, intent?)."""
        state = self.tracker.assets.get(asset)
        if state is None:
            return None
        view = self.tracker.active_view(asset, now_s)
        if view is None or view.opening is None or state.chainlink is None:
            return None

        features = extract_features(
            state,
            view,
            now_s=now_s,
            now_ns=now_ns,
            max_exchange_age_s=self.risk_config.max_exchange_age_s,
        )
        result = self.ensemble.probability_up(
            state,
            view,
            features,
            now_s=now_s,
            now_ns=now_ns,
            max_exchange_age_s=self.risk_config.max_exchange_age_s,
        )
        if result is None:
            return None

        side = Side.UP if result.p_up >= 0.5 else Side.DOWN
        probability = result.p_up if side is Side.UP else 1.0 - result.p_up
        seconds_remaining = view.seconds_remaining(now_s)
        in_window = seconds_remaining <= self.endgame.window_s

        signal_id = uuid.uuid4().hex[:24]
        opening = view.opening
        chainlink_price = state.chainlink.price
        distance = chainlink_price - opening.price
        chainlink_return = chainlink_price / opening.price - 1.0 if opening.price else 0.0

        book = view.book(side)
        reject: list[str] = []
        plan = None
        costs = None
        if book is None or not book.asks:
            reject.append("no executable ask liquidity")
        else:
            max_price = min(
                self.risk_config.max_entry_price, probability - self.risk_config.min_net_edge
            )
            plan = walk_asks(
                book,
                max_price=max_price,
                target_notional=self.risk_config.max_stake_per_trade_usd,
            )
            if plan is None:
                reject.append(f"no asks at or below max acceptable price {max_price:.3f}")
            else:
                costs = build_cost_stack(
                    self.risk_config,
                    executable_price=plan.vwap,
                    market_taker_fee_bps=view.market.taker_fee_bps,
                    model_uncertainty_extra=result.uncertainty,
                    seconds_remaining=seconds_remaining,
                    endgame_ramp_s=self.endgame.final_seconds_buffer_ramp_s,
                    endgame_extra_buffer=self.endgame.final_seconds_extra_buffer,
                    measured_delay_buffer=self.measured_delay_buffer,
                )

        gross: float | None = None
        net: float | None = None
        profit = 0.0
        if plan is not None and costs is not None:
            gross, net = net_edge(probability, plan, costs)
            profit = expected_profit_usd(probability, plan, costs)

        # Endgame gating (order intents only).
        reject.extend(
            self._endgame_gate(
                state,
                result,
                probability,
                seconds_remaining,
                now_ns,
                in_window,
                opening_price=opening.price,
                chainlink_return=chainlink_return,
            )
        )

        if plan is not None and costs is not None and book is not None and not reject:
            check_input = RiskCheckInput(
                view=view,
                state=state,
                book=book,
                probability=probability,
                executable_vwap=plan.vwap,
                executable_notional=plan.notional,
                net_edge=net if net is not None else -1.0,
                expected_profit_usd=profit,
                signal_created_ns=now_ns,
                seconds_remaining=seconds_remaining,
                health=health,  # type: ignore[arg-type]
                now_ns=now_ns,
            )
            reject.extend(self.risk.check(check_input))

        decision = SignalDecision.TRADE if not reject else SignalDecision.REJECT
        signal = Signal(
            id=signal_id,
            market_slug=view.market.slug,
            asset=asset,
            side=side,
            created_ns=now_ns,
            seconds_remaining=seconds_remaining,
            chainlink_price=chainlink_price,
            opening_price=opening.price,
            chainlink_distance=distance,
            chainlink_return=chainlink_return,
            probability=probability,
            probability_baseline=result.p_baseline if side is Side.UP else 1 - result.p_baseline,
            probability_empirical=(
                None
                if result.p_empirical is None
                else (result.p_empirical if side is Side.UP else 1 - result.p_empirical)
            ),
            model_disagreement=result.disagreement,
            executable_price=plan.vwap if plan else None,
            executable_size=plan.shares if plan else None,
            gross_edge=gross,
            net_edge=net,
            costs=costs.as_dict() if costs else {},
            decision=decision,
            reject_reasons=tuple(reject),
            in_endgame_window=in_window,
            feed_ages={
                "chainlink": state.chainlink.age_seconds(now_ns),
                **{
                    source.value: tick.age_seconds(now_ns)
                    for source, tick in state.exchange_ticks.items()
                },
            },
        )
        self.bus.publish(signal)
        metrics.SIGNALS.labels(asset=asset.value, decision=decision.value).inc()
        if net is not None and decision is SignalDecision.TRADE:
            metrics.SIGNAL_NET_EDGE.labels(asset=asset.value).observe(net)

        intent: OrderIntent | None = None
        if decision is SignalDecision.TRADE and plan is not None:
            intent = OrderIntent(
                signal_id=signal.id,
                market_slug=view.market.slug,
                asset=asset,
                side=side,
                token_id=view.market.token_id(side),
                limit_price=plan.worst_price,
                size=plan.shares,
                max_notional=plan.notional,
                created_ns=now_ns,
                mode=self.mode,
            )
        return signal, intent

    def _endgame_gate(
        self,
        state: AssetState,
        result: EnsembleResult,
        probability: float,
        seconds_remaining: float,
        now_ns: int,
        in_window: bool,
        *,
        opening_price: float,
        chainlink_return: float,
    ) -> list[str]:
        """Conditions that must hold before an order intent may be created."""
        cfg = self.endgame
        problems: list[str] = []
        if not in_window:
            problems.append("outside endgame activation window")
            return problems
        if seconds_remaining < cfg.hard_cutoff_s:
            problems.append(f"inside hard cutoff ({cfg.hard_cutoff_s}s before close)")
        if probability < cfg.min_probability:
            problems.append(f"probability {probability:.3f} < endgame min {cfg.min_probability}")
        if abs(chainlink_return) < cfg.min_abs_return:
            problems.append(
                f"chainlink return {chainlink_return:.6f} not material (min {cfg.min_abs_return})"
            )

        chainlink = state.chainlink
        if chainlink is None:
            problems.append("no chainlink print")
            return problems

        # Direction confirmation across exchanges (vs the interval opening price).
        mids = state.exchange_midpoints(now_ns, self.risk_config.max_exchange_age_s)
        agree = 0
        for mid in mids.values():
            if (mid >= opening_price) == (result.p_up >= 0.5):
                agree += 1
        if (
            len(mids) >= cfg.min_cross_exchange_agreement
            and agree < cfg.min_cross_exchange_agreement
        ):
            problems.append(f"only {agree}/{len(mids)} exchanges confirm direction")
        elif len(mids) < cfg.min_cross_exchange_agreement:
            problems.append(
                f"only {len(mids)} fresh exchange feeds (< {cfg.min_cross_exchange_agreement} required)"
            )
        dispersion = state.cross_exchange_dispersion(now_ns, self.risk_config.max_exchange_age_s)
        if dispersion is not None and dispersion > cfg.max_cross_exchange_dispersion:
            problems.append(f"cross-exchange dispersion {dispersion:.5f} too wide")
        return problems
