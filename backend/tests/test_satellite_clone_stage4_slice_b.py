"""Stage 4 Slice B — satellite clone with fresh step/config IDs (FR-054)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.db.session import dispose_engine
from app.main import app
from app.models.catalog import Exercise, Program
from app.models.progression import UserExerciseProgress
from app.models.user import User
from app.schemas.api import SatelliteCloneV1, SatelliteCreateV1
from app.services.auth_session import AuthSessionService
from app.services.errors import DomainError
from app.services.legal import record_legal_acceptance
from app.services.onboarding import complete_onboarding
from app.services.rate_limit import reset_memory_rate_limits
from app.services.satellites import clone_satellite, create_satellite, edit_satellite
from tests.legal_fixtures import latest_health_disclaimer


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine(settings.resolved_database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def _reset_limits() -> None:
    reset_memory_rate_limits()
    settings.rate_limit_store = "memory"
    yield
    reset_memory_rate_limits()


@pytest.fixture
async def api_client() -> AsyncClient:
    await dispose_engine()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        yield client
    await dispose_engine()


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


def _steps_body(*, mutation_id) -> SatelliteCreateV1:
    s1, s2 = new_uuid7(), new_uuid7()
    return SatelliteCreateV1.model_validate(
        {
            "schema_version": 1,
            "name": "Copenhagen",
            "exercise_type": "B",
            "active_metrics": {
                "schema_version": 1,
                "metrics": ["duration_sec", "sides"],
            },
            "schedule_kind": "daily",
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
                    "step_id": str(s1),
                    "name": "Short",
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
                    "step_id": str(s2),
                    "name": "Long",
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
            ],
            "client_mutation_id": str(mutation_id),
        }
    )


@pytest.mark.asyncio
async def test_clone_gets_fresh_step_ids_and_lineage(db: AsyncSession) -> None:
    user = await _ready(db, "clone-lineage@ex.com")
    source = await create_satellite(
        db, user=user, body=_steps_body(mutation_id=new_uuid7()), commit=True
    )
    source_step_ids = {s["step_id"] for s in source.steps}

    cloned = await clone_satellite(
        db,
        user=user,
        source_exercise_id=source.id,
        body=SatelliteCloneV1(
            schema_version=1,
            client_mutation_id=new_uuid7(),
            name="Copenhagen v2",
        ),
        commit=True,
    )
    assert cloned.id != source.id
    assert cloned.cloned_from_exercise_id == source.id
    assert cloned.name == "Copenhagen v2"
    assert cloned.revision == 1
    assert cloned.pending_config_version_id is None
    clone_step_ids = {s["step_id"] for s in cloned.steps}
    assert clone_step_ids.isdisjoint(source_step_ids)
    assert cloned.current_config_version_id != source.current_config_version_id

    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == cloned.id,
        )
    )
    assert progress is not None
    assert progress.current_step_number == 1
    assert str(progress.current_step_id) in clone_step_ids


@pytest.mark.asyncio
async def test_clone_edit_does_not_mutate_source(db: AsyncSession) -> None:
    user = await _ready(db, "clone-isolate@ex.com")
    source = await create_satellite(
        db, user=user, body=_steps_body(mutation_id=new_uuid7()), commit=True
    )
    cloned = await clone_satellite(
        db,
        user=user,
        source_exercise_id=source.id,
        body=SatelliteCloneV1(schema_version=1, client_mutation_id=new_uuid7()),
        commit=True,
    )
    edit_payload = SatelliteCreateV1.model_validate(
        {
            "schema_version": 1,
            "name": "Cloned renamed",
            "exercise_type": cloned.exercise_type,
            "active_metrics": cloned.active_metrics,
            "schedule_kind": cloned.schedule_kind,
            "progression": {
                "mode": "steps",
                "regression": {
                    "mode": "suggest_after_failed_days",
                    "threshold": 2,
                },
            },
            "steps": [
                {
                    "step_number": s["step_number"],
                    "step_id": s["step_id"],
                    "name": s.get("name"),
                    "rules": s["rules"],
                }
                for s in cloned.steps
            ],
            "client_mutation_id": str(new_uuid7()),
            "config_version_id": str(new_uuid7()),
            "expected_current_config_version_id": str(cloned.current_config_version_id),
        }
    )
    await edit_satellite(
        db,
        user=user,
        exercise_id=cloned.id,
        body=edit_payload,
        revision=2,
        commit=True,
    )
    src = await db.get(Exercise, source.id)
    assert src is not None
    assert src.name == "Copenhagen"
    assert src.revision == 1


@pytest.mark.asyncio
async def test_clone_limit_reached(db: AsyncSession) -> None:
    user = await _ready(db, "clone-limit@ex.com")
    for i in range(10):
        await create_satellite(
            db,
            user=user,
            body=SatelliteCreateV1.model_validate(
                {
                    "schema_version": 1,
                    "name": f"S{i}",
                    "exercise_type": "C",
                    "active_metrics": {"schema_version": 1, "metrics": []},
                    "schedule_kind": "daily",
                    "progression": {"mode": "goal_only"},
                    "steps": [
                        {
                            "step_number": 1,
                            "step_id": str(new_uuid7()),
                            "name": "Done",
                            "rules": {
                                "schema_version": 1,
                                "goal": {"type": "completed"},
                            },
                        }
                    ],
                    "client_mutation_id": str(new_uuid7()),
                }
            ),
            commit=True,
        )
    source_id = (
        await db.scalars(
            select(Exercise.id).where(
                Exercise.user_id == user.id, Exercise.kind == "satellite"
            )
        )
    ).first()
    assert source_id is not None
    with pytest.raises(DomainError) as exc:
        await clone_satellite(
            db,
            user=user,
            source_exercise_id=source_id,
            body=SatelliteCloneV1(schema_version=1, client_mutation_id=new_uuid7()),
            commit=False,
        )
    assert exc.value.error_code == "satellite_limit_reached"


@pytest.mark.idor
@pytest.mark.asyncio
async def test_clone_idor_404(api_client: AsyncClient, db: AsyncSession) -> None:
    owner = await _ready(db, "clone-idor-owner@ex.com")
    other = await _ready(db, "clone-idor-other@ex.com")
    source = await create_satellite(
        db, user=owner, body=_steps_body(mutation_id=new_uuid7()), commit=True
    )
    raw = await AuthSessionService().create_session(db, user=other, user_agent="t")
    api_client.cookies.set(settings.session_cookie_name, raw)
    res = await api_client.post(
        f"/api/satellites/{source.id}/clone",
        json={"schema_version": 1, "client_mutation_id": str(new_uuid7())},
    )
    assert res.status_code == 404
