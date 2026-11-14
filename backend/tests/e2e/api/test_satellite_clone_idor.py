"""Clone satellite IDOR over ASGI."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.db.session import dispose_engine
from app.main import app
from app.services.auth_session import AuthSessionService
from app.services.rate_limit import reset_memory_rate_limits
from app.services.satellites import create_satellite
from tests.integration.services.test_satellite_clone_stage4_slice_b import (
    _ready,
    _steps_body,
)


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
    from app.models.catalog import Exercise

    row = await db.get(Exercise, source.id)
    assert row is not None
    assert row.user_id == owner.id
