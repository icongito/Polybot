import pytest

from polybot.bus import EventBus
from polybot.execution.paper import PaperExecutor, PaperFillParams
from polybot.models.core import (
    Asset,
    BookLevel,
    BookSnapshot,
    Fill,
    OrderIntent,
    OrderStatus,
    Side,
    TradingMode,
)


def _book(ask_price: float = 0.60, size: float = 500) -> BookSnapshot:
    return BookSnapshot(
        token_id="up-token",
        asset=Asset.BTC,
        side=Side.UP,
        asks=(BookLevel(price=ask_price, size=size),),
        provider_ts=0.0,
        local_recv_ns=0,
    )


def _intent(limit_price: float = 0.65, size: float = 100.0) -> OrderIntent:
    return OrderIntent(
        signal_id="sig1",
        market_slug="btc-updown-5m-0",
        asset=Asset.BTC,
        side=Side.UP,
        token_id="up-token",
        limit_price=limit_price,
        size=size,
        max_notional=size * limit_price,
        created_ns=0,
        mode=TradingMode.PAPER,
    )


@pytest.mark.asyncio()
async def test_paper_executor_fills_against_the_walked_book() -> None:
    bus = EventBus()
    sub = bus.subscribe("test", lossless=True)
    params = PaperFillParams(
        network_latency_s=0.0,
        signing_latency_s=0.0,
        taker_delay_s=0.0,
        cancellation_hazard_per_s=0.0,
        partial_fill_min_fraction=1.0,
        seed=1,
    )
    executor = PaperExecutor(
        bus,
        params,
        book_at=lambda intent, ts: _book(),
        market_end_ts=lambda intent: 300.0,
        now_s=lambda: 100.0,
    )
    record = await executor.submit(_intent(limit_price=0.65, size=100.0))
    assert record.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)
    fill = sub.queue.get_nowait()
    assert isinstance(fill, Fill)
    assert fill.price == 0.60
    assert fill.size == 100.0
    assert fill.simulated


@pytest.mark.asyncio()
async def test_paper_executor_expires_orders_arriving_after_close() -> None:
    bus = EventBus()
    params = PaperFillParams(
        network_latency_s=10.0,
        signing_latency_s=10.0,
        taker_delay_s=10.0,
    )
    executor = PaperExecutor(
        bus,
        params,
        book_at=lambda intent, ts: _book(),
        market_end_ts=lambda intent: 100.0,  # closes almost immediately
        now_s=lambda: 99.0,  # arrival will land well past 100.0
    )
    record = await executor.submit(_intent())
    assert record.status == OrderStatus.EXPIRED


@pytest.mark.asyncio()
async def test_paper_executor_cancels_when_no_liquidity_survives() -> None:
    bus = EventBus()
    params = PaperFillParams(cancellation_hazard_per_s=1000.0, taker_delay_s=1.0, seed=1)
    executor = PaperExecutor(
        bus,
        params,
        book_at=lambda intent, ts: _book(),
        market_end_ts=lambda intent: 300.0,
        now_s=lambda: 100.0,
    )
    record = await executor.submit(_intent())
    assert record.status == OrderStatus.CANCELLED


@pytest.mark.asyncio()
async def test_paper_executor_never_fills_above_limit_price() -> None:
    bus = EventBus()
    params = PaperFillParams(
        network_latency_s=0.0,
        signing_latency_s=0.0,
        taker_delay_s=0.0,
        cancellation_hazard_per_s=0.0,
        partial_fill_min_fraction=1.0,
        seed=1,
    )
    executor = PaperExecutor(
        bus,
        params,
        book_at=lambda intent, ts: _book(ask_price=0.90),  # above our limit
        market_end_ts=lambda intent: 300.0,
        now_s=lambda: 100.0,
    )
    record = await executor.submit(_intent(limit_price=0.65))
    assert record.status == OrderStatus.CANCELLED
