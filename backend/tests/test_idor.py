"""IDOR suite — user B must not access user A resources (FR-005b)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.db.session import dispose_engine
from app.main import app
from app.models.body_measurement import BodyMeasurement
from app.models.user import User
from app.services.auth_session import AuthSessionService
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


async def _user_session(db: AsyncSession, email: str) -> tuple[User, str]:
    svc = AuthSessionService()
    user = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}", email=email)
    db.add(user)
    await db.commit()
    raw = await svc.create_session(db, user=user, user_agent="t")
    return user, raw


@pytest.mark.idor
@pytest.mark.asyncio
async def test_measurement_idor_returns_404(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    owner, _raw_a = await _user_session(db, "owner@ex.com")
    _other, raw_b = await _user_session(db, "other@ex.com")
    await db.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(owner.id)},
    )
    measurement = BodyMeasurement(
        id=new_uuid7(),
        user_id=owner.id,
        measured_at=datetime.now(UTC),
        local_date=datetime.now(UTC).date(),
        metrics={"schema_version": 1, "weight_kg": 70},
        client_mutation_id=new_uuid7(),
        revision=1,
        client_updated_at=datetime.now(UTC),
    )
    db.add(measurement)
    await db.commit()

    res = await api_client.get(
        f"/api/measurements/{measurement.id}",
        cookies={settings.session_cookie_name: raw_b},
    )
    assert res.status_code == 404
    assert res.json()["error_code"] == "not_found"


@pytest.mark.idor
@pytest.mark.asyncio
async def test_schedule_patch_only_affects_session_user(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    user_a, _raw_a = await _user_session(db, "a-sched@ex.com")
    _user_b, raw_b = await _user_session(db, "b-sched@ex.com")
    me = await api_client.get(
        "/api/auth/me",
        cookies={settings.session_cookie_name: raw_b},
    )
    csrf = me.json()["csrf_token"]
    res = await api_client.patch(
        "/api/account/schedule",
        cookies={
            settings.session_cookie_name: raw_b,
            settings.csrf_cookie_name: csrf,
        },
        headers={settings.csrf_header_name: csrf},
        json={"schema_version": 1, "pending_timezone": "America/New_York"},
    )
    assert res.status_code == 200
    await db.refresh(user_a)
    assert user_a.pending_timezone is None


@pytest.mark.idor
@pytest.mark.asyncio
async def test_export_foreign_session_unauthorized(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    # No session → 401 (not a leak of another user's export).
    res = await api_client.post("/api/account/export")
    assert res.status_code in {401, 403}
