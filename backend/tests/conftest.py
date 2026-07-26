from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

import app.models  # noqa: F401 — register ORM metadata for coverage / mappers
from app.db.session import dispose_engine, get_session_factory
from app.main import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    await dispose_engine()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await dispose_engine()


@pytest.fixture
async def db_session() -> AsyncIterator:
    await dispose_engine()
    async with get_session_factory()() as session:
        yield session
    await dispose_engine()
