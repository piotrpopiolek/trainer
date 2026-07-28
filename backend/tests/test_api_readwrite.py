"""API read/write smoke + IDOR (sessions, today, catalog, progress, measurements)."""

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
from app.models.legal import LegalDocument, LegalDocumentTranslation
from app.models.user import User
from app.models.workout import WorkoutSession
from app.services.auth_session import AuthSessionService
from app.services.legal import record_legal_acceptance
from app.services.onboarding import complete_onboarding
from app.services.rate_limit import reset_memory_rate_limits


@pytest.fixture(autouse=True)
def _reset_limits() -> None:
    reset_memory_rate_limits()
    settings.rate_limit_store = "memory"
    yield
    reset_memory_rate_limits()


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine(settings.resolved_database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def api_client() -> AsyncClient:
    await dispose_engine()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        yield client
    await dispose_engine()


async def _ready_user(db: AsyncSession, email: str) -> tuple[User, str]:
    if await db.scalar(select(Program).where(Program.slug == "cc_big_six")) is None:
        pytest.skip("seed catalog required")
    doc = await db.scalar(
        select(LegalDocument).where(LegalDocument.slug == "health_disclaimer")
    )
    if doc is None:
        pytest.skip("legal seed required")
    tr = await db.scalar(
        select(LegalDocumentTranslation).where(
            LegalDocumentTranslation.document_id == doc.id,
            LegalDocumentTranslation.locale == "pl-PL",
        )
    )
    assert tr is not None
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
            "document_version": "1",
            "accepted_locale": "pl-PL",
            "accepted_content_hash": tr.content_hash.hex(),
            "accepted_at": datetime.now(UTC).isoformat(),
        },
    )
    await db.commit()
    raw = await AuthSessionService().create_session(db, user=user, user_agent="t")
    return user, raw


@pytest.mark.asyncio
async def test_catalog_cc_etag_304(api_client: AsyncClient, db: AsyncSession) -> None:
    _user, raw = await _ready_user(db, "cat@ex.com")
    res = await api_client.get(
        "/api/catalog/cc?locale=pl-PL",
        cookies={settings.session_cookie_name: raw},
    )
    assert res.status_code == 200
    assert res.json()["resolved_locale"] == "pl-PL"
    assert len(res.json()["exercises"]) == 6
    etag = res.headers["etag"]
    res2 = await api_client.get(
        "/api/catalog/cc?locale=pl-PL",
        cookies={settings.session_cookie_name: raw},
        headers={"If-None-Match": etag},
    )
    assert res2.status_code == 304


