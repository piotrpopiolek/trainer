"""Pure satellite goal-only evaluator — no ORM, clock, UUID, or commit."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.domain.progression_types import ProgressionEvaluation
from app.schemas.satellite import (
    ActiveMetricsV1,
    SatelliteGoalCompletedV1,
    SatelliteGoalDurationV1,
    SatelliteGoalRepsV1,
    SatelliteLogResultV1,
    SatelliteRulesV1,
    parse_satellite_log_result,
    parse_satellite_rules,
)


def _weight_ok(logged: str | None, minimum: str | None) -> bool:
    if minimum is None:
        return True
    if logged is None:
        return False
    return Decimal(logged) >= Decimal(minimum)


def _validate_active_metrics(
    result: SatelliteLogResultV1,
    active: ActiveMetricsV1,
) -> None:
    required = set(active.metrics)
    for idx, s in enumerate(result.sets):
        present = {
            name
            for name, value in (
                ("reps", s.reps),
                ("duration_sec", s.duration_sec),
                ("weight_kg", s.weight_kg),
                ("sides", s.sides),
            )
            if value is not None
        }
        missing = required - present
        if missing:
            raise ValueError(f"active_metric_missing:{','.join(sorted(missing))}:{idx}")
        metric_extras = present - required
        if metric_extras:
            raise ValueError(f"metric_not_active:{','.join(sorted(metric_extras))}:{idx}")


def satellite_goal_met(
    rules: SatelliteRulesV1,
    result: SatelliteLogResultV1,
    *,
    active_metrics: ActiveMetricsV1,
) -> bool:
    _validate_active_metrics(result, active_metrics)
    goal = rules.goal
    if isinstance(goal, SatelliteGoalCompletedV1):
        if result.completed is not True:
            return False
        return True

    sets = result.sets
    if isinstance(goal, SatelliteGoalRepsV1):
        qualifying = [
            s
            for s in sets
            if s.reps is not None
            and s.reps >= goal.min_reps
            and _weight_ok(s.weight_kg, goal.min_weight_kg)
        ]
        if goal.require_both_sides:
            left = [s for s in qualifying if s.sides == "left"]
            right = [s for s in qualifying if s.sides == "right"]
            if any(s.sides == "bilateral" for s in sets):
                raise ValueError("bilateral_not_allowed_when_require_both_sides")
            return len(left) >= goal.sets and len(right) >= goal.sets
        return len(qualifying) >= goal.sets

    if isinstance(goal, SatelliteGoalDurationV1):
        qualifying = [
            s
            for s in sets
            if s.duration_sec is not None
            and s.duration_sec >= goal.min_duration_sec
            and _weight_ok(s.weight_kg, goal.min_weight_kg)
        ]
        if goal.require_both_sides:
            left = [s for s in qualifying if s.sides == "left"]
            right = [s for s in qualifying if s.sides == "right"]
            if any(s.sides == "bilateral" for s in sets):
                raise ValueError("bilateral_not_allowed_when_require_both_sides")
            return len(left) >= goal.sets and len(right) >= goal.sets
        return len(qualifying) >= goal.sets

    return False


@dataclass(frozen=True, slots=True)
class SatelliteEvaluationInput:
    rules: SatelliteRulesV1
    active_metrics: ActiveMetricsV1
    log_payload: dict[str, Any] | None
    skipped: bool
    already_evaluated: bool
    persisted_goal_met: bool
    progression_eligible: bool
    step_number: int
    schema_version: int


class SatelliteProgressionEvaluator:
    """Stage 1: goal-only — never mutates step / emits events."""

    def evaluate(self, inp: SatelliteEvaluationInput) -> ProgressionEvaluation:
        if inp.already_evaluated:
            skipped = None if inp.progression_eligible else "config_not_active_for_day"
            return ProgressionEvaluation(
                goal_met=inp.persisted_goal_met,
                counts_for_progression=False,
                progression_skipped=skipped if not inp.skipped else "skipped",
                step_number=inp.step_number,
                rules_snapshot=inp.rules.model_dump(mode="json"),
                progression_schema_version=inp.schema_version,
            )

        snapshot = inp.rules.model_dump(mode="json")
        if inp.skipped:
            return ProgressionEvaluation(
                goal_met=False,
                counts_for_progression=False,
                progression_skipped="skipped",
                rules_snapshot=snapshot,
                progression_schema_version=inp.schema_version,
                step_number=inp.step_number,
            )

        result = parse_satellite_log_result(inp.log_payload)
        # Empty sets ⇒ goal not met for reps/duration; type C uses completed=true.
        met = satellite_goal_met(inp.rules, result, active_metrics=inp.active_metrics)
        skipped = None if inp.progression_eligible else "config_not_active_for_day"
        return ProgressionEvaluation(
            goal_met=met,
            counts_for_progression=False,
            progression_skipped=skipped,
            rules_snapshot=snapshot,
            progression_schema_version=inp.schema_version,
            step_number=inp.step_number,
        )


def rules_from_payload(payload: dict[str, Any]) -> SatelliteRulesV1:
    return parse_satellite_rules(payload)
