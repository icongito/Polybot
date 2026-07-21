"""Edge computation against real executable order-book levels.

Never uses the displayed Polymarket percentage: the executable price is the
depth-walked volume-weighted average across actual ask levels up to a maximum
acceptable price (the spec's example: asks 500@0.72 / 300@0.74 / 900@0.78 with
max 0.75 -> consume the first two levels only).
"""

from __future__ import annotations

from dataclasses import dataclass

from polybot.config import RiskConfig
from polybot.models.core import BookSnapshot


@dataclass(frozen=True)
class ExecutablePlan:
    """Result of walking the ask side for a target notional."""

    shares: float
    notional: float
    vwap: float
    worst_price: float
    levels_used: int
    exhausted: bool  # True when the book ran out below max_price before target


def walk_asks(
    book: BookSnapshot, *, max_price: float, target_notional: float
) -> ExecutablePlan | None:
    """Walk ask levels at or below ``max_price`` until ``target_notional`` is spent."""
    shares = 0.0
    notional = 0.0
    worst = 0.0
    levels = 0
    for level in book.asks:
        if level.price > max_price:
            break
        remaining = target_notional - notional
        if remaining <= 0:
            break
        take = min(level.size, remaining / level.price)
        if take <= 0:
            break
        shares += take
        notional += take * level.price
        worst = level.price
        levels += 1
    if shares <= 0:
        return None
    return ExecutablePlan(
        shares=shares,
        notional=notional,
        vwap=notional / shares,
        worst_price=worst,
        levels_used=levels,
        exhausted=notional < target_notional * 0.999,
    )


@dataclass(frozen=True)
class CostStack:
    taker_fee: float
    expected_slippage: float
    execution_delay_buffer: float
    feed_latency_buffer: float
    model_uncertainty_buffer: float
    failed_fill_buffer: float

    @property
    def total(self) -> float:
        return (
            self.taker_fee
            + self.expected_slippage
            + self.execution_delay_buffer
            + self.feed_latency_buffer
            + self.model_uncertainty_buffer
            + self.failed_fill_buffer
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "taker_fee": self.taker_fee,
            "expected_slippage": self.expected_slippage,
            "execution_delay_buffer": self.execution_delay_buffer,
            "feed_latency_buffer": self.feed_latency_buffer,
            "model_uncertainty_buffer": self.model_uncertainty_buffer,
            "failed_fill_buffer": self.failed_fill_buffer,
        }


def build_cost_stack(
    risk: RiskConfig,
    *,
    executable_price: float,
    market_taker_fee_bps: float,
    model_uncertainty_extra: float,
    seconds_remaining: float,
    endgame_ramp_s: float,
    endgame_extra_buffer: float,
    measured_delay_buffer: float | None = None,
) -> CostStack:
    """Assemble the per-trade cost stack in probability units.

    Buffers grow as expiry approaches (inside ``endgame_ramp_s``): a late order
    faces higher risk of another Chainlink print, submission delay past close,
    and cancelled resting liquidity.
    """
    fee_rate = max(risk.taker_fee_rate, market_taker_fee_bps / 10_000)
    # Polymarket taker fees apply to proceeds/shares; conservatively express as
    # price-units cost on the entry price.
    taker_fee = fee_rate * executable_price

    ramp = 0.0
    if seconds_remaining < endgame_ramp_s and endgame_ramp_s > 0:
        ramp = (1.0 - seconds_remaining / endgame_ramp_s) * endgame_extra_buffer

    delay_buffer = (
        measured_delay_buffer if measured_delay_buffer is not None else risk.execution_delay_buffer
    )
    return CostStack(
        taker_fee=taker_fee,
        expected_slippage=risk.expected_slippage,
        execution_delay_buffer=delay_buffer + ramp / 2,
        feed_latency_buffer=risk.feed_latency_buffer + ramp / 4,
        model_uncertainty_buffer=risk.model_uncertainty_buffer + model_uncertainty_extra + ramp / 4,
        failed_fill_buffer=risk.failed_fill_buffer,
    )


def net_edge(probability: float, plan: ExecutablePlan, costs: CostStack) -> tuple[float, float]:
    """Returns (gross_edge, net_edge) in probability units at the plan VWAP."""
    gross = probability - plan.vwap
    return gross, gross - costs.total


def expected_profit_usd(probability: float, plan: ExecutablePlan, costs: CostStack) -> float:
    """Expected value in dollars for the walked plan after the cost stack."""
    _, edge = net_edge(probability, plan, costs)
    return edge * plan.shares
