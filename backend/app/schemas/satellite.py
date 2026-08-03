"""Satellite progression contracts (FR-051a / FR-052) — independent of ProgressionRulesV2."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.schemas.common import VersionedModel, parse_versioned
from app.services.errors import DomainError

MetricName = Literal["reps", "duration_sec", "weight_kg", "sides"]
SideName = Literal["left", "right", "bilateral"]

_WEIGHT_RE = r"^(?:0|[1-9]\d*)\.\d{3}$"


def parse_weight_kg(value: Any) -> str:
    """Canonical decimal string with exactly 3 fractional digits."""
    if isinstance(value, bool) or value is None:
        raise ValueError("invalid_weight_kg")
    if isinstance(value, float):
        raise ValueError("weight_kg_must_be_decimal_string")
    if isinstance(value, Decimal):
        text = f"{value.quantize(Decimal('0.001'))}"
    else:
        text = str(value).strip()
    if "e" in text.lower() or text in {"NaN", "Infinity", "-Infinity"}:
        raise ValueError("invalid_weight_kg")
    try:
        dec = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("invalid_weight_kg") from exc
    if not dec.is_finite() or dec <= 0:
        raise ValueError("invalid_weight_kg")
    quantized = dec.quantize(Decimal("0.001"))
    if quantized != dec and "." in text and len(text.split(".", 1)[1]) > 3:
        raise ValueError("weight_kg_too_many_places")
    out = f"{quantized:.3f}"
    if not __import__("re").fullmatch(_WEIGHT_RE, out):
        raise ValueError("invalid_weight_kg")
    return out


class ActiveMetricsV1(VersionedModel):
    SCHEMA_VERSION = 1
    schema_version: int = Field(1, ge=1)
    metrics: list[MetricName] = Field(default_factory=list)

    @field_validator("metrics")
    @classmethod
    def unique_sorted_metrics(cls, value: list[MetricName]) -> list[MetricName]:
        if len(value) != len(set(value)):
            raise ValueError("duplicate_metrics")
        return sorted(value)  # type: ignore[return-value]


class SatelliteGoalRepsV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["reps"] = "reps"
    sets: int = Field(..., ge=1)
    min_reps: int = Field(..., ge=1)
    min_weight_kg: Annotated[str, StringConstraints(pattern=_WEIGHT_RE)] | None = None
    require_both_sides: bool = False

    @field_validator("min_weight_kg", mode="before")
    @classmethod
    def normalize_weight(cls, value: Any) -> str | None:
        if value is None:
            return None
        return parse_weight_kg(value)


class SatelliteGoalDurationV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["duration"] = "duration"
    sets: int = Field(..., ge=1)
    min_duration_sec: int = Field(..., ge=1)
    min_weight_kg: Annotated[str, StringConstraints(pattern=_WEIGHT_RE)] | None = None
    require_both_sides: bool = False

    @field_validator("min_weight_kg", mode="before")
    @classmethod
    def normalize_weight(cls, value: Any) -> str | None:
        if value is None:
            return None
        return parse_weight_kg(value)


class SatelliteGoalCompletedV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["completed"] = "completed"


SatelliteGoalV1 = SatelliteGoalRepsV1 | SatelliteGoalDurationV1 | SatelliteGoalCompletedV1


class SatelliteRulesV1(VersionedModel):
    """Per-step satellite rules — goal only; advance/regress forbidden."""

    SCHEMA_VERSION = 1
    schema_version: int = Field(1, ge=1)
    goal: SatelliteGoalRepsV1 | SatelliteGoalDurationV1 | SatelliteGoalCompletedV1 = Field(
        ..., discriminator="type"
    )

    @model_validator(mode="before")
    @classmethod
    def reject_cc_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for banned in ("advance", "regress", "standards", "fail_sessions"):
                if banned in data:
                    raise ValueError(f"satellite_rules_forbid_{banned}")
        return data


class SatelliteProgressionPolicyGoalOnlyV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["goal_only"] = "goal_only"


class SatelliteProgressionPolicyStepsV1(BaseModel):
    """Reserved for Stage 3 — accepted in document shape but unused in Stage 1 engine."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["steps"] = "steps"
    regression: dict[str, Any] | None = None


