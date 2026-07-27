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
    get_current_user_rate_limited,
    require_csrf,
)
from app.db.session import get_session
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


class AccountStubResponse(BaseModel):
    schema_version: int = 1
    status: str


def _local_today(timezone_name: str) -> date:
    try:
        return datetime.now(ZoneInfo(timezone_name)).date()
    except ZoneInfoNotFoundError as exc:
        raise DomainError("invalid_timezone", http_status=422) from exc


@router.post("/export")
async def export_account(
    _csrf: None = Depends(require_csrf),
    ctx: AuthContext = Depends(get_current_user_rate_limited),
) -> StreamingResponse:
    del ctx  # auth + CSRF gate; full NDJSON stream in api-readwrite

    async def _chunks() -> AsyncIterator[bytes]:
        yield b'{"schema_version":1,"collection":"meta","status":"stub"}\n'

    return StreamingResponse(
        _chunks(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/delete")
async def delete_account(
    _csrf: None = Depends(require_csrf),
    ctx: AuthContext = Depends(get_current_user_rate_limited),
) -> AccountStubResponse:
    # Full AccountDeletionService lands in api-readwrite; CSRF + session gate here.
    del ctx
    return AccountStubResponse(status="stub")


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
