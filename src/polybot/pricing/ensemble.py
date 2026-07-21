"""Model 3: conservative ensemble — the only model live trading may use.

Blends the volatility baseline with the empirical model (when loaded) and
converts their disagreement into extra uncertainty: the blended probability is
shrunk toward 0.5 and the reported ``uncertainty`` term is added to the
strategy's model-uncertainty cost buffer.
"""

from __future__ import annotations

from dataclasses import dataclass

from polybot.config import ModelConfig
from polybot.pricing.baseline import BaselineModel, BaselineResult
from polybot.pricing.empirical import EmpiricalModel
from polybot.pricing.features import FeatureVector
from polybot.pricing.state import AssetState, MarketView


@dataclass(frozen=True)
class EnsembleResult:
    p_up: float
    p_baseline: float
    p_empirical: float | None
    disagreement: float
    uncertainty: float
    baseline: BaselineResult


class ConservativeEnsemble:
    def __init__(
        self,
        config: ModelConfig,
        baseline: BaselineModel,
        empirical: EmpiricalModel | None,
    ) -> None:
        self.config = config
        self.baseline = baseline
        self.empirical = empirical

    def probability_up(
        self,
        state: AssetState,
        view: MarketView,
        features: FeatureVector | None,
        *,
        now_s: float,
        now_ns: int,
        max_exchange_age_s: float,
    ) -> EnsembleResult | None:
        base = self.baseline.probability_up(
            state, view, now_s=now_s, now_ns=now_ns, max_exchange_age_s=max_exchange_age_s
        )
        if base is None:
            return None

        p_empirical: float | None = None
        if self.empirical is not None and features is not None:
            p_empirical = self.empirical.probability_up(features)

        if p_empirical is None:
            # Baseline only: penalize the missing second opinion with extra
            # uncertainty and a mild shrink toward 0.5.
            p_blend = 0.5 + (base.p_up - 0.5) * 0.9
            disagreement = 0.0
            uncertainty = 0.02
        else:
            p_blend = 0.5 * base.p_up + 0.5 * p_empirical
            disagreement = abs(base.p_up - p_empirical)
            # Disagreement shrinks confidence toward 0.5 and raises the buffer.
            shrink = min(1.0, disagreement * 2.0)
            p_blend = 0.5 + (p_blend - 0.5) * (1.0 - shrink * 0.5)
            uncertainty = disagreement * self.config.disagreement_uncertainty_scale

        clamp = self.config.probability_clamp
        p_blend = min(1 - clamp, max(clamp, p_blend))
        return EnsembleResult(
            p_up=p_blend,
            p_baseline=base.p_up,
            p_empirical=p_empirical,
            disagreement=disagreement,
            uncertainty=uncertainty,
            baseline=base,
        )
