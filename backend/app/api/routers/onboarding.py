"""Onboarding API (FR-010–013)."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_current_user_rate_limited
from app.db.session import get_session
from app.services import onboarding as onboarding_service

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class CompleteOnboardingRequest(BaseModel):
    schema_version: int = 1
    questionnaire: dict[str, Any]
    placement_test: dict[str, Any] | None = None
    chosen_steps: dict[str, Any] | None = None
    anchor_weekday: int = Field(default=1, ge=1, le=2)
    timezone: str | None = None
    started_on: date | None = None


class CompleteOnboardingResponse(BaseModel):
    schema_version: int = 1
    completed: bool = True
    recommended_steps: dict[str, Any]
    chosen_steps: dict[str, Any]


@router.post("/complete")
async def complete_onboarding(
    body: CompleteOnboardingRequest,
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> CompleteOnboardingResponse:
    row = await onboarding_service.complete_onboarding(
        db,
        ctx.user,
        questionnaire=body.questionnaire,
        placement_test=body.placement_test,
        chosen_steps=body.chosen_steps,
        anchor_weekday=body.anchor_weekday,
        timezone=body.timezone,
        started_on=body.started_on,
    )
    return CompleteOnboardingResponse(
        recommended_steps=row.recommended_steps,
        chosen_steps=row.chosen_steps,
    )
