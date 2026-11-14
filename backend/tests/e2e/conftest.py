"""ASGI client for health checks. Other e2e modules keep their own api_client."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import dispose_engine
from app.main import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    await dispose_engine()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await dispose_engine()
