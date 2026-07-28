"""Fixed-window rate limits (FR-005c) — OAuth IP buckets for auth-session."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_ip_for_rate_limit
from app.services.errors import RateLimitedError

_memory_lock = threading.Lock()
_memory_buckets: dict[tuple[str, datetime], int] = {}


def oauth_bucket_key(ip: str) -> str:
    return f"ip:{hash_ip_for_rate_limit(ip)}:oauth"


def user_api_bucket_key(user_id: object) -> str:
    return f"u:{user_id}:api"


def user_sync_push_bucket_key(user_id: object) -> str:
    return f"u:{user_id}:sync_push"


def _window_start(now: datetime | None = None) -> datetime:
    moment = now or datetime.now(UTC)
    return moment.replace(second=0, microsecond=0)


def _seconds_until_next_window(now: datetime | None = None) -> int:
    moment = now or datetime.now(UTC)
    return max(1, 60 - moment.second)


class RateLimiter(Protocol):
    async def hit(self, db: AsyncSession, *, bucket_key: str, limit: int) -> None: ...


class MemoryRateLimiter:
    async def hit(self, db: AsyncSession, *, bucket_key: str, limit: int) -> None:
        del db  # unused — memory store
        window = _window_start()
        key = (bucket_key, window)
        with _memory_lock:
            count = _memory_buckets.get(key, 0) + 1
            _memory_buckets[key] = count
        if count > limit:
            raise RateLimitedError(retry_after=_seconds_until_next_window())


class PostgresRateLimiter:
    async def hit(self, db: AsyncSession, *, bucket_key: str, limit: int) -> None:
        window = _window_start()
        result = await db.execute(
            text(
                """
                INSERT INTO rate_limit_buckets (bucket_key, window_start, count)
                VALUES (:bucket_key, :window_start, 1)
                ON CONFLICT (bucket_key, window_start)
                DO UPDATE SET count = rate_limit_buckets.count + 1
                RETURNING count
                """
            ),
            {"bucket_key": bucket_key, "window_start": window},
        )
        count = int(result.scalar_one())
        await db.commit()
        if count > limit:
            raise RateLimitedError(retry_after=_seconds_until_next_window())


def get_rate_limiter() -> RateLimiter:
    store = settings.rate_limit_store.lower()
    if settings.app_env in {"production", "staging"} and store == "memory":
        return PostgresRateLimiter()
    if store in {"postgres", "pg", "postgresql"}:
        return PostgresRateLimiter()
    return MemoryRateLimiter()


def reset_memory_rate_limits() -> None:
    with _memory_lock:
        _memory_buckets.clear()
