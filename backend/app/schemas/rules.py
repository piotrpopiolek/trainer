"""Progression rules on exercise_steps (FR-031 / FR-051a)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import VersionedModel


class AdvanceRuleV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sets: int = Field(..., ge=1)
    min_reps: int | None = Field(default=None, ge=0)
    min_duration_sec: int | None = Field(default=None, ge=0)
    require_both_sides: bool = False


class RegressRuleV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fail_sessions: int = Field(2, ge=1)


class GoalRuleV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["reps", "duration", "completed"]
    sets: int | None = Field(default=None, ge=1)
    min_reps: int | None = Field(default=None, ge=0)
    min_duration_sec: int | None = Field(default=None, ge=0)


class ProgressionRulesV1(VersionedModel):
    schema_version: int = Field(1, ge=1)
    advance: AdvanceRuleV1 | None = None
    regress: RegressRuleV1 | None = None
    goal: GoalRuleV1 | None = None
