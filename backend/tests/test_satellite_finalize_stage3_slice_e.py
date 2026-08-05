"""Stage 3 Slice E — lazy + cron satellite daily-outcome finalizer."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.models.catalog import Program
from app.models.progression import UserExerciseProgress
from app.models.satellite_progress import SatelliteDailyOutcome
from app.models.user import User
from app.schemas.api import SatelliteCreateV1, SessionCreateV1, SessionLogCreateV1
from app.services.auth_session import AuthSessionService
from app.services.legal import record_legal_acceptance
from app.services.onboarding import complete_onboarding
from app.services.satellite_finalize import (
    list_due_finalize_pairs,
    run_satellite_finalize_batch,
)
from app.services.satellites import create_satellite
from app.services.sessions import create_session
from app.services.today import build_today
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
                    "rules": {
                        "schema_version": 1,
                        "goal": {
                            "type": "duration",
                            "sets": 3,
                            "min_duration_sec": 20,
                            "require_both_sides": True,
                        },
                    },
                },
                {
                    "step_number": 2,
                    "step_id": str(new_uuid7()),
                    "name": "Long lever hold",
                    "rules": {
                        "schema_version": 1,
                        "goal": {
                            "type": "duration",
                            "sets": 3,
                            "min_duration_sec": 20,
                            "require_both_sides": True,
                        },
                    },
                },
                {
                    "step_number": 3,
                    "step_id": str(new_uuid7()),
                    "name": "Long lever lifted",
                    "rules": {
                        "schema_version": 1,
                        "goal": {
                            "type": "duration",
                            "sets": 3,
                            "min_duration_sec": 15,
                            "require_both_sides": True,
                        },
                    },
                },
            ],
            "client_mutation_id": str(mutation_id),
        }
    )


def _fail_sets() -> dict:
    return {
        "schema_version": 1,
        "sets": [
            {"duration_sec": 5, "sides": "left"},
            {"duration_sec": 5, "sides": "right"},
        ],
    }


async def _pending_overdue(
    db: AsyncSession,
    *,
    user: User,
    sat,
    local_date: date,
    step_number: int = 2,
) -> SatelliteDailyOutcome:
    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == sat.id,
        )
    )
    assert progress is not None
    progress.current_step_number = step_number
    progress.current_step_id = UUID(sat.steps[step_number - 1]["step_id"])
    await db.commit()

    await create_session(
        db,
        user=user,
        body=SessionCreateV1(
            schema_version=1,
            performed_at=datetime(
                local_date.year, local_date.month, local_date.day, 10, 0, tzinfo=UTC
            ),
            local_date=local_date,
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
            SatelliteDailyOutcome.local_date == local_date,
        )
    )
    assert outcome is not None
    assert outcome.status == "pending"
    await db.execute(
        update(SatelliteDailyOutcome)
        .where(SatelliteDailyOutcome.id == outcome.id)
        .values(finalize_after=datetime(2026, 1, 1, tzinfo=UTC))
    )
    await db.commit()
    await db.refresh(outcome)
    return outcome


@pytest.mark.asyncio
async def test_finalize_batch_idempotent_and_heartbeat(
    db: AsyncSession, tmp_path: Path
) -> None:
    user = await _ready(db, "finalize-batch@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    outcome = await _pending_overdue(
        db, user=user, sat=sat, local_date=date(2030, 8, 3)
    )

    now = datetime(2030, 8, 10, tzinfo=UTC)
    pairs = await list_due_finalize_pairs(db, now=now)
    assert (user.id, sat.id) in pairs

    heartbeat = tmp_path / "satellite_finalize.heartbeat"
    first = await run_satellite_finalize_batch(
        db, now=now, heartbeat_path=str(heartbeat)
    )
    assert first["fail"] == 0
    assert first["finalized"] >= 1
    assert heartbeat.is_file()

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
    assert progress.fail_streak == 1

    second = await run_satellite_finalize_batch(
        db, now=now, heartbeat_path=str(heartbeat)
    )
    assert second["fail"] == 0
    assert second["finalized"] == 0


@pytest.mark.asyncio
async def test_today_lazy_finalizes_overdue(db: AsyncSession) -> None:
    user = await _ready(db, "finalize-today@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    outcome = await _pending_overdue(
        db, user=user, sat=sat, local_date=date(2030, 8, 3)
    )

    # Freeze "now" by setting deadline far past; build_today uses real now.
    await build_today(db, user=user, local_date=date(2030, 8, 10))
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
    assert progress.fail_streak == 1

    # Durability: reopen a fresh session — finalize must survive GET /today commit.
    engine = create_async_engine(settings.resolved_database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as fresh:
        row = await fresh.get(SatelliteDailyOutcome, outcome.id)
        assert row is not None
        assert row.status == "finalized"
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_session_lazy_finalizes_prior_day(db: AsyncSession) -> None:
    user = await _ready(db, "finalize-session@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    prior = await _pending_overdue(
        db, user=user, sat=sat, local_date=date(2030, 8, 3)
    )

    await create_session(
        db,
        user=user,
        body=SessionCreateV1(
            schema_version=1,
            performed_at=datetime(2030, 8, 10, 12, 0, tzinfo=UTC),
            local_date=date(2030, 8, 10),
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
    await db.refresh(prior)
    assert prior.status == "finalized"
    assert prior.result == "failure"

    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == sat.id,
        )
    )
    assert progress is not None
    # Prior day finalized → streak 1; new day still pending (not past deadline).
    assert progress.fail_streak == 1
    today_outcome = await db.scalar(
        select(SatelliteDailyOutcome).where(
            SatelliteDailyOutcome.user_id == user.id,
            SatelliteDailyOutcome.exercise_id == sat.id,
            SatelliteDailyOutcome.local_date == date(2030, 8, 10),
        )
    )
    assert today_outcome is not None
    assert today_outcome.status == "pending"
