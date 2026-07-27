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
from app.services.errors import AuthError

router = APIRouter(prefix="/account", tags=["account"])


class SchedulePatchRequest(BaseModel):
    schema_version: int = 1
    pending_timezone: str | None = Field(default=None, min_length=1, max_length=64)


class SchedulePatchResponse(BaseModel):
    schema_version: int = 1
    pending_timezone: str | None
    timezone_effective_on: date | None


class AccountStubResponse(BaseModel):
    schema_version: int = 1
    status: str


def _local_today(timezone_name: str) -> date:
    try:
        return datetime.now(ZoneInfo(timezone_name)).date()
    except ZoneInfoNotFoundError as exc:
        raise AuthError("invalid_timezone", http_status=422) from exc


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
    if body.pending_timezone is not None:
        try:
            ZoneInfo(body.pending_timezone)
        except ZoneInfoNotFoundError as exc:
            raise AuthError("invalid_timezone", http_status=422) from exc
        user.pending_timezone = body.pending_timezone
        user.timezone_effective_on = _local_today(user.timezone) + timedelta(days=1)
    await db.commit()
    await db.refresh(user)
    return SchedulePatchResponse(
        pending_timezone=user.pending_timezone,
        timezone_effective_on=user.timezone_effective_on,
    )
