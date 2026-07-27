"""Placement test entry without nested schema_version."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import VersionedModel


class OnboardingQuestionnaireV1(VersionedModel):
    schema_version: int = Field(1, ge=1)
    experience_level: Literal["beginner", "intermediate", "advanced"]
    training_days_per_week: int = Field(..., ge=1, le=7)
    goals: list[str] = Field(default_factory=list, max_length=10)
    injuries_notes: str | None = Field(default=None, max_length=1000)


class PlacementTestEntryV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_slug: str = Field(..., min_length=1, max_length=64)
    max_reps: int = Field(..., ge=0)


class OnboardingPlacementTestV1(VersionedModel):
    schema_version: int = Field(1, ge=1)
    entries: list[PlacementTestEntryV1] = Field(default_factory=list)


class OnboardingStepsMapV1(VersionedModel):
    """Map exercise_slug → recommended/chosen step number (1–10)."""

    schema_version: int = Field(1, ge=1)
    steps: dict[str, int] = Field(default_factory=dict)
