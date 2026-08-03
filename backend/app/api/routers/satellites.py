"""Satellite exercises API (FR-050/051a)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_current_user_rate_limited, require_csrf
from app.db.session import get_session
from app.schemas.api import (
    ProgressionEventReadV1,
    ProgressItemV1,
    SatelliteCloneV1,
    SatelliteCreateV1,
    SatelliteReadV1,
    SatelliteUpdateV1,
)
from app.services import satellites as satellite_service
from app.services.errors import DomainError, NotFoundError
from app.services.satellite_progression import SatelliteProgressionOrchestrator
from app.services.sessions import event_to_read, progress_to_read

router = APIRouter(prefix="/satellites", tags=["satellites"])


class SatelliteListResponse(BaseModel):
    schema_version: int = 1
    items: list[SatelliteReadV1]


class SatelliteRegressionDecisionResponse(BaseModel):
    schema_version: int = 1
    recommendation_id: UUID
    status: str
    progress: ProgressItemV1
    event: ProgressionEventReadV1 | None = None


@router.get("", response_model=SatelliteListResponse)
async def list_satellites(
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> SatelliteListResponse:
    items = await satellite_service.list_satellites(db, user_id=ctx.user.id)
    return SatelliteListResponse(items=items)


@router.get("/{exercise_id}", response_model=SatelliteReadV1)
async def get_satellite(
    exercise_id: UUID,
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> SatelliteReadV1:
    try:
        return await satellite_service.get_satellite(
            db, user_id=ctx.user.id, exercise_id=exercise_id
        )
    except DomainError as exc:
        if exc.error_code == "not_found":
            raise NotFoundError() from exc
        raise


@router.post("", response_model=SatelliteReadV1)
async def create_satellite(
    body: SatelliteCreateV1,
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> SatelliteReadV1:
    return await satellite_service.create_satellite(db, user=ctx.user, body=body)


@router.patch("/{exercise_id}", response_model=SatelliteReadV1)
async def patch_satellite(
    exercise_id: UUID,
    body: SatelliteUpdateV1,
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
    _csrf: None = Depends(require_csrf),
) -> SatelliteReadV1:
    try:
        read, _outcome = await satellite_service.edit_satellite(
            db,
            user=ctx.user,
            exercise_id=exercise_id,
            body=body,
            revision=body.revision,
            commit=True,
        )
    except DomainError as exc:
        if exc.error_code == "not_found":
            raise NotFoundError() from exc
        raise
    return read


@router.post(
    "/{exercise_id}/regression-recommendations/{recommendation_id}/accept",
    response_model=SatelliteRegressionDecisionResponse,
)
async def accept_regression_recommendation(
    exercise_id: UUID,
    recommendation_id: UUID,
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
    _csrf: None = Depends(require_csrf),
) -> SatelliteRegressionDecisionResponse:
    try:
        rec, progress, event = await SatelliteProgressionOrchestrator().decide_recommendation(
            db,
            user_id=ctx.user.id,
            exercise_id=exercise_id,
            recommendation_id=recommendation_id,
            decision="accept",
        )
    except DomainError as exc:
        if exc.error_code == "not_found":
            raise NotFoundError() from exc
        raise
    return SatelliteRegressionDecisionResponse(
        recommendation_id=rec.id,
        status=rec.status,
        progress=progress_to_read(progress),
        event=event_to_read(event) if event is not None else None,
    )


@router.post(
    "/{exercise_id}/regression-recommendations/{recommendation_id}/decline",
    response_model=SatelliteRegressionDecisionResponse,
)
async def decline_regression_recommendation(
    exercise_id: UUID,
    recommendation_id: UUID,
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
    _csrf: None = Depends(require_csrf),
) -> SatelliteRegressionDecisionResponse:
    try:
        rec, progress, event = await SatelliteProgressionOrchestrator().decide_recommendation(
            db,
            user_id=ctx.user.id,
            exercise_id=exercise_id,
            recommendation_id=recommendation_id,
            decision="decline",
        )
    except DomainError as exc:
        if exc.error_code == "not_found":
            raise NotFoundError() from exc
        raise
    return SatelliteRegressionDecisionResponse(
        recommendation_id=rec.id,
        status=rec.status,
        progress=progress_to_read(progress),
        event=event_to_read(event) if event is not None else None,
    )
