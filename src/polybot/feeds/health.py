"""Aggregate feed-health gate consumed by the risk engine."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from polybot.feeds.base import FeedHealth
from polybot.models.core import FeedSource
from polybot.observability import metrics


@dataclass
class HealthReport:
    healthy: bool
    problems: list[str] = field(default_factory=list)
    ages: dict[str, float] = field(default_factory=dict)


class FeedHealthAggregator:
    def __init__(
        self,
        *,
        max_chainlink_age_s: float,
        max_exchange_age_s: float,
        min_exchange_feeds: int = 1,
    ) -> None:
        self._feeds: dict[FeedSource, FeedHealth] = {}
        self.max_chainlink_age_s = max_chainlink_age_s
        self.max_exchange_age_s = max_exchange_age_s
        self.min_exchange_feeds = min_exchange_feeds

    def register(self, health: FeedHealth) -> None:
        self._feeds[health.source] = health

    def sources(self) -> dict[FeedSource, FeedHealth]:
        """Read-only view of per-source health, for display purposes."""
        return dict(self._feeds)

    def report(self, now_ns: int | None = None) -> HealthReport:
        now = now_ns or time.time_ns()
        problems: list[str] = []
        ages: dict[str, float] = {}

        settlement_fresh = False
        exchange_fresh = 0
        for source, health in self._feeds.items():
            age = health.age_seconds(now)
            ages[source.value] = age
            metrics.FEED_AGE.labels(source=source.value).set(age if age != float("inf") else -1)
            if source.is_settlement:
                if health.connected and age <= self.max_chainlink_age_s:
                    settlement_fresh = True
            elif source in (
                FeedSource.BINANCE_SPOT,
                FeedSource.BINANCE_FUTURES,
                FeedSource.COINBASE,
                FeedSource.OKX,
            ):
                if health.connected and age <= self.max_exchange_age_s:
                    exchange_fresh += 1

        if not settlement_fresh:
            problems.append("no fresh settlement (Chainlink) feed")
        if exchange_fresh < self.min_exchange_feeds:
            problems.append(
                f"only {exchange_fresh} fresh exchange feeds (< {self.min_exchange_feeds})"
            )
        return HealthReport(healthy=not problems, problems=problems, ages=ages)
