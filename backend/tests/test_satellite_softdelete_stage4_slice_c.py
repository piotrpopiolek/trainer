"""Stage 4 Slice C — soft-delete pending cancel vs finalized no-rewind."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.models.catalog import Program
from app.models.progression import ProgressionEvent, UserExerciseProgress
from app.models.satellite_progress import SatelliteDailyOutcome
from app.models.user import User
from app.models.workout import WorkoutSession
from app.schemas.api import SatelliteCreateV1, SessionCreateV1, SessionLogCreateV1
from app.schemas.sync import SyncPushItemV1, SyncPushRequestV1
from app.services.auth_session import AuthSessionService
from app.services.legal import record_legal_acceptance
from app.services.onboarding import complete_onboarding
from app.services.satellites import create_satellite
from app.services.sessions import create_session, soft_delete_user_session
from app.services.sync_push import push_batch
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


async def _log_session(
    db: AsyncSession,
    *,
    user: User,
    sat,
    local_date: date,
    hour: int,
    sets: dict,
) -> WorkoutSession:
    read = await create_session(
        db,
        user=user,
        body=SessionCreateV1(
            schema_version=1,
            performed_at=datetime(
                local_date.year, local_date.month, local_date.day, hour, 0, tzinfo=UTC
            ),
            local_date=local_date,
            client_mutation_id=new_uuid7(),
            client_timezone="Europe/Warsaw",
            logs=[
                SessionLogCreateV1(
                    exercise_id=sat.id,
                    exercise_kind="satellite",
                    section="accessories",
                    sets=sets,
                    satellite_config_version_id=sat.current_config_version_id,
                    satellite_config_hash=sat.config_hash,
                )
            ],
        ),
        commit=True,
    )
    session = await db.get(WorkoutSession, read.id)
    assert session is not None
    return session


@pytest.mark.asyncio
async def test_pending_soft_delete_cancels_when_no_attempts(db: AsyncSession) -> None:
    user = await _ready(db, "s4c-pending-cancel@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    session = await _log_session(
        db,
        user=user,
        sat=sat,
        local_date=date(2026, 8, 3),
        hour=10,
        sets=_fail_sets(),
    )
    outcome = await db.scalar(
        select(SatelliteDailyOutcome).where(
            SatelliteDailyOutcome.user_id == user.id,
            SatelliteDailyOutcome.exercise_id == sat.id,
            SatelliteDailyOutcome.local_date == date(2026, 8, 3),
        )
    )
    assert outcome is not None
    assert outcome.status == "pending"

    await soft_delete_user_session(db, user_id=user.id, session_id=session.id)

    await db.refresh(outcome)
    assert outcome.status == "cancelled"
    assert outcome.has_attempt is False
    assert outcome.has_success is False
    assert outcome.representative_log_id is None
    assert outcome.source_log_deleted_at is not None

    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == sat.id,
        )
    )
    assert progress is not None
    assert progress.current_step_number == 1


@pytest.mark.asyncio
async def test_pending_soft_delete_recomputes_with_remaining_attempt(
    db: AsyncSession,
) -> None:
    user = await _ready(db, "s4c-pending-reagg@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    first = await _log_session(
        db,
        user=user,
        sat=sat,
        local_date=date(2026, 8, 3),
        hour=9,
        sets=_fail_sets(),
    )
    second = await _log_session(
        db,
        user=user,
        sat=sat,
        local_date=date(2026, 8, 3),
        hour=11,
        sets=_fail_sets(),
    )
    outcome = await db.scalar(
        select(SatelliteDailyOutcome).where(
            SatelliteDailyOutcome.user_id == user.id,
            SatelliteDailyOutcome.exercise_id == sat.id,
            SatelliteDailyOutcome.local_date == date(2026, 8, 3),
        )
    )
    assert outcome is not None
    assert outcome.status == "pending"
    first_rep = outcome.representative_log_id

    await soft_delete_user_session(db, user_id=user.id, session_id=first.id)

    await db.refresh(outcome)
    assert outcome.status == "pending"
    assert outcome.has_attempt is True
    assert outcome.has_success is False
    assert outcome.representative_log_id is not None
    assert outcome.representative_log_id != first_rep
    # Remaining session still present.
    await db.refresh(second)
    assert second.deleted_at is None


@pytest.mark.asyncio
async def test_finalized_soft_delete_marks_source_no_rewind(db: AsyncSession) -> None:
    user = await _ready(db, "s4c-final-norewind@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    session = await _log_session(
        db,
        user=user,
        sat=sat,
        local_date=date(2026, 8, 3),
        hour=10,
        sets=_success_sets(),
    )
    outcome = await db.scalar(
        select(SatelliteDailyOutcome).where(
            SatelliteDailyOutcome.user_id == user.id,
            SatelliteDailyOutcome.exercise_id == sat.id,
            SatelliteDailyOutcome.local_date == date(2026, 8, 3),
        )
    )
    assert outcome is not None
    assert outcome.status == "finalized"
    assert outcome.result == "success"
    rep = outcome.representative_log_id

    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == sat.id,
        )
    )
    assert progress is not None
    assert progress.current_step_number == 2
    n_adv_before = await db.scalar(
        select(func.count())
        .select_from(ProgressionEvent)
        .where(
            ProgressionEvent.user_id == user.id,
            ProgressionEvent.exercise_id == sat.id,
            ProgressionEvent.event_type == "satellite_advance",
        )
    )

    await soft_delete_user_session(db, user_id=user.id, session_id=session.id)

    await db.refresh(outcome)
    await db.refresh(progress)
    assert outcome.status == "finalized"
    assert outcome.result == "success"
    assert outcome.representative_log_id == rep
    assert outcome.source_log_deleted_at is not None
    assert progress.current_step_number == 2
    n_adv_after = await db.scalar(
        select(func.count())
        .select_from(ProgressionEvent)
        .where(
            ProgressionEvent.user_id == user.id,
            ProgressionEvent.exercise_id == sat.id,
            ProgressionEvent.event_type == "satellite_advance",
        )
    )
    assert int(n_adv_after or 0) == int(n_adv_before or 0)


@pytest.mark.asyncio
async def test_soft_delete_idempotent_second_call(db: AsyncSession) -> None:
    user = await _ready(db, "s4c-idempotent@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    session = await _log_session(
        db,
        user=user,
        sat=sat,
        local_date=date(2026, 8, 3),
        hour=10,
        sets=_fail_sets(),
    )
    await soft_delete_user_session(db, user_id=user.id, session_id=session.id)
    outcome = await db.scalar(
        select(SatelliteDailyOutcome).where(
            SatelliteDailyOutcome.user_id == user.id,
            SatelliteDailyOutcome.exercise_id == sat.id,
            SatelliteDailyOutcome.local_date == date(2026, 8, 3),
        )
    )
    assert outcome is not None
    first_deleted_at = outcome.source_log_deleted_at
    assert first_deleted_at is not None

    await soft_delete_user_session(db, user_id=user.id, session_id=session.id)
    await db.refresh(outcome)
    assert outcome.status == "cancelled"
    assert outcome.source_log_deleted_at == first_deleted_at


@pytest.mark.asyncio
async def test_sync_soft_delete_pending_cancels_outcome(db: AsyncSession) -> None:
    user = await _ready(db, "s4c-sync-delete@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    session = await _log_session(
        db,
        user=user,
        sat=sat,
        local_date=date(2026, 8, 3),
        hour=10,
        sets=_fail_sets(),
    )
    del_mut = new_uuid7()
    out = await push_batch(
        db,
        user=user,
        body=SyncPushRequestV1(
            schema_version=1,
            device_id="dev-s4c",
            items=[
                SyncPushItemV1(
                    client_mutation_id=del_mut,
                    entity_type="workout_session",
                    entity_id=session.id,
                    op="delete",
                    revision=2,
                    payload=None,
                )
            ],
        ),
    )
    assert len(out.results) == 1
    assert out.results[0].status == "applied"

    outcome = await db.scalar(
        select(SatelliteDailyOutcome).where(
            SatelliteDailyOutcome.user_id == user.id,
            SatelliteDailyOutcome.exercise_id == sat.id,
            SatelliteDailyOutcome.local_date == date(2026, 8, 3),
        )
    )
    assert outcome is not None
    assert outcome.status == "cancelled"
    assert outcome.source_log_deleted_at is not None
