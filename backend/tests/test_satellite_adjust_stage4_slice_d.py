"""Stage 4 Slice D — satellite manual override + rebuild + delete hints."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.models.catalog import Program
from app.models.progression import UserExerciseProgress
from app.models.satellite_progress import SatelliteDailyOutcome
from app.models.user import User
from app.schemas.api import (
    ProgressOverrideRequestV1,
    SatelliteCreateV1,
    SessionCreateV1,
    SessionLogCreateV1,
)
from app.services.auth_session import AuthSessionService
from app.services.errors import DomainError
from app.services.legal import record_legal_acceptance
from app.services.onboarding import complete_onboarding
from app.services.progression import ProgressionEngine
from app.services.satellite_progression import SatelliteProgressionOrchestrator
from app.services.satellites import create_satellite
from app.services.sessions import create_session, soft_delete_user_session
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


@pytest.mark.asyncio
async def test_soft_delete_returns_adjust_hint_for_finalized(db: AsyncSession) -> None:
    user = await _ready(db, "s4d-hint@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    session = await create_session(
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
                    sets=_success_sets(),
                    satellite_config_version_id=sat.current_config_version_id,
                    satellite_config_hash=sat.config_hash,
                )
            ],
        ),
        commit=True,
    )
    deleted = await soft_delete_user_session(
        db, user_id=user.id, session_id=session.id
    )
    assert len(deleted.soft_delete_outcome_hints) == 1
    hint = deleted.soft_delete_outcome_hints[0]
    assert hint.exercise_id == sat.id
    assert hint.status == "finalized"
    outcome = await db.get(SatelliteDailyOutcome, hint.related_outcome_id)
    assert outcome is not None
    assert outcome.source_log_deleted_at is not None


@pytest.mark.asyncio
async def test_satellite_manual_override_with_related_outcome(
    db: AsyncSession,
) -> None:
    user = await _ready(db, "s4d-override@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    session = await create_session(
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
                    sets=_success_sets(),
                    satellite_config_version_id=sat.current_config_version_id,
                    satellite_config_hash=sat.config_hash,
                )
            ],
        ),
        commit=True,
    )
    deleted = await soft_delete_user_session(
        db, user_id=user.id, session_id=session.id
    )
    related = deleted.soft_delete_outcome_hints[0].related_outcome_id

    engine = ProgressionEngine()
    ev = await engine.manual_override(
        db,
        user_id=user.id,
        exercise_id=sat.id,
        to_step=1,
        reason="delete_adjust",
        related_outcome_id=related,
    )
    await db.commit()

    assert ev.event_type == "satellite_manual_override"
    assert ev.related_outcome_id == related
    assert ev.from_step == 2
    assert ev.to_step == 1

    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == sat.id,
        )
    )
    assert progress is not None
    assert progress.current_step_number == 1
    assert progress.current_step_id == UUID(str(sat.steps[0]["step_id"]))
    assert progress.fail_streak == 0

    outcome = await db.get(SatelliteDailyOutcome, related)
    assert outcome is not None
    assert outcome.status == "finalized"
    assert outcome.result == "success"


@pytest.mark.asyncio
async def test_rebuild_matches_cache_after_override(db: AsyncSession) -> None:
    user = await _ready(db, "s4d-rebuild@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
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
                    sets=_success_sets(),
                    satellite_config_version_id=sat.current_config_version_id,
                    satellite_config_hash=sat.config_hash,
                )
            ],
        ),
        commit=True,
    )
    orch = SatelliteProgressionOrchestrator()
    await orch.manual_override(
        db,
        user_id=user.id,
        exercise_id=sat.id,
        to_step=1,
        commit=True,
    )
    step, step_id, streak = await orch.rebuild_satellite_progress(
        db, user_id=user.id, exercise_id=sat.id, apply=False
    )
    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == sat.id,
        )
    )
    assert progress is not None
    assert step == progress.current_step_number == 1
    assert step_id == progress.current_step_id
    assert streak == progress.fail_streak == 0


@pytest.mark.asyncio
async def test_override_rejects_foreign_related_outcome(db: AsyncSession) -> None:
    user = await _ready(db, "s4d-idor@ex.com")
    other = await _ready(db, "s4d-idor-other@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    other_sat = await create_satellite(
        db, user=other, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    session = await create_session(
        db,
        user=other,
        body=SessionCreateV1(
            schema_version=1,
            performed_at=datetime(2026, 8, 3, 10, 0, tzinfo=UTC),
            local_date=date(2026, 8, 3),
            client_mutation_id=new_uuid7(),
            client_timezone="Europe/Warsaw",
            logs=[
                SessionLogCreateV1(
                    exercise_id=other_sat.id,
                    exercise_kind="satellite",
                    section="accessories",
                    sets=_success_sets(),
                    satellite_config_version_id=other_sat.current_config_version_id,
                    satellite_config_hash=other_sat.config_hash,
                )
            ],
        ),
        commit=True,
    )
    deleted = await soft_delete_user_session(
        db, user_id=other.id, session_id=session.id
    )
    foreign_outcome = deleted.soft_delete_outcome_hints[0].related_outcome_id

    engine = ProgressionEngine()
    with pytest.raises(DomainError) as ei:
        await engine.manual_override(
            db,
            user_id=user.id,
            exercise_id=sat.id,
            to_step=2,
            related_outcome_id=foreign_outcome,
        )
    assert ei.value.error_code == "related_outcome_not_found"


@pytest.mark.asyncio
async def test_progress_override_request_accepts_related_outcome() -> None:
    body = ProgressOverrideRequestV1.model_validate(
        {
            "schema_version": 1,
            "to_step": 2,
            "related_outcome_id": str(new_uuid7()),
        }
    )
    assert body.to_step == 2
    assert body.related_outcome_id is not None


@pytest.mark.asyncio
async def test_dispatcher_cc_rejects_related_outcome(db: AsyncSession) -> None:
    user = await _ready(db, "s4d-cc-related@ex.com")
    from app.models.catalog import Exercise

    cc = await db.scalar(
        select(Exercise).where(Exercise.kind == "cc", Exercise.user_id.is_(None)).limit(1)
    )
    if cc is None:
        pytest.skip("seed catalog required")
    engine = ProgressionEngine()
    with pytest.raises(DomainError) as ei:
        await engine.manual_override(
            db,
            user_id=user.id,
            exercise_id=cc.id,
            to_step=1,
            related_outcome_id=new_uuid7(),
        )
    assert ei.value.error_code == "related_outcome_cc_unsupported"
