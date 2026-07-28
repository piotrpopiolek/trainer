"""Satellite exercises API (FR-050/051a)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_current_user_rate_limited
from app.db.session import get_session
from app.schemas.api import SatelliteCreateV1, SatelliteReadV1
from app.services import satellites as satellite_service

router = APIRouter(prefix="/satellites", tags=["satellites"])


class SatelliteListResponse(BaseModel):
    schema_version: int = 1
    items: list[SatelliteReadV1]


@router.get("", response_model=SatelliteListResponse)
async def list_satellites(
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> SatelliteListResponse:
    items = await satellite_service.list_satellites(db, user_id=ctx.user.id)
    return SatelliteListResponse(items=items)


@router.post("", response_model=SatelliteReadV1)
async def create_satellite(
    body: SatelliteCreateV1,
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> SatelliteReadV1:
    return await satellite_service.create_satellite(db, user=ctx.user, body=body)
