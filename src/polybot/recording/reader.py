"""Reads back capture files written by :mod:`polybot.recording.writer`."""

from __future__ import annotations

import gzip
from collections.abc import Iterator
from pathlib import Path

from polybot.recording.schema import CaptureEnvelope


def open_capture(path: str | Path) -> Iterator[CaptureEnvelope]:
    p = Path(path)
    opener = gzip.open if p.suffix == ".gz" else open
    with opener(p, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield CaptureEnvelope.model_validate_json(line)


def list_captures(capture_dir: str | Path, asset: str | None = None) -> list[Path]:
    root = Path(capture_dir)
    pattern = f"{asset}/*.ndjson*" if asset else "*/*.ndjson*"
    return sorted(root.glob(pattern))
