from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

import app.models  # noqa: F401 — register ORM metadata for coverage / mappers
from app.db.session import SessionLocal
from app.main import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def db_session() -> AsyncIterator:
    async with SessionLocal() as session:
        yield session
