"""SQLAlchemy 2.x ORM schema."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[type, Any]] = {dict[str, Any]: JSON}


class MarketRow(Base):
    __tablename__ = "markets"

    slug: Mapped[str] = mapped_column(String(128), primary_key=True)
    asset: Mapped[str] = mapped_column(String(16), index=True)
    condition_id: Mapped[str] = mapped_column(String(80))
    up_token_id: Mapped[str] = mapped_column(String(80))
    down_token_id: Mapped[str] = mapped_column(String(80))
    start_ts: Mapped[float] = mapped_column(Float, index=True)
    end_ts: Mapped[float] = mapped_column(Float)
    tick_size: Mapped[float] = mapped_column(Float)
    taker_fee_bps: Mapped[float] = mapped_column(Float, default=0.0)
    rules_valid: Mapped[bool] = mapped_column(Boolean)
    rules_problems: Mapped[str] = mapped_column(Text, default="")
    resolution_source: Mapped[str] = mapped_column(Text, default="")
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MarketResultRow(Base):
    __tablename__ = "market_results"

    slug: Mapped[str] = mapped_column(ForeignKey("markets.slug"), primary_key=True)
    asset: Mapped[str] = mapped_column(String(16), index=True)
    opening_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    closing_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    opening_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    winner: Mapped[str | None] = mapped_column(String(8), nullable=True)
    resolved_at_ns: Mapped[int] = mapped_column(BigInteger, default=0)
    complete: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class SignalRow(Base):
    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    market_slug: Mapped[str] = mapped_column(String(128), index=True)
    asset: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(8))
    created_ns: Mapped[int] = mapped_column(BigInteger)
    seconds_remaining: Mapped[float] = mapped_column(Float)
    probability: Mapped[float] = mapped_column(Float)
    executable_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    gross_edge: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_edge: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision: Mapped[str] = mapped_column(String(12), index=True)
    reject_reasons: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (Index("ix_signals_market_decision", "market_slug", "decision"),)


class OrderRow(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    signal_id: Mapped[str] = mapped_column(String(40), index=True)
    market_slug: Mapped[str] = mapped_column(String(128), index=True)
    asset: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(8))
    token_id: Mapped[str] = mapped_column(String(80))
    limit_price: Mapped[float] = mapped_column(Float)
    size: Mapped[float] = mapped_column(Float)
    mode: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(20), index=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_ns: Mapped[int] = mapped_column(BigInteger)
    submitted_ns: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    acknowledged_ns: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class FillRow(Base):
    __tablename__ = "fills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(80), index=True)
    signal_id: Mapped[str] = mapped_column(String(40), index=True)
    market_slug: Mapped[str] = mapped_column(String(128), index=True)
    asset: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(8))
    price: Mapped[float] = mapped_column(Float)
    size: Mapped[float] = mapped_column(Float)
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    fill_ts: Mapped[float] = mapped_column(Float)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)


class CaptureFileRow(Base):
    __tablename__ = "capture_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_slug: Mapped[str] = mapped_column(String(128), index=True)
    path: Mapped[str] = mapped_column(Text)
    events: Mapped[int] = mapped_column(Integer, default=0)
    complete: Mapped[bool] = mapped_column(Boolean, default=False)
