"""Sync push/pull happy-path + IDOR (FR-072*/075)."""

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
from app.models.workout import WorkoutSession
from app.services.auth_session import AuthSessionService
from app.services.legal import record_legal_acceptance
from app.services.onboarding import complete_onboarding
from app.services.rate_limit import reset_memory_rate_limits
from tests.legal_fixtures import latest_health_disclaimer


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
    raw = await AuthSessionService().create_session(db, user=user, user_agent="t")
    return user, raw


@pytest.mark.asyncio
async def test_sync_push_session_and_pull(api_client: AsyncClient, db: AsyncSession) -> None:
    _user, raw = await _ready_user(db, "sync1@ex.com")
    push_id = new_uuid7()
    session_id = new_uuid7()
    push_ex = await db.scalar(select(Exercise).where(Exercise.slug == "push_ups"))
    assert push_ex is not None
    performed = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    push_body = {
        "schema_version": 1,
        "device_id": "dev-1",
        "items": [
            {
                "client_mutation_id": str(push_id),
                "entity_type": "workout_session",
                "entity_id": str(session_id),
                "op": "upsert",
                "revision": 1,
                "payload": {
                    "schema_version": 1,
                    "performed_at": performed.isoformat(),
                    "local_date": "2026-07-27",
                    "client_mutation_id": str(push_id),
                    "logs": [
                        {
                            "exercise_id": str(push_ex.id),
                            "exercise_kind": "cc",
                            "section": "main",
                            "sets": {
                                "schema_version": 1,
                                "sets": [{"reps": 10}, {"reps": 10}, {"reps": 10}],
                            },
                        }
                    ],
                },
            }
        ],
    }
    res = await api_client.post(
        "/api/sync/push",
        cookies={settings.session_cookie_name: raw},
        json=push_body,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["results"][0]["status"] == "applied", body
    assert body["results"][0]["client_mutation_id"] == str(push_id)

    res2 = await api_client.post(
        "/api/sync/push",
        cookies={settings.session_cookie_name: raw},
        json=push_body,
    )
    assert res2.json()["results"][0]["status"] == "idempotent", res2.json()

    pull = await api_client.get(
        "/api/sync/pull",
        cookies={settings.session_cookie_name: raw},
    )
    assert pull.status_code == 200
    assert pull.json()["server_time"]
    assert any(s["id"] == str(session_id) for s in pull.json()["sessions"])
    assert len(pull.json()["progress"]) >= 6


@pytest.mark.asyncio
async def test_sync_push_batch_too_large(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    _user, raw = await _ready_user(db, "sync-big@ex.com")
    items = [
        {
            "client_mutation_id": str(uuid4()),
            "entity_type": "body_measurement",
            "entity_id": str(uuid4()),
            "op": "upsert",
            "revision": 1,
            "payload": {
                "schema_version": 1,
                "measured_at": datetime.now(UTC).isoformat(),
                "local_date": date.today().isoformat(),
                "metrics": {"schema_version": 1, "weight_kg": 70},
                "client_mutation_id": str(uuid4()),
            },
        }
        for _ in range(21)
    ]
    res = await api_client.post(
        "/api/sync/push",
        cookies={settings.session_cookie_name: raw},
        json={"schema_version": 1, "items": items},
    )
    assert res.status_code == 422
    assert res.json()["error_code"] == "batch_too_large"


@pytest.mark.idor
@pytest.mark.asyncio
async def test_sync_push_foreign_session_not_found(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    owner, _raw_a = await _ready_user(db, "sync-a@ex.com")
    _other, raw_b = await _ready_user(db, "sync-b@ex.com")
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
    res = await api_client.post(
        "/api/sync/push",
        cookies={settings.session_cookie_name: raw_b},
        json={
            "schema_version": 1,
            "items": [
                {
                    "client_mutation_id": str(uuid4()),
                    "entity_type": "workout_session",
                    "entity_id": str(session.id),
                    "op": "delete",
                    "revision": 1,
                    "payload": None,
                }
            ],
        },
    )
    assert res.status_code == 200
    assert res.json()["results"][0]["status"] == "rejected"
    assert res.json()["results"][0]["error_code"] == "not_found"


@pytest.mark.asyncio
async def test_sync_pull_stale_since_resync(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    _user, raw = await _ready_user(db, "sync-resync@ex.com")
    stale = (datetime.now(UTC) - timedelta(days=40)).isoformat()
    res = await api_client.get(
        "/api/sync/pull",
        params={"since": stale},
        cookies={settings.session_cookie_name: raw},
    )
    assert res.status_code == 200
    assert res.json()["resync_required"] is True


@pytest.mark.asyncio
async def test_sync_push_measurement_and_pull_delta(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    _user, raw = await _ready_user(db, "sync-meas@ex.com")
    mid = new_uuid7()
    mut = uuid4()
    measured = datetime.now(UTC)
    push = await api_client.post(
        "/api/sync/push",
        cookies={settings.session_cookie_name: raw},
        json={
            "schema_version": 1,
            "device_id": "dev-m",
            "items": [
                {
                    "client_mutation_id": str(mut),
                    "entity_type": "body_measurement",
                    "entity_id": str(mid),
                    "op": "upsert",
                    "revision": 1,
                    "payload": {
                        "schema_version": 1,
                        "measured_at": measured.isoformat(),
                        "local_date": measured.date().isoformat(),
                        "metrics": {"schema_version": 1, "weight_kg": 77.5},
                        "client_mutation_id": str(mut),
                    },
                }
            ],
        },
    )
    assert push.status_code == 200, push.text
    assert push.json()["results"][0]["status"] == "applied"

    before = datetime.now(UTC) - timedelta(seconds=5)
    pull1 = await api_client.get(
        "/api/sync/pull",
        params={"since": before.isoformat(), "device_id": "dev-m"},
        cookies={settings.session_cookie_name: raw},
    )
    assert pull1.status_code == 200
    assert pull1.json()["resync_required"] is False
    assert any(m["id"] == str(mid) for m in pull1.json()["measurements"])

    del_mut = uuid4()
    deleted = await api_client.post(
        "/api/sync/push",
        cookies={settings.session_cookie_name: raw},
        json={
            "schema_version": 1,
            "items": [
                {
                    "client_mutation_id": str(del_mut),
                    "entity_type": "body_measurement",
                    "entity_id": str(mid),
                    "op": "delete",
                    "revision": 2,
                    "payload": None,
                }
            ],
        },
    )
    assert deleted.json()["results"][0]["status"] == "applied"

    pull2 = await api_client.get(
        "/api/sync/pull",
        params={"since": before.isoformat()},
        cookies={settings.session_cookie_name: raw},
    )
    assert pull2.status_code == 200
    tombs = pull2.json()["tombstones"]
    assert any(
        t["entity_type"] == "body_measurement" and t["id"] == str(mid) for t in tombs
    )


@pytest.mark.asyncio
async def test_sync_push_mutation_payload_mismatch(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    _user, raw = await _ready_user(db, "sync-mismatch@ex.com")
    mid = new_uuid7()
    mut = uuid4()
    measured = datetime.now(UTC)
    base_item = {
        "client_mutation_id": str(mut),
        "entity_type": "body_measurement",
        "entity_id": str(mid),
        "op": "upsert",
        "revision": 1,
        "payload": {
            "schema_version": 1,
            "measured_at": measured.isoformat(),
            "local_date": measured.date().isoformat(),
            "metrics": {"schema_version": 1, "weight_kg": 70},
            "client_mutation_id": str(mut),
        },
    }
    first = await api_client.post(
        "/api/sync/push",
        cookies={settings.session_cookie_name: raw},
        json={"schema_version": 1, "items": [base_item]},
    )
    assert first.json()["results"][0]["status"] == "applied"
    mismatch = {
        **base_item,
        "payload": {
            **base_item["payload"],
            "metrics": {"schema_version": 1, "weight_kg": 99},
        },
    }
    second = await api_client.post(
        "/api/sync/push",
        cookies={settings.session_cookie_name: raw},
        json={"schema_version": 1, "items": [mismatch]},
    )
    assert second.json()["results"][0]["status"] == "rejected"
    assert second.json()["results"][0]["error_code"] == "mutation_payload_mismatch"
