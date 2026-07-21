"""Core domain models shared across the bot.

All models are immutable (frozen) Pydantic models. Timestamps follow a strict
convention:

* ``*_ts`` — float unix seconds as reported by the remote provider/exchange.
* ``*_ns`` — int nanoseconds from the local monotonic-adjusted wall clock
  (``time.time_ns()``).
"""

from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Asset(enum.StrEnum):
    BTC = "BTC"
    ETH = "ETH"
    SOL = "SOL"
    XRP = "XRP"
    DOGE = "DOGE"
    BNB = "BNB"
    HYPE = "HYPE"


class FeedSource(enum.StrEnum):
    CHAINLINK_STREAMS = "chainlink_streams"
    RTDS_CHAINLINK = "rtds_chainlink"
    BINANCE_SPOT = "binance_spot"
    BINANCE_FUTURES = "binance_futures"
    COINBASE = "coinbase"
    OKX = "okx"
    CLOB_MARKET = "clob_market"
    CLOB_USER = "clob_user"
    GAMMA = "gamma"
    REPLAY = "replay"

    @property
    def is_settlement(self) -> bool:
        """True when this source carries the price the market resolves against."""
        return self in (FeedSource.CHAINLINK_STREAMS, FeedSource.RTDS_CHAINLINK)


class TradingMode(enum.StrEnum):
    OBSERVE = "observe"
    PAPER = "paper"
    SHADOW = "shadow"
    LIVE = "live"


class Side(enum.StrEnum):
    UP = "up"
    DOWN = "down"

    @property
    def other(self) -> Side:
        return Side.DOWN if self is Side.UP else Side.UP


class Tick(FrozenModel):
    """One normalized price observation from any feed."""

    source: FeedSource
    asset: Asset
    symbol: str
    provider_ts: float
    exchange_ts: float | None = None
    local_recv_ns: int
    seq: int | None = None
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    processing_latency_ns: int = 0

    @property
    def mid(self) -> float | None:
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2.0
        return self.last

    @property
    def price(self) -> float:
        """Best available point price: mid if quoted, else last."""
        mid = self.mid
        if mid is None:
            raise ValueError(f"tick from {self.source} has no usable price")
        return mid

    def age_seconds(self, now_ns: int) -> float:
        return max(0.0, (now_ns - self.local_recv_ns) / 1e9)


class BookLevel(FrozenModel):
    price: float
    size: float


class BookSnapshot(FrozenModel):
    """L2 order book for a single outcome token."""

    token_id: str
    asset: Asset
    side: Side
    bids: tuple[BookLevel, ...] = ()
    asks: tuple[BookLevel, ...] = ()
    provider_ts: float
    local_recv_ns: int
    seq: int | None = None
    tick_size: float = 0.01

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def spread(self) -> float | None:
        if self.bids and self.asks:
            return self.asks[0].price - self.bids[0].price
        return None

    def depth_at_or_below(self, max_price: float) -> float:
        """Total ask size executable at or below ``max_price``."""
        return sum(level.size for level in self.asks if level.price <= max_price)

    def age_seconds(self, now_ns: int) -> float:
        return max(0.0, (now_ns - self.local_recv_ns) / 1e9)


class ResolutionRules(FrozenModel):
    """Parsed + validated resolution semantics of one market."""

    raw_description: str
    resolution_source: str
    references_chainlink: bool
    up_wins_on_equal: bool
    interval_start_ts: float | None
    interval_end_ts: float | None
    valid: bool
    problems: tuple[str, ...] = ()


class MarketInfo(FrozenModel):
    """Discovered metadata for one 5-minute Up/Down market."""

    slug: str
    asset: Asset
    condition_id: str
    question_id: str | None = None
    up_token_id: str
    down_token_id: str
    start_ts: float
    end_ts: float
    tick_size: float
    neg_risk: bool = False
    taker_fee_bps: float = 0.0
    maker_fee_bps: float = 0.0
    order_book_enabled: bool = True
    accepting_orders: bool = True
    rules: ResolutionRules
    discovered_at_ns: int
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def tradable(self) -> bool:
        return self.order_book_enabled and self.accepting_orders and self.rules.valid

    def token_id(self, side: Side) -> str:
        return self.up_token_id if side is Side.UP else self.down_token_id


class OpeningPrice(FrozenModel):
    """The verified Chainlink opening print for one interval."""

    asset: Asset
    market_slug: str
    price: float
    source: FeedSource
    provider_ts: float
    local_recv_ns: int
    verified: bool
    verification_note: str = ""


class SignalDecision(enum.StrEnum):
    TRADE = "trade"
    REJECT = "reject"


class Signal(FrozenModel):
    """One evaluated opportunity (traded or rejected — all are recorded)."""

    id: str
    market_slug: str
    asset: Asset
    side: Side
    created_ns: int
    seconds_remaining: float
    chainlink_price: float
    opening_price: float
    chainlink_distance: float
    chainlink_return: float
    probability: float
    probability_baseline: float
    probability_empirical: float | None
    model_disagreement: float
    executable_price: float | None
    executable_size: float | None
    gross_edge: float | None
    net_edge: float | None
    costs: dict[str, float] = Field(default_factory=dict)
    decision: SignalDecision
    reject_reasons: tuple[str, ...] = ()
    in_endgame_window: bool = False
    feed_ages: dict[str, float] = Field(default_factory=dict)


class OrderIntent(FrozenModel):
    """A fully-specified order the execution layer may submit."""

    signal_id: str
    market_slug: str
    asset: Asset
    side: Side
    token_id: str
    limit_price: float
    size: float
    max_notional: float
    created_ns: int
    mode: TradingMode


class OrderStatus(enum.StrEnum):
    BUILT = "built"
    SIGNED = "signed"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    ABORTED_PRECHECK = "aborted_precheck"
    EXPIRED = "expired"


class OrderRecord(FrozenModel):
    intent: OrderIntent
    order_id: str | None = None
    status: OrderStatus
    submitted_ns: int | None = None
    acknowledged_ns: int | None = None
    detail: str = ""


class Fill(FrozenModel):
    order_id: str
    signal_id: str
    market_slug: str
    asset: Asset
    side: Side
    token_id: str
    price: float
    size: float
    fee: float
    fill_ts: float
    local_recv_ns: int
    simulated: bool


class MarketResult(FrozenModel):
    """Final settlement of one interval."""

    market_slug: str
    asset: Asset
    start_ts: float
    end_ts: float
    opening_price: float | None
    closing_price: float | None
    winner: Side | None
    opening_verified: bool
    resolved_at_ns: int
