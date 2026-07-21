"""Live and shadow execution via the official Polymarket CLOB client.

* LIVE: builds, signs, and posts a marketable FAK limit order with an
  explicit limit price. Bounded retries only (a failed post is not retried —
  the opportunity is gone; the strategy will re-evaluate).
* SHADOW: builds and signs the identical order and completes every
  validation, then stops before the POST. Used to measure realistic
  signal-to-ready latency without market impact.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY

from polybot.config import ExecutionConfig
from polybot.execution.delay import DelayTracker
from polybot.models.core import OrderIntent, OrderRecord, OrderStatus, TradingMode
from polybot.observability import metrics

logger = logging.getLogger(__name__)


def build_clob_client(config: ExecutionConfig) -> ClobClient:
    creds = None
    if config.api_key and config.api_secret and config.api_passphrase:
        creds = ApiCreds(
            api_key=config.api_key,
            api_secret=config.api_secret,
            api_passphrase=config.api_passphrase,
        )
    return ClobClient(
        config.clob_base_url,
        chain_id=config.chain_id,
        key=config.private_key or None,
        creds=creds,
        signature_type=config.signature_type or None,
        funder=config.funder_address or None,
    )


class ClobExecutor:
    def __init__(
        self,
        client: ClobClient,
        config: ExecutionConfig,
        delay_tracker: DelayTracker,
        *,
        shadow: bool,
    ) -> None:
        self.client = client
        self.config = config
        self.delay_tracker = delay_tracker
        self.shadow = shadow

    async def submit(self, intent: OrderIntent) -> OrderRecord:
        if intent.size < self.config.min_order_size_shares:
            return self._terminal(
                intent,
                OrderStatus.REJECTED,
                f"size {intent.size:.2f} below CLOB minimum {self.config.min_order_size_shares}",
            )
        try:
            signed = await asyncio.to_thread(self._build_and_sign, intent)
        except Exception as exc:
            logger.exception("order build/sign failed")
            return self._terminal(intent, OrderStatus.REJECTED, f"sign failed: {exc!r}")

        if self.shadow:
            record = OrderRecord(
                intent=intent,
                order_id=None,
                status=OrderStatus.SIGNED,
                submitted_ns=None,
                detail="shadow mode: signed and validated, not sent",
            )
            metrics.ORDERS.labels(
                asset=intent.asset.value,
                status=record.status.value,
                mode=TradingMode.SHADOW.value,
            ).inc()
            return record

        submitted_ns = time.time_ns()
        try:
            response: dict[str, Any] = await asyncio.wait_for(
                asyncio.to_thread(self.client.post_order, signed, OrderType.FAK),
                timeout=self.config.submit_timeout_s,
            )
        except TimeoutError:
            return self._terminal(
                intent, OrderStatus.REJECTED, "post_order timeout", submitted_ns=submitted_ns
            )
        except Exception as exc:
            logger.exception("post_order failed")
            return self._terminal(
                intent, OrderStatus.REJECTED, f"post failed: {exc!r}", submitted_ns=submitted_ns
            )

        ack_ns = time.time_ns()
        order_id = str(response.get("orderID") or response.get("orderId") or "")
        success = bool(response.get("success", bool(order_id)))
        status = OrderStatus.ACKNOWLEDGED if success else OrderStatus.REJECTED
        if order_id:
            self.delay_tracker.on_submitted(order_id, submitted_ns)
            self.delay_tracker.on_acknowledged(order_id, ack_ns)
        record = OrderRecord(
            intent=intent,
            order_id=order_id or None,
            status=status,
            submitted_ns=submitted_ns,
            acknowledged_ns=ack_ns,
            detail=str(response.get("errorMsg") or response.get("status") or ""),
        )
        metrics.ORDERS.labels(
            asset=intent.asset.value, status=status.value, mode=intent.mode.value
        ).inc()
        return record

    def _build_and_sign(self, intent: OrderIntent) -> Any:
        args = OrderArgs(
            token_id=intent.token_id,
            price=round(intent.limit_price, 4),
            size=round(intent.size, 2),
            side=BUY,
        )
        return self.client.create_order(args)

    def _terminal(
        self,
        intent: OrderIntent,
        status: OrderStatus,
        detail: str,
        submitted_ns: int | None = None,
    ) -> OrderRecord:
        metrics.ORDERS.labels(
            asset=intent.asset.value, status=status.value, mode=intent.mode.value
        ).inc()
        return OrderRecord(
            intent=intent,
            order_id=None,
            status=status,
            submitted_ns=submitted_ns,
            detail=detail,
        )
