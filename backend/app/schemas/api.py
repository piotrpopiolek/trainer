"""HTTP / domain DTOs for sessions, today, progress, catalog, satellites, measurements."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import VersionedModel
from app.schemas.satellite import (
    SatelliteProgressionPolicyGoalOnlyV1,
    SatelliteProgressionPolicyStepsV1,
)
from app.schemas.sets import SessionSetsV1


class BodyMetricsV1(VersionedModel):
    """FR-061: defaults weight/waist/biceps; optional chest/thigh/neck/abdomen/hips/calf."""

    SCHEMA_VERSION = 1
    schema_version: int = Field(1, ge=1)
    weight_kg: float | None = Field(default=None, ge=0)
    waist_cm: float | None = Field(default=None, ge=0)
    biceps_cm: float | None = Field(default=None, ge=0)
    chest_cm: float | None = Field(default=None, ge=0)
    thigh_cm: float | None = Field(default=None, ge=0)
    neck_cm: float | None = Field(default=None, ge=0)
    abdomen_cm: float | None = Field(default=None, ge=0)
    hips_cm: float | None = Field(default=None, ge=0)
    calves_cm: float | None = Field(default=None, ge=0)
    # Alias for db-plan `calf_cm` (accepted; stored key remains calves_cm when both sent).
    calf_cm: float | None = Field(default=None, ge=0)


class SessionLogCreateV1(BaseModel):
    """Write DTO — server strips goal_met / rules_snapshot / etc (FR-046a)."""

    model_config = ConfigDict(extra="ignore")

    exercise_id: UUID
    exercise_kind: Literal["cc", "satellite"] = "cc"
    section: Literal["main", "accessories"] = "main"
    skipped: bool = False
    sets: dict[str, Any] | None = None
    notes: str | None = Field(default=None, max_length=1000)
    sort_order: int = Field(default=0, ge=0)
    client_mutation_id: UUID | None = None
    satellite_config_version_id: UUID | None = None
    satellite_config_hash: str | None = None
    # Ignored if present (FR-046a):
    goal_met: Any = None
    rules_snapshot: Any = None
    goal_evaluated_at: Any = None
    counts_for_progression: Any = None
    progression_skipped: Any = None
    content_locale: Any = None
    step_number: Any = None
    current_step_number: Any = None
    fail_streak: Any = None


class SessionCreateV1(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: int = Field(1, ge=1)
    performed_at: datetime
    local_date: date
    notes: str | None = Field(default=None, max_length=2000)
    client_mutation_id: UUID
    client_updated_at: datetime | None = None
    client_timezone: str | None = Field(default=None, max_length=64)
    logs: list[SessionLogCreateV1] = Field(default_factory=list)
    revision: Any = None  # strip


class SessionLogReadV1(BaseModel):
    schema_version: int = 1
    id: UUID
    exercise_id: UUID
    exercise_kind: str
    section: str
    step_number: int | None
    local_date: date
    performed_at: datetime
    content_locale: str
    exercise_name_snapshot: str
    step_label_snapshot: str | None
    skipped: bool
    sets: dict[str, Any] | None
    goal_met: bool
    goal_evaluated_at: datetime | None
    counts_for_progression: bool
    progression_skipped: str | None = None
    satellite_config_version_id: UUID | None = None
    satellite_config_hash: str | None = None
    notes: str | None
    sort_order: int
    revision: int
    # no rules_snapshot on read-model surfaces (FR-040b / FR-075)


class ProgressionEventReadV1(BaseModel):
    schema_version: int = 1
    id: UUID
    exercise_id: UUID
    session_id: UUID | None
    event_type: str
    from_step: int
    to_step: int
    reason: str | None
    created_at: datetime


class ProgressItemV1(BaseModel):
    schema_version: int = 1
    exercise_id: UUID
    current_step_number: int
    fail_streak: int
    last_session_at: datetime | None
    is_active: bool


class SessionReadV1(BaseModel):
    schema_version: int = 1
    id: UUID
    performed_at: datetime
    local_date: date
    notes: str | None
    revision: int
    deleted_at: datetime | None
    logs: list[SessionLogReadV1]
    progression_events: list[ProgressionEventReadV1] = Field(default_factory=list)
    progress: list[ProgressItemV1] = Field(default_factory=list)


class ProgressOverrideRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(1, ge=1)
    to_step: int = Field(..., ge=1)
    reason: str | None = Field(default=None, max_length=500)


class TodayCcExerciseV1(BaseModel):
    schema_version: int = 1
    exercise_id: UUID
    slug: str | None
    name: str
    current_step_number: int
    advance: dict[str, Any] | None = None
    regress: dict[str, Any] | None = None
    standards: dict[str, Any] | None = None
    step_name: str | None = None
    description: str | None = None
    execution: str | None = None
    rationale: str | None = None
    technique: str | None = None


class TodaySatelliteV1(BaseModel):
    schema_version: int = 1
    exercise_id: UUID
    name: str
    exercise_type: str
    schedule_kind: str | None
    schedule_category: str | None
    current_step_number: int | None = None
    step_name: str | None = None
    active_metrics: dict[str, Any] | None = None
    goal: dict[str, Any] | None = None
    config_version_id: UUID | None = None
    config_hash: str | None = None


class TodaySessionDto(BaseModel):
    schema_version: int = 1
    local_date: date
    timezone: str
    split_day: int | None
    is_rest_day: bool
    cc_day_override: int | None = None
    requested_locale: str
    resolved_locale: str
    cc_exercises: list[TodayCcExerciseV1]
    satellites: list[TodaySatelliteV1]
    sessions: list[SessionReadV1]
    progress: list[ProgressItemV1]


class CatalogStepV1(BaseModel):
    schema_version: int = 1
    step_number: int
    name: str
    description: str
    execution: str = ""
    rationale: str = ""
    technique: str = ""
    content_status: str
    rules: dict[str, Any]


class CatalogExerciseV1(BaseModel):
    schema_version: int = 1
    id: UUID
    slug: str | None
    name: str
    description: str | None
    exercise_type: str
    steps: list[CatalogStepV1]


class CatalogDayV1(BaseModel):
    schema_version: int = 1
    day_index: int
    name: str
    exercise_ids: list[UUID]


class CatalogCcResponseV1(BaseModel):
    schema_version: int = 1
    program_slug: str
    program_name: str
    program_description: str | None
    catalog_version: int
    requested_locale: str
    resolved_locale: str
    days: list[CatalogDayV1]
    exercises: list[CatalogExerciseV1]


class SatelliteStepCreateV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_number: int = Field(..., ge=1)
    rules: dict[str, Any]
    name: str | None = None
    description: str | None = None
    step_id: UUID | None = None


class SatelliteCreateV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(1, ge=1)
    name: str = Field(..., min_length=1, max_length=200)
    exercise_type: Literal["B", "C"]
    active_metrics: dict[str, Any]
    equipment: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    schedule_kind: Literal["daily", "weekdays", "category"]
    weekdays: list[int] | None = None
    schedule_category: Literal["anytime", "post_workout", "rest_day"] | None = None
    steps: list[SatelliteStepCreateV1] = Field(..., min_length=1, max_length=5)
    progression: (
        SatelliteProgressionPolicyGoalOnlyV1 | SatelliteProgressionPolicyStepsV1
    ) = Field(
        default_factory=SatelliteProgressionPolicyGoalOnlyV1,
        discriminator="mode",
    )
    client_mutation_id: UUID
    client_updated_at: datetime | None = None
    config_version_id: UUID | None = None
    # Slice F: CAS base for activating a newly registered version on an existing exercise.
    expected_current_config_version_id: UUID | None = None


class SatelliteReadV1(BaseModel):
    schema_version: int = 1
    id: UUID
    name: str
    exercise_type: str
    active_metrics: dict[str, Any]
    schedule_kind: str | None
    weekdays: list[int] | None
    schedule_category: str | None
    revision: int
    current_config_version_id: UUID | None = None
    config_hash: str | None = None
    steps: list[dict[str, Any]]


class MeasurementCreateV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(1, ge=1)
    measured_at: datetime
    local_date: date
    metrics: dict[str, Any]
    notes: str | None = Field(default=None, max_length=1000)
    client_mutation_id: UUID
    client_updated_at: datetime | None = None


class MeasurementReadV1(BaseModel):
    schema_version: int = 1
    id: UUID
    measured_at: datetime
    local_date: date
    metrics: dict[str, Any]
    notes: str | None
    revision: int


# Re-export for routers that validate sets
__all__ = [
    "BodyMetricsV1",
    "SessionSetsV1",
    "SessionCreateV1",
    "SessionReadV1",
    "TodaySessionDto",
    "ProgressOverrideRequestV1",
    "CatalogCcResponseV1",
    "SatelliteCreateV1",
    "SatelliteReadV1",
    "MeasurementCreateV1",
    "MeasurementReadV1",
]
