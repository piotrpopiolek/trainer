"""Stage 4 Slice A — satellite edit, topology lock, pending promote."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
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
from app.models.user import User
from app.schemas.api import SatelliteCreateV1, SessionCreateV1, SessionLogCreateV1
from app.services.auth_session import AuthSessionService
from app.services.errors import DomainError
from app.services.legal import record_legal_acceptance
from app.services.onboarding import complete_onboarding
from app.services.rate_limit import reset_memory_rate_limits
from app.services.satellites import (
    create_satellite,
    edit_satellite,
    promote_pending_satellite_configs,
)
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


def _goal_only_body(*, mutation_id, name: str = "Hip Thrust", reps: int = 10) -> SatelliteCreateV1:
    return SatelliteCreateV1.model_validate(
        {
            "schema_version": 1,
            "name": name,
            "exercise_type": "B",
            "active_metrics": {
                "schema_version": 1,
                "metrics": ["reps", "weight_kg", "sides"],
            },
            "schedule_kind": "daily",
            "progression": {"mode": "goal_only"},
            "steps": [
                {
                    "step_number": 1,
                    "step_id": str(new_uuid7()),
                    "name": "Main",
                    "rules": {
                        "schema_version": 1,
                        "goal": {
                            "type": "reps",
                            "sets": 3,
                            "min_reps": reps,
                            "require_both_sides": True,
                            "min_weight_kg": "40.000",
                        },
                    },
                }
            ],
            "client_mutation_id": str(mutation_id),
        }
    )


def _edit_body_from_read(
    sat,
    *,
    revision: int,
    name: str | None = None,
    reps: int | None = None,
) -> SatelliteCreateV1:
    step = sat.steps[0]
    rules = dict(step["rules"])
    goal = dict(rules.get("goal") or {})
    if reps is not None:
        goal["min_reps"] = reps
        rules["goal"] = goal
    return SatelliteCreateV1.model_validate(
        {
            "schema_version": 1,
            "name": name or sat.name,
            "exercise_type": sat.exercise_type,
            "active_metrics": sat.active_metrics,
            "equipment": sat.equipment,
            "tags": sat.tags,
            "schedule_kind": sat.schedule_kind,
            "weekdays": sat.weekdays,
            "schedule_category": sat.schedule_category,
            "progression": {"mode": "goal_only"},
            "steps": [
                {
                    "step_number": step["step_number"],
                    "step_id": step["step_id"],
                    "name": step.get("name"),
                    "description": step.get("description"),
                    "rules": rules,
                }
            ],
            "client_mutation_id": str(new_uuid7()),
            "config_version_id": str(new_uuid7()),
            "expected_current_config_version_id": str(sat.current_config_version_id),
        }
    )


@pytest.mark.asyncio
async def test_edit_before_history_activates_immediately(db: AsyncSession) -> None:
    user = await _ready(db, "edit-pre@ex.com")
    sat = await create_satellite(
        db, user=user, body=_goal_only_body(mutation_id=new_uuid7()), commit=True
    )
    body = _edit_body_from_read(sat, revision=2, name="HT v2", reps=12)
    read, outcome = await edit_satellite(
        db, user=user, exercise_id=sat.id, body=body, revision=2, commit=True
    )
    assert outcome.activation_applied is True
    assert outcome.pending_applied is False
    assert read.name == "HT v2"
    assert read.pending_config_version_id is None
    assert read.config_status == "current"
    assert read.revision == 2
    assert read.current_config_version_id != sat.current_config_version_id


@pytest.mark.asyncio
async def test_edit_after_history_sets_pending_until_promote(db: AsyncSession) -> None:
    user = await _ready(db, "edit-post@ex.com")
    sat = await create_satellite(
        db, user=user, body=_goal_only_body(mutation_id=new_uuid7()), commit=True
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
                    sets={
                        "schema_version": 1,
                        "sets": [
                            {"reps": 12, "weight_kg": "40.000", "sides": "left"},
                            {"reps": 12, "weight_kg": "40.000", "sides": "right"},
                        ],
                    },
                    satellite_config_version_id=sat.current_config_version_id,
                    satellite_config_hash=sat.config_hash,
                )
            ],
        ),
        commit=True,
    )
    old_current = sat.current_config_version_id
    body = _edit_body_from_read(sat, revision=2, reps=15)
    read, outcome = await edit_satellite(
        db, user=user, exercise_id=sat.id, body=body, revision=2, commit=True
    )
    assert outcome.pending_applied is True
    assert outcome.activation_applied is False
    assert read.current_config_version_id == old_current
    assert read.pending_config_version_id is not None
    assert read.config_effective_on is not None
    assert read.config_status == "pending"

    # Before effective date — still current.
    n = await promote_pending_satellite_configs(
        db, user=user, local_date=read.config_effective_on - timedelta(days=1)
    )
    await db.commit()
    assert n == 0

    n = await promote_pending_satellite_configs(
        db, user=user, local_date=read.config_effective_on
    )
    await db.commit()
    assert n == 1
    ex = await db.get(Exercise, sat.id)
    assert ex is not None
    assert ex.pending_config_version_id is None
    assert ex.current_config_version_id == read.pending_config_version_id


@pytest.mark.asyncio
async def test_edit_does_not_reinterpret_existing_or_pending_old_config_logs(
    db: AsyncSession,
) -> None:
    """Gate 4: goal-changing edit must not rewrite prior logs or old-version logs."""
    from app.models.workout import SessionExerciseLog

    user = await _ready(db, "edit-no-reinterpret@ex.com")
    sat = await create_satellite(
        db,
        user=user,
        body=_goal_only_body(mutation_id=new_uuid7(), reps=10),
        commit=True,
    )
    old_version_id = sat.current_config_version_id
    old_hash = sat.config_hash
    sets_ok_for_10 = {
        "schema_version": 1,
        "sets": [
            {"reps": 12, "weight_kg": "40.000", "sides": "left"},
            {"reps": 12, "weight_kg": "40.000", "sides": "right"},
            {"reps": 12, "weight_kg": "40.000", "sides": "left"},
            {"reps": 12, "weight_kg": "40.000", "sides": "right"},
            {"reps": 12, "weight_kg": "40.000", "sides": "left"},
            {"reps": 12, "weight_kg": "40.000", "sides": "right"},
        ],
    }
    first = await create_session(
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
                    sets=sets_ok_for_10,
                    satellite_config_version_id=old_version_id,
                    satellite_config_hash=old_hash,
                )
            ],
        ),
        commit=True,
    )
    first_log = await db.get(SessionExerciseLog, first.logs[0].id)
    assert first_log is not None
    assert first_log.goal_met is True
    assert first_log.satellite_config_version_id == old_version_id
    snap_before = dict(first_log.rules_snapshot or {})

    body = _edit_body_from_read(sat, revision=2, reps=15)
    read, outcome = await edit_satellite(
        db, user=user, exercise_id=sat.id, body=body, revision=2, commit=True
    )
    assert outcome.pending_applied is True
    pending_id = read.pending_config_version_id
    pending_hash = read.pending_config_hash
    assert pending_id is not None
    assert pending_hash is not None
    assert read.current_config_version_id == old_version_id

    await db.refresh(first_log)
    assert first_log.goal_met is True
    assert first_log.satellite_config_version_id == old_version_id
    assert first_log.rules_snapshot == snap_before

    # Pending offline-style log still referencing the pre-edit version.
    late_old = await create_session(
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
                    sets=sets_ok_for_10,
                    satellite_config_version_id=old_version_id,
                    satellite_config_hash=old_hash,
                )
            ],
        ),
        commit=True,
    )
    old_style = await db.get(SessionExerciseLog, late_old.logs[0].id)
    assert old_style is not None
    assert old_style.goal_met is True
    assert old_style.satellite_config_version_id == old_version_id
    assert old_style.progression_skipped is None

    # Same sets against pending (min_reps=15) — not active for this day.
    pending_log_session = await create_session(
        db,
        user=user,
        body=SessionCreateV1(
            schema_version=1,
            performed_at=datetime(2026, 8, 3, 19, 0, tzinfo=UTC),
            local_date=date(2026, 8, 3),
            client_mutation_id=new_uuid7(),
            client_timezone="Europe/Warsaw",
            logs=[
                SessionLogCreateV1(
                    exercise_id=sat.id,
                    exercise_kind="satellite",
                    section="accessories",
                    sets=sets_ok_for_10,
                    satellite_config_version_id=pending_id,
                    satellite_config_hash=pending_hash,
                )
            ],
        ),
        commit=True,
    )
    pending_style = await db.get(SessionExerciseLog, pending_log_session.logs[0].id)
    assert pending_style is not None
    assert pending_style.satellite_config_version_id == pending_id
    assert pending_style.progression_skipped == "config_not_active_for_day"
    # Historical goal uses pending version rules (12 < 15) — not today's current.
    assert pending_style.goal_met is False


@pytest.mark.asyncio
async def test_topology_locked_after_history(db: AsyncSession) -> None:
    user = await _ready(db, "edit-topo@ex.com")
    sat = await create_satellite(
        db, user=user, body=_goal_only_body(mutation_id=new_uuid7()), commit=True
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
                    sets={
                        "schema_version": 1,
                        "sets": [
                            {"reps": 12, "weight_kg": "40.000", "sides": "left"},
                            {"reps": 12, "weight_kg": "40.000", "sides": "right"},
                        ],
                    },
                    satellite_config_version_id=sat.current_config_version_id,
                    satellite_config_hash=sat.config_hash,
                )
            ],
        ),
        commit=True,
    )
    body = _edit_body_from_read(sat, revision=2)
    payload = body.model_dump(mode="json")
    payload["steps"][0]["step_id"] = str(new_uuid7())
    body2 = SatelliteCreateV1.model_validate(payload)
    with pytest.raises(DomainError) as exc:
        await edit_satellite(
            db, user=user, exercise_id=sat.id, body=body2, revision=2, commit=False
        )
    assert exc.value.error_code == "satellite_step_topology_locked"


@pytest.mark.asyncio
async def test_today_promotes_pending_config(db: AsyncSession) -> None:
    user = await _ready(db, "edit-today@ex.com")
    sat = await create_satellite(
        db, user=user, body=_goal_only_body(mutation_id=new_uuid7()), commit=True
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
                    sets={
                        "schema_version": 1,
                        "sets": [
                            {"reps": 12, "weight_kg": "40.000", "sides": "left"},
                            {"reps": 12, "weight_kg": "40.000", "sides": "right"},
                        ],
                    },
                    satellite_config_version_id=sat.current_config_version_id,
                    satellite_config_hash=sat.config_hash,
                )
            ],
        ),
        commit=True,
    )
    body = _edit_body_from_read(sat, revision=2, reps=14)
    read, _ = await edit_satellite(
        db, user=user, exercise_id=sat.id, body=body, revision=2, commit=True
    )
    assert read.config_effective_on is not None
    pending_id = read.pending_config_version_id
    await build_today(db, user=user, local_date=read.config_effective_on)
    ex = await db.get(Exercise, sat.id)
    assert ex is not None
    assert ex.pending_config_version_id is None
    assert ex.current_config_version_id == pending_id


@pytest.mark.idor
@pytest.mark.asyncio
async def test_patch_satellite_idor_404(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    owner = await _ready(db, "edit-idor-owner@ex.com")
    other = await _ready(db, "edit-idor-other@ex.com")
    sat = await create_satellite(
        db, user=owner, body=_goal_only_body(mutation_id=new_uuid7()), commit=True
    )
    raw = await AuthSessionService().create_session(db, user=other, user_agent="t")
    api_client.cookies.set(settings.session_cookie_name, raw)
    me = await api_client.get("/api/auth/me")
    csrf = me.json()["csrf_token"]
    body = _edit_body_from_read(sat, revision=2, name="stolen")
    payload = body.model_dump(mode="json")
    payload["revision"] = 2
    res = await api_client.patch(
        f"/api/satellites/{sat.id}",
        json=payload,
        cookies={settings.csrf_cookie_name: csrf},
        headers={settings.csrf_header_name: csrf},
    )
    assert res.status_code == 404
