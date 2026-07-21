"""Clock services: nanosecond timestamps, simulated time for replay, and
NTP/chrony drift measurement gating live trading."""

from __future__ import annotations

import asyncio
import logging
import re
import socket
import struct
import time
from typing import Protocol

logger = logging.getLogger(__name__)

NTP_EPOCH_OFFSET = 2208988800  # seconds between 1900-01-01 and 1970-01-01


class Clock(Protocol):
    def now_ns(self) -> int: ...

    def now_s(self) -> float: ...


class WallClock:
    """Real wall clock, nanosecond resolution where the platform supports it."""

    def now_ns(self) -> int:
        return time.time_ns()

    def now_s(self) -> float:
        return time.time()


class SimClock:
    """Deterministic clock driven by the replay engine."""

    def __init__(self, start_ns: int = 0) -> None:
        self._now_ns = start_ns

    def now_ns(self) -> int:
        return self._now_ns

    def now_s(self) -> float:
        return self._now_ns / 1e9

    def advance_to_ns(self, ts_ns: int) -> None:
        if ts_ns < self._now_ns:
            raise ValueError(f"SimClock cannot go backwards: {ts_ns} < {self._now_ns}")
        self._now_ns = ts_ns


async def chrony_offset_s() -> float | None:
    """Read the current offset from chronyc if available."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "chronyc",
            "tracking",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
    except (FileNotFoundError, TimeoutError, OSError):
        return None
    match = re.search(r"System time\s*:\s*([\d.]+) seconds (fast|slow)", stdout.decode())
    if not match:
        return None
    offset = float(match.group(1))
    return offset if match.group(2) == "fast" else -offset


def _ntp_query_blocking(server: str, timeout: float) -> float:
    """Single SNTP query; returns local-minus-server offset in seconds."""
    packet = b"\x1b" + 47 * b"\0"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        t_send = time.time()
        sock.sendto(packet, (server, 123))
        data, _ = sock.recvfrom(512)
        t_recv = time.time()
    if len(data) < 48:
        raise ValueError("short NTP response")
    unpacked: tuple[int, ...] = struct.unpack("!12I", data[:48])
    tx_ts = unpacked[10] + unpacked[11] / 2**32 - NTP_EPOCH_OFFSET
    rx_ts = unpacked[8] + unpacked[9] / 2**32 - NTP_EPOCH_OFFSET
    # Standard NTP offset: ((rx - send) + (tx - recv)) / 2, from server view.
    return float(-(((rx_ts - t_send) + (tx_ts - t_recv)) / 2.0))


async def ntp_offset_s(server: str = "pool.ntp.org", timeout_s: float = 3.0) -> float | None:
    try:
        return await asyncio.to_thread(_ntp_query_blocking, server, timeout_s)
    except (OSError, ValueError, TimeoutError):
        return None


class DriftMonitor:
    """Periodically measures clock drift; exposes a trading gate.

    Prefers chrony (authoritative when the host runs chronyd) and falls back
    to a direct SNTP probe. If neither source is reachable the drift is
    unknown and trading is blocked (fail-closed).
    """

    def __init__(self, max_drift_s: float, check_interval_s: float = 60.0) -> None:
        self.max_drift_s = max_drift_s
        self.check_interval_s = check_interval_s
        self.last_offset_s: float | None = None
        self.last_checked_ns: int | None = None
        self._task: asyncio.Task[None] | None = None

    async def measure_once(self) -> float | None:
        offset = await chrony_offset_s()
        if offset is None:
            offset = await ntp_offset_s()
        self.last_offset_s = offset
        self.last_checked_ns = time.time_ns()
        if offset is None:
            logger.warning("clock drift unknown: chrony and NTP both unreachable")
        elif abs(offset) > self.max_drift_s:
            logger.error("clock drift %.4fs exceeds limit %.4fs", offset, self.max_drift_s)
        return offset

    @property
    def trading_allowed(self) -> bool:
        return self.last_offset_s is not None and abs(self.last_offset_s) <= self.max_drift_s

    async def _run(self) -> None:
        while True:
            await self.measure_once()
            await asyncio.sleep(self.check_interval_s)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="drift-monitor")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
