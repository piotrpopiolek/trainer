"""Pure daily-outcome fold and finalize-after clock."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.domain.satellite_progression import (
    DailyOutcomeState,
    compute_finalize_after,
    finalize_pending_failure,
    fold_daily_outcome,
)


def test_compute_finalize_after_warsaw_plus_36h() -> None:
    # 2026-08-03 Europe/Warsaw is CEST (UTC+2): local EOD → 21:59:59.999999Z + 36h
    got = compute_finalize_after(date(2026, 8, 3), timezone_name="Europe/Warsaw")
    assert got == datetime(2026, 8, 5, 9, 59, 59, 999999, tzinfo=UTC)

def test_fold_success_resets_streak_and_finalizes() -> None:
    now = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
    deadline = now + timedelta(hours=40)
    fold = fold_daily_outcome(
        None,
        goal_met=True,
        skipped=False,
        eligible=True,
        already_evaluated=False,
        log_id="log-1",
        now=now,
        finalize_after=deadline,
        step_number=2,
        fail_streak=3,
        step_ladder=[(1, "a"), (2, "b"), (3, "c")],
    )
    assert fold.state.status == "finalized"
    assert fold.state.result == "success"
    assert fold.fail_streak == 0
    assert fold.counts_for_progression is True
    assert fold.advance_to == 3
    assert fold.advance_to_step_id == "c"

def test_fold_fail_attempt_stays_pending() -> None:
    now = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
    deadline = now + timedelta(hours=40)
    fold = fold_daily_outcome(
        None,
        goal_met=False,
        skipped=False,
        eligible=True,
        already_evaluated=False,
        log_id="log-1",
        now=now,
        finalize_after=deadline,
        step_number=2,
        fail_streak=0,
    )
    assert fold.state.status == "pending"
    assert fold.state.has_attempt is True
    assert fold.state.has_success is False
    assert fold.fail_streak is None

def test_finalize_failure_increments_streak_only_above_step_1() -> None:
    pending = DailyOutcomeState(
        status="pending",
        has_attempt=True,
        has_success=False,
        result=None,
        finalize_after=datetime(2026, 8, 1, 0, 0, tzinfo=UTC),
        finalized_at=None,
        representative_log_id="log-1",
        result_snapshot=None,
    )
    now = datetime(2026, 8, 5, 0, 0, tzinfo=UTC)
    s1, streak1, did1 = finalize_pending_failure(
        pending, now=now, step_number=1, fail_streak=0
    )
    assert did1 and s1.result == "failure" and streak1 is None

    s2, streak2, did2 = finalize_pending_failure(
        pending, now=now, step_number=2, fail_streak=1
    )
    assert did2 and streak2 == 2

def test_fold_after_deadline_marks_daily_finalized() -> None:
    pending = DailyOutcomeState(
        status="pending",
        has_attempt=True,
        has_success=False,
        result=None,
        finalize_after=datetime(2026, 8, 1, 0, 0, tzinfo=UTC),
        finalized_at=None,
        representative_log_id="log-1",
        result_snapshot=None,
    )
    fold = fold_daily_outcome(
        pending,
        goal_met=True,
        skipped=False,
        eligible=True,
        already_evaluated=False,
        log_id="log-2",
        now=datetime(2026, 8, 5, 0, 0, tzinfo=UTC),
        finalize_after=datetime(2026, 8, 1, 0, 0, tzinfo=UTC),
        step_number=2,
        fail_streak=0,
    )
    assert fold.progression_skipped == "daily_finalized"
    assert fold.state.result == "failure"
    assert fold.counts_for_progression is False
    assert fold.fail_streak == 1

def test_fold_ineligible_still_finalizes_overdue_pending() -> None:
    pending = DailyOutcomeState(
        status="pending",
        has_attempt=True,
        has_success=False,
        result=None,
        finalize_after=datetime(2026, 8, 1, 0, 0, tzinfo=UTC),
        finalized_at=None,
        representative_log_id="log-1",
        result_snapshot=None,
    )
    fold = fold_daily_outcome(
        pending,
        goal_met=False,
        skipped=False,
        eligible=False,
        already_evaluated=False,
        log_id="log-detached",
        now=datetime(2026, 8, 5, 0, 0, tzinfo=UTC),
        finalize_after=datetime(2026, 8, 10, 0, 0, tzinfo=UTC),
        step_number=2,
        fail_streak=0,
    )
    assert fold.state.status == "finalized"
    assert fold.state.result == "failure"
    assert fold.newly_finalized is True
    assert fold.fail_streak == 1
    assert fold.progression_skipped == "config_not_active_for_day"
    assert fold.counts_for_progression is False
