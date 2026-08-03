"""Stage 3 Slice B — daily outcome fold (success / fail+36h / streak rules)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.domain.satellite_progression import (
    DailyOutcomeState,
    compute_finalize_after,
    finalize_pending_failure,
    fold_daily_outcome,
)
from app.models.catalog import Program
from app.models.progression import UserExerciseProgress
from app.models.satellite_progress import SatelliteDailyOutcome
from app.models.user import User
from app.schemas.api import SatelliteCreateV1, SessionCreateV1, SessionLogCreateV1
from app.services.auth_session import AuthSessionService
from app.services.legal import record_legal_acceptance
from app.services.onboarding import complete_onboarding
from app.services.satellite_progression import SatelliteProgressionOrchestrator
from app.services.satellites import create_satellite
from app.services.sessions import create_session
from tests.legal_fixtures import latest_health_disclaimer


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine(settings.resolved_database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _ready(db: AsyncSession, email: str) -> User:
    if await db.scalar(select(Program).where(Program.slug == "cc_big_six")) is None:
        pytest.skip("seed catalog required")
    doc, tr = await latest_health_disclaimer(db)
    user = User(
        id=new_uuid7(),
        google_sub=f"sub-{new_uuid7()}",
        email=email,
        locale="pl-PL",
        timezone="Europe/Warsaw",
    )
    db.add(user)
    await db.commit()
    await complete_onboarding(
        db,
        user,
        questionnaire={
            "schema_version": 1,
            "experience_level": "beginner",
            "training_days_per_week": 3,
            "goals": ["strength"],
        },
        started_on=date(2026, 7, 1),
        anchor_weekday=1,
    )
    await record_legal_acceptance(
        db,
        user_id=user.id,
        payload={
            "schema_version": 1,
            "client_mutation_id": str(uuid4()),
            "document_slug": "health_disclaimer",
            "document_version": doc.version,
            "accepted_locale": "pl-PL",
            "accepted_content_hash": tr.content_hash.hex(),
            "accepted_at": datetime.now(UTC).isoformat(),
        },
    )
    await db.commit()
    await AuthSessionService().create_session(db, user=user, user_agent="t")
    return user


def _duration_rules(*, min_duration_sec: int) -> dict:
    return {
        "schema_version": 1,
        "goal": {
            "type": "duration",
            "sets": 3,
            "min_duration_sec": min_duration_sec,
            "min_weight_kg": None,
            "require_both_sides": True,
        },
    }


def _copenhagen_body(*, mutation_id) -> SatelliteCreateV1:
    return SatelliteCreateV1.model_validate(
        {
            "schema_version": 1,
            "name": "Copenhagen Plank",
            "exercise_type": "B",
            "active_metrics": {
                "schema_version": 1,
                "metrics": ["duration_sec", "sides"],
            },
            "schedule_kind": "category",
            "schedule_category": "post_workout",
            "equipment": ["bench"],
            "progression": {
                "mode": "steps",
                "regression": {
                    "mode": "suggest_after_failed_days",
                    "threshold": 2,
                },
            },
            "steps": [
                {
                    "step_number": 1,
                    "step_id": str(new_uuid7()),
                    "name": "Short lever hold",
                    "rules": _duration_rules(min_duration_sec=20),
                },
                {
                    "step_number": 2,
                    "step_id": str(new_uuid7()),
                    "name": "Long lever hold",
                    "rules": _duration_rules(min_duration_sec=20),
                },
                {
                    "step_number": 3,
                    "step_id": str(new_uuid7()),
                    "name": "Long lever lifted",
                    "rules": _duration_rules(min_duration_sec=15),
                },
            ],
            "client_mutation_id": str(mutation_id),
        }
    )


def _success_sets() -> dict:
    return {
        "schema_version": 1,
        "sets": [
            {"duration_sec": 20, "sides": "left"},
            {"duration_sec": 20, "sides": "right"},
            {"duration_sec": 20, "sides": "left"},
            {"duration_sec": 20, "sides": "right"},
            {"duration_sec": 20, "sides": "left"},
            {"duration_sec": 20, "sides": "right"},
        ],
    }


def _fail_sets() -> dict:
    return {
        "schema_version": 1,
        "sets": [
            {"duration_sec": 5, "sides": "left"},
            {"duration_sec": 5, "sides": "right"},
        ],
    }


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


@pytest.mark.asyncio
async def test_fail_then_success_same_day_finalizes_success(db: AsyncSession) -> None:
    user = await _ready(db, "outcome-fail-success@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    await create_session(
        db,
        user=user,
        body=SessionCreateV1(
            schema_version=1,
            performed_at=datetime(2026, 8, 3, 9, 0, tzinfo=UTC),
            local_date=date(2026, 8, 3),
            client_mutation_id=new_uuid7(),
            client_timezone="Europe/Warsaw",
            logs=[
                SessionLogCreateV1(
                    exercise_id=sat.id,
                    exercise_kind="satellite",
                    section="accessories",
                    sets=_fail_sets(),
                    satellite_config_version_id=sat.current_config_version_id,
                    satellite_config_hash=sat.config_hash,
                )
            ],
        ),
        commit=True,
    )
    pending = await db.scalar(
        select(SatelliteDailyOutcome).where(
            SatelliteDailyOutcome.user_id == user.id,
            SatelliteDailyOutcome.exercise_id == sat.id,
        )
    )
    assert pending is not None
    assert pending.status == "pending"
    assert pending.has_attempt is True

    read = await create_session(
        db,
        user=user,
        body=SessionCreateV1(
            schema_version=1,
            performed_at=datetime(2026, 8, 3, 18, 0, tzinfo=UTC),
            local_date=date(2026, 8, 3),
            client_mutation_id=new_uuid7(),
            client_timezone="Europe/Warsaw",
            logs=[
                SessionLogCreateV1(
                    exercise_id=sat.id,
                    exercise_kind="satellite",
                    section="accessories",
                    sets=_success_sets(),
                    satellite_config_version_id=sat.current_config_version_id,
                    satellite_config_hash=sat.config_hash,
                )
            ],
        ),
        commit=True,
    )
    assert read.logs[0].goal_met is True
    await db.refresh(pending)
    assert pending.status == "finalized"
    assert pending.result == "success"


@pytest.mark.asyncio
async def test_lazy_finalize_failure_step1_no_streak(db: AsyncSession) -> None:
    user = await _ready(db, "outcome-lazy-fail@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    # local_date near "now" so deadline is still in the future → pending attempt.
    day = date(2026, 8, 3)
    await create_session(
        db,
        user=user,
        body=SessionCreateV1(
            schema_version=1,
            performed_at=datetime(2026, 8, 3, 10, 0, tzinfo=UTC),
            local_date=day,
            client_mutation_id=new_uuid7(),
            client_timezone="Europe/Warsaw",
            logs=[
                SessionLogCreateV1(
                    exercise_id=sat.id,
                    exercise_kind="satellite",
                    section="accessories",
                    sets=_fail_sets(),
                    satellite_config_version_id=sat.current_config_version_id,
                    satellite_config_hash=sat.config_hash,
                )
            ],
        ),
        commit=True,
    )
    outcome = await db.scalar(
        select(SatelliteDailyOutcome).where(
            SatelliteDailyOutcome.user_id == user.id,
            SatelliteDailyOutcome.exercise_id == sat.id,
        )
    )
    assert outcome is not None
    assert outcome.status == "pending"
    assert outcome.has_attempt is True
    await db.execute(
        update(SatelliteDailyOutcome)
        .where(SatelliteDailyOutcome.id == outcome.id)
        .values(finalize_after=datetime(2026, 8, 2, 0, 0, tzinfo=UTC))
    )
    await db.commit()

    n = await SatelliteProgressionOrchestrator().finalize_due_outcomes(
        db, user_id=user.id, now=datetime(2026, 8, 4, 0, 0, tzinfo=UTC)
    )
    await db.commit()
    assert n == 1
    await db.refresh(outcome)
    assert outcome.status == "finalized"
    assert outcome.result == "failure"

    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == sat.id,
        )
    )
    assert progress is not None
    assert progress.current_step_number == 1
    assert progress.fail_streak == 0


@pytest.mark.asyncio
async def test_lazy_finalize_failure_step2_increments_streak(db: AsyncSession) -> None:
    user = await _ready(db, "outcome-step2-streak@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == sat.id,
        )
    )
    assert progress is not None
    steps = sat.steps
    progress.current_step_number = 2
    progress.current_step_id = __import__("uuid").UUID(steps[1]["step_id"])
    await db.commit()

    await create_session(
        db,
        user=user,
        body=SessionCreateV1(
            schema_version=1,
            performed_at=datetime(2026, 8, 3, 10, 0, tzinfo=UTC),
            local_date=date(2026, 8, 3),
            client_mutation_id=new_uuid7(),
            client_timezone="Europe/Warsaw",
            logs=[
                SessionLogCreateV1(
                    exercise_id=sat.id,
                    exercise_kind="satellite",
                    section="accessories",
                    sets=_fail_sets(),
                    satellite_config_version_id=sat.current_config_version_id,
                    satellite_config_hash=sat.config_hash,
                )
            ],
        ),
        commit=True,
    )
    outcome = await db.scalar(
        select(SatelliteDailyOutcome).where(
            SatelliteDailyOutcome.user_id == user.id,
            SatelliteDailyOutcome.exercise_id == sat.id,
        )
    )
    assert outcome is not None
    assert outcome.status == "pending"
    await db.execute(
        update(SatelliteDailyOutcome)
        .where(SatelliteDailyOutcome.id == outcome.id)
        .values(finalize_after=datetime(2026, 8, 2, 0, 0, tzinfo=UTC))
    )
    await db.commit()

    n = await SatelliteProgressionOrchestrator().finalize_due_outcomes(
        db, user_id=user.id, now=datetime(2026, 8, 4, 0, 0, tzinfo=UTC)
    )
    await db.commit()
    assert n == 1
    await db.refresh(progress)
    assert progress.fail_streak == 1
    assert progress.current_step_number == 2
