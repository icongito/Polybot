from polybot.config import ExecutionConfig, RiskConfig
from polybot.discovery.validation import validate_resolution_rules
from polybot.execution.precheck import pre_submission_check
from polybot.models.core import (
    Asset,
    BookLevel,
    BookSnapshot,
    FeedSource,
    MarketInfo,
    OpeningPrice,
    OrderIntent,
    Side,
    Signal,
    SignalDecision,
    Tick,
    TradingMode,
)
from polybot.pricing.state import AssetState, MarketView
from polybot.pricing.vol import RealizedVol


def _market() -> MarketInfo:
    rules = validate_resolution_rules(
        "Resolves Up if Chainlink price >= open. Window 00:00:00 ET - 00:05:00 ET.",
        "Chainlink",
        0.0,
        300.0,
    )
    return MarketInfo(
        slug="btc-updown-5m-0",
        asset=Asset.BTC,
        condition_id="c",
        up_token_id="u",
        down_token_id="d",
        start_ts=0.0,
        end_ts=300.0,
        tick_size=0.01,
        rules=rules,
        discovered_at_ns=0,
    )


def _fresh_view_and_state(now_ns: int, *, ask_price: float = 0.63) -> tuple[MarketView, AssetState]:
    market = _market()
    view = MarketView(market=market)
    view.opening = OpeningPrice(
        asset=Asset.BTC,
        market_slug=market.slug,
        price=100.0,
        source=FeedSource.RTDS_CHAINLINK,
        provider_ts=0.0,
        local_recv_ns=0,
        verified=True,
    )
    view.books[Side.UP] = BookSnapshot(
        token_id="u",
        asset=Asset.BTC,
        side=Side.UP,
        asks=(BookLevel(price=ask_price, size=500),),
        bids=(BookLevel(price=ask_price - 0.02, size=500),),
        provider_ts=now_ns / 1e9,
        local_recv_ns=now_ns,
    )
    state = AssetState(Asset.BTC, RealizedVol(60.0, 1e-6, 1))
    state.chainlink = Tick(
        source=FeedSource.RTDS_CHAINLINK,
        asset=Asset.BTC,
        symbol="btc/usd",
        provider_ts=now_ns / 1e9,
        local_recv_ns=now_ns,
        last=100.5,
    )
    state.exchange_ticks[FeedSource.BINANCE_SPOT] = Tick(
        source=FeedSource.BINANCE_SPOT,
        asset=Asset.BTC,
        symbol="btcusdt",
        provider_ts=now_ns / 1e9,
        local_recv_ns=now_ns,
        bid=100.4,
        ask=100.6,
    )
    return view, state


def _signal(now_ns: int, executable_price: float = 0.63, probability: float = 0.85) -> Signal:
    return Signal(
        id="sig1",
        market_slug="btc-updown-5m-0",
        asset=Asset.BTC,
        side=Side.UP,
        created_ns=now_ns,
        seconds_remaining=200.0,
        chainlink_price=100.5,
        opening_price=100.0,
        chainlink_distance=0.5,
        chainlink_return=0.005,
        probability=probability,
        probability_baseline=probability,
        probability_empirical=None,
        model_disagreement=0.0,
        executable_price=executable_price,
        executable_size=500.0,
        gross_edge=0.22,
        net_edge=0.15,
        decision=SignalDecision.TRADE,
    )


def _intent(now_ns: int, limit_price: float = 0.63) -> OrderIntent:
    return OrderIntent(
        signal_id="sig1",
        market_slug="btc-updown-5m-0",
        asset=Asset.BTC,
        side=Side.UP,
        token_id="u",
        limit_price=limit_price,
        size=50.0,
        max_notional=31.5,
        created_ns=now_ns,
        mode=TradingMode.PAPER,
    )


def test_precheck_passes_when_nothing_has_moved() -> None:
    now_ns = 100_000_000_000
    view, state = _fresh_view_and_state(now_ns)
    result = pre_submission_check(
        _intent(now_ns),
        _signal(now_ns),
        view,
        state,
        now_s=now_ns / 1e9,
        now_ns=now_ns,
        exec_config=ExecutionConfig(),
        risk_config=RiskConfig(),
        fresh_probability=0.85,
    )
    assert result.ok
    assert not result.problems


def test_precheck_aborts_when_ask_price_moved_beyond_tolerance() -> None:
    now_ns = 100_000_000_000
    # Book now shows a materially worse ask than what the signal was built on.
    view, state = _fresh_view_and_state(now_ns, ask_price=0.80)
    result = pre_submission_check(
        _intent(now_ns),
        _signal(now_ns, executable_price=0.63),
        view,
        state,
        now_s=now_ns / 1e9,
        now_ns=now_ns,
        exec_config=ExecutionConfig(precheck_price_tolerance=0.01),
        risk_config=RiskConfig(),
        fresh_probability=0.85,
    )
    assert not result.ok
    assert any("vwap moved" in p or "liquidity" in p for p in result.problems)


def test_precheck_aborts_when_opening_price_no_longer_verified() -> None:
    now_ns = 100_000_000_000
    view, state = _fresh_view_and_state(now_ns)
    view.opening = OpeningPrice(
        asset=Asset.BTC,
        market_slug=view.market.slug,
        price=100.0,
        source=FeedSource.RTDS_CHAINLINK,
        provider_ts=0.0,
        local_recv_ns=0,
        verified=False,
    )
    result = pre_submission_check(
        _intent(now_ns),
        _signal(now_ns),
        view,
        state,
        now_s=now_ns / 1e9,
        now_ns=now_ns,
        exec_config=ExecutionConfig(),
        risk_config=RiskConfig(),
        fresh_probability=0.85,
    )
    assert not result.ok
    assert any("opening price" in p for p in result.problems)


def test_precheck_aborts_when_market_already_closed() -> None:
    now_ns = 100_000_000_000
    view, state = _fresh_view_and_state(now_ns)
    result = pre_submission_check(
        _intent(now_ns),
        _signal(now_ns),
        view,
        state,
        now_s=view.market.end_ts + 1.0,
        now_ns=now_ns,  # past close
        exec_config=ExecutionConfig(),
        risk_config=RiskConfig(),
        fresh_probability=0.85,
    )
    assert not result.ok
    assert any("closed" in p for p in result.problems)


def test_precheck_aborts_when_signal_is_stale() -> None:
    now_ns = 100_000_000_000
    view, state = _fresh_view_and_state(now_ns)
    late_ns = now_ns + int(2 * 1e9)  # 2s later
    result = pre_submission_check(
        _intent(now_ns),
        _signal(now_ns),
        view,
        state,
        now_s=late_ns / 1e9,
        now_ns=late_ns,
        exec_config=ExecutionConfig(precheck_max_signal_age_s=0.75),
        risk_config=RiskConfig(),
        fresh_probability=0.85,
    )
    assert not result.ok
    assert any("aged" in p for p in result.problems)


def test_precheck_aborts_when_probability_moved_beyond_tolerance() -> None:
    now_ns = 100_000_000_000
    view, state = _fresh_view_and_state(now_ns)
    result = pre_submission_check(
        _intent(now_ns),
        _signal(now_ns, probability=0.85),
        view,
        state,
        now_s=now_ns / 1e9,
        now_ns=now_ns,
        exec_config=ExecutionConfig(precheck_probability_tolerance=0.03),
        risk_config=RiskConfig(),
        fresh_probability=0.60,  # model re-evaluated much lower on recheck
    )
    assert not result.ok
    assert any("probability moved" in p for p in result.problems)
