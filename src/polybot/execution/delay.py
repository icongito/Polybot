"""Measurement of actual execution delays.

Polymarket applies a configured taker-order delay; we never trust the
documented value — we measure submission -> acknowledgement -> fill from our
own order lifecycle and expose rolling quantiles that feed the execution
delay buffer and the paper fill model.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from polybot.observability import metrics


@dataclass
class DelayTracker:
    window: int = 200
    submit_to_ack_s: deque[float] = field(default_factory=deque)
    ack_to_fill_s: deque[float] = field(default_factory=deque)
    _pending_submit_ns: dict[str, int] = field(default_factory=dict)
    _ack_ns: dict[str, int] = field(default_factory=dict)

    def on_submitted(self, order_id: str, submitted_ns: int) -> None:
        self._pending_submit_ns[order_id] = submitted_ns

    def on_acknowledged(self, order_id: str, ack_ns: int) -> None:
        submitted = self._pending_submit_ns.pop(order_id, None)
        self._ack_ns[order_id] = ack_ns
        if submitted is not None:
            delay = (ack_ns - submitted) / 1e9
            self._push(self.submit_to_ack_s, delay)
            metrics.SUBMIT_LATENCY.observe(delay)

    def on_fill(self, order_id: str, fill_ns: int) -> None:
        ack = self._ack_ns.pop(order_id, None)
        if ack is not None:
            self._push(self.ack_to_fill_s, (fill_ns - ack) / 1e9)

    def _push(self, series: deque[float], value: float) -> None:
        series.append(value)
        while len(series) > self.window:
            series.popleft()

    def quantile_submit_to_ack(self, q: float = 0.9) -> float | None:
        return _quantile(self.submit_to_ack_s, q)

    def quantile_ack_to_fill(self, q: float = 0.9) -> float | None:
        return _quantile(self.ack_to_fill_s, q)

    def suggested_delay_buffer(self, base_buffer: float) -> float:
        """Extra probability-units buffer implied by measured delays.

        Longer measured delays widen the buffer linearly (1s of delay ~ 1pt of
        price risk at 5-minute-market volatility; deliberately conservative).
        """
        measured = self.quantile_submit_to_ack(0.9)
        if measured is None:
            return base_buffer
        return max(base_buffer, min(0.10, measured * 0.01))


def _quantile(series: deque[float], q: float) -> float | None:
    if not series:
        return None
    ordered = sorted(series)
    index = min(len(ordered) - 1, max(0, int(q * (len(ordered) - 1))))
    return ordered[index]
