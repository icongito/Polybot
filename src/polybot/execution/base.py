"""Execution backend protocol shared by live/shadow/paper backends."""

from __future__ import annotations

from typing import Protocol

from polybot.models.core import OrderIntent, OrderRecord


class ExecutionBackend(Protocol):
    async def submit(self, intent: OrderIntent) -> OrderRecord: ...
