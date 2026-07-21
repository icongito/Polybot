"""Per-market resolution-rule validation.

Every market's description is parsed and checked before the market is
considered tradable. The bot never assumes all markets share the same rules:
if the text does not clearly state Chainlink settlement and the
"close >= open resolves Up" convention for the expected interval, the market
is recorded but never traded.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from polybot.models.core import ResolutionRules

_CHAINLINK_RE = re.compile(r"chainlink", re.IGNORECASE)
_UP_ON_EQUAL_PATTERNS = (
    re.compile(r"higher than or equal", re.IGNORECASE),
    re.compile(r"greater than or equal", re.IGNORECASE),
    re.compile(r"equal to or (higher|greater)", re.IGNORECASE),
    re.compile(r"at or above", re.IGNORECASE),
    re.compile(r">=\s*(the\s+)?(open|start)", re.IGNORECASE),
)
_DOWN_ON_EQUAL_PATTERNS = (
    re.compile(r"resolve[sd]?\s+(to\s+)?[\"']?down[\"']?\s+if.*equal", re.IGNORECASE | re.DOTALL),
)
_TIMESTAMP_RE = re.compile(
    r"(\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?\s*(?:ET|EST|EDT|UTC)?)", re.IGNORECASE
)


def validate_resolution_rules(
    description: str,
    resolution_source: str,
    expected_start_ts: float,
    expected_end_ts: float,
) -> ResolutionRules:
    problems: list[str] = []

    text = f"{description}\n{resolution_source}"
    references_chainlink = bool(_CHAINLINK_RE.search(text))
    if not references_chainlink:
        problems.append("resolution text does not reference Chainlink")

    up_wins_on_equal = any(p.search(description) for p in _UP_ON_EQUAL_PATTERNS)
    if any(p.search(description) for p in _DOWN_ON_EQUAL_PATTERNS):
        up_wins_on_equal = False
        problems.append("market resolves DOWN on equality (non-standard tie rule)")
    if not up_wins_on_equal and not problems:
        problems.append("could not confirm 'close >= open resolves Up' tie rule")

    interval = expected_end_ts - expected_start_ts
    if abs(interval - 300.0) > 1.0:
        problems.append(f"interval is {interval:.0f}s, expected 300s")
    if not _TIMESTAMP_RE.search(description):
        # Not fatal on its own, but recorded — descriptions normally state the window.
        problems.append("no explicit time window found in description")

    valid = references_chainlink and up_wins_on_equal and abs(interval - 300.0) <= 1.0
    return ResolutionRules(
        raw_description=description,
        resolution_source=resolution_source,
        references_chainlink=references_chainlink,
        up_wins_on_equal=up_wins_on_equal,
        interval_start_ts=expected_start_ts,
        interval_end_ts=expected_end_ts,
        valid=valid,
        problems=tuple(problems),
    )


def format_window(start_ts: float, end_ts: float) -> str:
    fmt = "%Y-%m-%d %H:%M:%S UTC"
    return (
        f"{datetime.fromtimestamp(start_ts, tz=UTC).strftime(fmt)}"
        f" -> {datetime.fromtimestamp(end_ts, tz=UTC).strftime(fmt)}"
    )
