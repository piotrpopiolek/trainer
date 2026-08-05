"""Stage 3 Slice C — satellite_advance on daily success (+1, last step caps)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.domain.satellite_progression import fold_daily_outcome
from app.models.catalog import Program
from app.models.progression import ProgressionEvent, UserExerciseProgress
from app.models.satellite_progress import SatelliteDailyOutcome
from app.models.user import User
from app.schemas.api import SatelliteCreateV1, SessionCreateV1, SessionLogCreateV1
from app.services.auth_session import AuthSessionService
from app.services.legal import record_legal_acceptance
from app.services.onboarding import complete_onboarding
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


def _success_sets(*, min_duration: int = 20) -> dict:
    return {
        "schema_version": 1,
        "sets": [
            {"duration_sec": min_duration, "sides": "left"},
            {"duration_sec": min_duration, "sides": "right"},
            {"duration_sec": min_duration, "sides": "left"},
            {"duration_sec": min_duration, "sides": "right"},
            {"duration_sec": min_duration, "sides": "left"},
            {"duration_sec": min_duration, "sides": "right"},
        ],
    }


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


@pytest.mark.asyncio
async def test_two_successes_same_day_one_advance_event(db: AsyncSession) -> None:
    user = await _ready(db, "advance-once@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    for hour in (10, 18):
        await create_session(
            db,
            user=user,
            body=SessionCreateV1(
                schema_version=1,
                performed_at=datetime(2026, 8, 3, hour, 0, tzinfo=UTC),
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

    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == sat.id,
        )
    )
    assert progress is not None
    assert progress.current_step_number == 2

    n_adv = await db.scalar(
        select(func.count())
        .select_from(ProgressionEvent)
        .where(
            ProgressionEvent.user_id == user.id,
            ProgressionEvent.exercise_id == sat.id,
            ProgressionEvent.event_type == "satellite_advance",
        )
    )
    assert int(n_adv or 0) == 1

    outcomes = await db.scalar(
        select(func.count())
        .select_from(SatelliteDailyOutcome)
        .where(
            SatelliteDailyOutcome.user_id == user.id,
            SatelliteDailyOutcome.exercise_id == sat.id,
        )
    )
    assert int(outcomes or 0) == 1


@pytest.mark.asyncio
async def test_fail_then_success_same_day_advances_once(db: AsyncSession) -> None:
    user = await _ready(db, "advance-fail-ok@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    fail_sets = {
        "schema_version": 1,
        "sets": [
            {"duration_sec": 5, "sides": "left"},
            {"duration_sec": 5, "sides": "right"},
        ],
    }
    await create_session(
        db,
        user=user,
        body=SessionCreateV1(
            schema_version=1,
            performed_at=datetime(2030, 8, 3, 9, 0, tzinfo=UTC),
            local_date=date(2030, 8, 3),
            client_mutation_id=new_uuid7(),
            client_timezone="Europe/Warsaw",
            logs=[
                SessionLogCreateV1(
                    exercise_id=sat.id,
                    exercise_kind="satellite",
                    section="accessories",
                    sets=fail_sets,
                    satellite_config_version_id=sat.current_config_version_id,
                    satellite_config_hash=sat.config_hash,
                )
            ],
        ),
        commit=True,
    )
    await create_session(
        db,
        user=user,
        body=SessionCreateV1(
            schema_version=1,
            performed_at=datetime(2030, 8, 3, 16, 0, tzinfo=UTC),
            local_date=date(2030, 8, 3),
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
    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == sat.id,
        )
    )
    assert progress is not None
    assert progress.current_step_number == 2
    n_adv = await db.scalar(
        select(func.count())
        .select_from(ProgressionEvent)
        .where(
            ProgressionEvent.user_id == user.id,
            ProgressionEvent.exercise_id == sat.id,
            ProgressionEvent.event_type == "satellite_advance",
        )
    )
    assert int(n_adv or 0) == 1
    outcome = await db.scalar(
        select(SatelliteDailyOutcome).where(
            SatelliteDailyOutcome.user_id == user.id,
            SatelliteDailyOutcome.exercise_id == sat.id,
            SatelliteDailyOutcome.local_date == date(2030, 8, 3),
        )
    )
    assert outcome is not None
    assert outcome.status == "finalized"
    assert outcome.result == "success"


@pytest.mark.asyncio
async def test_last_step_success_no_advance(db: AsyncSession) -> None:
    user = await _ready(db, "advance-cap@ex.com")
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
    step3 = UUID(sat.steps[2]["step_id"])
    progress.current_step_number = 3
    progress.current_step_id = step3
    await db.commit()

    read = await create_session(
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
                    sets=_success_sets(min_duration=15),
                    satellite_config_version_id=sat.current_config_version_id,
                    satellite_config_hash=sat.config_hash,
                )
            ],
        ),
        commit=True,
    )
    assert read.logs[0].goal_met is True
    await db.refresh(progress)
    assert progress.current_step_number == 3
    assert progress.current_step_id == step3

    n_adv = await db.scalar(
        select(func.count())
        .select_from(ProgressionEvent)
        .where(
            ProgressionEvent.user_id == user.id,
            ProgressionEvent.event_type == "satellite_advance",
        )
    )
    assert int(n_adv or 0) == 0
