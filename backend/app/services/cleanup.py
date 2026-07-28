"""Cleanup expired auth/oauth/rate-limit rows (FR-005c / FR-005d)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import AuthSession, OAuthState
from app.models.sync import RateLimitBucket

logger = logging.getLogger(__name__)

AUTH_SESSION_RETENTION_DAYS = 7
OAUTH_STATE_RETENTION_HOURS = 24
RATE_LIMIT_RETENTION_HOURS = 2


async def cleanup_auth_sessions(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    retention_days: int = AUTH_SESSION_RETENTION_DAYS,
) -> int:
    """Hard-delete sessions with revoked_at or expires_at older than retention (FR-005d)."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
    result = await db.execute(
        delete(AuthSession).where(
            or_(
                AuthSession.revoked_at < cutoff,
                AuthSession.expires_at < cutoff,
            ),
        )
    )
    return int(result.rowcount or 0)


async def cleanup_oauth_states(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    retention_hours: int = OAUTH_STATE_RETENTION_HOURS,
) -> int:
    """Drop expired / consumed OAuth PKCE states."""
    cutoff = (now or datetime.now(UTC)) - timedelta(hours=retention_hours)
    result = await db.execute(
        delete(OAuthState).where(
            or_(
                OAuthState.expires_at < cutoff,
                OAuthState.consumed_at.is_not(None),
            )
        )
    )
    return int(result.rowcount or 0)


async def cleanup_rate_limit_buckets(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    retention_hours: int = RATE_LIMIT_RETENTION_HOURS,
) -> int:
    """Drop fixed-window buckets older than ~2h (FR-005c)."""
    cutoff = (now or datetime.now(UTC)) - timedelta(hours=retention_hours)
    result = await db.execute(
        delete(RateLimitBucket).where(RateLimitBucket.window_start < cutoff)
    )
    return int(result.rowcount or 0)


async def run_cleanup_batch(db: AsyncSession) -> dict[str, int]:
    now = datetime.now(UTC)
    auth_n = await cleanup_auth_sessions(db, now=now)
    oauth_n = await cleanup_oauth_states(db, now=now)
    rl_n = await cleanup_rate_limit_buckets(db, now=now)
    await db.commit()
    logger.info(
        "cleanup.ok auth_sessions=%s oauth_states=%s rate_limit_buckets=%s",
        auth_n,
        oauth_n,
        rl_n,
        extra={
            "event": "cleanup.ok",
            "auth_sessions": auth_n,
            "oauth_states": oauth_n,
            "rate_limit_buckets": rl_n,
        },
    )
    return {
        "auth_sessions": auth_n,
        "oauth_states": oauth_n,
        "rate_limit_buckets": rl_n,
    }
