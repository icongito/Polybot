"""Repository layer: persistence of domain objects into Postgres."""

from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from polybot.models.core import Fill, MarketInfo, MarketResult, OrderRecord, Signal
from polybot.persistence.orm import (
    CaptureFileRow,
    FillRow,
    MarketResultRow,
    MarketRow,
    OrderRow,
    SignalRow,
)


def _upsert(session: AsyncSession):  # type: ignore[no-untyped-def]
    """Pick the dialect-appropriate insert-with-on-conflict constructor."""
    bind = session.get_bind()
    return sqlite_insert if bind.dialect.name == "sqlite" else pg_insert


class Repository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_market(self, market: MarketInfo) -> None:
        insert = _upsert(self.session)
        values = {
            "slug": market.slug,
            "asset": market.asset.value,
            "condition_id": market.condition_id,
            "up_token_id": market.up_token_id,
            "down_token_id": market.down_token_id,
            "start_ts": market.start_ts,
            "end_ts": market.end_ts,
            "tick_size": market.tick_size,
            "taker_fee_bps": market.taker_fee_bps,
            "rules_valid": market.rules.valid,
            "rules_problems": json.dumps(list(market.rules.problems)),
            "resolution_source": market.rules.resolution_source,
            "raw": market.raw,
        }
        stmt = insert(MarketRow).values(**values)
        stmt = stmt.on_conflict_do_update(index_elements=["slug"], set_=values)
        await self.session.execute(stmt)

    async def save_result(self, result: MarketResult, *, complete: bool) -> None:
        insert = _upsert(self.session)
        values = {
            "slug": result.market_slug,
            "asset": result.asset.value,
            "opening_price": result.opening_price,
            "closing_price": result.closing_price,
            "opening_verified": result.opening_verified,
            "winner": result.winner.value if result.winner else None,
            "resolved_at_ns": result.resolved_at_ns,
            "complete": complete,
        }
        stmt = insert(MarketResultRow).values(**values)
        stmt = stmt.on_conflict_do_update(index_elements=["slug"], set_=values)
        await self.session.execute(stmt)

    async def save_signal(self, signal: Signal) -> None:
        insert = _upsert(self.session)
        values = {
            "id": signal.id,
            "market_slug": signal.market_slug,
            "asset": signal.asset.value,
            "side": signal.side.value,
            "created_ns": signal.created_ns,
            "seconds_remaining": signal.seconds_remaining,
            "probability": signal.probability,
            "executable_price": signal.executable_price,
            "gross_edge": signal.gross_edge,
            "net_edge": signal.net_edge,
            "decision": signal.decision.value,
            "reject_reasons": json.dumps(list(signal.reject_reasons)),
            "payload": json.loads(signal.model_dump_json()),
        }
        stmt = insert(SignalRow).values(**values)
        stmt = stmt.on_conflict_do_nothing(index_elements=["id"])
        await self.session.execute(stmt)

    async def save_order(self, record: OrderRecord) -> None:
        self.session.add(
            OrderRow(
                order_id=record.order_id,
                signal_id=record.intent.signal_id,
                market_slug=record.intent.market_slug,
                asset=record.intent.asset.value,
                side=record.intent.side.value,
                token_id=record.intent.token_id,
                limit_price=record.intent.limit_price,
                size=record.intent.size,
                mode=record.intent.mode.value,
                status=record.status.value,
                detail=record.detail,
                created_ns=record.intent.created_ns,
                submitted_ns=record.submitted_ns,
                acknowledged_ns=record.acknowledged_ns,
            )
        )

    async def save_fill(self, fill: Fill) -> None:
        self.session.add(
            FillRow(
                order_id=fill.order_id,
                signal_id=fill.signal_id,
                market_slug=fill.market_slug,
                asset=fill.asset.value,
                side=fill.side.value,
                price=fill.price,
                size=fill.size,
                fee=fill.fee,
                fill_ts=fill.fill_ts,
                simulated=fill.simulated,
            )
        )

    async def register_capture_file(
        self, market_slug: str, path: str, events: int, complete: bool
    ) -> None:
        self.session.add(
            CaptureFileRow(market_slug=market_slug, path=path, events=events, complete=complete)
        )

    async def count_completed_markets(self) -> int:
        stmt = (
            select(func.count())
            .select_from(MarketResultRow)
            .where(MarketResultRow.complete.is_(True))
        )
        return int((await self.session.execute(stmt)).scalar_one())
