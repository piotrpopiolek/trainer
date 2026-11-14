"""Pure satellite set aggregation."""

from __future__ import annotations

from datetime import date

from app.services.satellite_progress_read import aggregate_sets_point


def test_aggregate_sets_point_reps_weight_sides() -> None:
    pt = aggregate_sets_point(
        local_date=date(2026, 8, 1),
        goal_met=True,
        sets_doc={
            "schema_version": 1,
            "completed": None,
            "sets": [
                {"reps": 10, "weight_kg": "20.000", "sides": "left"},
                {"reps": 12, "weight_kg": "22.500", "sides": "right"},
            ],
        },
    )
    assert pt.best_reps == 12
    assert pt.best_reps_left == 10
    assert pt.best_reps_right == 12
    assert pt.best_weight_kg == 22.5
    assert pt.best_weight_left == 20.0
    assert pt.best_weight_right == 22.5
    assert pt.completed is None

def test_aggregate_sets_point_type_c_completed() -> None:
    pt = aggregate_sets_point(
        local_date=date(2026, 8, 1),
        goal_met=True,
        sets_doc={"schema_version": 1, "completed": True, "sets": []},
    )
    assert pt.completed is True
    assert pt.best_reps is None
