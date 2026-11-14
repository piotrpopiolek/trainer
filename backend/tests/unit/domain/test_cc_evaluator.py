"""CC evaluator transitions with no session, clock, or UUID (FR-030b/034/035)."""

from __future__ import annotations

import pytest

from app.domain.cc_progression import CcEvaluationInput, CcProgressionEvaluator
from app.schemas.rules import ProgressionRulesV1
from app.services.cc_progression import CcProgressionOrchestrator


def _rules() -> ProgressionRulesV1:
    return ProgressionRulesV1.model_validate(
        {
            "schema_version": 1,
            "advance": {"sets": 3, "min_reps": 10, "require_both_sides": False},
            "regress": {"fail_sessions": 2},
        }
    )


def _sets(reps: list[int]) -> dict:
    return {"schema_version": 1, "sets": [{"reps": rep} for rep in reps]}


def _input(**overrides: object) -> CcEvaluationInput:
    payload: dict[str, object] = {
        "rules": _rules(),
        "sets_payload": _sets([10, 10, 10]),
        "skipped": False,
        "already_evaluated": False,
        "persisted_goal_met": False,
        "persisted_counts_for_progression": False,
        "persisted_progression_skipped": None,
        "is_tip": True,
        "current_step_number": 3,
        "max_step_number": 10,
        "fail_streak": 0,
        "schema_version": 1,
    }
    payload.update(overrides)
    return CcEvaluationInput(**payload)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("overrides", "goal_met", "event_type", "to_step", "fail_streak", "skipped"),
    [
        pytest.param({}, True, "advance", 4, 0, None, id="tip-success-advances"),
        pytest.param(
            {"current_step_number": 10, "max_step_number": 10},
            True,
            None,
            None,
            0,
            None,
            id="tip-success-at-max-stays",
        ),
        pytest.param(
            {"sets_payload": _sets([10, 10, 9])},
            False,
            None,
            None,
            1,
            None,
            id="tip-short-set-does-not-advance",
        ),
        pytest.param(
            {
                "sets_payload": _sets([1, 1, 1]),
                "fail_streak": 1,
                "current_step_number": 4,
            },
            False,
            "regress",
            3,
            0,
            None,
            id="second-miss-regresses",
        ),
        pytest.param(
            {
                "sets_payload": _sets([1]),
                "fail_streak": 1,
                "current_step_number": 1,
            },
            False,
            None,
            None,
            2,
            None,
            id="miss-on-step-1-does-not-regress",
        ),
        pytest.param(
            {"is_tip": False},
            True,
            None,
            None,
            None,
            "late_log",
            id="late-success-does-not-move-step",
        ),
        pytest.param(
            {"skipped": True, "sets_payload": None},
            False,
            None,
            None,
            None,
            "skipped",
            id="skipped-does-not-move-step",
        ),
    ],
)
def test_cc_evaluator_matches_orchestrator_evaluator(
    overrides: dict[str, object],
    goal_met: bool,
    event_type: str | None,
    to_step: int | None,
    fail_streak: int | None,
    skipped: str | None,
) -> None:
    inp = _input(**overrides)
    direct = CcProgressionEvaluator().evaluate(inp)
    via_orchestrator = CcProgressionOrchestrator()._evaluator.evaluate(inp)
    assert via_orchestrator == direct
    assert direct.goal_met is goal_met
    assert direct.progression_skipped == skipped
    assert direct.counts_for_progression is (skipped is None)
    if event_type is None:
        assert direct.events == ()
    else:
        assert len(direct.events) == 1
        assert direct.events[0].event_type == event_type
        assert direct.events[0].to_step == to_step
    if fail_streak is None:
        assert direct.progress_patch is None
    else:
        assert direct.progress_patch is not None
        assert direct.progress_patch.fail_streak == fail_streak
        expected_step = to_step if to_step is not None else inp.current_step_number
        assert direct.progress_patch.current_step_number == expected_step


def test_already_evaluated_does_not_emit_a_new_transition() -> None:
    result = CcProgressionEvaluator().evaluate(
        _input(
            already_evaluated=True,
            persisted_goal_met=True,
            persisted_counts_for_progression=True,
            sets_payload=_sets([1]),
            fail_streak=4,
        )
    )
    assert result.events == ()
    assert result.progress_patch is None
    assert result.goal_met is True
    assert result.step_number == 3


def test_orchestrator_holds_the_pure_evaluator() -> None:
    assert type(CcProgressionOrchestrator()._evaluator) is CcProgressionEvaluator
