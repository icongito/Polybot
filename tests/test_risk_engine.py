from pathlib import Path

from polybot.clock import DriftMonitor
from polybot.config import RiskConfig
from polybot.discovery.validation import validate_resolution_rules
from polybot.feeds.health import HealthReport
from polybot.models.core import (
    Asset,
    BookLevel,
    BookSnapshot,
    FeedSource,
    MarketInfo,
    OpeningPrice,
    Side,
    Tick,
)
from polybot.pricing.state import AssetState, MarketView
from polybot.pricing.vol import RealizedVol
from polybot.risk.engine import GeoGate, KillSwitch, RiskCheckInput, RiskEngine


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


def _healthy_view(now_ns: int) -> tuple[MarketView, AssetState, BookSnapshot]:
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
    book = BookSnapshot(
        token_id="u",
        asset=Asset.BTC,
        side=Side.UP,
        bids=(BookLevel(price=0.60, size=500),),
        asks=(BookLevel(price=0.63, size=500),),
        provider_ts=now_ns / 1e9,
        local_recv_ns=now_ns,
    )
    view.books[Side.UP] = book
    return view, state, book


def _engine(risk_config: RiskConfig | None = None) -> RiskEngine:
    drift = DriftMonitor(0.25)
    drift.last_offset_s = 0.0
    return RiskEngine(
        config=risk_config or RiskConfig(),
        drift=drift,
        kill_switch=KillSwitch(file_path=str(Path("/nonexistent-kill-file"))),
        geo=GeoGate(eligible=True, attestation="ok"),
    )


def test_all_checks_pass_for_healthy_signal() -> None:
    now_ns = 100_000_000_000
    view, state, book = _healthy_view(now_ns)
    engine = _engine()
    inp = RiskCheckInput(
        view=view,
        state=state,
        book=book,
        probability=0.85,
        executable_vwap=0.63,
        executable_notional=31.5,
        net_edge=0.10,
        expected_profit_usd=5.0,
        signal_created_ns=now_ns,
        seconds_remaining=200.0,
        health=HealthReport(healthy=True),
        now_ns=now_ns,
    )
    assert engine.check(inp) == []


def test_kill_switch_blocks_all_trading() -> None:
    now_ns = 100_000_000_000
    view, state, book = _healthy_view(now_ns)
    engine = _engine()
    engine.kill_switch.engage("manual stop")
    inp = RiskCheckInput(
        view=view,
        state=state,
        book=book,
        probability=0.85,
        executable_vwap=0.63,
        executable_notional=31.5,
        net_edge=0.10,
        expected_profit_usd=5.0,
        signal_created_ns=now_ns,
        seconds_remaining=200.0,
        health=HealthReport(healthy=True),
        now_ns=now_ns,
    )
    problems = engine.check(inp)
    assert any("kill switch" in p for p in problems)


def test_net_edge_below_minimum_is_rejected() -> None:
    now_ns = 100_000_000_000
    view, state, book = _healthy_view(now_ns)
    engine = _engine(RiskConfig(min_net_edge=0.05))
    inp = RiskCheckInput(
        view=view,
        state=state,
        book=book,
        probability=0.85,
        executable_vwap=0.63,
        executable_notional=31.5,
        net_edge=0.01,
        expected_profit_usd=5.0,
        signal_created_ns=now_ns,
        seconds_remaining=200.0,
        health=HealthReport(healthy=True),
        now_ns=now_ns,
    )
    problems = engine.check(inp)
    assert any("net edge" in p for p in problems)


def test_stale_chainlink_feed_is_rejected() -> None:
    now_ns = 100_000_000_000
    view, state, book = _healthy_view(now_ns)
    # chainlink tick is 10s stale relative to "now".
    stale_now_ns = now_ns + 10_000_000_000
    engine = _engine(RiskConfig(max_chainlink_age_s=5.0))
    inp = RiskCheckInput(
        view=view,
        state=state,
        book=book,
        probability=0.85,
        executable_vwap=0.63,
        executable_notional=31.5,
        net_edge=0.10,
        expected_profit_usd=5.0,
        signal_created_ns=stale_now_ns,
        seconds_remaining=200.0,
        health=HealthReport(healthy=True),
        now_ns=stale_now_ns,
    )
    problems = engine.check(inp)
    assert any("chainlink" in p for p in problems)