@pytest.mark.asyncio
async def test_today_and_session_create(api_client: AsyncClient, db: AsyncSession) -> None:
    _user, raw = await _ready_user(db, "today@ex.com")
    # Monday 2026-07-27 → D1 with anchor 1
    res = await api_client.get(
        "/api/today",
        params={"local_date": "2026-07-27"},
        cookies={settings.session_cookie_name: raw},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["is_rest_day"] is False
    assert body["split_day"] == 1
    assert len(body["cc_exercises"]) == 2

    push = await db.scalar(select(Exercise).where(Exercise.slug == "push_ups"))
    assert push is not None
    performed = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    create = await api_client.post(
        "/api/sessions",
        cookies={settings.session_cookie_name: raw},
        json={
            "schema_version": 1,
            "performed_at": performed.isoformat(),
            "local_date": "2026-07-27",
            "client_mutation_id": str(uuid4()),
            "logs": [
                {
                    "exercise_id": str(push.id),
                    "exercise_kind": "cc",
                    "section": "main",
                    "sets": {
                        "schema_version": 1,
                        "sets": [{"reps": 10}, {"reps": 10}, {"reps": 10}],
                    },
                }
            ],
        },
    )
    assert create.status_code == 200, create.text
    payload = create.json()
    assert payload["logs"][0]["goal_met"] is True
    assert payload["logs"][0]["counts_for_progression"] is True
    assert any(e["event_type"] == "advance" for e in payload["progression_events"])
    assert "rules_snapshot" not in payload["logs"][0]


@pytest.mark.asyncio
async def test_session_idor_404(api_client: AsyncClient, db: AsyncSession) -> None:
    owner, _raw_a = await _ready_user(db, "own-s@ex.com")
    _other, raw_b = await _ready_user(db, "oth-s@ex.com")
    session = WorkoutSession(
        id=new_uuid7(),
        user_id=owner.id,
        performed_at=datetime.now(UTC),
        local_date=date(2026, 7, 27),
        client_mutation_id=new_uuid7(),
        revision=1,
        client_updated_at=datetime.now(UTC),
    )
    db.add(session)
    await db.commit()
    res = await api_client.get(
        f"/api/sessions/{session.id}",
        cookies={settings.session_cookie_name: raw_b},
    )
    assert res.status_code == 404
    assert res.json()["error_code"] == "not_found"


@pytest.mark.idor
@pytest.mark.asyncio
async def test_progress_override_idor(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    _owner, _raw_a = await _ready_user(db, "own-p@ex.com")
    _other, raw_b = await _ready_user(db, "oth-p@ex.com")
    # Foreign UUID that is not an exercise owned/visible path — use random UUID.
    res = await api_client.post(
        f"/api/progress/{uuid4()}/override",
        cookies={settings.session_cookie_name: raw_b},
        json={"schema_version": 1, "to_step": 2},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_measurement_create_list(api_client: AsyncClient, db: AsyncSession) -> None:
    _user, raw = await _ready_user(db, "meas@ex.com")
    now = datetime.now(UTC)
    res = await api_client.post(
        "/api/measurements",
        cookies={settings.session_cookie_name: raw},
        json={
            "schema_version": 1,
            "measured_at": now.isoformat(),
            "local_date": now.date().isoformat(),
            "metrics": {"schema_version": 1, "weight_kg": 80.5},
            "client_mutation_id": str(uuid4()),
        },
    )
    assert res.status_code == 200, res.text
    mid = res.json()["id"]
    listed = await api_client.get(
        "/api/measurements",
        cookies={settings.session_cookie_name: raw},
    )
    assert listed.status_code == 200
    assert any(i["id"] == mid for i in listed.json()["items"])


@pytest.mark.asyncio
async def test_export_ndjson_not_stub(api_client: AsyncClient, db: AsyncSession) -> None:
    _user, raw = await _ready_user(db, "exp@ex.com")
    me = await api_client.get(
        "/api/auth/me", cookies={settings.session_cookie_name: raw}
    )
    csrf = me.json()["csrf_token"]
    res = await api_client.post(
        "/api/account/export",
        cookies={
            settings.session_cookie_name: raw,
            settings.csrf_cookie_name: csrf,
        },
        headers={settings.csrf_header_name: csrf},
    )
    assert res.status_code == 200
    text = res.text
    assert '"status": "stub"' not in text
    assert '"collection": "meta"' in text
    assert "done" in text


@pytest.mark.asyncio
async def test_session_create_legal_required(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    """FR-014a: online session create without disclaimer → 403 legal_required."""
    user = User(
        id=new_uuid7(),
        google_sub=f"sub-{new_uuid7()}",
        email="nolegal@ex.com",
        locale="pl-PL",
        timezone="Europe/Warsaw",
    )
    db.add(user)
    await db.commit()
    raw = await AuthSessionService().create_session(db, user=user, user_agent="t")
    performed = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    res = await api_client.post(
        "/api/sessions",
        cookies={settings.session_cookie_name: raw},
        json={
            "schema_version": 1,
            "performed_at": performed.isoformat(),
            "local_date": "2026-07-27",
            "client_mutation_id": str(uuid4()),
            "logs": [],
        },
    )
    assert res.status_code == 403
    assert res.json()["error_code"] == "legal_required"


@pytest.mark.asyncio
async def test_progress_override_success(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    """FR-038: manual override resets step via API (own CC exercise)."""
    _user, raw = await _ready_user(db, "ovr@ex.com")
    push = await db.scalar(select(Exercise).where(Exercise.slug == "push_ups"))
    assert push is not None
    res = await api_client.post(
        f"/api/progress/{push.id}/override",
        cookies={settings.session_cookie_name: raw},
        json={"schema_version": 1, "to_step": 2, "reason": "test_override"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["progress"]["exercise_id"] == str(push.id)
    assert body["progress"]["current_step_number"] == 2
    assert body["progress"]["fail_streak"] == 0
    assert body["event"]["event_type"] == "manual_override"
    assert body["event"]["to_step"] == 2


def _satellite_create_body(*, name: str = "Band rows") -> dict:
    return {
        "schema_version": 1,
        "name": name,
        "exercise_type": "B",
        "active_metrics": {"schema_version": 1, "metrics": ["reps"]},
        "schedule_kind": "daily",
        "steps": [
            {
                "step_number": 1,
                "name": "Goal",
                "rules": {
                    "schema_version": 1,
                    "goal": {"type": "reps", "sets": 3, "min_reps": 10},
                },
            }
        ],
        "client_mutation_id": str(uuid4()),
    }


@pytest.mark.idor
@pytest.mark.asyncio
async def test_satellite_create_only_visible_to_owner(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    """FR-050/005b: satellite create binds to session user; list is not leaked."""
    _owner, raw_a = await _ready_user(db, "sat-a@ex.com")
    _other, raw_b = await _ready_user(db, "sat-b@ex.com")
    created = await api_client.post(
        "/api/satellites",
        cookies={settings.session_cookie_name: raw_a},
        json=_satellite_create_body(name="Owner sat"),
    )
    assert created.status_code == 200, created.text
    sat_id = created.json()["id"]
    assert created.json()["name"] == "Owner sat"
    assert created.json()["revision"] == 1

    own_list = await api_client.get(
        "/api/satellites",
        cookies={settings.session_cookie_name: raw_a},
    )
    assert own_list.status_code == 200
    assert any(i["id"] == sat_id for i in own_list.json()["items"])

    other_list = await api_client.get(
        "/api/satellites",
        cookies={settings.session_cookie_name: raw_b},
    )
    assert other_list.status_code == 200
    assert all(i["id"] != sat_id for i in other_list.json()["items"])


@pytest.mark.idor
@pytest.mark.asyncio
async def test_progress_override_foreign_satellite_idor(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    """FR-005b: User B cannot override progress on User A's satellite."""
    _owner, raw_a = await _ready_user(db, "sat-own@ex.com")
    _other, raw_b = await _ready_user(db, "sat-oth@ex.com")
    created = await api_client.post(
        "/api/satellites",
        cookies={settings.session_cookie_name: raw_a},
        json=_satellite_create_body(name="Private sat"),
    )
    assert created.status_code == 200, created.text
    sat_id = created.json()["id"]
    res = await api_client.post(
        f"/api/progress/{sat_id}/override",
        cookies={settings.session_cookie_name: raw_b},
        json={"schema_version": 1, "to_step": 1},
    )
    assert res.status_code == 404
    assert res.json()["error_code"] == "not_found"
