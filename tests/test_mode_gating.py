import pytest

from polybot.app import PolybotApp
from polybot.config import (
    LIVE_CONFIRM_ENV,
    LIVE_CONFIRM_VALUE,
    MIN_RECORDED_MARKETS_FOR_LIVE,
    AppConfig,
)
from polybot.models.core import TradingMode


@pytest.fixture(autouse=True)
def _clear_live_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LIVE_CONFIRM_ENV, raising=False)


def test_live_mode_without_confirmation_env_downgrades_to_shadow() -> None:
    config = AppConfig(mode=TradingMode.LIVE)
    assert config.mode is TradingMode.SHADOW


def test_live_mode_with_confirmation_env_is_accepted_at_config_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(LIVE_CONFIRM_ENV, LIVE_CONFIRM_VALUE)
    config = AppConfig(mode=TradingMode.LIVE)
    assert config.mode is TradingMode.LIVE


def test_live_mode_with_wrong_confirmation_value_downgrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(LIVE_CONFIRM_ENV, "yes-please")
    config = AppConfig(mode=TradingMode.LIVE)
    assert config.mode is TradingMode.SHADOW


def test_non_live_modes_are_unaffected_by_confirmation_env() -> None:
    for mode in (TradingMode.OBSERVE, TradingMode.PAPER, TradingMode.SHADOW):
        config = AppConfig(mode=mode)
        assert config.mode is mode


def test_default_mode_is_observe() -> None:
    assert AppConfig().mode is TradingMode.OBSERVE


def test_app_refuses_live_without_enough_recorded_markets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(LIVE_CONFIRM_ENV, LIVE_CONFIRM_VALUE)
    app = PolybotApp(AppConfig(mode=TradingMode.LIVE))
    app._completed_markets_cache = MIN_RECORDED_MARKETS_FOR_LIVE - 1
    app._enforce_live_gate()
    assert app.mode is TradingMode.SHADOW
    assert app.strategy.mode is TradingMode.SHADOW


def test_app_arms_live_with_confirmation_and_enough_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(LIVE_CONFIRM_ENV, LIVE_CONFIRM_VALUE)
    app = PolybotApp(AppConfig(mode=TradingMode.LIVE))
    app._completed_markets_cache = MIN_RECORDED_MARKETS_FOR_LIVE
    app._enforce_live_gate()
    assert app.mode is TradingMode.LIVE
