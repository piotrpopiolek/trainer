"""Slice F: applied_detached on lost config activation CAS (FR-072d / FR-073)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.models.catalog import (
    Exercise,
    Program,
    SatelliteConfigActivation,
    SatelliteConfigVersion,
)
from app.models.sync import ClientMutation, SyncConflictLog
from app.models.user import User
from app.schemas.api import SatelliteCreateV1, SessionCreateV1, SessionLogCreateV1
from app.schemas.sync import SyncPushItemV1, SyncPushRequestV1
from app.services.auth_session import AuthSessionService
from app.services.legal import record_legal_acceptance
from app.services.onboarding import complete_onboarding
from app.services.satellites import create_satellite, register_satellite_config_version
from app.services.sessions import create_session
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


def _type_c_body(
    *,
    mutation_id,
    config_version_id=None,
    expected_current=None,
    step_id=None,
    name: str = "Mobility",
) -> SatelliteCreateV1:
    return SatelliteCreateV1.model_validate(
        {
            "schema_version": 1,
            "name": name,
            "exercise_type": "C",
            "active_metrics": {"schema_version": 1, "metrics": []},
            "schedule_kind": "daily",
            "config_version_id": str(config_version_id) if config_version_id else None,
            "expected_current_config_version_id": (
                str(expected_current) if expected_current else None
            ),
            "steps": [
                {
                    "step_number": 1,
                    "step_id": str(step_id or new_uuid7()),
                    "name": name,
                    "rules": {
                        "schema_version": 1,
                        "goal": {"type": "completed"},
                    },
                }
            ],
            "client_mutation_id": str(mutation_id),
        }
    )


@pytest.mark.asyncio
async def test_lost_activation_cas_returns_detached(db: AsyncSession) -> None:
    user = await _ready(db, "detached-cas@ex.com")
    sat = await create_satellite(
        db, user=user, body=_type_c_body(mutation_id=new_uuid7(), name="Base"), commit=True
    )
    v1 = sat.current_config_version_id
    assert v1 is not None

    # Winning registration moves current to V2.
    v2 = new_uuid7()
    ex = await db.get(Exercise, sat.id)
    assert ex is not None
    win = await register_satellite_config_version(
        db,
        user=user,
        exercise=ex,
        body=_type_c_body(
            mutation_id=new_uuid7(),
            config_version_id=v2,
            expected_current=v1,
            name="Winner",
        ),
        effective_from=date(2026, 8, 1),
    )
    await db.commit()
    assert win.activation_applied is True
    assert win.config_version_id == v2

    # Stale CAS base (still expects V1) → version registered, activation lost.
    v3 = new_uuid7()
    await db.refresh(ex)
    lost = await register_satellite_config_version(
        db,
        user=user,
        exercise=ex,
        body=_type_c_body(
            mutation_id=new_uuid7(),
            config_version_id=v3,
            expected_current=v1,
            name="Loser",
        ),
        effective_from=date(2026, 8, 2),
    )
    await db.commit()
    assert lost.activation_applied is False
    assert lost.config_version_id == v3

    stored = await db.get(SatelliteConfigVersion, v3)
    assert stored is not None
    act = await db.scalar(
        select(SatelliteConfigActivation).where(
            SatelliteConfigActivation.config_version_id == v3
        )
    )
    assert act is None
    await db.refresh(ex)
    assert ex.current_config_version_id == v2


@pytest.mark.asyncio
async def test_sync_applied_detached_claim_and_conflict(db: AsyncSession) -> None:
    user = await _ready(db, "detached-sync@ex.com")
    user_id = user.id
    sat = await create_satellite(
        db, user=user, body=_type_c_body(mutation_id=new_uuid7(), name="SyncBase"), commit=True
    )
    v1 = sat.current_config_version_id
    assert v1 is not None

    ex = await db.get(Exercise, sat.id)
    assert ex is not None
    v2 = new_uuid7()
    await register_satellite_config_version(
        db,
        user=user,
        exercise=ex,
        body=_type_c_body(
            mutation_id=new_uuid7(),
            config_version_id=v2,
            expected_current=v1,
            name="SyncWinner",
        ),
        effective_from=date(2026, 8, 1),
    )
    await db.commit()

    v3 = new_uuid7()
    mut = new_uuid7()
    body = _type_c_body(
        mutation_id=mut,
        config_version_id=v3,
        expected_current=v1,
        name="SyncLoser",
    )
    out = await push_batch(
        db,
        user=user,
        body=SyncPushRequestV1(
            schema_version=1,
            items=[
                SyncPushItemV1(
                    client_mutation_id=mut,
                    entity_type="satellite",
                    entity_id=sat.id,
                    op="upsert",
                    revision=2,
                    payload=body.model_dump(mode="json"),
                )
            ],
        ),
    )
    assert len(out.results) == 1
    result = out.results[0]
    assert result.status == "applied_detached"
    assert result.activation_applied is False
    assert result.registered_config_version_id == v3
    assert result.conflict_id is not None
    conflict_id = result.conflict_id

    await db.rollback()
    claim = await db.scalar(
        select(ClientMutation).where(
            ClientMutation.user_id == user_id,
            ClientMutation.client_mutation_id == mut,
        )
    )
    assert claim is not None
    assert claim.result_status == "applied_detached"
    conflict = await db.get(SyncConflictLog, conflict_id)
    assert conflict is not None
    assert conflict.conflict_kind == "satellite_config_activation_lost"


@pytest.mark.asyncio
async def test_applied_detached_fulfills_session_depends_on(db: AsyncSession) -> None:
    """Detached config registration still satisfies depends_on (FR-072d)."""
    user = await _ready(db, "detached-deps@ex.com")
    user_id = user.id
    sat = await create_satellite(
        db, user=user, body=_type_c_body(mutation_id=new_uuid7(), name="DepBase"), commit=True
    )
    sat_id = sat.id
    v1 = sat.current_config_version_id
    assert v1 is not None

    ex = await db.get(Exercise, sat_id)
    assert ex is not None
    v2 = new_uuid7()
    await register_satellite_config_version(
        db,
        user=user,
        exercise=ex,
        body=_type_c_body(
            mutation_id=new_uuid7(),
            config_version_id=v2,
            expected_current=v1,
            name="DepWinner",
        ),
        effective_from=date(2026, 8, 1),
    )
    await db.commit()

    v3 = new_uuid7()
    sat_mut = new_uuid7()
    body = _type_c_body(
        mutation_id=sat_mut,
        config_version_id=v3,
        expected_current=v1,
        name="DepLoser",
    )
    first = await push_batch(
        db,
        user=user,
        body=SyncPushRequestV1(
            schema_version=1,
            items=[
                SyncPushItemV1(
                    client_mutation_id=sat_mut,
                    entity_type="satellite",
                    entity_id=sat_id,
                    op="upsert",
                    revision=2,
                    payload=body.model_dump(mode="json"),
                )
            ],
        ),
    )
    assert first.results[0].status == "applied_detached"

    await db.rollback()
    user = await db.get(User, user_id)
    assert user is not None
    stored = await db.get(SatelliteConfigVersion, v3)
    assert stored is not None
    hash_hex = stored.config_hash.hex()
    sess_mut = new_uuid7()
    second = await push_batch(
        db,
        user=user,
        body=SyncPushRequestV1(
            schema_version=1,
            items=[
                SyncPushItemV1(
                    client_mutation_id=sess_mut,
                    entity_type="workout_session",
                    entity_id=new_uuid7(),
                    depends_on=[sat_mut],
                    payload={
                        "schema_version": 1,
                        "performed_at": datetime(2026, 8, 3, 10, 0, tzinfo=UTC).isoformat(),
                        "local_date": "2026-08-03",
                        "client_mutation_id": str(sess_mut),
                        "client_timezone": "Europe/Warsaw",
                        "logs": [
                            {
                                "exercise_id": str(sat_id),
                                "exercise_kind": "satellite",
                                "section": "accessories",
                                "sets": {
                                    "schema_version": 1,
                                    "completed": True,
                                    "sets": [],
                                },
                                "satellite_config_version_id": str(v3),
                                "satellite_config_hash": hash_hex,
                            }
                        ],
                    },
                )
            ],
        ),
    )
    result = second.results[0]
    assert result.error_code not in {
        "dependency_missing",
        "dependency_failed",
        "dependency_cycle",
    }
    assert result.status == "applied"


@pytest.mark.asyncio
async def test_log_on_detached_version_skips_progression(db: AsyncSession) -> None:
    user = await _ready(db, "detached-log@ex.com")
    sat = await create_satellite(
        db, user=user, body=_type_c_body(mutation_id=new_uuid7(), name="LogBase"), commit=True
    )
    v1 = sat.current_config_version_id
    assert v1 is not None

    ex = await db.get(Exercise, sat.id)
    assert ex is not None
    v2 = new_uuid7()
    await register_satellite_config_version(
        db,
        user=user,
        exercise=ex,
        body=_type_c_body(
            mutation_id=new_uuid7(),
            config_version_id=v2,
            expected_current=v1,
            name="LogWinner",
        ),
        effective_from=date(2026, 8, 1),
    )
    await db.commit()

    v3 = new_uuid7()
    lost = await register_satellite_config_version(
        db,
        user=user,
        exercise=ex,
        body=_type_c_body(
            mutation_id=new_uuid7(),
            config_version_id=v3,
            expected_current=v1,
            name="LogDetached",
        ),
    )
    await db.commit()
    assert lost.activation_applied is False

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
                    sets={"schema_version": 1, "completed": True, "sets": []},
                    satellite_config_version_id=v3,
                    satellite_config_hash=lost.config_hash_hex,
                )
            ],
        ),
        commit=True,
    )
    log = read.logs[0]
    assert log.goal_met is True
    assert log.counts_for_progression is False
    assert log.progression_skipped == "config_not_active_for_day"


@pytest.mark.asyncio
async def test_register_refreshes_exercise_step_rules_for_list(db: AsyncSession) -> None:
    """Successful config activation must update ExerciseStep so list matches document."""
    from app.models.catalog import ExerciseStep
    from app.services.satellites import list_satellites

    user = await _ready(db, "register-steps@ex.com")
    create_body = SatelliteCreateV1.model_validate(
        {
            "schema_version": 1,
            "name": "Hip thrust",
            "exercise_type": "B",
            "active_metrics": {"schema_version": 1, "metrics": ["reps"]},
            "schedule_kind": "daily",
            "steps": [
                {
                    "step_number": 1,
                    "name": "Base",
                    "rules": {
                        "schema_version": 1,
                        "goal": {"type": "reps", "sets": 3, "min_reps": 10},
                    },
                }
            ],
            "client_mutation_id": str(new_uuid7()),
        }
    )
    sat = await create_satellite(db, user=user, body=create_body, commit=True)
    v1 = sat.current_config_version_id
    assert v1 is not None
    before = await list_satellites(db, user_id=user.id)
    assert before[0].steps[0]["rules"]["goal"]["min_reps"] == 10

    ex = await db.get(Exercise, sat.id)
    assert ex is not None
    body = SatelliteCreateV1.model_validate(
        {
            "schema_version": 1,
            "name": "Hip thrust",
            "exercise_type": "B",
            "active_metrics": {"schema_version": 1, "metrics": ["reps"]},
            "schedule_kind": "daily",
            "expected_current_config_version_id": str(v1),
            "steps": [
                {
                    "step_number": 1,
                    "name": "Updated",
                    "rules": {
                        "schema_version": 1,
                        "goal": {"type": "reps", "sets": 3, "min_reps": 12},
                    },
                }
            ],
            "client_mutation_id": str(new_uuid7()),
        }
    )
    win = await register_satellite_config_version(
        db, user=user, exercise=ex, body=body, effective_from=date(2026, 8, 1)
    )
    await db.commit()
    assert win.activation_applied is True

    step = await db.scalar(
        select(ExerciseStep).where(
            ExerciseStep.exercise_id == sat.id, ExerciseStep.step_number == 1
        )
    )
    assert step is not None
    assert step.rules["goal"]["min_reps"] == 12

    listed = await list_satellites(db, user_id=user.id)
    assert listed[0].steps[0]["rules"]["goal"]["min_reps"] == 12
