"""Small reactive widgets shared by the dashboard."""

from __future__ import annotations

import time

from textual.reactive import reactive
from textual.widgets import Static

from polybot.tui import theme


class HeartbeatWidget(Static):
    """Animated activity/health pulse.

    Cycles a braille spinner every 100ms (proof the event loop is alive) and
    colors itself from feed health: green while a message arrived in the
    last 2s, amber up to 5s, red/STALE beyond that. This doubles as the
    "activity check" — a stopped spinner or a red dot both mean something is
    actually wrong, not just a UI animation for its own sake.
    """

    frame: reactive[int] = reactive(0)
    last_message_ns: reactive[int | None] = reactive(None)

    def on_mount(self) -> None:
        self.set_interval(0.1, self._advance)

    def _advance(self) -> None:
        self.frame = (self.frame + 1) % len(theme.HEARTBEAT_FRAMES)

    def watch_frame(self, _frame: int) -> None:
        self._update_display()

    def watch_last_message_ns(self, _value: int | None) -> None:
        self._update_display()

    def _update_display(self) -> None:
        spinner = theme.HEARTBEAT_FRAMES[self.frame]
        if self.last_message_ns is None:
            self.update(f"[bold {theme.TEXT_MUTED}]{spinner} starting...[/]")
            return
        age = (time.time_ns() - self.last_message_ns) / 1e9
        if age <= 2.0:
            color, label = theme.GREEN, "live"
        elif age <= 5.0:
            color, label = theme.AMBER, "slow"
        else:
            color, label = theme.RED, "STALE"
        dot = "●" if self.frame % 2 == 0 or color == theme.RED else "○"
        self.update(f"[bold {color}]{spinner} {dot} {label} ({age:4.1f}s)[/]")


class ModeBadge(Static):
    mode: reactive[str] = reactive("observe")

    def watch_mode(self, mode: str) -> None:
        color = theme.MODE_COLORS.get(mode, theme.BLUE_GREY)
        self.update(f"[bold white on {color}]  {mode.upper()}  [/]")
