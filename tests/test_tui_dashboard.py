"""Dashboard smoke tests: mounts, refreshes, and animates without crashing
against a stub app-state exposing only what PolybotDashboard reads."""

from __future__ import annotations

import time
import types

import pytest

from polybot.bus import EventBus
from polybot.clock import DriftMonitor, WallClock
from polybot.config import AppConfig
from polybot.feeds.base import FeedHealth
from polybot.feeds.health import FeedHealthAggregator
from polybot.models.core import Asset, FeedSource
from polybot.pricing.state import PriceStateTracker
from polybot.tui.dashboard import PolybotDashboard
from polybot.tui.widgets import HeartbeatWidget


def _stub_app_state() -> types.SimpleNamespace:
    bus = EventBus()
    tracker = PriceStateTracker(list(Asset))
    health = FeedHealthAggregator(max_chainlink_age_s=5.0, max_exchange_age_s=5.0)
    fh = FeedHealth(FeedSource.RTDS_CHAINLINK)
    fh.connected = True
    fh.touch(time.time_ns())
    health.register(fh)
    drift = DriftMonitor(0.25)
    drift.last_offset_s = 0.01
    config = AppConfig()
    return types.SimpleNamespace(
        bus=bus,
        mode=config.mode,
        clock=WallClock(),
        drift=drift,
        health=health,
        tracker=tracker,
        assets=list(Asset),
        config=config,
    )


@pytest.mark.asyncio()
async def test_dashboard_mounts_and_refreshes_without_error() -> None:
    dashboard = PolybotDashboard(_stub_app_state())
    async with dashboard.run_test(size=(160, 44)) as pilot:
        await pilot.pause()
        dashboard.refresh_state()
        await pilot.pause()


@pytest.mark.asyncio()
async def test_heartbeat_animates_over_time() -> None:
    dashboard = PolybotDashboard(_stub_app_state())
    async with dashboard.run_test(size=(160, 44)) as pilot:
        await pilot.pause()  # let the widget tree settle before timing frames
        heartbeat = dashboard.query_one("#heartbeat", HeartbeatWidget)
        frames = []
        for _ in range(4):
            await pilot.pause(0.15)
            frames.append(heartbeat.frame)
        assert len(set(frames)) > 1


@pytest.mark.asyncio()
async def test_dashboard_handles_missing_market_data_gracefully() -> None:
    """Before any market has been discovered, every asset row should show
    placeholders rather than crashing the render."""
    dashboard = PolybotDashboard(_stub_app_state())
    async with dashboard.run_test(size=(160, 44)) as pilot:
        await pilot.pause()
        dashboard.refresh_state()
        await pilot.pause()
        from textual.widgets import DataTable

        table = dashboard.query_one("#markets_table", DataTable)
        assert table.row_count == len(Asset)
