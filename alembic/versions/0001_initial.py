"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-01-01 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.create_table(
        "markets",
        sa.Column("slug", sa.String(128), primary_key=True),
        sa.Column("asset", sa.String(16), nullable=False),
        sa.Column("condition_id", sa.String(80), nullable=False),
        sa.Column("up_token_id", sa.String(80), nullable=False),
        sa.Column("down_token_id", sa.String(80), nullable=False),
        sa.Column("start_ts", sa.Float, nullable=False),
        sa.Column("end_ts", sa.Float, nullable=False),
        sa.Column("tick_size", sa.Float, nullable=False),
        sa.Column("taker_fee_bps", sa.Float, nullable=False, server_default="0"),
        sa.Column("rules_valid", sa.Boolean, nullable=False),
        sa.Column("rules_problems", sa.Text, nullable=False, server_default=""),
        sa.Column("resolution_source", sa.Text, nullable=False, server_default=""),
        sa.Column("raw", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_markets_asset", "markets", ["asset"])
    op.create_index("ix_markets_start_ts", "markets", ["start_ts"])

    op.create_table(
        "market_results",
        sa.Column("slug", sa.String(128), sa.ForeignKey("markets.slug"), primary_key=True),
        sa.Column("asset", sa.String(16), nullable=False),
        sa.Column("opening_price", sa.Float, nullable=True),
        sa.Column("closing_price", sa.Float, nullable=True),
        sa.Column("opening_verified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("winner", sa.String(8), nullable=True),
        sa.Column("resolved_at_ns", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("complete", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_market_results_asset", "market_results", ["asset"])
    op.create_index("ix_market_results_complete", "market_results", ["complete"])

    op.create_table(
        "signals",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("market_slug", sa.String(128), nullable=False),
        sa.Column("asset", sa.String(16), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("created_ns", sa.BigInteger, nullable=False),
        sa.Column("seconds_remaining", sa.Float, nullable=False),
        sa.Column("probability", sa.Float, nullable=False),
        sa.Column("executable_price", sa.Float, nullable=True),
        sa.Column("gross_edge", sa.Float, nullable=True),
        sa.Column("net_edge", sa.Float, nullable=True),
        sa.Column("decision", sa.String(12), nullable=False),
        sa.Column("reject_reasons", sa.Text, nullable=False, server_default=""),
        sa.Column("payload", sa.JSON, nullable=False),
    )
    op.create_index("ix_signals_market_slug", "signals", ["market_slug"])
    op.create_index("ix_signals_asset", "signals", ["asset"])
    op.create_index("ix_signals_decision", "signals", ["decision"])
    op.create_index("ix_signals_market_decision", "signals", ["market_slug", "decision"])

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.String(80), nullable=True),
        sa.Column("signal_id", sa.String(40), nullable=False),
        sa.Column("market_slug", sa.String(128), nullable=False),
        sa.Column("asset", sa.String(16), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("token_id", sa.String(80), nullable=False),
        sa.Column("limit_price", sa.Float, nullable=False),
        sa.Column("size", sa.Float, nullable=False),
        sa.Column("mode", sa.String(12), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("detail", sa.Text, nullable=False, server_default=""),
        sa.Column("created_ns", sa.BigInteger, nullable=False),
        sa.Column("submitted_ns", sa.BigInteger, nullable=True),
        sa.Column("acknowledged_ns", sa.BigInteger, nullable=True),
    )
    op.create_index("ix_orders_order_id", "orders", ["order_id"])
    op.create_index("ix_orders_signal_id", "orders", ["signal_id"])
    op.create_index("ix_orders_market_slug", "orders", ["market_slug"])
    op.create_index("ix_orders_status", "orders", ["status"])

    op.create_table(
        "fills",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.String(80), nullable=False),
        sa.Column("signal_id", sa.String(40), nullable=False),
        sa.Column("market_slug", sa.String(128), nullable=False),
        sa.Column("asset", sa.String(16), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("price", sa.Float, nullable=False),
        sa.Column("size", sa.Float, nullable=False),
        sa.Column("fee", sa.Float, nullable=False, server_default="0"),
        sa.Column("fill_ts", sa.Float, nullable=False),
        sa.Column("simulated", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_fills_order_id", "fills", ["order_id"])
    op.create_index("ix_fills_signal_id", "fills", ["signal_id"])
    op.create_index("ix_fills_market_slug", "fills", ["market_slug"])

    op.create_table(
        "capture_files",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("market_slug", sa.String(128), nullable=False),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("events", sa.Integer, nullable=False, server_default="0"),
        sa.Column("complete", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_capture_files_market_slug", "capture_files", ["market_slug"])


def downgrade() -> None:
    op.drop_table("capture_files")
    op.drop_table("fills")
    op.drop_table("orders")
    op.drop_table("signals")
    op.drop_table("market_results")
    op.drop_table("markets")
