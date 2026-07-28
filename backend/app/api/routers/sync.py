"""Sync push/pull HTTP (FR-072*/075)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_current_user_rate_limited
from app.core.config import settings
from app.db.session import get_session
from app.schemas.sync import SyncPullResponseV1, SyncPushRequestV1, SyncPushResponseV1
from app.services.rate_limit import get_rate_limiter, user_sync_push_bucket_key
from app.services.sync_pull import pull
from app.services.sync_push import push_batch

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/push", response_model=SyncPushResponseV1)
async def sync_push(
    body: SyncPushRequestV1,
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> SyncPushResponseV1:
    limiter = get_rate_limiter()
    await limiter.hit(
        db,
        bucket_key=user_sync_push_bucket_key(ctx.user.id),
        limit=settings.sync_push_rate_limit_per_minute,
    )
    return await push_batch(db, user=ctx.user, body=body)


@router.get("/pull", response_model=SyncPullResponseV1)
async def sync_pull(
    since: datetime | None = Query(default=None),
    locale: str | None = Query(default=None),
    device_id: str | None = Query(default=None),
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> SyncPullResponseV1:
    return await pull(
        db,
        user=ctx.user,
        since=since,
        locale=locale,
        device_id=device_id,
    )
