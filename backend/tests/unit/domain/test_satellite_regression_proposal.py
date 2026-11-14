"""Regression suggestion threshold, no persistence."""

from __future__ import annotations

from app.domain.satellite_progression import propose_regression_suggestion


def test_propose_regression_suggestion_threshold() -> None:
    ladder = [(1, "a"), (2, "b"), (3, "c")]
    assert (
        propose_regression_suggestion(
            step_number=2, fail_streak=1, threshold=2, step_ladder=ladder
        )
        is None
    )
    hit = propose_regression_suggestion(
        step_number=2, fail_streak=2, threshold=2, step_ladder=ladder
    )
    assert hit is not None
    assert hit.from_step == 2
    assert hit.to_step == 1
    assert hit.from_step_id == "b"
    assert hit.to_step_id == "a"
    assert (
        propose_regression_suggestion(
            step_number=1, fail_streak=5, threshold=2, step_ladder=ladder
        )
        is None
    )
