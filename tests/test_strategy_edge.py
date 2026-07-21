from polybot.config import RiskConfig
from polybot.models.core import Asset, BookLevel, BookSnapshot, Side
from polybot.strategy.edge import build_cost_stack, net_edge, walk_asks


def _book(levels: list[tuple[float, float]]) -> BookSnapshot:
    return BookSnapshot(
        token_id="tok",
        asset=Asset.BTC,
        side=Side.UP,
        asks=tuple(BookLevel(price=p, size=s) for p, s in levels),
        provider_ts=0.0,
        local_recv_ns=0,
    )


def test_walk_asks_matches_spec_worked_example() -> None:
    """500@0.72, 300@0.74, 900@0.78; max acceptable price 0.75 -> only the
    first two levels (500 + 300 = 800 shares) may be consumed."""
    book = _book([(0.72, 500), (0.74, 300), (0.78, 900)])

    plan = walk_asks(book, max_price=0.75, target_notional=10_000)

    assert plan is not None
    assert plan.shares == 800
    assert plan.levels_used == 2
    assert plan.worst_price == 0.74
    expected_notional = 500 * 0.72 + 300 * 0.74
    assert plan.notional == expected_notional
    assert plan.vwap == expected_notional / 800


def test_walk_asks_never_crosses_max_price() -> None:
    book = _book([(0.72, 500), (0.74, 300), (0.78, 900)])
    plan = walk_asks(book, max_price=0.75, target_notional=1_000_000)
    assert plan is not None
    assert plan.worst_price <= 0.75
    assert plan.shares == 800  # the 0.78 level must never be touched


def test_walk_asks_stops_at_target_notional() -> None:
    book = _book([(0.50, 1000)])
    plan = walk_asks(book, max_price=0.60, target_notional=100.0)
    assert plan is not None
    assert plan.notional <= 100.0 + 1e-9
    assert plan.shares == 200  # 100 / 0.50


def test_walk_asks_returns_none_when_nothing_executable() -> None:
    book = _book([(0.90, 500)])
    plan = walk_asks(book, max_price=0.75, target_notional=100.0)
    assert plan is None


def test_uses_actual_book_levels_not_displayed_percentage() -> None:
    """A 50%-looking market (mid ~0.50) can still have an unfavorable walked
    VWAP once real depth is consumed — the edge calc must reflect that."""
    book = _book([(0.50, 10), (0.90, 1000)])
    plan = walk_asks(book, max_price=0.95, target_notional=500.0)
    assert plan is not None
    # 10 shares @ 0.50 then the remainder at 0.90 - VWAP is much worse than 0.50.
    assert plan.vwap > 0.80


def test_net_edge_subtracts_full_cost_stack() -> None:
    book = _book([(0.60, 1000)])
    plan = walk_asks(book, max_price=0.70, target_notional=600.0)
    assert plan is not None
    costs = build_cost_stack(
        RiskConfig(
            taker_fee_rate=0.01,
            expected_slippage=0.01,
            execution_delay_buffer=0.01,
            feed_latency_buffer=0.01,
            model_uncertainty_buffer=0.01,
            failed_fill_buffer=0.01,
        ),
        executable_price=plan.vwap,
        market_taker_fee_bps=0.0,
        model_uncertainty_extra=0.0,
        seconds_remaining=200.0,
        endgame_ramp_s=15.0,
        endgame_extra_buffer=0.05,
    )
    gross, net = net_edge(0.90, plan, costs)
    assert gross == 0.90 - 0.60
    # 5 buffers of ~0.01 each plus the 1% taker fee on price 0.60.
    assert net < gross
    assert net == gross - costs.total


def test_cost_stack_grows_inside_endgame_ramp() -> None:
    risk = RiskConfig()
    far = build_cost_stack(
        risk,
        executable_price=0.5,
        market_taker_fee_bps=0.0,
        model_uncertainty_extra=0.0,
        seconds_remaining=200.0,
        endgame_ramp_s=15.0,
        endgame_extra_buffer=0.05,
    )
    near = build_cost_stack(
        risk,
        executable_price=0.5,
        market_taker_fee_bps=0.0,
        model_uncertainty_extra=0.0,
        seconds_remaining=1.0,
        endgame_ramp_s=15.0,
        endgame_extra_buffer=0.05,
    )
    assert near.total > far.total
