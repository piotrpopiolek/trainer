"""Body measurements read path — first IDOR surface (FR-005b)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_current_user_rate_limited
from app.db.session import get_session
from app.models.body_measurement import BodyMeasurement
from app.repositories.access import get_for_user

router = APIRouter(prefix="/measurements", tags=["measurements"])


class MeasurementResponse(BaseModel):
    schema_version: int = 1
    id: str
    measured_at: datetime
    local_date: date
    metrics: dict[str, Any]
    notes: str | None
    revision: int


@router.get("/{measurement_id}")
async def get_measurement(
    measurement_id: UUID,
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> MeasurementResponse:
    await db.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(ctx.user.id)},
    )
    row = await get_for_user(
        db,
        BodyMeasurement,
        user_id=ctx.user.id,
        entity_id=measurement_id,
    )
    return MeasurementResponse(
        id=str(row.id),
        measured_at=row.measured_at,
        local_date=row.local_date,
        metrics=row.metrics,
        notes=row.notes,
        revision=row.revision,
    )
