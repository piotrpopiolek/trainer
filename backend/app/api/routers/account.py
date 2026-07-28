"""Account mutations guarded by CSRF (FR-005a / FR-006a/b / FR-022b)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    AuthContext,
    get_auth_session_service,
    get_current_user_rate_limited,
    require_csrf,
)
from app.db.session import get_session
from app.services.account import soft_delete_account, stream_account_export
from app.services.auth_session import AuthSessionService
from app.services.cc_day import get_active_enrollment
from app.services.errors import DomainError

router = APIRouter(prefix="/account", tags=["account"])


class SchedulePatchRequest(BaseModel):
    schema_version: int = 1
    pending_timezone: str | None = Field(default=None, min_length=1, max_length=64)
    pending_anchor_weekday: int | None = Field(default=None, ge=1, le=2)


class SchedulePatchResponse(BaseModel):
    schema_version: int = 1
    pending_timezone: str | None
    timezone_effective_on: date | None
    pending_anchor_weekday: int | None = None
    schedule_effective_on: date | None = None


class AccountDeleteResponse(BaseModel):
    schema_version: int = 1
    status: str
    purge_after: str | None = None


def _local_today(timezone_name: str) -> date:
    try:
        return datetime.now(ZoneInfo(timezone_name)).date()
    except ZoneInfoNotFoundError as exc:
        raise DomainError("invalid_timezone", http_status=422) from exc


@router.post("/export")
async def export_account(
    _csrf: None = Depends(require_csrf),
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    async def _chunks() -> AsyncIterator[bytes]:
        async for chunk in stream_account_export(db, user_id=ctx.user.id):
            yield chunk

    return StreamingResponse(
        _chunks(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/delete", response_model=AccountDeleteResponse)
async def delete_account(
    _csrf: None = Depends(require_csrf),
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
    auth_sessions: AuthSessionService = Depends(get_auth_session_service),
) -> AccountDeleteResponse:
    result = await soft_delete_account(db, user=ctx.user, auth_sessions=auth_sessions)
    return AccountDeleteResponse(
        status=result["status"],
        purge_after=result.get("purge_after"),
    )


@router.patch("/schedule")
async def patch_schedule(
    body: SchedulePatchRequest,
    _csrf: None = Depends(require_csrf),
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> SchedulePatchResponse:
    user = ctx.user
    tomorrow = _local_today(user.timezone) + timedelta(days=1)
    enrollment = await get_active_enrollment(db, user.id)

    if body.pending_timezone is not None:
        try:
            ZoneInfo(body.pending_timezone)
        except ZoneInfoNotFoundError as exc:
            raise DomainError("invalid_timezone", http_status=422) from exc
        user.pending_timezone = body.pending_timezone
        user.timezone_effective_on = tomorrow

    if body.pending_anchor_weekday is not None:
        if enrollment is None:
            raise DomainError("enrollment_required", http_status=422)
        enrollment.pending_anchor_weekday = body.pending_anchor_weekday
        enrollment.schedule_effective_on = tomorrow

    await db.commit()
    await db.refresh(user)
    if enrollment is not None:
        await db.refresh(enrollment)

    return SchedulePatchResponse(
        pending_timezone=user.pending_timezone,
        timezone_effective_on=user.timezone_effective_on,
        pending_anchor_weekday=(
            enrollment.pending_anchor_weekday if enrollment else None
        ),
        schedule_effective_on=(
            enrollment.schedule_effective_on if enrollment else None
        ),
    )
