"""Configuration: YAML file + environment overrides via pydantic-settings.

Precedence (highest wins): environment variables (``POLYBOT_`` prefix, ``__``
nested delimiter) > YAML file (``POLYBOT_CONFIG`` path or ``config/default.yaml``)
> field defaults.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from polybot.models.core import Asset, TradingMode

LIVE_CONFIRM_ENV = "POLYBOT_LIVE_CONFIRM"
LIVE_CONFIRM_VALUE = "I_UNDERSTAND_LIVE_TRADING_RISKS"
MIN_RECORDED_MARKETS_FOR_LIVE = 1000


class ExchangeFeedConfig(BaseModel):
    enabled: bool = True
    symbols: dict[Asset, str] = Field(default_factory=dict)

    def symbol_for(self, asset: Asset) -> str | None:
        return self.symbols.get(asset)


class FeedsConfig(BaseModel):
    rtds_url: str = "wss://ws-live-data.polymarket.com"
    clob_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws"
    chainlink_streams_ws_url: str = "wss://ws.testnet-dataengine.chain.link"
    chainlink_streams_api_key: str = ""
    chainlink_streams_api_secret: str = ""
    chainlink_stream_feed_ids: dict[Asset, str] = Field(default_factory=dict)
    binance_spot: ExchangeFeedConfig = Field(
        default_factory=lambda: ExchangeFeedConfig(
            symbols={
                Asset.BTC: "btcusdt",
                Asset.ETH: "ethusdt",
                Asset.SOL: "solusdt",
                Asset.XRP: "xrpusdt",
                Asset.DOGE: "dogeusdt",
                Asset.BNB: "bnbusdt",
                # HYPE is not listed on Binance spot.
            }
        )
    )
    binance_futures: ExchangeFeedConfig = Field(
        default_factory=lambda: ExchangeFeedConfig(
            symbols={
                Asset.BTC: "btcusdt",
                Asset.ETH: "ethusdt",
                Asset.SOL: "solusdt",
                Asset.XRP: "xrpusdt",
                Asset.DOGE: "dogeusdt",
                Asset.BNB: "bnbusdt",
                Asset.HYPE: "hypeusdt",
            }
        )
    )
    coinbase: ExchangeFeedConfig = Field(
        default_factory=lambda: ExchangeFeedConfig(
            symbols={
                Asset.BTC: "BTC-USD",
                Asset.ETH: "ETH-USD",
                Asset.SOL: "SOL-USD",
                Asset.XRP: "XRP-USD",
                Asset.DOGE: "DOGE-USD",
                # BNB and HYPE are not listed on Coinbase.
            }
        )
    )
    okx: ExchangeFeedConfig = Field(
        default_factory=lambda: ExchangeFeedConfig(
            enabled=False,
            symbols={
                Asset.BTC: "BTC-USDT",
                Asset.ETH: "ETH-USDT",
                Asset.SOL: "SOL-USDT",
                Asset.XRP: "XRP-USDT",
                Asset.DOGE: "DOGE-USDT",
                Asset.BNB: "BNB-USDT",
                Asset.HYPE: "HYPE-USDT",
            },
        )
    )
    binance_spot_ws: str = "wss://stream.binance.com:9443/stream"
    binance_futures_ws: str = "wss://fstream.binance.com/stream"
    coinbase_ws: str = "wss://ws-feed.exchange.coinbase.com"
    okx_ws: str = "wss://ws.okx.com:8443/ws/v5/public"
    reconnect_initial_delay_s: float = 0.5
    reconnect_max_delay_s: float = 30.0
    heartbeat_timeout_s: float = 20.0

    @property
    def chainlink_streams_enabled(self) -> bool:
        return bool(self.chainlink_streams_api_key and self.chainlink_streams_api_secret)


class DiscoveryConfig(BaseModel):
    gamma_base_url: str = "https://gamma-api.polymarket.com"
    interval_seconds: int = 300
    slug_template: str = "{asset}-updown-5m-{window_ts}"
    preload_lead_s: float = 60.0
    poll_interval_s: float = 5.0
    request_timeout_s: float = 5.0


class ModelConfig(BaseModel):
    vol_ewma_halflife_s: float = 60.0
    vol_floor_per_sqrt_s: float = 1e-6
    vol_sample_min_ticks: int = 20
    exchange_lead_weight: float = 0.6
    probability_clamp: float = 0.02
    empirical_model_path: str = "data/models/empirical.json"
    empirical_min_training_samples: int = 500
    disagreement_uncertainty_scale: float = 0.5
    chainlink_update_interval_hint_s: float = 1.0


class EndgameConfig(BaseModel):
    window_s: float = 15.0
    hard_cutoff_s: float = 2.0
    min_abs_return: float = 0.0001
    min_probability: float = 0.70
    min_cross_exchange_agreement: int = 2
    max_cross_exchange_dispersion: float = 0.0005
    final_seconds_buffer_ramp_s: float = 5.0
    final_seconds_extra_buffer: float = 0.05


class RiskConfig(BaseModel):
    max_stake_per_trade_usd: float = 50.0
    max_stake_per_market_usd: float = 100.0
    max_daily_loss_usd: float = 200.0
    max_simultaneous_exposure_usd: float = 300.0
    max_orders_per_interval: int = 2
    min_net_edge: float = 0.03
    min_expected_profit_usd: float = 1.0
    max_entry_price: float = 0.97
    max_spread: float = 0.10
    max_slippage: float = 0.02
    max_chainlink_age_s: float = 5.0
    max_exchange_age_s: float = 5.0
    max_book_age_s: float = 3.0
    max_signal_age_s: float = 0.75
    max_source_divergence: float = 0.002
    max_clock_drift_s: float = 0.25
    taker_fee_rate: float = 0.0
    expected_slippage: float = 0.005
    execution_delay_buffer: float = 0.01
    feed_latency_buffer: float = 0.005
    model_uncertainty_buffer: float = 0.02
    failed_fill_buffer: float = 0.01
    kill_switch_file: str = "data/KILL"
    kill_switch_redis_key: str = "polybot:kill"
    geo_eligible: bool = False
    geo_attestation: str = ""


class StorageConfig(BaseModel):
    database_url: str = "postgresql+asyncpg://polybot:polybot@localhost:5432/polybot"
    redis_url: str = "redis://localhost:6379/0"
    capture_dir: str = "data/capture"
    compress_captures: bool = True


class ExecutionConfig(BaseModel):
    clob_base_url: str = "https://clob.polymarket.com"
    chain_id: int = 137
    private_key: str = ""
    api_key: str = ""
    api_secret: str = ""
    api_passphrase: str = ""
    funder_address: str = ""
    signature_type: int = 0
    min_order_size_shares: float = 5.0
    submit_timeout_s: float = 3.0
    precheck_price_tolerance: float = 0.01
    precheck_probability_tolerance: float = 0.03
    precheck_max_signal_age_s: float = 0.75


class ObservabilityConfig(BaseModel):
    metrics_port: int = 9109
    log_level: str = "INFO"
    log_json: bool = True


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="POLYBOT_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    mode: TradingMode = TradingMode.OBSERVE
    assets: list[Asset] = Field(default_factory=lambda: list(Asset))
    feeds: FeedsConfig = Field(default_factory=FeedsConfig)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    endgame: EndgameConfig = Field(default_factory=EndgameConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)

    @model_validator(mode="after")
    def _gate_live_mode(self) -> AppConfig:
        """LIVE requires the explicit confirmation env var; downgrade otherwise.

        The second LIVE gate (>= MIN_RECORDED_MARKETS_FOR_LIVE recorded markets)
        needs a database query and is enforced at startup in app.py.
        """
        if self.mode is TradingMode.LIVE and os.environ.get(LIVE_CONFIRM_ENV) != LIVE_CONFIRM_VALUE:
            object.__setattr__(self, "mode", TradingMode.SHADOW)
        return self


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load config from YAML (if present) with env-var overrides on top."""
    candidates: list[Path] = []
    if path is not None:
        candidates.append(Path(path))
    elif env_path := os.environ.get("POLYBOT_CONFIG"):
        candidates.append(Path(env_path))
    else:
        candidates.append(Path("config/default.yaml"))

    data: dict[str, Any] = {}
    for candidate in candidates:
        if candidate.is_file():
            loaded = yaml.safe_load(candidate.read_text()) or {}
            if not isinstance(loaded, dict):
                raise ValueError(f"config file {candidate} must contain a mapping")
            data = _deep_merge(data, loaded)
    return AppConfig(**data)
