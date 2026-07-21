"""Prometheus metrics registry and HTTP exporter."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, start_http_server

FEED_MESSAGES = Counter("polybot_feed_messages_total", "Messages received per feed", ["source"])
FEED_RECONNECTS = Counter("polybot_feed_reconnects_total", "Feed reconnect attempts", ["source"])
FEED_AGE = Gauge("polybot_feed_age_seconds", "Seconds since last message per feed", ["source"])
FEED_LATENCY = Histogram(
    "polybot_feed_latency_seconds",
    "provider_ts -> local receive latency",
    ["source"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
CLOCK_DRIFT = Gauge("polybot_clock_drift_seconds", "Measured local clock drift")
MARKETS_DISCOVERED = Counter("polybot_markets_discovered_total", "Markets discovered", ["asset"])
MARKETS_COMPLETED = Counter("polybot_markets_completed_total", "Markets fully recorded", ["asset"])
SIGNALS = Counter("polybot_signals_total", "Signals generated", ["asset", "decision"])
SIGNAL_NET_EDGE = Histogram(
    "polybot_signal_net_edge",
    "Net edge of trade-decision signals",
    ["asset"],
    buckets=(0.0, 0.01, 0.02, 0.03, 0.05, 0.08, 0.12, 0.2, 0.5),
)
ORDERS = Counter("polybot_orders_total", "Orders by status", ["asset", "status", "mode"])
FILLS = Counter("polybot_fills_total", "Fills", ["asset", "mode"])
FILL_NOTIONAL = Counter("polybot_fill_notional_usd_total", "Filled notional", ["asset", "mode"])
SUBMIT_LATENCY = Histogram(
    "polybot_submit_to_ack_seconds",
    "Order submission to acknowledgement latency",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
)
PNL_REALIZED = Gauge("polybot_realized_pnl_usd", "Realized PnL today", ["mode"])
EXPOSURE = Gauge("polybot_open_exposure_usd", "Current open exposure")
KILL_SWITCH = Gauge("polybot_kill_switch_engaged", "1 when the kill switch is engaged")


def start_metrics_server(port: int) -> None:
    start_http_server(port)
