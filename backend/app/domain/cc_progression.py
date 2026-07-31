"""Pure CC progression evaluator — no ORM, clock, UUID, or commit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.progression_types import (
    EventProposal,
    ProgressStatePatch,
    ProgressionEvaluation,
)
from app.schemas.rules import AdvanceRuleV1, ProgressionRules, ProgressionRulesV1, ProgressionRulesV2
from app.schemas.common import parse_versioned
from app.schemas.sets import SessionSetV1, SessionSetsV1


def _normalize_side(sides: str | None) -> str | None:
    if sides is None:
        return None
    s = sides.strip().lower()
    if s in {"l", "left"}:
        return "left"
    if s in {"r", "right"}:
        return "right"
    return s


def _set_meets_advance(s: SessionSetV1, adv: AdvanceRuleV1) -> bool:
    if adv.min_reps is not None and adv.min_duration_sec is not None:
        return (s.reps or 0) >= adv.min_reps and (s.duration_sec or 0) >= adv.min_duration_sec
    if adv.min_reps is not None:
        return (s.reps or 0) >= adv.min_reps
    if adv.min_duration_sec is not None:
        return (s.duration_sec or 0) >= adv.min_duration_sec
    return False


def cc_goal_met(rules: ProgressionRules, sets_payload: dict[str, Any] | None) -> bool:
    if sets_payload is None:
        return False
    sets_doc = parse_versioned(SessionSetsV1, sets_payload)
    sets = sets_doc.sets
    if rules.advance is None:
        return False
    adv = rules.advance
    hits = [s for s in sets if _set_meets_advance(s, adv)]
    if not adv.require_both_sides:
        return len(hits) >= adv.sets
    left = [s for s in hits if _normalize_side(s.sides) == "left"]
    right = [s for s in hits if _normalize_side(s.sides) == "right"]
    return len(left) >= adv.sets and len(right) >= adv.sets


@dataclass(frozen=True, slots=True)
class CcEvaluationInput:
    rules: ProgressionRulesV1 | ProgressionRulesV2
    sets_payload: dict[str, Any] | None
    skipped: bool
    already_evaluated: bool
    persisted_goal_met: bool
    persisted_counts_for_progression: bool
    persisted_progression_skipped: str | None
    is_tip: bool
    current_step_number: int
    max_step_number: int
    fail_streak: int
    schema_version: int


class CcProgressionEvaluator:
    def evaluate(self, inp: CcEvaluationInput) -> ProgressionEvaluation:
        if inp.already_evaluated:
            skipped = inp.persisted_progression_skipped
            if inp.skipped:
                skipped = "skipped"
            elif not inp.persisted_counts_for_progression:
                skipped = skipped or "late_log"
            return ProgressionEvaluation(
                goal_met=inp.persisted_goal_met,
                counts_for_progression=inp.persisted_counts_for_progression,
                progression_skipped=skipped,
                is_tip=inp.persisted_counts_for_progression,
                step_number=inp.current_step_number,
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
                step_number=inp.current_step_number,
            )

        met = cc_goal_met(inp.rules, inp.sets_payload)
        if not inp.is_tip:
            return ProgressionEvaluation(
                goal_met=met,
                counts_for_progression=False,
                progression_skipped="late_log",
                rules_snapshot=snapshot,
                progression_schema_version=inp.schema_version,
                step_number=inp.current_step_number,
            )

        events: list[EventProposal] = []
        from_step = inp.current_step_number
        fail_streak = inp.fail_streak
        to_step = from_step

        if met:
            fail_streak = 0
            if from_step < inp.max_step_number:
                to_step = from_step + 1
                events.append(
                    EventProposal(
                        event_type="advance",
                        from_step=from_step,
                        to_step=to_step,
                        reason="advance_threshold_met",
                        rules_snapshot=snapshot,
                        progression_schema_version=inp.schema_version,
                    )
                )
        elif inp.rules.regress is not None:
            fail_needed = inp.rules.regress.fail_sessions
            fail_streak += 1
            if fail_streak >= fail_needed and from_step > 1:
                to_step = from_step - 1
                fail_streak = 0
                events.append(
                    EventProposal(
                        event_type="regress",
                        from_step=from_step,
                        to_step=to_step,
                        reason="fail_streak_threshold",
                        rules_snapshot=snapshot,
                        progression_schema_version=inp.schema_version,
                    )
                )

        return ProgressionEvaluation(
            goal_met=met,
            counts_for_progression=True,
            progression_skipped=None,
            is_tip=True,
            rules_snapshot=snapshot,
            progression_schema_version=inp.schema_version,
            step_number=inp.current_step_number,
            progress_patch=ProgressStatePatch(
                current_step_number=to_step,
                fail_streak=fail_streak,
            ),
            events=tuple(events),
        )
