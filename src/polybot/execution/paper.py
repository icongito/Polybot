"""Paper execution: simulates marketable FAK limit orders against the real
(recorded or live) order book, modeling taker delay, stale-order
cancellation, partial fills, fees, and slippage.

The fill model is shared with the replay engine so paper results and replay
results are produced by the same code path.
"""

from __future__ import annotations

import logging
import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from polybot.bus import EventBus
from polybot.models.core import (
    BookSnapshot,
    Fill,
    OrderIntent,
    OrderRecord,
    OrderStatus,
)
from polybot.observability import metrics

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PaperFillParams:
    """Latency / adverse-selection model for simulated fills."""

    network_latency_s: float = 0.08
    signing_latency_s: float = 0.02
    taker_delay_s: float = 0.5
    cancellation_hazard_per_s: float = 0.35  # chance/second a resting level is pulled
    partial_fill_min_fraction: float = 0.3
    fee_rate: float = 0.0
    seed: int | None = None


class PaperExecutor:
    """Simulates execution; needs callbacks to read the book at a given time.

    ``book_at`` returns the book snapshot that is current at the simulated
    arrival time (for live paper mode this is simply the latest book; for
    replay it is the book reconstructed at ``arrival_ts``).
    ``market_end_ts`` returns the close time for an intent's market.
    """

    def __init__(
        self,
        bus: EventBus,
        params: PaperFillParams,
        *,
        book_at: Callable[[OrderIntent, float], BookSnapshot | None],
        market_end_ts: Callable[[OrderIntent], float],
        now_s: Callable[[], float],
    ) -> None:
        self.bus = bus
        self.params = params
        self._book_at = book_at
        self._market_end_ts = market_end_ts
        self._now_s = now_s
        self._rng = random.Random(params.seed)

    async def submit(self, intent: OrderIntent) -> OrderRecord:
        order_id = f"paper-{uuid.uuid4().hex[:16]}"
        submit_ts = self._now_s()
        arrival_ts = (
            submit_ts
            + self.params.signing_latency_s
            + self.params.network_latency_s
            + self.params.taker_delay_s
        )
        end_ts = self._market_end_ts(intent)
        if arrival_ts >= end_ts:
            return self._record(
                intent, order_id, OrderStatus.EXPIRED, "order arrived after market close", submit_ts
            )

        book = self._book_at(intent, arrival_ts)
        if book is None or not book.asks:
            return self._record(
                intent, order_id, OrderStatus.CANCELLED, "no book at simulated arrival", submit_ts
            )

        # Walk asks at arrival; each level survives cancellation with
        # probability exp-decay over the taker delay.
        survival = max(0.0, 1.0 - self.params.cancellation_hazard_per_s * self.params.taker_delay_s)
        filled = 0.0
        notional = 0.0
        for level in book.asks:
            if level.price > intent.limit_price:
                break
            if filled >= intent.size:
                break
            if self._rng.random() > survival:
                continue  # this level was cancelled before arrival
            available = level.size * (
                self.params.partial_fill_min_fraction
                + (1 - self.params.partial_fill_min_fraction) * self._rng.random()
            )
            take = min(available, intent.size - filled)
            filled += take
            notional += take * level.price
        if filled <= 0:
            return self._record(
                intent,
                order_id,
                OrderStatus.CANCELLED,
                "FAK found no surviving liquidity",
                submit_ts,
            )

        vwap = notional / filled
        fee = notional * self.params.fee_rate
        fill = Fill(
            order_id=order_id,
            signal_id=intent.signal_id,
            market_slug=intent.market_slug,
            asset=intent.asset,
            side=intent.side,
            token_id=intent.token_id,
            price=vwap,
            size=filled,
            fee=fee,
            fill_ts=arrival_ts,
            local_recv_ns=int(arrival_ts * 1e9),
            simulated=True,
        )
        self.bus.publish(fill)
        metrics.FILLS.labels(asset=intent.asset.value, mode=intent.mode.value).inc()
        metrics.FILL_NOTIONAL.labels(asset=intent.asset.value, mode=intent.mode.value).inc(notional)
        status = (
            OrderStatus.FILLED if filled >= intent.size * 0.999 else OrderStatus.PARTIALLY_FILLED
        )
        return self._record(
            intent,
            order_id,
            status,
            f"filled {filled:.1f}/{intent.size:.1f} @ {vwap:.4f}",
            submit_ts,
        )

    def _record(
        self,
        intent: OrderIntent,
        order_id: str,
        status: OrderStatus,
        detail: str,
        submit_ts: float,
    ) -> OrderRecord:
        metrics.ORDERS.labels(
            asset=intent.asset.value, status=status.value, mode=intent.mode.value
        ).inc()
        return OrderRecord(
            intent=intent,
            order_id=order_id,
            status=status,
            submitted_ns=int(submit_ts * 1e9),
            acknowledged_ns=int((submit_ts + self.params.network_latency_s) * 1e9),
            detail=detail,
        )
