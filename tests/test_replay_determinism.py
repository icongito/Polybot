"""Replay engine: determinism and no-lookahead.

Builds a small synthetic capture file for one interval (market, opening,
a rising chainlink/exchange price path, order books, and the final result)
and checks that:

* Running replay twice over the identical file yields byte-identical
  probability/edge outputs (determinism).
* The strategy never sees book state from *after* the current simulated
  instant (no lookahead) — verified by asserting probabilities computed
  early in the interval do not already reflect the final, later price.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from polybot.config import AppConfig
from polybot.discovery.validation import validate_resolution_rules
from polybot.models.core import (
    Asset,
    BookLevel,
    BookSnapshot,
    FeedSource,
    MarketInfo,
    MarketResult,
    OpeningPrice,
    Side,
    Tick,
)
from polybot.recording.schema import CaptureEnvelope
from polybot.replay.engine import ReplayEngine

START_TS = 1_700_000_000.0
END_TS = START_TS + 300.0


def _market_info() -> MarketInfo:
    rules = validate_resolution_rules(
        "Resolves Up if the Chainlink price at close is higher than or equal to the "
        "price at open. Window 00:00:00 ET - 00:05:00 ET.",
        "Chainlink BTC/USD Data Streams",
        START_TS,
        END_TS,
    )
    return MarketInfo(
        slug="btc-updown-5m-1700000000",
        asset=Asset.BTC,
        condition_id="cond1",
        up_token_id="up-token",
        down_token_id="down-token",
        start_ts=START_TS,
        end_ts=END_TS,
        tick_size=0.01,
        rules=rules,
        discovered_at_ns=int(START_TS * 1e9),
    )


def _write_capture(path: Path) -> None:
    market = _market_info()
    envelopes: list[CaptureEnvelope] = []

    def add(tag: str, recv_ns: int, data: dict) -> None:  # type: ignore[type-arg]
        envelopes.append(CaptureEnvelope(t=tag, recv_ns=recv_ns, data=data))  # type: ignore[arg-type]

    add("market", int(START_TS * 1e9) - 10_000_000_000, json.loads(market.model_dump_json()))

    opening = OpeningPrice(
        asset=Asset.BTC,
        market_slug=market.slug,
        price=100.0,
        source=FeedSource.RTDS_CHAINLINK,
        provider_ts=START_TS,
        local_recv_ns=int(START_TS * 1e9),
        verified=True,
    )
    add("opening", int(START_TS * 1e9), json.loads(opening.model_dump_json()))

    # Price path: flat for the first 60s, then a steady rise to +2% by close.
    # The rise is what the strategy should only "see" progressively.
    n_steps = 60
    for i in range(n_steps):
        t = START_TS + 60.0 + i * (240.0 / n_steps)
        frac = i / (n_steps - 1)
        price = 100.0 + 2.0 * frac  # linear ramp to 102.0
        recv_ns = int(t * 1e9)
        chainlink_tick = Tick(
            source=FeedSource.RTDS_CHAINLINK,
            asset=Asset.BTC,
            symbol="btc/usd",
            provider_ts=t,
            local_recv_ns=recv_ns,
            last=price,
        )
        add("tick", recv_ns, json.loads(chainlink_tick.model_dump_json()))
        exch_tick = Tick(
            source=FeedSource.BINANCE_SPOT,
            asset=Asset.BTC,
            symbol="btcusdt",
            provider_ts=t,
            local_recv_ns=recv_ns,
            bid=price - 0.02,
            ask=price + 0.02,
        )
        add("tick", recv_ns, json.loads(exch_tick.model_dump_json()))

        up_price = 0.5 + 0.4 * frac  # order book roughly tracks the move
        book_up = BookSnapshot(
            token_id="up-token",
            asset=Asset.BTC,
            side=Side.UP,
            bids=(BookLevel(price=round(up_price - 0.02, 3), size=500),),
            asks=(BookLevel(price=round(up_price + 0.02, 3), size=500),),
            provider_ts=t,
            local_recv_ns=recv_ns,
        )
        add("book", recv_ns, json.loads(book_up.model_dump_json()))
        book_down = BookSnapshot(
            token_id="down-token",
            asset=Asset.BTC,
            side=Side.DOWN,
            bids=(BookLevel(price=round(0.48 - 0.4 * frac, 3), size=500),),
            asks=(BookLevel(price=round(0.52 - 0.4 * frac, 3), size=500),),
            provider_ts=t,
            local_recv_ns=recv_ns,
        )
        add("book", recv_ns, json.loads(book_down.model_dump_json()))

    result = MarketResult(
        market_slug=market.slug,
        asset=Asset.BTC,
        start_ts=START_TS,
        end_ts=END_TS,
        opening_price=100.0,
        closing_price=102.0,
        winner=Side.UP,
        opening_verified=True,
        resolved_at_ns=int(END_TS * 1e9),
    )
    add("result", int(END_TS * 1e9), json.loads(result.model_dump_json()))

    envelopes.sort(key=lambda e: e.recv_ns)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for env in envelopes:
            handle.write(env.model_dump_json() + "\n")


@pytest.fixture()
def capture_file(tmp_path: Path) -> Path:
    path = tmp_path / "btc-updown-5m-1700000000.ndjson.gz"
    _write_capture(path)
    return path


async def _run(capture_file: Path) -> ReplayEngine:
    config = AppConfig()
    engine = ReplayEngine(config, [Asset.BTC])
    await engine.run([capture_file])
    return engine


@pytest.mark.asyncio()
async def test_replay_is_deterministic(capture_file: Path) -> None:
    engine1 = await _run(capture_file)
    engine2 = await _run(capture_file)

    probs1 = [s.probability for s in engine1.result.signals]
    probs2 = [s.probability for s in engine2.result.signals]
    assert probs1 == probs2
    assert len(probs1) > 0

    edges1 = [s.net_edge for s in engine1.result.signals]
    edges2 = [s.net_edge for s in engine2.result.signals]
    assert edges1 == edges2


@pytest.mark.asyncio()
async def test_replay_signal_ordering_is_monotonic_in_sim_time(capture_file: Path) -> None:
    """Signals must be produced in non-decreasing simulated time -- the
    engine advances a SimClock strictly forward and never revisits the past."""
    engine = await _run(capture_file)
    timestamps = [s.created_ns for s in engine.result.signals]
    assert timestamps == sorted(timestamps)


@pytest.mark.asyncio()
async def test_replay_does_not_leak_future_price_into_early_signals(capture_file: Path) -> None:
    """No-lookahead: a signal generated 200s before close (price still near
    the open) must not already reflect the size of the eventual +2% move --
    its distance-from-open should be small, not the final 2.0 value."""
    engine = await _run(capture_file)
    early_signals = [s for s in engine.result.signals if s.seconds_remaining > 200.0]
    assert early_signals, "expected at least one signal early in the interval"
    for signal in early_signals:
        assert abs(signal.chainlink_distance) < 0.5, (
            f"early signal at seconds_remaining={signal.seconds_remaining} already reflects "
            f"a late-interval move: distance={signal.chainlink_distance}"
        )


@pytest.mark.asyncio()
async def test_replay_records_the_market_result(capture_file: Path) -> None:
    engine = await _run(capture_file)
    assert len(engine.result.results) == 1
    assert engine.result.results[0].winner is Side.UP
    assert engine.result.results[0].opening_price == 100.0
    assert engine.result.results[0].closing_price == 102.0
