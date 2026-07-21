"""Live terminal dashboard for a running :class:`~polybot.app.PolybotApp`.

Deliberately does no independent work: every number on screen is read from
state the trading loop already maintains (``app.tracker``, ``app.health``,
``app.drift``, ``app.risk``) plus the most recent :class:`Signal` per asset
drained from the event bus. No extra network calls, no duplicated model
evaluation — the dashboard is a pure, cheap view over the live app.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import ClassVar, Protocol

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, RichLog, Static

from polybot.bus import EventBus
from polybot.clock import Clock, DriftMonitor
from polybot.config import AppConfig
from polybot.feeds.health import FeedHealthAggregator
from polybot.models.core import Asset, Side, Signal, SignalDecision, TradingMode
from polybot.pricing.state import PriceStateTracker
from polybot.tui import theme
from polybot.tui.widgets import HeartbeatWidget, ModeBadge

REFRESH_INTERVAL_S = 0.25


class DashboardState(Protocol):
    """Everything the dashboard reads from a running app.

    Deliberately narrow: the dashboard depends on this read-only surface, not
    the full :class:`~polybot.app.PolybotApp` — any object exposing these
    attributes (the real app, or a stub in tests) can drive it.
    """

    bus: EventBus
    mode: TradingMode
    clock: Clock
    drift: DriftMonitor
    health: FeedHealthAggregator
    tracker: PriceStateTracker
    assets: list[Asset]
    config: AppConfig


def _markup(text: str) -> Text:
    """Cell content for DataTable: parses ``[color]...[/]`` markup and
    reports correct display width, unlike a plain str (which DataTable
    renders literally, markup tags and all)."""
    return Text.from_markup(text)


def _fmt_price(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "--"


def _fmt_pct(value: float | None) -> str:
    return f"{value * 100:5.1f}%" if value is not None else "--"


def _countdown_style(
    seconds_remaining: float | None, endgame_window_s: float, hard_cutoff_s: float
) -> str:
    if seconds_remaining is None:
        return theme.TEXT_MUTED
    if seconds_remaining <= hard_cutoff_s:
        return theme.RED
    if seconds_remaining <= endgame_window_s:
        return theme.AMBER
    return theme.GREEN


class PolybotDashboard(App[None]):
    CSS = f"""
    Screen {{
        background: {theme.BACKGROUND};
        color: {theme.TEXT};
        scrollbar-background: {theme.PANEL};
        scrollbar-color: {theme.BORDER};
        scrollbar-color-hover: {theme.TEAL};
        scrollbar-color-active: {theme.TEAL};
        scrollbar-corner-color: {theme.PANEL};
    }}
    * {{
        scrollbar-background: {theme.PANEL};
        scrollbar-color: {theme.BORDER};
        scrollbar-color-hover: {theme.TEAL};
        scrollbar-color-active: {theme.TEAL};
        scrollbar-corner-color: {theme.PANEL};
    }}
    #header {{
        height: 3;
        background: {theme.PANEL_ALT};
        border-bottom: solid {theme.BORDER};
        padding: 0 2;
    }}
    #header Static {{
        background: {theme.PANEL_ALT};
        color: {theme.TEXT};
        content-align: left middle;
        width: auto;
        height: 3;
        margin: 0 2 0 0;
    }}
    #title {{
        text-style: bold;
        color: {theme.TEXT};
    }}
    #mode_badge {{
        height: 3;
        content-align: center middle;
    }}
    #clock {{
        width: 1fr;
        content-align: right middle;
        color: {theme.TEXT_MUTED};
        margin: 0;
    }}
    #body {{
        height: 1fr;
    }}
    #left {{
        width: 2fr;
        border: round {theme.BORDER};
        background: {theme.PANEL};
        padding: 0 1;
    }}
    #right {{
        width: 1fr;
        border: round {theme.BORDER};
        background: {theme.PANEL};
        padding: 0 1;
    }}
    #feed_health {{
        height: 40%;
        border-bottom: solid {theme.BORDER};
    }}
    #signal_log {{
        height: 60%;
        background: {theme.PANEL};
        color: {theme.TEXT};
    }}
    DataTable {{
        background: {theme.PANEL};
        color: {theme.TEXT};
    }}
    DataTable > .datatable--header {{
        background: {theme.PANEL_ALT};
        color: {theme.TEXT};
        text-style: bold;
    }}
    DataTable > .datatable--cursor {{
        background: {theme.PANEL_ALT};
    }}
    Footer {{
        background: {theme.PANEL_ALT};
        color: {theme.TEXT};
    }}
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit"),
    ]

    def __init__(self, app_state: DashboardState) -> None:
        super().__init__()
        self.app_state = app_state
        self.latest_signal: dict[Asset, Signal] = {}
        self._sub = app_state.bus.subscribe("tui-signals", maxsize=500)
        self._drain_task: asyncio.Task[None] | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="header"):
            yield Static("POLYBOT · 5-MIN CRYPTO UP/DOWN", id="title")
            yield ModeBadge(id="mode_badge")
            yield Static("", id="drift_status")
            yield HeartbeatWidget(id="heartbeat")
            yield Static("", id="clock")
        with Horizontal(id="body"):
            with Vertical(id="left"):
                yield DataTable(id="markets_table")
            with Vertical(id="right"):
                yield DataTable(id="feed_health")
                yield RichLog(id="signal_log", markup=True, max_lines=300, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        markets = self.query_one("#markets_table", DataTable)
        for label, width in (
            ("Asset", 6),
            ("T-remaining", 10),
            ("Open", 9),
            ("Chainlink", 10),
            ("Δ open", 7),
            ("P(Up)", 7),
            ("P(Down)", 8),
            ("Up bid/ask", 13),
            ("Down bid/ask", 13),
            ("Net edge", 9),
            ("Window", 8),
        ):
            markets.add_column(label, width=width)
        markets.cursor_type = "row"

        health = self.query_one("#feed_health", DataTable)
        for label, width in (("Feed", 15), ("Status", 8), ("Age", 8)):
            health.add_column(label, width=width)
        health.cursor_type = "none"

        self.query_one("#mode_badge", ModeBadge).mode = self.app_state.mode.value

        self._drain_task = asyncio.create_task(self._drain_signals(), name="tui-drain-signals")
        self.set_interval(REFRESH_INTERVAL_S, self.refresh_state)
        self.refresh_state()

    async def _drain_signals(self) -> None:
        async for event in self._sub:
            if isinstance(event, Signal):
                self.latest_signal[event.asset] = event
                self._log_signal(event)

    def _log_signal(self, signal: Signal) -> None:
        log = self.query_one("#signal_log", RichLog)
        ts = datetime.fromtimestamp(signal.created_ns / 1e9, tz=UTC).strftime("%H:%M:%S")
        side_color = theme.GREEN if signal.side is Side.UP else theme.RED
        if signal.decision is SignalDecision.TRADE:
            edge = f"{signal.net_edge:.4f}" if signal.net_edge is not None else "--"
            log.write(
                f"[{theme.TEXT_MUTED}]{ts}[/] [bold {theme.GREEN}]TRADE[/] "
                f"[{side_color}]{signal.asset.value} {signal.side.value.upper()}[/] "
                f"p={signal.probability:.3f} px={_fmt_price(signal.executable_price)} edge={edge}"
            )
        else:
            reason = signal.reject_reasons[0] if signal.reject_reasons else "?"
            log.write(
                f"[{theme.TEXT_MUTED}]{ts} reject[/] [{side_color}]{signal.asset.value} "
                f"{signal.side.value.upper()}[/] [{theme.TEXT_MUTED}]{reason}[/]"
            )

    def refresh_state(self) -> None:
        app_state = self.app_state
        now_s = app_state.clock.now_s()
        now_ns = app_state.clock.now_ns()

        self.query_one("#clock", Static).update(
            datetime.fromtimestamp(now_s, tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        )
        self.query_one("#mode_badge", ModeBadge).mode = app_state.mode.value

        drift = app_state.drift.last_offset_s
        drift_widget = self.query_one("#drift_status", Static)
        if drift is None:
            drift_widget.update(f"[{theme.RED}]drift: unknown[/]")
        else:
            color = theme.GREEN if app_state.drift.trading_allowed else theme.RED
            drift_widget.update(f"[{color}]drift: {drift * 1000:+.0f}ms[/]")

        last_message_ns = max(
            (h.last_message_ns for h in app_state.health.sources().values() if h.last_message_ns),
            default=None,
        )
        self.query_one("#heartbeat", HeartbeatWidget).last_message_ns = last_message_ns

        self._refresh_markets(now_s)
        self._refresh_feed_health(now_ns)

    def _refresh_markets(self, now_s: float) -> None:
        table = self.query_one("#markets_table", DataTable)
        table.clear()
        endgame = self.app_state.config.endgame
        for asset in self.app_state.assets:
            view = self.app_state.tracker.active_view(asset, now_s)
            state = self.app_state.tracker.assets.get(asset)
            signal = self.latest_signal.get(asset)

            if view is None or state is None:
                table.add_row(
                    asset.value, "--", "--", "--", "--", "--", "--", "--", "--", "--", "--"
                )
                continue

            seconds_remaining = view.seconds_remaining(now_s)
            style = _countdown_style(seconds_remaining, endgame.window_s, endgame.hard_cutoff_s)
            countdown = _markup(f"[{style}]{seconds_remaining:5.1f}s[/]")

            opening = view.opening.price if view.opening else None
            chainlink = state.chainlink.price if state.chainlink else None
            distance = (
                f"{chainlink - opening:+.2f}"
                if opening is not None and chainlink is not None
                else "--"
            )

            p_up = (
                signal.probability
                if signal and signal.side is Side.UP
                else (1 - signal.probability if signal else None)
            )
            p_down = 1 - p_up if p_up is not None else None

            up_book = view.book(Side.UP)
            down_book = view.book(Side.DOWN)
            up_quote = f"{_fmt_price(up_book.best_bid if up_book else None)}/{_fmt_price(up_book.best_ask if up_book else None)}"
            down_quote = f"{_fmt_price(down_book.best_bid if down_book else None)}/{_fmt_price(down_book.best_ask if down_book else None)}"

            net_edge_text = "--"
            if signal is not None and signal.net_edge is not None:
                color = theme.GREEN if signal.decision is SignalDecision.TRADE else theme.TEXT_MUTED
                net_edge_text = f"[{color}]{signal.net_edge:+.4f}[/]"

            window_flag = ""
            if signal is not None and signal.in_endgame_window:
                window_flag = f"[bold {theme.AMBER}]ENDGAME[/]"

            table.add_row(
                _markup(f"[bold]{asset.value}[/]"),
                countdown,
                _fmt_price(opening),
                _fmt_price(chainlink),
                distance,
                _fmt_pct(p_up),
                _fmt_pct(p_down),
                up_quote,
                down_quote,
                _markup(net_edge_text),
                _markup(window_flag),
            )

    def _refresh_feed_health(self, now_ns: int) -> None:
        table = self.query_one("#feed_health", DataTable)
        table.clear()
        for source, health in sorted(
            self.app_state.health.sources().items(), key=lambda kv: kv[0].value
        ):
            age = health.age_seconds(now_ns)
            if not health.connected:
                status, color = "DOWN", theme.RED
            elif age <= 3.0:
                status, color = "OK", theme.GREEN
            elif age <= 10.0:
                status, color = "SLOW", theme.AMBER
            else:
                status, color = "STALE", theme.RED
            age_text = f"{age:5.1f}s" if age != float("inf") else "--"
            table.add_row(source.value, _markup(f"[{color}]{status}[/]"), age_text)

    async def action_quit(self) -> None:
        if self._drain_task is not None:
            self._drain_task.cancel()
        self.exit()


async def run_dashboard(app_state: DashboardState, stop_event: asyncio.Event) -> None:
    """Run the dashboard until the user quits or ``stop_event`` fires."""
    dashboard = PolybotDashboard(app_state)
    dashboard_task = asyncio.create_task(dashboard.run_async(), name="tui-dashboard")
    stop_task = asyncio.create_task(stop_event.wait(), name="tui-stop-wait")
    done, pending = await asyncio.wait(
        {dashboard_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
    )
    if stop_task in done and not dashboard_task.done():
        dashboard.exit()
        await dashboard_task
    for task in pending:
        task.cancel()
    stop_event.set()
