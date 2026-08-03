"""Pure satellite progression — goal_met + daily-outcome fold helpers (no ORM/clock/UUID)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.progression_types import ProgressionEvaluation, ProgressStatePatch
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

FAILED_DAY_GRACE = timedelta(hours=36)


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
        return result.completed is True

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


def compute_finalize_after(local_date: date, *, timezone_name: str) -> datetime:
    """End of ``local_date`` in user TZ + 36 h (FR-053), as UTC-aware datetime."""
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    end_of_day = datetime.combine(local_date, time(23, 59, 59, 999999), tzinfo=tz)
    return (end_of_day + FAILED_DAY_GRACE).astimezone(UTC)


OutcomeStatus = Literal["pending", "finalized", "cancelled"]
OutcomeResult = Literal["success", "failure"]


@dataclass(frozen=True, slots=True)
class DailyOutcomeState:
    status: OutcomeStatus
    has_attempt: bool
    has_success: bool
    result: OutcomeResult | None
    finalize_after: datetime | None
    finalized_at: datetime | None
    representative_log_id: str | None
    result_snapshot: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class DailyOutcomeFoldResult:
    state: DailyOutcomeState
    counts_for_progression: bool
    progression_skipped: str | None
    """Streak cache patch; None = leave unchanged."""
    fail_streak: int | None
    newly_finalized: bool
    """Advance at most +1 on newly finalized success; None = stay (last step / no success)."""
    advance_from: int | None = None
    advance_to: int | None = None
    advance_to_step_id: str | None = None


@dataclass(frozen=True, slots=True)
class RegressionSuggestionProposal:
    """Pure proposal when failed_day streak hits threshold (no auto-regress)."""

    from_step: int
    to_step: int
    from_step_id: str
    to_step_id: str
    failed_day_streak: int
    threshold: int


def propose_regression_suggestion(
    *,
    step_number: int,
    fail_streak: int,
    threshold: int,
    step_ladder: list[tuple[int, str]],
) -> RegressionSuggestionProposal | None:
    """Suggest −1 step when streak ≥ threshold; never on step 1."""
    if step_number <= 1 or threshold < 1 or fail_streak < threshold:
        return None
    ladder = sorted(step_ladder, key=lambda t: t[0])
    from_id = next((sid for num, sid in ladder if num == step_number), None)
    to_id = next((sid for num, sid in ladder if num == step_number - 1), None)
    if from_id is None or to_id is None:
        return None
    return RegressionSuggestionProposal(
        from_step=step_number,
        to_step=step_number - 1,
        from_step_id=from_id,
        to_step_id=to_id,
        failed_day_streak=fail_streak,
        threshold=threshold,
    )


def _snapshot(*, result: OutcomeResult, has_attempt: bool, has_success: bool) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "result": result,
        "has_attempt": has_attempt,
        "has_success": has_success,
    }


def _finalize_failure(
    state: DailyOutcomeState,
    *,
    now: datetime,
    step_number: int,
    fail_streak: int,
) -> tuple[DailyOutcomeState, int | None, bool]:
    new_state = DailyOutcomeState(
        status="finalized",
        has_attempt=True,
        has_success=False,
        result="failure",
        finalize_after=state.finalize_after,
        finalized_at=now,
        representative_log_id=state.representative_log_id,
        result_snapshot=_snapshot(
            result="failure",
            has_attempt=True,
            has_success=False,
        ),
    )
    # Step 1 does not accumulate failed-day streak (FR-053).
    streak: int | None = None
    if step_number > 1:
        streak = fail_streak + 1
    return new_state, streak, True


def fold_daily_outcome(
    current: DailyOutcomeState | None,
    *,
    goal_met: bool,
    skipped: bool,
    eligible: bool,
    already_evaluated: bool,
    log_id: str,
    now: datetime,
    finalize_after: datetime,
    step_number: int,
    fail_streak: int,
    step_ladder: list[tuple[int, str]] | None = None,
) -> DailyOutcomeFoldResult:
    """Pure daily-outcome fold; success may propose +1 advance (FR-053)."""
    empty = DailyOutcomeState(
        status="pending",
        has_attempt=False,
        has_success=False,
        result=None,
        finalize_after=None,
        finalized_at=None,
        representative_log_id=None,
        result_snapshot=None,
    )
    ladder = sorted(step_ladder or [], key=lambda t: t[0])
    max_step = ladder[-1][0] if ladder else step_number

    state = current
    streak: int | None = None
    newly_finalized = False

    # Lazy finalize prior pending attempt even when this log is skipped /
    # ineligible (still must close the day once finalize_after has passed).
    if (
        state is not None
        and state.status == "pending"
        and state.has_attempt
        and not state.has_success
        and state.finalize_after is not None
        and now >= state.finalize_after
    ):
        state, streak, newly_finalized = _finalize_failure(
            state, now=now, step_number=step_number, fail_streak=fail_streak
        )

    if skipped:
        return DailyOutcomeFoldResult(
            state=state or empty,
            counts_for_progression=False,
            progression_skipped="skipped",
            fail_streak=streak,
            newly_finalized=newly_finalized,
        )
    if not eligible:
        return DailyOutcomeFoldResult(
            state=state or empty,
            counts_for_progression=False,
            progression_skipped="config_not_active_for_day",
            fail_streak=streak,
            newly_finalized=newly_finalized,
        )

    if state is not None and state.status == "finalized":
        return DailyOutcomeFoldResult(
            state=state,
            counts_for_progression=False,
            progression_skipped="daily_finalized",
            fail_streak=streak,
            newly_finalized=newly_finalized,
        )

    if already_evaluated:
        return DailyOutcomeFoldResult(
            state=state or empty,
            counts_for_progression=False,
            progression_skipped=None,
            fail_streak=streak,
            newly_finalized=newly_finalized,
        )

    if goal_met:
        base = state or empty
        state = DailyOutcomeState(
            status="finalized",
            has_attempt=True,
            has_success=True,
            result="success",
            finalize_after=base.finalize_after or finalize_after,
            finalized_at=now,
            representative_log_id=log_id,
            result_snapshot=_snapshot(result="success", has_attempt=True, has_success=True),
        )
        advance_from: int | None = None
        advance_to: int | None = None
        advance_to_step_id: str | None = None
        if step_number < max_step:
            nxt = step_number + 1
            match = next((sid for num, sid in ladder if num == nxt), None)
            if match is not None:
                advance_from = step_number
                advance_to = nxt
                advance_to_step_id = match
        return DailyOutcomeFoldResult(
            state=state,
            counts_for_progression=True,
            progression_skipped=None,
            fail_streak=0,
            newly_finalized=True,
            advance_from=advance_from,
            advance_to=advance_to,
            advance_to_step_id=advance_to_step_id,
        )

    # Failed attempt — keep pending unless deadline already passed.
    base = state or empty
    state = DailyOutcomeState(
        status="pending",
        has_attempt=True,
        has_success=False,
        result=None,
        finalize_after=base.finalize_after or finalize_after,
        finalized_at=None,
        representative_log_id=base.representative_log_id or log_id,
        result_snapshot=None,
    )
    if state.finalize_after is not None and now >= state.finalize_after:
        state, streak, newly_finalized = _finalize_failure(
            state, now=now, step_number=step_number, fail_streak=fail_streak
        )
        return DailyOutcomeFoldResult(
            state=state,
            counts_for_progression=True,
            progression_skipped=None,
            fail_streak=streak,
            newly_finalized=newly_finalized,
        )
    return DailyOutcomeFoldResult(
        state=state,
        counts_for_progression=True,
        progression_skipped=None,
        fail_streak=streak,
        newly_finalized=False,
    )


def finalize_pending_failure(
    state: DailyOutcomeState,
    *,
    now: datetime,
    step_number: int,
    fail_streak: int,
) -> tuple[DailyOutcomeState, int | None, bool]:
    """Finalize a pending no-success outcome after deadline (idempotent)."""
    if state.status != "pending" or state.has_success or not state.has_attempt:
        return state, None, False
    if state.finalize_after is None or now < state.finalize_after:
        return state, None, False
    return _finalize_failure(
        state, now=now, step_number=step_number, fail_streak=fail_streak
    )


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
    """Per-log goal_met; daily-outcome / advance applied by orchestrator."""

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
        met = satellite_goal_met(inp.rules, result, active_metrics=inp.active_metrics)
        skipped = None if inp.progression_eligible else "config_not_active_for_day"
        return ProgressionEvaluation(
            goal_met=met,
            counts_for_progression=False,
            progression_skipped=skipped,
            rules_snapshot=snapshot,
            progression_schema_version=inp.schema_version,
            step_number=inp.step_number,
            progress_patch=ProgressStatePatch(),
        )


def rules_from_payload(payload: dict[str, Any]) -> SatelliteRulesV1:
    return parse_satellite_rules(payload)
