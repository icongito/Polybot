"""Envelope format for the append-only capture log.

Every bus event (and a few internal events like discovery responses and
rejected signals) is wrapped in a single-line JSON envelope:

    {"t": "<event type tag>", "recv_ns": <int>, "data": {...}}

``recv_ns`` is always the local receive/creation nanosecond timestamp so the
replay engine can merge multiple capture files in strict chronological order
without ever looking at wall-clock "now".
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

EventTag = Literal[
    "tick",
    "book",
    "market",
    "opening",
    "signal",
    "order",
    "fill",
    "result",
]


class CaptureEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    t: EventTag
    recv_ns: int
    data: dict[str, Any]
