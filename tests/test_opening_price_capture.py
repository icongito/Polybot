from polybot.bus import EventBus
from polybot.clock import SimClock
from polybot.config import DiscoveryConfig
from polybot.discovery.scheduler import IntervalState, MarketScheduler
from polybot.models.core import (
    Asset,
    FeedSource,
    MarketInfo,
    OpeningPrice,
    ResolutionRules,
    Tick,
)

RULES = ResolutionRules(
    raw_description="Resolves Up if Chainlink price >= open.",
    resolution_source="Chainlink",
    references_chainlink=True,
    up_wins_on_equal=True,
    interval_start_ts=1_000.0,
    interval_end_ts=1_300.0,
    valid=True,
)


def _market(start_ts: float = 1_000.0) -> MarketInfo:
    return MarketInfo(
        slug="btc-updown-5m-1000",
        asset=Asset.BTC,
        condition_id="c1",
        up_token_id="up1",
        down_token_id="down1",
        start_ts=start_ts,
        end_ts=start_ts + 300,
        tick_size=0.01,
        rules=RULES,
        discovered_at_ns=0,
    )


def _scheduler() -> MarketScheduler:
    return MarketScheduler(
        config=DiscoveryConfig(),
        discovery=None,  # type: ignore[arg-type]
        bus=EventBus(),
        clock=SimClock(),
        assets=[Asset.BTC],
    )


def _tick(provider_ts: float, price: float, source: FeedSource = FeedSource.RTDS_CHAINLINK) -> Tick:
    return Tick(
        source=source,
        asset=Asset.BTC,
        symbol="btc/usd",
        provider_ts=provider_ts,
        local_recv_ns=int(provider_ts * 1e9),
        last=price,
    )


def test_opening_verified_when_pre_and_post_boundary_prints_agree() -> None:
    scheduler = _scheduler()
    market = _market()
    state = IntervalState(market=market)
    scheduler.current[Asset.BTC] = state

    scheduler.on_settlement_tick(_tick(998.0, 100.00))  # pre-boundary
    scheduler.on_settlement_tick(_tick(1000.1, 100.001))  # first at/after boundary

    assert state.opening is not None
    assert state.opening.verified
    assert state.opening.price == 100.001


def test_opening_unverified_without_pre_boundary_print() -> None:
    scheduler = _scheduler()
    state = IntervalState(market=_market())
    scheduler.current[Asset.BTC] = state

    scheduler.on_settlement_tick(_tick(1000.1, 100.0))

    assert state.opening is not None
    assert not state.opening.verified
    assert "no settlement print" in state.opening.verification_note


def test_opening_unverified_when_pre_post_prices_diverge() -> None:
    scheduler = _scheduler()
    state = IntervalState(market=_market())
    scheduler.current[Asset.BTC] = state

    scheduler.on_settlement_tick(_tick(998.0, 100.00))
    scheduler.on_settlement_tick(_tick(1000.1, 105.00))  # >> tolerance away

    assert state.opening is not None
    assert not state.opening.verified
    assert "diverge" in state.opening.verification_note


def test_opening_unverified_when_first_print_arrives_late() -> None:
    scheduler = _scheduler()
    state = IntervalState(market=_market())
    scheduler.current[Asset.BTC] = state

    scheduler.on_settlement_tick(_tick(990.0, 100.00))
    scheduler.on_settlement_tick(_tick(1015.0, 100.001))  # 15s after boundary

    assert state.opening is not None
    assert not state.opening.verified
    assert "after start" in state.opening.verification_note


def test_opening_only_captured_once_per_interval() -> None:
    scheduler = _scheduler()
    state = IntervalState(market=_market())
    scheduler.current[Asset.BTC] = state

    scheduler.on_settlement_tick(_tick(998.0, 100.00))
    scheduler.on_settlement_tick(_tick(1000.1, 100.001))
    first_opening: OpeningPrice = state.opening  # type: ignore[assignment]
    scheduler.on_settlement_tick(_tick(1050.0, 110.0))  # later move must not overwrite opening

    assert state.opening is first_opening
    assert state.opening.price == 100.001
