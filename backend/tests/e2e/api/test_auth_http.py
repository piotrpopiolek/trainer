"""Auth HTTP: me, logout, OAuth start/callback, rate limit."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.db.session import dispose_engine
from app.main import app
from app.models.user import User
from app.services.auth_session import AuthSessionService
from app.services.oauth_google import GoogleOAuthService


@pytest.fixture(autouse=True)
def _reset_rate_limits() -> None:
    from app.services.rate_limit import reset_memory_rate_limits

    reset_memory_rate_limits()
    settings.oauth_rate_limit_per_minute = 10
    settings.rate_limit_store = "memory"
    yield
    reset_memory_rate_limits()
    settings.oauth_rate_limit_per_minute = 10

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

@pytest.mark.asyncio
async def test_me_requires_session(api_client: AsyncClient) -> None:
    res = await api_client.get("/api/auth/me")
    assert res.status_code == 401
    assert res.json()["error_code"] == "unauthorized"

@pytest.mark.asyncio
async def test_me_with_session_cookie(api_client: AsyncClient, db: AsyncSession) -> None:
    svc = AuthSessionService()
    user = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}", email="me@ex.com")
    db.add(user)
    await db.commit()
    raw = await svc.create_session(db, user=user, user_agent="test")
    res = await api_client.get(
        "/api/auth/me",
        cookies={settings.session_cookie_name: raw},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["schema_version"] == 1
    assert body["email"] == "me@ex.com"

@pytest.mark.asyncio
async def test_logout_revokes_current(api_client: AsyncClient, db: AsyncSession) -> None:
    svc = AuthSessionService()
    user = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}", email="out@ex.com")
    db.add(user)
    await db.commit()
    raw = await svc.create_session(db, user=user, user_agent="test")
    res = await api_client.post(
        "/api/auth/logout",
        cookies={settings.session_cookie_name: raw},
    )
    assert res.status_code == 200
    me = await api_client.get(
        "/api/auth/me",
        cookies={settings.session_cookie_name: raw},
    )
    assert me.status_code == 401

@pytest.mark.asyncio
async def test_logout_all_revokes_other_sessions(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    svc = AuthSessionService()
    user = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}", email="all@ex.com")
    db.add(user)
    await db.commit()
    raw_a = await svc.create_session(db, user=user, user_agent="a")
    raw_b = await svc.create_session(db, user=user, user_agent="b")

    res = await api_client.post(
        "/api/auth/logout-all",
        cookies={settings.session_cookie_name: raw_a},
    )
    assert res.status_code == 200

    for raw in (raw_a, raw_b):
        me = await api_client.get(
            "/api/auth/me",
            cookies={settings.session_cookie_name: raw},
        )
        assert me.status_code == 401

@pytest.mark.asyncio
async def test_google_start_requires_config(api_client: AsyncClient) -> None:
    settings.google_client_id = ""
    settings.google_client_secret = ""
    res = await api_client.get("/api/auth/google/start", follow_redirects=False)
    assert res.status_code == 503
    assert res.json()["error_code"] == "oauth_not_configured"

@pytest.mark.asyncio
async def test_oauth_callback_rejects_missing_state_cookie(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    settings.google_client_id = "test-client"
    settings.google_client_secret = "test-secret"
    oauth = GoogleOAuthService()
    _url, state = await oauth.start(db)
    res = await api_client.get(
        "/api/auth/google/callback",
        params={"code": "fake-code", "state": state},
        follow_redirects=False,
    )
    assert res.status_code == 302
    assert "oauth_state_invalid" in res.headers["location"]

@pytest.mark.asyncio
async def test_oauth_callback_rejects_mismatched_state_cookie(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    settings.google_client_id = "test-client"
    settings.google_client_secret = "test-secret"
    oauth = GoogleOAuthService()
    _url, state = await oauth.start(db)
    res = await api_client.get(
        "/api/auth/google/callback",
        params={"code": "fake-code", "state": state},
        cookies={settings.oauth_state_cookie_name: "other-state"},
        follow_redirects=False,
    )
    assert res.status_code == 302
    assert "oauth_state_invalid" in res.headers["location"]

@pytest.mark.asyncio
async def test_oauth_start_sets_state_cookie(api_client: AsyncClient) -> None:
    from app.services.rate_limit import reset_memory_rate_limits

    reset_memory_rate_limits()
    settings.google_client_id = "test-client"
    settings.google_client_secret = "test-secret"
    settings.rate_limit_store = "memory"
    res = await api_client.get("/api/auth/google/start", follow_redirects=False)
    assert res.status_code == 302
    assert settings.oauth_state_cookie_name in res.cookies
    cookie_state = res.cookies[settings.oauth_state_cookie_name]
    assert f"state={cookie_state}" in res.headers["location"]

@pytest.mark.asyncio
async def test_oauth_rate_limit_returns_429(api_client: AsyncClient) -> None:
    from app.services.rate_limit import reset_memory_rate_limits

    reset_memory_rate_limits()
    settings.google_client_id = "test-client"
    settings.google_client_secret = "test-secret"
    settings.rate_limit_store = "memory"
    settings.oauth_rate_limit_per_minute = 3
    try:
        for _ in range(3):
            res = await api_client.get("/api/auth/google/start", follow_redirects=False)
            assert res.status_code == 302
        limited = await api_client.get("/api/auth/google/start", follow_redirects=False)
        assert limited.status_code == 429
        assert limited.json()["error_code"] == "rate_limited"
        assert "Retry-After" in limited.headers
    finally:
        settings.oauth_rate_limit_per_minute = 10
        reset_memory_rate_limits()
