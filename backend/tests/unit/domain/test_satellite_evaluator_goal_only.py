"""Goal-only satellite evaluator records goal_met and does not move the step."""

from __future__ import annotations

import pytest

from app.domain.satellite_progression import (
    SatelliteEvaluationInput,
    SatelliteProgressionEvaluator,
)
from app.schemas.satellite import (
    ActiveMetricsV1,
    SatelliteGoalRepsV1,
    SatelliteRulesV1,
)


def _rules() -> SatelliteRulesV1:
    return SatelliteRulesV1(
        schema_version=1,
        goal=SatelliteGoalRepsV1(type="reps", sets=3, min_reps=10),
    )


def _input(*, reps: list[int], eligible: bool) -> SatelliteEvaluationInput:
    return SatelliteEvaluationInput(
        rules=_rules(),
        active_metrics=ActiveMetricsV1(schema_version=1, metrics=["reps"]),
        log_payload={
            "schema_version": 1,
            "sets": [{"reps": rep} for rep in reps],
        },
        skipped=False,
        already_evaluated=False,
        persisted_goal_met=False,
        progression_eligible=eligible,
        step_number=1,
        schema_version=1,
    )


@pytest.mark.parametrize(
    ("reps", "eligible", "goal_met", "skipped"),
    [
        pytest.param([10, 10, 10], True, True, None, id="goal-met-does-not-advance"),
        pytest.param([10, 10, 9], True, False, None, id="goal-miss-does-not-advance"),
        pytest.param(
            [10, 10, 10],
            False,
            True,
            "config_not_active_for_day",
            id="ineligible-success-does-not-advance",
        ),
    ],
)
def test_goal_only_evaluator_does_not_move_step(
    reps: list[int],
    eligible: bool,
    goal_met: bool,
    skipped: str | None,
) -> None:
    result = SatelliteProgressionEvaluator().evaluate(_input(reps=reps, eligible=eligible))
    assert result.goal_met is goal_met
    assert result.events == ()
    assert result.counts_for_progression is False
    assert result.progression_skipped == skipped
    assert result.step_number == 1
    assert result.progress_patch is not None
    assert result.progress_patch.current_step_number is None
    assert result.progress_patch.fail_streak is None
