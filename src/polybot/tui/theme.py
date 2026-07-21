"""Light (not white) color palette for the terminal dashboard.

A warm parchment/eggshell theme — legible in bright rooms, easy on the eyes,
deliberately not stark white. Every color used by the dashboard lives here so
the look stays consistent across widgets.
"""

from __future__ import annotations

BACKGROUND = "#f4efe6"
PANEL = "#ece2d0"
PANEL_ALT = "#e4d8c2"
BORDER = "#cdbe9e"
TEXT = "#2e2a22"
TEXT_MUTED = "#7a705d"

GREEN = "#2f7a4f"
GREEN_SOFT = "#5a9c76"
RED = "#b4483a"
RED_SOFT = "#c97267"
AMBER = "#b3821f"
TEAL = "#2d6e7e"
BLUE_GREY = "#5b6b7a"

MODE_COLORS = {
    "observe": BLUE_GREY,
    "paper": TEAL,
    "shadow": AMBER,
    "live": RED,
}

HEARTBEAT_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