SatelliteProgressionPolicyV1 = (
    SatelliteProgressionPolicyGoalOnlyV1 | SatelliteProgressionPolicyStepsV1
)


class SatelliteSetV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reps: int | None = Field(default=None, ge=0)
    duration_sec: int | None = Field(default=None, ge=0)
    weight_kg: Annotated[str, StringConstraints(pattern=_WEIGHT_RE)] | None = None
    sides: SideName | None = None
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("weight_kg", mode="before")
    @classmethod
    def normalize_weight(cls, value: Any) -> str | None:
        if value is None:
            return None
        return parse_weight_kg(value)

    @model_validator(mode="after")
    def at_least_one_metric(self) -> SatelliteSetV1:
        if (
            self.reps is None
            and self.duration_sec is None
            and self.weight_kg is None
            and self.sides is None
            and self.notes is None
        ):
            raise ValueError("empty_set")
        return self


class SatelliteLogResultV1(VersionedModel):
    SCHEMA_VERSION = 1
    schema_version: int = Field(1, ge=1)
    completed: bool | None = None
    sets: list[SatelliteSetV1] = Field(default_factory=list)


class SatelliteConfigStepV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: UUID
    sort_order: int = Field(..., ge=1)
    rules: SatelliteRulesV1


class SatelliteConfigDocumentV1(VersionedModel):
    """Canonical config hashed for immutability (excludes UI/schedule/names)."""

    SCHEMA_VERSION = 1
    schema_version: int = Field(1, ge=1)
    exercise_type: Literal["B", "C"]
    active_metrics: ActiveMetricsV1
    progression: SatelliteProgressionPolicyGoalOnlyV1 | SatelliteProgressionPolicyStepsV1 = Field(
        ..., discriminator="mode"
    )
    steps: list[SatelliteConfigStepV1] = Field(..., min_length=1, max_length=5)

    @model_validator(mode="after")
    def validate_steps_and_metrics(self) -> SatelliteConfigDocumentV1:
        step_ids = [s.step_id for s in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("duplicate_step_id")
        orders = [s.sort_order for s in self.steps]
        if len(orders) != len(set(orders)):
            raise ValueError("duplicate_sort_order")
        if self.progression.mode == "goal_only" and len(self.steps) != 1:
            raise ValueError("goal_only_requires_one_step")
        if self.progression.mode == "steps" and not (2 <= len(self.steps) <= 5):
            raise ValueError("steps_mode_requires_2_to_5")
        metrics = set(self.active_metrics.metrics)
        for step in self.steps:
            goal = step.rules.goal
            if goal.type == "reps" and "reps" not in metrics:
                raise ValueError("active_metric_missing_reps")
            if goal.type == "duration" and "duration_sec" not in metrics:
                raise ValueError("active_metric_missing_duration")
            if (
                goal.type != "completed"
                and getattr(goal, "require_both_sides", False)
                and "sides" not in metrics
            ):
                raise ValueError("active_metric_missing_sides")
            if (
                goal.type != "completed"
                and getattr(goal, "min_weight_kg", None) is not None
                and "weight_kg" not in metrics
            ):
                raise ValueError("active_metric_missing_weight")
        if self.exercise_type == "C" and any(
            s.rules.goal.type != "completed" for s in self.steps
        ):
            raise ValueError("type_c_requires_completed_goal")
        return self


def parse_satellite_rules(payload: dict[str, Any] | None) -> SatelliteRulesV1:
    if not isinstance(payload, dict):
        raise DomainError("schema_invalid", http_status=422)
    return parse_versioned(SatelliteRulesV1, payload)


def parse_satellite_log_result(payload: dict[str, Any] | None) -> SatelliteLogResultV1:
    if not isinstance(payload, dict):
        raise DomainError("schema_invalid", http_status=422)
    return parse_versioned(SatelliteLogResultV1, payload)


def parse_satellite_config_document(payload: dict[str, Any] | None) -> SatelliteConfigDocumentV1:
    if not isinstance(payload, dict):
        raise DomainError("schema_invalid", http_status=422)
    return parse_versioned(SatelliteConfigDocumentV1, payload)
