"""Pure satellite goal_met and JCS key order."""

from __future__ import annotations

from app.domain.canonical_json import sha256_jcs_hex
from app.domain.satellite_progression import satellite_goal_met
from app.schemas.satellite import (
    ActiveMetricsV1,
    SatelliteGoalCompletedV1,
    SatelliteGoalRepsV1,
    SatelliteLogResultV1,
    SatelliteRulesV1,
    SatelliteSetV1,
)


def test_satellite_goal_met_both_sides_and_weight() -> None:
    rules = SatelliteRulesV1(
        schema_version=1,
        goal=SatelliteGoalRepsV1(
            type="reps",
            sets=3,
            min_reps=10,
            require_both_sides=True,
            min_weight_kg=None,
        ),
    )
    active = ActiveMetricsV1(schema_version=1, metrics=["reps", "weight_kg", "sides"])
    ok = SatelliteLogResultV1(
        schema_version=1,
        completed=None,
        sets=[
            SatelliteSetV1(reps=10, weight_kg="20.000", sides="left"),
            SatelliteSetV1(reps=10, weight_kg="20.000", sides="left"),
            SatelliteSetV1(reps=10, weight_kg="20.000", sides="left"),
            SatelliteSetV1(reps=10, weight_kg="20.000", sides="right"),
            SatelliteSetV1(reps=10, weight_kg="20.000", sides="right"),
            SatelliteSetV1(reps=10, weight_kg="20.000", sides="right"),
        ],
    )
    assert satellite_goal_met(rules, ok, active_metrics=active)

    weak_right = SatelliteLogResultV1(
        schema_version=1,
        completed=None,
        sets=[
            SatelliteSetV1(reps=10, weight_kg="20.000", sides="left"),
            SatelliteSetV1(reps=10, weight_kg="20.000", sides="left"),
            SatelliteSetV1(reps=10, weight_kg="20.000", sides="left"),
            SatelliteSetV1(reps=10, weight_kg="20.000", sides="right"),
            SatelliteSetV1(reps=9, weight_kg="20.000", sides="right"),
            SatelliteSetV1(reps=10, weight_kg="20.000", sides="right"),
        ],
    )
    assert not satellite_goal_met(rules, weak_right, active_metrics=active)

def test_completed_requires_explicit_flag() -> None:
    rules = SatelliteRulesV1(
        schema_version=1, goal=SatelliteGoalCompletedV1(type="completed")
    )
    active = ActiveMetricsV1(schema_version=1, metrics=[])
    assert not satellite_goal_met(
        rules,
        SatelliteLogResultV1(schema_version=1, completed=None, sets=[]),
        active_metrics=active,
    )
    assert satellite_goal_met(
        rules,
        SatelliteLogResultV1(schema_version=1, completed=True, sets=[]),
        active_metrics=active,
    )

def test_jcs_hash_stable_for_key_order() -> None:
    a = {
        "schema_version": 1,
        "exercise_type": "B",
        "active_metrics": {"schema_version": 1, "metrics": ["reps", "sides", "weight_kg"]},
        "progression": {"mode": "goal_only"},
        "steps": [
            {
                "step_id": "01920000-0000-7000-8000-0000000000b1",
                "sort_order": 1,
                "rules": {
                    "schema_version": 1,
                    "goal": {
                        "type": "reps",
                        "sets": 3,
                        "min_reps": 10,
                        "min_weight_kg": None,
                        "require_both_sides": True,
                    },
                },
            }
        ],
    }
    b = {
        "steps": a["steps"],
        "progression": a["progression"],
        "active_metrics": {
            "metrics": ["weight_kg", "sides", "reps"],
            "schema_version": 1,
        },
        "exercise_type": "B",
        "schema_version": 1,
    }
    # After Pydantic normalize metrics are sorted; raw dicts differ until canonicalize sorts keys.
    assert sha256_jcs_hex(a) == sha256_jcs_hex(
        {
            **b,
            "active_metrics": {
                "schema_version": 1,
                "metrics": sorted(b["active_metrics"]["metrics"]),
            },
        }
    )
