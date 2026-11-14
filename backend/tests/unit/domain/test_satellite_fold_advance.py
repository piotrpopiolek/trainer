"""Daily-outcome fold advance proposal."""

from __future__ import annotations

from datetime import UTC, datetime

from app.domain.satellite_progression import fold_daily_outcome


def test_fold_success_proposes_advance_until_last_step() -> None:
    now = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
    ladder = [(1, "s1"), (2, "s2"), (3, "s3")]
    mid = fold_daily_outcome(
        None,
        goal_met=True,
        skipped=False,
        eligible=True,
        already_evaluated=False,
        log_id="log-1",
        now=now,
        finalize_after=now,
        step_number=2,
        fail_streak=1,
        step_ladder=ladder,
    )
    assert mid.advance_from == 2
    assert mid.advance_to == 3
    assert mid.advance_to_step_id == "s3"
    assert mid.fail_streak == 0

    last = fold_daily_outcome(
        None,
        goal_met=True,
        skipped=False,
        eligible=True,
        already_evaluated=False,
        log_id="log-2",
        now=now,
        finalize_after=now,
        step_number=3,
        fail_streak=0,
        step_ladder=ladder,
    )
    assert last.advance_to is None
    assert last.state.result == "success"
