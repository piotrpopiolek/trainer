"""FR-030b pure characterization: companion guard and goal semantics."""

from __future__ import annotations

from pathlib import Path

import pytest

_CC_COMPANION_TESTS = (
    "test_two_fails_cause_regress",
    "test_three_success_advances",
    "test_late_log_does_not_mutate_progress",
    "test_soft_delete_does_not_rewind_progress",
    "test_manual_override_resets_fail_streak",
    "test_session_date_immutable",
    "test_immutable_after_evaluate",
)

def test_fr030b_companion_cc_suite_still_present() -> None:
    """Guard: CC tip/late/fail/override/immutability live in the companion file."""
    companion = (
        Path(__file__).resolve().parents[2]
        / "integration"
        / "services"
        / "test_progression_engine.py"
    ).read_text(encoding="utf-8")
    missing = [name for name in _CC_COMPANION_TESTS if f"def {name}" not in companion]
    assert missing == [], f"FR-030b companion CC tests missing: {missing}"

def test_stage1_satellite_goal_reps_duration_completed_semantics() -> None:
    from app.domain.satellite_progression import satellite_goal_met
    from app.schemas.satellite import (
        ActiveMetricsV1,
        SatelliteGoalCompletedV1,
        SatelliteGoalDurationV1,
        SatelliteGoalRepsV1,
        SatelliteLogResultV1,
        SatelliteRulesV1,
        SatelliteSetV1,
    )

    reps = SatelliteRulesV1(
        schema_version=1,
        goal=SatelliteGoalRepsV1(type="reps", sets=3, min_reps=10),
    )
    active_reps = ActiveMetricsV1(schema_version=1, metrics=["reps"])
    assert satellite_goal_met(
        reps,
        SatelliteLogResultV1(
            schema_version=1,
            sets=[
                SatelliteSetV1(reps=10),
                SatelliteSetV1(reps=10),
                SatelliteSetV1(reps=10),
            ],
        ),
        active_metrics=active_reps,
    )
    assert not satellite_goal_met(
        reps,
        SatelliteLogResultV1(
            schema_version=1,
            sets=[
                SatelliteSetV1(reps=10),
                SatelliteSetV1(reps=10),
                SatelliteSetV1(reps=9),
            ],
        ),
        active_metrics=active_reps,
    )

    duration = SatelliteRulesV1(
        schema_version=1,
        goal=SatelliteGoalDurationV1(type="duration", sets=2, min_duration_sec=20),
    )
    active_dur = ActiveMetricsV1(schema_version=1, metrics=["duration_sec"])
    assert satellite_goal_met(
        duration,
        SatelliteLogResultV1(
            schema_version=1,
            sets=[
                SatelliteSetV1(duration_sec=20),
                SatelliteSetV1(duration_sec=25),
            ],
        ),
        active_metrics=active_dur,
    )

    completed = SatelliteRulesV1(
        schema_version=1, goal=SatelliteGoalCompletedV1(type="completed")
    )
    active_c = ActiveMetricsV1(schema_version=1, metrics=[])
    assert not satellite_goal_met(
        completed,
        SatelliteLogResultV1(schema_version=1, completed=None, sets=[]),
        active_metrics=active_c,
    )
    assert satellite_goal_met(
        completed,
        SatelliteLogResultV1(schema_version=1, completed=True, sets=[]),
        active_metrics=active_c,
    )
    with pytest.raises(ValueError, match="empty_set"):
        SatelliteSetV1()
