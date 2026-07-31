"""ProgressionEngine + session immutability (FR-034/034a/035/038/039)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.models.catalog import Exercise, ExerciseStep
from app.models.progression import ProgressionEvent, UserExerciseProgress
from app.models.user import User
from app.models.workout import SessionExerciseLog, WorkoutSession
from app.schemas.rules import ProgressionRulesV1, parse_progression_rules
from app.services.progression import ProgressionEngine, goal_met_from_sets
from app.services.session_rules import (
    DuplicateExerciseSameDayError,
    SessionDateImmutableError,
    SessionImmutableAfterEvaluateError,
    assert_dates_unchanged,
    assert_mutable_for_content_update,
    assert_no_active_cc_log_same_day,
    soft_delete_session,
)


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine(settings.resolved_database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _cc_exercise(db: AsyncSession) -> Exercise:
    ex = await db.scalar(select(Exercise).where(Exercise.slug == "push_ups", Exercise.kind == "cc"))
    if ex is None:
        pytest.skip("seed catalog required")
    return ex


async def _user(db: AsyncSession) -> User:
    user = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}", email=f"{new_uuid7()}@ex.com")
    db.add(user)
    await db.flush()
    return user


def _sets(reps: list[int]) -> dict:
    return {
        "schema_version": 1,
        "sets": [{"reps": r} for r in reps],
    }


def _sets_meeting_push(step: int) -> dict:
    """Sets that meet push_ups advance (=progression) for the given step."""
    # From backend/seed/cc/step_standards.json
    table: dict[int, tuple[int, int, bool]] = {
        1: (3, 50, False),
        2: (3, 40, False),
        3: (3, 30, False),
        4: (2, 25, False),
        5: (2, 20, False),
        6: (2, 20, False),
        7: (2, 20, True),
        8: (2, 20, True),
        9: (2, 20, True),
        10: (1, 100, True),
    }
    sets_n, reps, both = table[step]
    if not both:
        return _sets([reps] * sets_n)
    out: list[dict] = []
    for _ in range(sets_n):
        out.append({"reps": reps, "sides": "left"})
    for _ in range(sets_n):
        out.append({"reps": reps, "sides": "right"})
    return {"schema_version": 1, "sets": out}


async def _session_with_log(
    db: AsyncSession,
    *,
    user: User,
    exercise: Exercise,
    local_date: date,
    performed_at: datetime,
    sets: dict,
    step_number: int = 1,
) -> tuple[WorkoutSession, SessionExerciseLog]:
    session = WorkoutSession(
        id=new_uuid7(),
        user_id=user.id,
        performed_at=performed_at,
        local_date=local_date,
        client_mutation_id=new_uuid7(),
        revision=1,
        client_updated_at=performed_at,
    )
    db.add(session)
    await db.flush()  # composite FK has no ORM dependency edge → flush parent first
    log = SessionExerciseLog(
        id=new_uuid7(),
        session_id=session.id,
        user_id=user.id,
        exercise_id=exercise.id,
        exercise_kind="cc",
        section="main",
        step_number=step_number,
        local_date=local_date,
        performed_at=performed_at,
        content_locale="pl-PL",
        exercise_name_snapshot="Push-ups",
        skipped=False,
        sets=sets,
        # ck_session_logs_skipped_false requires snapshot+schema on insert;
        # evaluate_log overwrites with step rules.
        rules_snapshot={"schema_version": 1},
        progression_schema_version=1,
        sort_order=0,
        client_mutation_id=new_uuid7(),
        revision=1,
        client_updated_at=performed_at,
    )
    db.add(log)
    await db.flush()
    return session, log


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


@pytest.mark.asyncio
async def test_two_fails_cause_regress(db: AsyncSession) -> None:
    engine = ProgressionEngine()
    user = await _user(db)
    exercise = await _cc_exercise(db)
    db.add(
        UserExerciseProgress(
            id=new_uuid7(),
            user_id=user.id,
            exercise_id=exercise.id,
            current_step_number=3,
            fail_streak=0,
            is_active=True,
        )
    )
    await db.commit()

    d1 = date(2026, 7, 1)
    t1 = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    s1, log1 = await _session_with_log(
        db,
        user=user,
        exercise=exercise,
        local_date=d1,
        performed_at=t1,
        sets=_sets([5, 5, 5]),
        step_number=3,
    )
    r1 = await engine.evaluate_log(db, log1, session=s1)
    await db.commit()
    assert r1.is_tip and not r1.goal_met and not r1.events
    assert log1.counts_for_progression is True

    mid = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == exercise.id,
        )
    )
    assert mid is not None
    assert mid.current_step_number == 3
    assert mid.fail_streak == 1  # single fail: no regress yet; gap must not reset

    d2 = date(2026, 7, 8)  # calendar gap must not reset streak
    t2 = datetime(2026, 7, 8, 10, 0, tzinfo=UTC)
    s2, log2 = await _session_with_log(
        db,
        user=user,
        exercise=exercise,
        local_date=d2,
        performed_at=t2,
        sets=_sets([4, 4, 4]),
        step_number=3,
    )
    r2 = await engine.evaluate_log(db, log2, session=s2)
    await db.commit()
    assert r2.is_tip
    assert len(r2.events) == 1
    assert r2.events[0].event_type == "regress"
    assert r2.events[0].to_step == 2
    assert r2.events[0].rules_snapshot is not None

    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == exercise.id,
        )
    )
    assert progress is not None
    assert progress.current_step_number == 2
    assert progress.fail_streak == 0


@pytest.mark.asyncio
async def test_success_resets_fail_streak_without_advance_at_max(db: AsyncSession) -> None:
    """FR-034a: tip success clears fail_streak even when already at step ceiling."""
    engine = ProgressionEngine()
    user = await _user(db)
    exercise = await _cc_exercise(db)
    db.add(
        UserExerciseProgress(
            id=new_uuid7(),
            user_id=user.id,
            exercise_id=exercise.id,
            current_step_number=10,
            fail_streak=1,
            is_active=True,
        )
    )
    await db.commit()
    d = date(2026, 7, 4)
    t = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)
    session, log = await _session_with_log(
        db,
        user=user,
        exercise=exercise,
        local_date=d,
        performed_at=t,
        sets=_sets_meeting_push(10),
        step_number=10,
    )
    result = await engine.evaluate_log(db, log, session=session)
    await db.commit()
    assert result.is_tip and result.goal_met
    assert result.events == []  # no advance past MAX_CC_STEP
    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == exercise.id,
        )
    )
    assert progress is not None
    assert progress.current_step_number == 10
    assert progress.fail_streak == 0


@pytest.mark.asyncio
async def test_three_success_advances(db: AsyncSession) -> None:
    engine = ProgressionEngine()
    user = await _user(db)
    exercise = await _cc_exercise(db)
    db.add(
        UserExerciseProgress(
            id=new_uuid7(),
            user_id=user.id,
            exercise_id=exercise.id,
            current_step_number=1,
            fail_streak=0,
            is_active=True,
        )
    )
    await db.commit()

    d = date(2026, 7, 2)
    t = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
    session, log = await _session_with_log(
        db,
        user=user,
        exercise=exercise,
        local_date=d,
        performed_at=t,
        sets=_sets_meeting_push(1),
        step_number=1,
    )
    result = await engine.evaluate_log(db, log, session=session)
    await db.commit()
    assert result.is_tip and result.goal_met
    assert result.events[0].event_type == "advance"
    assert result.events[0].to_step == 2
    assert log.counts_for_progression is True
    assert log.rules_snapshot is not None
    assert log.content_locale == "pl-PL"
    assert log.progression_schema_version is not None

    step = await db.scalar(
        select(ExerciseStep).where(
            ExerciseStep.exercise_id == exercise.id,
            ExerciseStep.step_number == 1,
        )
    )
    assert step is not None
    # FR-037: snapshot is step rules used at evaluate (not reinterpreted later).
    snap = parse_progression_rules(log.rules_snapshot)
    seed = parse_progression_rules(step.rules)
    assert snap == seed
    assert result.events[0].rules_snapshot == log.rules_snapshot


@pytest.mark.asyncio
async def test_late_log_does_not_mutate_progress(db: AsyncSession) -> None:
    engine = ProgressionEngine()
    user = await _user(db)
    exercise = await _cc_exercise(db)
    db.add(
        UserExerciseProgress(
            id=new_uuid7(),
            user_id=user.id,
            exercise_id=exercise.id,
            current_step_number=2,
            fail_streak=1,
            is_active=True,
        )
    )
    await db.commit()

    # Tip first (newer date)
    newer_day = date(2026, 7, 10)
    newer_at = datetime(2026, 7, 10, 18, 0, tzinfo=UTC)
    s_new, log_new = await _session_with_log(
        db,
        user=user,
        exercise=exercise,
        local_date=newer_day,
        performed_at=newer_at,
        sets=_sets_meeting_push(1),
        step_number=2,
    )
    await engine.evaluate_log(db, log_new, session=s_new)
    await db.commit()

    progress_before = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == exercise.id,
        )
    )
    assert progress_before is not None
    step_before = progress_before.current_step_number
    streak_before = progress_before.fail_streak

    # Late log (older date) evaluated after tip exists
    older_day = date(2026, 7, 3)
    older_at = datetime(2026, 7, 3, 9, 0, tzinfo=UTC)
    s_old, log_old = await _session_with_log(
        db,
        user=user,
        exercise=exercise,
        local_date=older_day,
        performed_at=older_at,
        sets=_sets([1, 1, 1]),
        step_number=2,
    )
    late = await engine.evaluate_log(db, log_old, session=s_old)
    await db.commit()

    assert late.is_tip is False
    assert late.progression_skipped == "late_log"
    assert log_old.counts_for_progression is False
    assert log_old.goal_evaluated_at is not None
    assert log_old.rules_snapshot is not None

    progress_after = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == exercise.id,
        )
    )
    assert progress_after is not None
    assert progress_after.current_step_number == step_before
    assert progress_after.fail_streak == streak_before
    events = (
        await db.scalars(
            select(ProgressionEvent).where(
                ProgressionEvent.session_id == s_old.id,
            )
        )
    ).all()
    assert events == []


@pytest.mark.asyncio
async def test_session_date_immutable(db: AsyncSession) -> None:
    user = await _user(db)
    session = WorkoutSession(
        id=new_uuid7(),
        user_id=user.id,
        performed_at=datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
        local_date=date(2026, 7, 1),
        client_mutation_id=new_uuid7(),
        revision=1,
        client_updated_at=datetime.now(UTC),
    )
    db.add(session)
    await db.commit()
    # Positive: identical dates allowed.
    assert_dates_unchanged(
        session,
        performed_at=session.performed_at,
        local_date=session.local_date,
    )
    with pytest.raises(SessionDateImmutableError):
        assert_dates_unchanged(
            session,
            performed_at=session.performed_at + timedelta(hours=1),
            local_date=session.local_date,
        )
    with pytest.raises(SessionDateImmutableError):
        assert_dates_unchanged(
            session,
            performed_at=session.performed_at,
            local_date=session.local_date + timedelta(days=1),
        )


@pytest.mark.asyncio
async def test_immutable_after_evaluate(db: AsyncSession) -> None:
    engine = ProgressionEngine()
    user = await _user(db)
    exercise = await _cc_exercise(db)
    db.add(
        UserExerciseProgress(
            id=new_uuid7(),
            user_id=user.id,
            exercise_id=exercise.id,
            current_step_number=1,
            fail_streak=0,
            is_active=True,
        )
    )
    await db.commit()
    d = date(2026, 7, 5)
    t = datetime(2026, 7, 5, 11, 0, tzinfo=UTC)
    session, log = await _session_with_log(
        db, user=user, exercise=exercise, local_date=d, performed_at=t, sets=_sets_meeting_push(1)
    )
    # Positive: before evaluate, content updates are allowed.
    await assert_mutable_for_content_update(db, session)
    await engine.evaluate_log(db, log, session=session)
    await db.commit()
    with pytest.raises(SessionImmutableAfterEvaluateError):
        await assert_mutable_for_content_update(db, session)


@pytest.mark.asyncio
async def test_soft_delete_supersedes_logs_and_allows_new_same_day(
    db: AsyncSession,
) -> None:
    user = await _user(db)
    exercise = await _cc_exercise(db)
    d = date(2026, 7, 6)
    t = datetime(2026, 7, 6, 8, 0, tzinfo=UTC)
    session, log = await _session_with_log(
        db, user=user, exercise=exercise, local_date=d, performed_at=t, sets=_sets_meeting_push(1)
    )
    await db.commit()
    with pytest.raises(DuplicateExerciseSameDayError):
        await assert_no_active_cc_log_same_day(
            db, user_id=user.id, exercise_id=exercise.id, local_date=d
        )

    await soft_delete_session(db, session)
    await db.commit()
    assert session.deleted_at is not None
    assert log.superseded_at is not None
    # After soft-delete, new log same day is allowed (no raise).
    await assert_no_active_cc_log_same_day(
        db, user_id=user.id, exercise_id=exercise.id, local_date=d
    )
    # Idempotent soft-delete (already tombstoned).
    deleted_at = session.deleted_at
    await soft_delete_session(db, session)
    assert session.deleted_at == deleted_at


@pytest.mark.asyncio
async def test_soft_delete_does_not_rewind_progress(db: AsyncSession) -> None:
    """FR-038: soft-delete of evaluated tip does not rewind step / events."""
    engine = ProgressionEngine()
    user = await _user(db)
    exercise = await _cc_exercise(db)
    db.add(
        UserExerciseProgress(
            id=new_uuid7(),
            user_id=user.id,
            exercise_id=exercise.id,
            current_step_number=1,
            fail_streak=0,
            is_active=True,
        )
    )
    await db.commit()
    d = date(2026, 7, 7)
    t = datetime(2026, 7, 7, 9, 0, tzinfo=UTC)
    session, log = await _session_with_log(
        db,
        user=user,
        exercise=exercise,
        local_date=d,
        performed_at=t,
        sets=_sets_meeting_push(1),
        step_number=1,
    )
    result = await engine.evaluate_log(db, log, session=session)
    await db.commit()
    assert result.events[0].event_type == "advance"
    event_id = result.events[0].id

    await soft_delete_session(db, session)
    await db.commit()

    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == exercise.id,
        )
    )
    assert progress is not None
    assert progress.current_step_number == 2
    ev = await db.scalar(select(ProgressionEvent).where(ProgressionEvent.id == event_id))
    assert ev is not None
    assert ev.event_type == "advance"


@pytest.mark.asyncio
async def test_evaluate_log_is_idempotent(db: AsyncSession) -> None:
    engine = ProgressionEngine()
    user = await _user(db)
    exercise = await _cc_exercise(db)
    db.add(
        UserExerciseProgress(
            id=new_uuid7(),
            user_id=user.id,
            exercise_id=exercise.id,
            current_step_number=1,
            fail_streak=0,
            is_active=True,
        )
    )
    await db.commit()
    d = date(2026, 7, 11)
    t = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
    session, log = await _session_with_log(
        db,
        user=user,
        exercise=exercise,
        local_date=d,
        performed_at=t,
        sets=_sets_meeting_push(1),
        step_number=1,
    )
    first = await engine.evaluate_log(db, log, session=session)
    await db.commit()
    assert first.is_tip and len(first.events) == 1

    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == exercise.id,
        )
    )
    assert progress is not None
    step_after = progress.current_step_number
    streak_after = progress.fail_streak

    second = await engine.evaluate_log(db, log, session=session)
    await db.commit()
    assert second.events == []
    assert second.is_tip is True
    assert second.goal_met is True
    assert progress.current_step_number == step_after
    assert progress.fail_streak == streak_after
    events = (
        await db.scalars(
            select(ProgressionEvent).where(ProgressionEvent.session_id == session.id)
        )
    ).all()
    assert len(events) == 1


@pytest.mark.asyncio
async def test_evaluate_uses_progress_step_not_client_log_step(db: AsyncSession) -> None:
    """FR-035: goal_met / rules vs bieżący krok — client step_number is ignored."""
    engine = ProgressionEngine()
    user = await _user(db)
    exercise = await _cc_exercise(db)
    db.add(
        UserExerciseProgress(
            id=new_uuid7(),
            user_id=user.id,
            exercise_id=exercise.id,
            current_step_number=3,
            fail_streak=0,
            is_active=True,
        )
    )
    await db.commit()
    d = date(2026, 7, 4)
    t = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)
    # Client claims step 1 (easier), progress is on step 3.
    session, log = await _session_with_log(
        db,
        user=user,
        exercise=exercise,
        local_date=d,
        performed_at=t,
        sets=_sets_meeting_push(1),
        step_number=1,
    )
    result = await engine.evaluate_log(db, log, session=session)
    await db.commit()
    assert log.step_number == 3
    assert result.is_tip and result.goal_met
    assert result.events[0].event_type == "advance"
    assert result.events[0].from_step == 3
    assert result.events[0].to_step == 4


@pytest.mark.asyncio
async def test_manual_override_resets_fail_streak(db: AsyncSession) -> None:
    engine = ProgressionEngine()
    user = await _user(db)
    exercise = await _cc_exercise(db)
    db.add(
        UserExerciseProgress(
            id=new_uuid7(),
            user_id=user.id,
            exercise_id=exercise.id,
            current_step_number=4,
            fail_streak=1,
            is_active=True,
        )
    )
    await db.commit()
    ev = await engine.manual_override(db, user_id=user.id, exercise_id=exercise.id, to_step=2)
    await db.commit()
    assert ev.event_type == "manual_override"
    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == exercise.id,
        )
    )
    assert progress is not None
    assert progress.current_step_number == 2
    assert progress.fail_streak == 0
