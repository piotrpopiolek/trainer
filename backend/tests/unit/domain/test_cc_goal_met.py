"""CC goal_met thresholds without a session."""

from __future__ import annotations

from app.schemas.rules import ProgressionRulesV1
from app.services.progression import goal_met_from_sets


def _sets(reps: list[int]) -> dict:
    return {
        "schema_version": 1,
        "sets": [{"reps": r} for r in reps],
    }

def test_goal_met_advance_threshold() -> None:
    rules = ProgressionRulesV1.model_validate(
        {
            "schema_version": 1,
            "advance": {"sets": 3, "min_reps": 10, "require_both_sides": False},
            "regress": {"fail_sessions": 2},
        }
    )
    assert goal_met_from_sets(rules, _sets([10, 10, 10]))
    assert not goal_met_from_sets(rules, _sets([10, 10, 9]))

def test_goal_met_require_both_sides() -> None:
    rules = ProgressionRulesV1.model_validate(
        {
            "schema_version": 1,
            "advance": {"sets": 2, "min_reps": 10, "require_both_sides": True},
            "regress": {"fail_sessions": 2},
        }
    )
    both = {
        "schema_version": 1,
        "sets": [
            {"reps": 10, "sides": "left"},
            {"reps": 10, "sides": "left"},
            {"reps": 10, "sides": "right"},
            {"reps": 10, "sides": "right"},
        ],
    }
    left_only = {
        "schema_version": 1,
        "sets": [
            {"reps": 10, "sides": "left"},
            {"reps": 10, "sides": "left"},
        ],
    }
    assert goal_met_from_sets(rules, both)
    assert not goal_met_from_sets(rules, left_only)
