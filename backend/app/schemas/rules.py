"""Progression rules on exercise_steps (FR-031 / FR-051a)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import VersionedModel, parse_versioned
from app.services.errors import DomainError


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
    SCHEMA_VERSION = 1
    schema_version: int = Field(1, ge=1)
    advance: AdvanceRuleV1 | None = None
    regress: RegressRuleV1 | None = None
    goal: GoalRuleV1 | None = None


class StandardsV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beginner: AdvanceRuleV1
    intermediate: AdvanceRuleV1
    progression: AdvanceRuleV1


class ProgressionRulesV2(VersionedModel):
    """CC steps: three display standards; engine advances only on `advance` ≡ progression."""

    SCHEMA_VERSION = 2
    schema_version: int = Field(2, ge=1)
    standards: StandardsV2
    advance: AdvanceRuleV1
    regress: RegressRuleV1 | None = None
    goal: GoalRuleV1 | None = None

    @model_validator(mode="after")
    def advance_must_match_progression(self) -> ProgressionRulesV2:
        if self.advance.model_dump() != self.standards.progression.model_dump():
            raise ValueError("advance must equal standards.progression")
        return self


ProgressionRules = ProgressionRulesV1 | ProgressionRulesV2


def parse_progression_rules(payload: dict[str, Any] | None) -> ProgressionRules:
    """Dispatch rules document by schema_version (v1 satellites / v2 CC steps)."""
    if not isinstance(payload, dict):
        raise DomainError("schema_invalid", http_status=422)
    version = payload.get("schema_version")
    if version == 1:
        return parse_versioned(ProgressionRulesV1, payload)
    if version == 2:
        return parse_versioned(ProgressionRulesV2, payload)
    if version is None:
        raise DomainError("schema_version_required", http_status=422)
    raise DomainError("schema_version_unsupported", http_status=422)
