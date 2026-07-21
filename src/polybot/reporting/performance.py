"""Performance report: aggregates recorded/replayed signals, orders, fills,
and results into every metric the spec requires, with breakdowns."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from polybot.models.core import (
    Fill,
    MarketResult,
    OrderRecord,
    OrderStatus,
    Signal,
    SignalDecision,
)

SECONDS_BUCKETS = (5, 15, 30, 60, 120, 300)
DISTANCE_BUCKETS_BPS = (2, 5, 10, 25, 50, 100)
PROBABILITY_BUCKETS = (0.55, 0.65, 0.75, 0.85, 0.95, 1.01)
DIVERGENCE_BUCKETS_BPS = (1, 2, 5, 10, 20)


def _bucket(value: float, edges: tuple[float, ...]) -> str:
    for edge in edges:
        if value <= edge:
            return f"<= {edge}"
    return f"> {edges[-1]}"


@dataclass
class BucketStats:
    signals: int = 0
    trades: int = 0
    fills: int = 0
    net_pnl_usd: float = 0.0
    wins: int = 0

    def accuracy(self) -> float | None:
        return self.wins / self.fills if self.fills else None


@dataclass
class PerformanceReport:
    markets_observed: int = 0
    signals_generated: int = 0
    signals_rejected: int = 0
    trades_simulated: int = 0
    trades_filled: int = 0
    fill_rate: float | None = None
    accuracy: float | None = None
    gross_pnl_usd: float = 0.0
    net_pnl_usd: float = 0.0
    fees_usd: float = 0.0
    slippage_usd: float = 0.0
    max_drawdown_usd: float = 0.0
    avg_predicted_probability: float | None = None
    avg_entry_price: float | None = None
    avg_theoretical_edge: float | None = None
    avg_realized_edge: float | None = None
    avg_event_to_submission_latency_s: float | None = None
    avg_submission_to_fill_latency_s: float | None = None
    by_asset: dict[str, BucketStats] = field(default_factory=dict)
    by_seconds_remaining: dict[str, BucketStats] = field(default_factory=dict)
    by_distance_bps: dict[str, BucketStats] = field(default_factory=dict)
    by_entry_probability: dict[str, BucketStats] = field(default_factory=dict)
    by_divergence_bps: dict[str, BucketStats] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "markets_observed": self.markets_observed,
            "signals_generated": self.signals_generated,
            "signals_rejected": self.signals_rejected,
            "trades_simulated": self.trades_simulated,
            "trades_filled": self.trades_filled,
            "fill_rate": self.fill_rate,
            "accuracy": self.accuracy,
            "gross_pnl_usd": self.gross_pnl_usd,
            "net_pnl_usd": self.net_pnl_usd,
            "fees_usd": self.fees_usd,
            "slippage_usd": self.slippage_usd,
            "max_drawdown_usd": self.max_drawdown_usd,
            "avg_predicted_probability": self.avg_predicted_probability,
            "avg_entry_price": self.avg_entry_price,
            "avg_theoretical_edge": self.avg_theoretical_edge,
            "avg_realized_edge": self.avg_realized_edge,
            "avg_event_to_submission_latency_s": self.avg_event_to_submission_latency_s,
            "avg_submission_to_fill_latency_s": self.avg_submission_to_fill_latency_s,
            "by_asset": {k: vars(v) for k, v in self.by_asset.items()},
            "by_seconds_remaining": {k: vars(v) for k, v in self.by_seconds_remaining.items()},
            "by_distance_bps": {k: vars(v) for k, v in self.by_distance_bps.items()},
            "by_entry_probability": {k: vars(v) for k, v in self.by_entry_probability.items()},
            "by_divergence_bps": {k: vars(v) for k, v in self.by_divergence_bps.items()},
        }


def build_report(
    *,
    markets: list[MarketResult],
    signals: list[Signal],
    orders: list[OrderRecord],
    fills: list[Fill],
) -> PerformanceReport:
    report = PerformanceReport()
    report.markets_observed = len(markets)
    report.signals_generated = len(signals)
    report.signals_rejected = sum(1 for s in signals if s.decision is SignalDecision.REJECT)

    trade_signals = [s for s in signals if s.decision is SignalDecision.TRADE]
    report.trades_simulated = len(trade_signals)
    filled_orders = [
        o for o in orders if o.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)
    ]
    report.trades_filled = len(filled_orders)
    report.fill_rate = (
        report.trades_filled / report.trades_simulated if report.trades_simulated else None
    )

    if trade_signals:
        report.avg_predicted_probability = statistics.fmean(s.probability for s in trade_signals)
        entry_prices = [s.executable_price for s in trade_signals if s.executable_price is not None]
        if entry_prices:
            report.avg_entry_price = statistics.fmean(entry_prices)
        gross_edges = [s.gross_edge for s in trade_signals if s.gross_edge is not None]
        if gross_edges:
            report.avg_theoretical_edge = statistics.fmean(gross_edges)

    results_by_slug = {r.market_slug: r for r in markets}
    signal_by_id = {s.id: s for s in signals}

    realized_edges: list[float] = []
    submit_latencies: list[float] = []
    fill_latencies: list[float] = []
    for order in orders:
        if order.submitted_ns is not None:
            submit_latencies.append((order.submitted_ns - order.intent.created_ns) / 1e9)

    running_pnl = 0.0
    peak_pnl = 0.0
    max_dd = 0.0
    wins = 0

    order_by_id = {o.order_id: o for o in orders if o.order_id}
    for fill in fills:
        result = results_by_slug.get(fill.market_slug)
        signal = signal_by_id.get(fill.signal_id)
        matched_order = order_by_id.get(fill.order_id)
        if matched_order is not None and matched_order.submitted_ns is not None:
            fill_latencies.append(fill.local_recv_ns / 1e9 - matched_order.submitted_ns / 1e9)

        report.fees_usd += fill.fee
        won: bool | None = None
        pnl = -fill.fee
        if result is not None and result.winner is not None:
            won = result.winner is fill.side
            payoff = fill.size if won else 0.0
            pnl += payoff - fill.price * fill.size
            report.gross_pnl_usd += payoff - fill.price * fill.size
            wins += 1 if won else 0
        running_pnl += pnl
        peak_pnl = max(peak_pnl, running_pnl)
        max_dd = max(max_dd, peak_pnl - running_pnl)

        if signal is not None:
            realized_edges.append(signal.probability - fill.price)
            _bump(report.by_asset, fill.asset.value, pnl, won)
            _bump(
                report.by_seconds_remaining,
                _bucket(signal.seconds_remaining, SECONDS_BUCKETS),
                pnl,
                won,
            )
            distance_bps = abs(signal.chainlink_return) * 10_000
            _bump(report.by_distance_bps, _bucket(distance_bps, DISTANCE_BUCKETS_BPS), pnl, won)
            _bump(
                report.by_entry_probability,
                _bucket(signal.probability, PROBABILITY_BUCKETS),
                pnl,
                won,
            )
            divergence_bps = abs(signal.costs.get("model_uncertainty_buffer", 0.0)) * 10_000
            _bump(
                report.by_divergence_bps, _bucket(divergence_bps, DIVERGENCE_BUCKETS_BPS), pnl, won
            )

    report.net_pnl_usd = running_pnl
    report.max_drawdown_usd = max_dd
    report.accuracy = wins / len(fills) if fills else None
    if realized_edges:
        report.avg_realized_edge = statistics.fmean(realized_edges)
    if submit_latencies:
        report.avg_event_to_submission_latency_s = statistics.fmean(submit_latencies)
    if fill_latencies:
        report.avg_submission_to_fill_latency_s = statistics.fmean(fill_latencies)

    _fill_bucket_signal_counts(report, trade_signals)
    return report


def _bump(buckets: dict[str, BucketStats], key: str, pnl: float, won: bool | None) -> None:
    stats = buckets.setdefault(key, BucketStats())
    stats.fills += 1
    stats.net_pnl_usd += pnl
    if won:
        stats.wins += 1


def _fill_bucket_signal_counts(report: PerformanceReport, trade_signals: list[Signal]) -> None:
    for signal in trade_signals:
        for buckets, key in (
            (report.by_asset, signal.asset.value),
            (report.by_seconds_remaining, _bucket(signal.seconds_remaining, SECONDS_BUCKETS)),
            (
                report.by_distance_bps,
                _bucket(abs(signal.chainlink_return) * 10_000, DISTANCE_BUCKETS_BPS),
            ),
            (report.by_entry_probability, _bucket(signal.probability, PROBABILITY_BUCKETS)),
            (
                report.by_divergence_bps,
                _bucket(
                    signal.costs.get("model_uncertainty_buffer", 0.0) * 10_000,
                    DIVERGENCE_BUCKETS_BPS,
                ),
            ),
        ):
            buckets.setdefault(key, BucketStats()).trades += 1
