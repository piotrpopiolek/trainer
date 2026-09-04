"""Progress list + manual override (FR-038 / US-016b) + satellite progress charts."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_current_user_rate_limited
from app.db.session import get_session
from app.models.catalog import Exercise
from app.models.progression import UserExerciseProgress
from app.schemas.api import (
    ProgressionEventReadV1,
    ProgressItemV1,
    ProgressOverrideRequestV1,
    SatelliteProgressItemV1,
    SatelliteProgressListV1,
)
from app.services.errors import DomainError, NotFoundError
from app.services.progression import ProgressionEngine
from app.services.satellite_progress_read import (
    get_satellite_progress_item,
    list_satellite_progress,
)
from app.services.sessions import (
    event_to_read,
    last_session_summaries_by_exercise,
    progress_to_read,
)

router = APIRouter(prefix="/progress", tags=["progress"])
_engine = ProgressionEngine()


class ProgressListResponse(BaseModel):
    schema_version: int = 1
    items: list[ProgressItemV1]


class ProgressOverrideResponse(BaseModel):
    schema_version: int = 1
    progress: ProgressItemV1
    event: ProgressionEventReadV1


async def _owned_progress_exercise(
    db: AsyncSession,
    *,
    user_id: UUID,
    exercise_id: UUID,
) -> Exercise:
    exercise = await db.scalar(select(Exercise).where(Exercise.id == exercise_id))
    if exercise is None or exercise.deleted_at is not None:
        raise NotFoundError()
    if exercise.kind == "cc":
        if exercise.user_id is not None:
            raise NotFoundError()
        return exercise
    if exercise.kind == "satellite" and exercise.user_id == user_id:
        return exercise
    raise NotFoundError()


@router.get("/satellites", response_model=SatelliteProgressListV1)
async def list_satellite_progress_route(
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> SatelliteProgressListV1:
    return await list_satellite_progress(
        db,
        user_id=ctx.user.id,
        timezone_name=ctx.user.timezone or "Europe/Warsaw",
    )


@router.get("/satellites/{exercise_id}", response_model=SatelliteProgressItemV1)
async def get_satellite_progress_route(
    exercise_id: UUID,
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> SatelliteProgressItemV1:
    return await get_satellite_progress_item(
        db,
        user_id=ctx.user.id,
        exercise_id=exercise_id,
        timezone_name=ctx.user.timezone or "Europe/Warsaw",
    )


@router.get("", response_model=ProgressListResponse)
async def list_progress(
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> ProgressListResponse:
    rows = (
        await db.scalars(
            select(UserExerciseProgress).where(UserExerciseProgress.user_id == ctx.user.id)
        )
    ).all()
    summaries = await last_session_summaries_by_exercise(
        db,
        user_id=ctx.user.id,
        exercise_ids=[r.exercise_id for r in rows],
    )
    return ProgressListResponse(
        items=[
            progress_to_read(
                r,
                last_session_summary=summaries.get(r.exercise_id),
            )
            for r in rows
        ]
    )


@router.post("/{exercise_id}/override", response_model=ProgressOverrideResponse)
async def override_progress(
    exercise_id: UUID,
    body: ProgressOverrideRequestV1,
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> ProgressOverrideResponse:
    await _owned_progress_exercise(db, user_id=ctx.user.id, exercise_id=exercise_id)
    try:
        ev = await _engine.manual_override(
            db,
            user_id=ctx.user.id,
            exercise_id=exercise_id,
            to_step=body.to_step,
            reason=body.reason,
            related_outcome_id=body.related_outcome_id,
        )
    except DomainError:
        raise
    await db.commit()
    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == ctx.user.id,
            UserExerciseProgress.exercise_id == exercise_id,
        )
    )
    if progress is None:
        raise NotFoundError()
    return ProgressOverrideResponse(progress=progress_to_read(progress), event=event_to_read(ev))
