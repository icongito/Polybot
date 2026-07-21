"""Model 1: volatility baseline.

Treats the remaining log move of the settlement price as ~N(mu, sigma^2 * tau)
where sigma is realized vol and mu a small momentum drift, then

    P(close >= open) = Phi((log(anchor/open) + mu*tau) / (sigma*sqrt(tau)))

The anchor blends the latest Chainlink print with the exchange consensus
(exchanges lead the next Chainlink update); the blend weight scales with how
stale the Chainlink print is. Near expiry the model accounts for Chainlink's
discrete update cadence: if no further update is likely to land, the current
print already decides the market.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from polybot.config import ModelConfig
from polybot.pricing.state import AssetState, MarketView


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass(frozen=True)
class BaselineResult:
    p_up: float
    anchor_price: float
    stdev_remaining: float
    p_no_more_updates: float


class BaselineModel:
    def __init__(self, config: ModelConfig) -> None:
        self.config = config

    def probability_up(
        self,
        state: AssetState,
        view: MarketView,
        *,
        now_s: float,
        now_ns: int,
        max_exchange_age_s: float,
    ) -> BaselineResult | None:
        if state.chainlink is None or view.opening is None or not view.opening.verified:
            return None
        opening = view.opening.price
        chainlink = state.chainlink.price
        if opening <= 0 or chainlink <= 0:
            return None

        tau = view.seconds_remaining(now_s)
        consensus = state.consensus_exchange_price(now_ns, max_exchange_age_s)

        # Blend chainlink with exchange consensus; weight rises with chainlink age.
        anchor = chainlink
        if consensus is not None:
            chainlink_age = state.chainlink.age_seconds(now_ns)
            staleness = min(
                1.0, chainlink_age / max(0.5, self.config.chainlink_update_interval_hint_s * 2)
            )
            weight = self.config.exchange_lead_weight * staleness
            anchor = math.exp((1 - weight) * math.log(chainlink) + weight * math.log(consensus))

        # Probability that no further chainlink update lands before expiry
        # (Poisson arrival at the observed cadence).
        cadence = (
            state.chainlink_update_interval_s() or self.config.chainlink_update_interval_hint_s
        )
        p_no_update = math.exp(-tau / cadence) if cadence > 0 else 0.0

        # Conditional on a final update landing: diffusion from the anchor.
        stdev = state.vol.remaining_move_stdev(tau)
        drift = state.momentum.value * tau * 0.25  # heavily damped momentum drift
        log_distance = math.log(anchor / opening) + drift
        if stdev > 1e-12:
            p_diffusion = normal_cdf(log_distance / stdev)
        else:
            p_diffusion = 1.0 if log_distance >= 0 else 0.0

        # Conditional on NO further update: the latest *chainlink* print decides.
        p_frozen = 1.0 if chainlink >= opening else 0.0

        p_up = p_no_update * p_frozen + (1 - p_no_update) * p_diffusion
        clamp = self.config.probability_clamp
        p_up = min(1 - clamp, max(clamp, p_up))
        return BaselineResult(
            p_up=p_up,
            anchor_price=anchor,
            stdev_remaining=stdev,
            p_no_more_updates=p_no_update,
        )
