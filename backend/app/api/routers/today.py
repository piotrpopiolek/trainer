"""GET /today (FR-040b)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_current_user_rate_limited
from app.db.session import get_session
from app.schemas.api import TodaySessionDto
from app.services.today import build_today

router = APIRouter(tags=["today"])


@router.get("/today", response_model=TodaySessionDto)
async def get_today(
    local_date: date | None = None,
    cc_day_override: int | None = Query(default=None, ge=1, le=3),
    locale: str | None = None,
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> TodaySessionDto:
    return await build_today(
        db,
        user=ctx.user,
        local_date=local_date,
        cc_day_override=cc_day_override,
        locale=locale,
    )
