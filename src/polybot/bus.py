"""In-process async event bus.

Feeds publish normalized events; the strategy engine, recorder, and metrics
each subscribe with an independent bounded queue. Slow subscribers drop the
oldest events (feeds must never back-pressure the socket reads) — except
subscribers marked lossless (the recorder), which grow unbounded and are
drained by their own writer task.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from polybot.models.core import BookSnapshot, Fill, MarketInfo, OpeningPrice, Signal, Tick

logger = logging.getLogger(__name__)

Event = Tick | BookSnapshot | MarketInfo | OpeningPrice | Signal | Fill


@dataclass
class Subscription:
    name: str
    queue: asyncio.Queue[Event]
    lossless: bool
    dropped: int = 0

    async def __aiter__(self) -> AsyncIterator[Event]:
        while True:
            yield await self.queue.get()


@dataclass
class EventBus:
    default_maxsize: int = 10_000
    _subs: list[Subscription] = field(default_factory=list)

    def subscribe(
        self, name: str, *, lossless: bool = False, maxsize: int | None = None
    ) -> Subscription:
        size = 0 if lossless else (maxsize or self.default_maxsize)
        sub = Subscription(name=name, queue=asyncio.Queue(maxsize=size), lossless=lossless)
        self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        if sub in self._subs:
            self._subs.remove(sub)

    def publish(self, event: Event) -> None:
        for sub in self._subs:
            if sub.lossless:
                sub.queue.put_nowait(event)
                continue
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    sub.queue.get_nowait()
                except asyncio.QueueEmpty:  # pragma: no cover - race window
                    pass
                sub.queue.put_nowait(event)
                sub.dropped += 1
                if sub.dropped % 1000 == 1:
                    logger.warning("subscriber %s dropped %d events", sub.name, sub.dropped)
