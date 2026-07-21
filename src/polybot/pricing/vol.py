"""Short-horizon realized volatility from high-frequency ticks.

Maintains an EWMA of squared log-returns normalized per second, yielding a
per-sqrt-second volatility usable directly in the Brownian remaining-move
model: stdev of the remaining return over ``tau`` seconds = sigma * sqrt(tau).
"""

from __future__ import annotations

import math


class RealizedVol:
    def __init__(self, halflife_s: float, floor_per_sqrt_s: float, min_ticks: int) -> None:
        self.halflife_s = halflife_s
        self.floor = floor_per_sqrt_s
        self.min_ticks = min_ticks
        self._last_price: float | None = None
        self._last_ts: float | None = None
        self._var_per_s: float | None = None  # EWMA variance of returns per second
        self.samples = 0

    def update(self, price: float, ts: float) -> None:
        if price <= 0:
            return
        if self._last_price is None or self._last_ts is None:
            self._last_price, self._last_ts = price, ts
            return
        dt = ts - self._last_ts
        if dt <= 0:
            return
        log_return = math.log(price / self._last_price)
        var_per_s = (log_return * log_return) / dt
        alpha = 1 - math.exp(-math.log(2) * dt / self.halflife_s)
        if self._var_per_s is None:
            self._var_per_s = var_per_s
        else:
            self._var_per_s += alpha * (var_per_s - self._var_per_s)
        self._last_price, self._last_ts = price, ts
        self.samples += 1

    @property
    def ready(self) -> bool:
        return self.samples >= self.min_ticks and self._var_per_s is not None

    def sigma_per_sqrt_s(self) -> float:
        """Volatility of log returns per sqrt(second), floored."""
        if self._var_per_s is None:
            return self.floor
        return max(self.floor, math.sqrt(self._var_per_s))

    def remaining_move_stdev(self, seconds: float) -> float:
        """Stdev of the log return over the next ``seconds`` seconds."""
        return self.sigma_per_sqrt_s() * math.sqrt(max(0.0, seconds))
