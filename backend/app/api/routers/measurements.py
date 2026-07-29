"""Body measurements CRUD (FR-060/061 / FR-005b)."""

from __future__ import annotations

from datetime import UTC
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_current_user_rate_limited
from app.core.ids import new_uuid7
from app.db.session import get_session
from app.models.body_measurement import BodyMeasurement
from app.repositories.access import get_for_user
from app.schemas.api import BodyMetricsV1, MeasurementCreateV1, MeasurementReadV1
from app.schemas.common import parse_versioned
from app.services.measurements import soft_delete_measurement as mark_measurement_deleted

router = APIRouter(prefix="/measurements", tags=["measurements"])


class MeasurementListResponse(BaseModel):
    schema_version: int = 1
    items: list[MeasurementReadV1]


def _to_read(row: BodyMeasurement) -> MeasurementReadV1:
    return MeasurementReadV1(
        id=row.id,
        measured_at=row.measured_at,
        local_date=row.local_date,
        metrics=row.metrics,
        notes=row.notes,
        revision=row.revision,
    )


async def _set_rls(db: AsyncSession, user_id: UUID) -> None:
    await db.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(user_id)},
    )


@router.get("", response_model=MeasurementListResponse)
async def list_measurements(
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> MeasurementListResponse:
    await _set_rls(db, ctx.user.id)
    rows = (
        await db.scalars(
            select(BodyMeasurement).where(
                BodyMeasurement.user_id == ctx.user.id,
                BodyMeasurement.deleted_at.is_(None),
            )
        )
    ).all()
    return MeasurementListResponse(items=[_to_read(r) for r in rows])


@router.post("", response_model=MeasurementReadV1)
async def create_measurement(
    body: MeasurementCreateV1,
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> MeasurementReadV1:
    await _set_rls(db, ctx.user.id)
    parse_versioned(BodyMetricsV1, body.metrics)
    measured_at = body.measured_at
    if measured_at.tzinfo is None:
        measured_at = measured_at.replace(tzinfo=UTC)
    row = BodyMeasurement(
        id=new_uuid7(),
        user_id=ctx.user.id,
        measured_at=measured_at,
        local_date=body.local_date,
        metrics=body.metrics,
        notes=body.notes,
        client_mutation_id=body.client_mutation_id,
        revision=1,
        client_updated_at=body.client_updated_at or measured_at,
    )
    db.add(row)
    await db.commit()
    await _set_rls(db, ctx.user.id)
    await db.refresh(row)
    return _to_read(row)


@router.get("/{measurement_id}", response_model=MeasurementReadV1)
async def get_measurement(
    measurement_id: UUID,
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> MeasurementReadV1:
    await _set_rls(db, ctx.user.id)
    row = await get_for_user(
        db,
        BodyMeasurement,
        user_id=ctx.user.id,
        entity_id=measurement_id,
    )
    return _to_read(row)


@router.delete("/{measurement_id}", response_model=MeasurementReadV1)
async def soft_delete_measurement(
    measurement_id: UUID,
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> MeasurementReadV1:
    await _set_rls(db, ctx.user.id)
    row = await get_for_user(
        db,
        BodyMeasurement,
        user_id=ctx.user.id,
        entity_id=measurement_id,
    )
    if row.deleted_at is None:
        await mark_measurement_deleted(db, row)
        await db.commit()
        await _set_rls(db, ctx.user.id)
        await db.refresh(row)
    return _to_read(row)
