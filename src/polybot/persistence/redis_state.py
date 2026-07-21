"""Redis-backed hot runtime state: kill switch flag and daily counters."""

from __future__ import annotations

import redis.asyncio as aioredis


class RedisState:
    def __init__(self, url: str) -> None:
        self._redis: aioredis.Redis = aioredis.from_url(url, decode_responses=True)

    async def is_kill_switch_set(self, key: str) -> bool:
        try:
            return bool(await self._redis.exists(key))
        except Exception:
            # Redis unreachable => fail closed for trading decisions.
            return True

    async def engage_kill_switch(self, key: str, reason: str) -> None:
        await self._redis.set(key, reason)

    async def clear_kill_switch(self, key: str) -> None:
        await self._redis.delete(key)

    async def incr_daily(self, key: str, amount: float) -> float:
        return float(await self._redis.incrbyfloat(key, amount))

    async def get_float(self, key: str, default: float = 0.0) -> float:
        value = await self._redis.get(key)
        return float(value) if value is not None else default

    async def close(self) -> None:
        await self._redis.aclose()
