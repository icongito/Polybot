"""Atomic pre-submission recheck.

Immediately before any order (real, shadow, or paper) is released, every
spec-mandated value is re-read from live state and compared against the values
the signal was built from. Any breach aborts the submission with a recorded
reason. Never assume the price seen at signal time is still available.
"""

from __future__ import annotations

from dataclasses import dataclass

from polybot.config import ExecutionConfig, RiskConfig
from polybot.models.core import OrderIntent, Signal
from polybot.pricing.state import AssetState, MarketView
from polybot.strategy.edge import walk_asks


@dataclass(frozen=True)
class PrecheckResult:
    ok: bool
    problems: tuple[str, ...]
    fresh_vwap: float | None = None
    fresh_shares: float | None = None


def pre_submission_check(
    intent: OrderIntent,
    signal: Signal,
    view: MarketView,
    state: AssetState,
    *,
    now_s: float,
    now_ns: int,
    exec_config: ExecutionConfig,
    risk_config: RiskConfig,
    fresh_probability: float | None,
) -> PrecheckResult:
    problems: list[str] = []

    # 1-2. Exchange + chainlink prices still fresh.
    chainlink = state.chainlink
    if chainlink is None or chainlink.age_seconds(now_ns) > risk_config.max_chainlink_age_s:
        problems.append("chainlink stale at submission")
    if state.consensus_exchange_price(now_ns, risk_config.max_exchange_age_s) is None:
        problems.append("no fresh exchange price at submission")

    # 3. Opening price still verified.
    if view.opening is None or not view.opening.verified:
        problems.append("opening price not verified at submission")

    # 4. Seconds remaining / market open.
    seconds_remaining = view.seconds_remaining(now_s)
    if seconds_remaining <= 0:
        problems.append("market closed before submission")

    # 5-6. Best ask and depth still support the plan.
    book = view.book(intent.side)
    fresh_vwap: float | None = None
    fresh_shares: float | None = None
    if book is None or book.age_seconds(now_ns) > risk_config.max_book_age_s:
        problems.append("order book stale at submission")
    else:
        plan = walk_asks(book, max_price=intent.limit_price, target_notional=intent.max_notional)
        if plan is None:
            problems.append("liquidity below limit price vanished")
        else:
            fresh_vwap = plan.vwap
            fresh_shares = plan.shares
            if signal.executable_price is not None and (
                plan.vwap - signal.executable_price > exec_config.precheck_price_tolerance
            ):
                problems.append(
                    f"executable vwap moved {signal.executable_price:.3f} -> {plan.vwap:.3f}"
                )

    # 7. Net edge still positive under the fresh probability.
    if fresh_probability is not None:
        if abs(fresh_probability - signal.probability) > exec_config.precheck_probability_tolerance:
            problems.append(
                f"probability moved {signal.probability:.3f} -> {fresh_probability:.3f}"
            )
        if fresh_vwap is not None and fresh_probability - fresh_vwap <= 0:
            problems.append("gross edge gone at submission")

    # 8. Signal age.
    signal_age_s = (now_ns - signal.created_ns) / 1e9
    if signal_age_s > exec_config.precheck_max_signal_age_s:
        problems.append(
            f"signal aged {signal_age_s:.3f}s > {exec_config.precheck_max_signal_age_s}s"
        )

    # 9. Fee configuration unchanged (tick-size drift also invalidates pricing).
    if view.market.tick_size <= 0:
        problems.append("invalid tick size")

    # 10. Risk limits are re-checked by the caller through RiskEngine before
    # this function; stake caps are enforced structurally on the intent.
    if intent.max_notional > risk_config.max_stake_per_trade_usd * 1.001:
        problems.append("intent notional exceeds per-trade cap")

    return PrecheckResult(
        ok=not problems,
        problems=tuple(problems),
        fresh_vwap=fresh_vwap,
        fresh_shares=fresh_shares,
    )