def test_stake_per_trade_cap_is_enforced() -> None:
    now_ns = 100_000_000_000
    view, state, book = _healthy_view(now_ns)
    engine = _engine(RiskConfig(max_stake_per_trade_usd=10.0))
    inp = RiskCheckInput(
        view=view,
        state=state,
        book=book,
        probability=0.85,
        executable_vwap=0.63,
        executable_notional=31.5,
        net_edge=0.10,
        expected_profit_usd=5.0,
        signal_created_ns=now_ns,
        seconds_remaining=200.0,
        health=HealthReport(healthy=True),
        now_ns=now_ns,
    )
    problems = engine.check(inp)
    assert any("stake per trade" in p for p in problems)


def test_max_orders_per_interval_is_enforced() -> None:
    now_ns = 100_000_000_000
    view, state, book = _healthy_view(now_ns)
    view.orders_submitted = 5
    engine = _engine(RiskConfig(max_orders_per_interval=2))
    inp = RiskCheckInput(
        view=view,
        state=state,
        book=book,
        probability=0.85,
        executable_vwap=0.63,
        executable_notional=31.5,
        net_edge=0.10,
        expected_profit_usd=5.0,
        signal_created_ns=now_ns,
        seconds_remaining=200.0,
        health=HealthReport(healthy=True),
        now_ns=now_ns,
    )
    problems = engine.check(inp)
    assert any("orders per interval" in p for p in problems)


def test_unhealthy_feeds_block_trading() -> None:
    now_ns = 100_000_000_000
    view, state, book = _healthy_view(now_ns)
    engine = _engine()
    inp = RiskCheckInput(
        view=view,
        state=state,
        book=book,
        probability=0.85,
        executable_vwap=0.63,
        executable_notional=31.5,
        net_edge=0.10,
        expected_profit_usd=5.0,
        signal_created_ns=now_ns,
        seconds_remaining=200.0,
        health=HealthReport(healthy=False, problems=["no fresh settlement feed"]),
        now_ns=now_ns,
    )
    problems = engine.check(inp)
    assert any("feed health" in p for p in problems)


def test_geo_ineligibility_blocks_trading() -> None:
    now_ns = 100_000_000_000
    view, state, book = _healthy_view(now_ns)
    drift = DriftMonitor(0.25)
    drift.last_offset_s = 0.0
    engine = RiskEngine(
        config=RiskConfig(),
        drift=drift,
        kill_switch=KillSwitch(file_path="/nonexistent-kill-file"),
        geo=GeoGate(eligible=False, attestation=""),
    )
    inp = RiskCheckInput(
        view=view,
        state=state,
        book=book,
        probability=0.85,
        executable_vwap=0.63,
        executable_notional=31.5,
        net_edge=0.10,
        expected_profit_usd=5.0,
        signal_created_ns=now_ns,
        seconds_remaining=200.0,
        health=HealthReport(healthy=True),
        now_ns=now_ns,
    )
    problems = engine.check(inp)
    assert any("geographic" in p for p in problems)


def test_unknown_clock_drift_blocks_trading() -> None:
    now_ns = 100_000_000_000
    view, state, book = _healthy_view(now_ns)
    drift = DriftMonitor(0.25)  # never measured -> last_offset_s is None
    engine = RiskEngine(
        config=RiskConfig(),
        drift=drift,
        kill_switch=KillSwitch(file_path="/nonexistent-kill-file"),
        geo=GeoGate(eligible=True, attestation="ok"),
    )
    inp = RiskCheckInput(
        view=view,
        state=state,
        book=book,
        probability=0.85,
        executable_vwap=0.63,
        executable_notional=31.5,
        net_edge=0.10,
        expected_profit_usd=5.0,
        signal_created_ns=now_ns,
        seconds_remaining=200.0,
        health=HealthReport(healthy=True),
        now_ns=now_ns,
    )
    problems = engine.check(inp)
    assert any("drift" in p for p in problems)


def test_kill_switch_with_no_file_path_starts_disengaged() -> None:
    """Regression: file_path=None must disable the file check entirely.

    A sentinel path like /dev/null looks unused but always exists on disk,
    so Path(...).exists() would silently and permanently engage the switch.
    Replay explicitly passes file_path=None for exactly this reason.
    """
    switch = KillSwitch(file_path=None)
    assert not switch.engaged


def test_kill_switch_engage_sets_reason() -> None:
    switch = KillSwitch(file_path=None)
    switch.engage("manual")
    assert switch.engaged
    assert switch.engaged_reason == "manual"


def test_kill_switch_dev_null_would_have_falsely_engaged() -> None:
    """Documents the failure mode the fix above prevents."""
    switch = KillSwitch(file_path="/dev/null")
    assert switch.engaged
