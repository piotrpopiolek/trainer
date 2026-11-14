"""HTTP soft-delete and progress list. User setup stays in the service suite."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.db.session import dispose_engine
from app.main import app
from app.models.workout import WorkoutSession
from app.services.rate_limit import reset_memory_rate_limits
from tests.integration.services.test_api_coverage_boost import _ready_user


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
async def test_session_soft_delete_and_progress_list(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    user, raw = await _ready_user(db, "sess-del@ex.com")
    session = WorkoutSession(
        id=new_uuid7(),
        user_id=user.id,
        performed_at=datetime(2026, 7, 27, 10, 0, tzinfo=UTC),
        local_date=date(2026, 7, 27),
        client_mutation_id=new_uuid7(),
        revision=1,
        client_updated_at=datetime.now(UTC),
    )
    db.add(session)
    await db.commit()

    deleted = await api_client.delete(
        f"/api/sessions/{session.id}",
        cookies={settings.session_cookie_name: raw},
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_at"] is not None

    progress = await api_client.get(
        "/api/progress",
        cookies={settings.session_cookie_name: raw},
    )
    assert progress.status_code == 200
    assert len(progress.json()["items"]) >= 6

    detail = await api_client.get(
        f"/api/sessions/{session.id}",
        cookies={settings.session_cookie_name: raw},
    )
    assert detail.status_code == 200
