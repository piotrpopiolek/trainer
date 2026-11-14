"""Optional direct session. Most integration modules own a per-file db fixture."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from app.db.session import dispose_engine, get_session_factory


@pytest.fixture
async def db_session() -> AsyncIterator:
    await dispose_engine()
    async with get_session_factory()() as session:
        yield session
    await dispose_engine()
