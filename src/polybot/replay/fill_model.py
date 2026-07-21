"""Book history index used by the replay fill model.

The strategy's signal generation only ever sees state already replayed up to
the current simulated time ("no future data"). The *fill* model is different:
once an order is submitted, Polymarket's actual taker delay means the fill
happens at ``now + latencies`` — a short, deterministic offset in the future.
Since replay already holds the full recorded interval on disk, looking up the
book at that fixed future offset is not a leak into the strategy; it is
exactly what "model network/signing/taker delay against the recorded book"
requires. This module is the only place replay is allowed to look forward.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field

from polybot.models.core import BookSnapshot


@dataclass
class BookHistory:
    _by_token: dict[str, list[tuple[int, BookSnapshot]]] = field(default_factory=dict)

    def add(self, snapshot: BookSnapshot) -> None:
        series = self._by_token.setdefault(snapshot.token_id, [])
        series.append((snapshot.local_recv_ns, snapshot))

    def finalize(self) -> None:
        for series in self._by_token.values():
            series.sort(key=lambda item: item[0])

    def at(self, token_id: str, ts_ns: int) -> BookSnapshot | None:
        """Last known book for ``token_id`` at or before ``ts_ns``."""
        series = self._by_token.get(token_id)
        if not series:
            return None
        keys = [item[0] for item in series]
        idx = bisect.bisect_right(keys, ts_ns) - 1
        if idx < 0:
            return None
        return series[idx][1]
