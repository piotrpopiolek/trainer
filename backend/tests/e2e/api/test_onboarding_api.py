"""POST /onboarding/complete over ASGI."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.db.session import dispose_engine
from app.main import app
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

@pytest.mark.asyncio
async def test_onboarding_api(api_client: AsyncClient, db: AsyncSession) -> None:
    from app.models.catalog import Program

    if await db.scalar(select(Program).where(Program.slug == "cc_big_six")) is None:
        pytest.skip("seed catalog required")

    svc = AuthSessionService()
    user = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}", email="apiob@ex.com")
    db.add(user)
    await db.commit()
    raw = await svc.create_session(db, user=user, user_agent="t")
    res = await api_client.post(
        "/api/onboarding/complete",
        cookies={settings.session_cookie_name: raw},
        json={
            "schema_version": 1,
            "questionnaire": {
                "schema_version": 1,
                "experience_level": "intermediate",
                "training_days_per_week": 3,
            },
            "anchor_weekday": 2,
            "started_on": "2026-07-27",
        },
    )
    assert res.status_code == 200
    assert res.json()["chosen_steps"]["steps"]["pull_ups"] == 3
