"""Platform guards: CSRF, body limit, API rate limit, get_for_user (FR-005a/b/c)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.db.session import dispose_engine
from app.main import app
from app.models.body_measurement import BodyMeasurement
from app.models.user import User
from app.repositories.access import get_for_user
from app.services.auth_session import AuthSessionService
from app.services.errors import NotFoundError
from app.services.rate_limit import reset_memory_rate_limits


@pytest.fixture(autouse=True)
def _reset_limits() -> None:
    reset_memory_rate_limits()
    settings.rate_limit_store = "memory"
    settings.api_rate_limit_per_minute = 100
    settings.oauth_rate_limit_per_minute = 10
    yield
    reset_memory_rate_limits()
    settings.api_rate_limit_per_minute = 100


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


async def _session_for(db: AsyncSession, email: str) -> tuple[User, str]:
    svc = AuthSessionService()
    user = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}", email=email)
    db.add(user)
    await db.commit()
    raw = await svc.create_session(db, user=user, user_agent="t")
    return user, raw


@pytest.mark.asyncio
async def test_body_too_large_rejected(api_client: AsyncClient) -> None:
    res = await api_client.post(
        "/api/account/export",
        content=b"x",
        headers={"content-length": str(settings.max_body_bytes + 1)},
    )
    assert res.status_code == 422
    assert res.json()["error_code"] == "payload_too_large"


@pytest.mark.asyncio
async def test_export_requires_csrf(api_client: AsyncClient, db: AsyncSession) -> None:
    _user, raw = await _session_for(db, "csrf@ex.com")
    res = await api_client.post(
        "/api/account/export",
        cookies={settings.session_cookie_name: raw},
    )
    assert res.status_code == 403
    assert res.json()["error_code"] == "csrf_invalid"


@pytest.mark.asyncio
async def test_export_with_csrf_ok(api_client: AsyncClient, db: AsyncSession) -> None:
    _user, raw = await _session_for(db, "csrfok@ex.com")
    me = await api_client.get(
        "/api/auth/me",
        cookies={settings.session_cookie_name: raw},
    )
    assert me.status_code == 200
    csrf = me.json()["csrf_token"]
    assert csrf
    # httpx may not expose Set-Cookie for __Host-; send both cookies explicitly.
    res = await api_client.post(
        "/api/account/export",
        cookies={
            settings.session_cookie_name: raw,
            settings.csrf_cookie_name: csrf,
        },
        headers={settings.csrf_header_name: csrf},
    )
    assert res.status_code == 200
    assert "stub" in res.text


@pytest.mark.asyncio
async def test_schedule_patch_sets_pending_tz(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    user, raw = await _session_for(db, "tz@ex.com")
    me = await api_client.get(
        "/api/auth/me",
        cookies={settings.session_cookie_name: raw},
    )
    csrf = me.json()["csrf_token"]
    res = await api_client.patch(
        "/api/account/schedule",
        cookies={
            settings.session_cookie_name: raw,
            settings.csrf_cookie_name: csrf,
        },
        headers={settings.csrf_header_name: csrf},
        json={"schema_version": 1, "pending_timezone": "Europe/Berlin"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["pending_timezone"] == "Europe/Berlin"
    assert body["timezone_effective_on"] is not None
    await db.refresh(user)
    assert user.pending_timezone == "Europe/Berlin"


@pytest.mark.asyncio
async def test_api_rate_limit_per_user(api_client: AsyncClient, db: AsyncSession) -> None:
    settings.api_rate_limit_per_minute = 2
    _user, raw = await _session_for(db, "rl@ex.com")
    cookies = {settings.session_cookie_name: raw}
    assert (await api_client.get("/api/auth/me", cookies=cookies)).status_code == 200
    # /me uses get_current_user without API rate limit; hit measurements path instead.
    mid = new_uuid7()
    r1 = await api_client.get(f"/api/measurements/{mid}", cookies=cookies)
    r2 = await api_client.get(f"/api/measurements/{mid}", cookies=cookies)
    r3 = await api_client.get(f"/api/measurements/{mid}", cookies=cookies)
    assert r1.status_code == 404
    assert r2.status_code == 404
    assert r3.status_code == 429
    assert r3.json()["error_code"] == "rate_limited"


@pytest.mark.asyncio
async def test_get_for_user_foreign_is_not_found(db: AsyncSession) -> None:
    from sqlalchemy import text

    owner = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}", email="a@ex.com")
    other = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}", email="b@ex.com")
    db.add_all([owner, other])
    await db.commit()
    await db.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(owner.id)},
    )
    row = BodyMeasurement(
        id=new_uuid7(),
        user_id=owner.id,
        measured_at=datetime.now(UTC),
        local_date=datetime.now(UTC).date(),
        metrics={"schema_version": 1, "weight_kg": 80},
        client_mutation_id=new_uuid7(),
        revision=1,
        client_updated_at=datetime.now(UTC),
    )
    db.add(row)
    await db.commit()

    await db.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(other.id)},
    )
    with pytest.raises(NotFoundError):
        await get_for_user(db, BodyMeasurement, user_id=other.id, entity_id=row.id)

    await db.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(owner.id)},
    )
    found = await get_for_user(db, BodyMeasurement, user_id=owner.id, entity_id=row.id)
    assert found.id == row.id
