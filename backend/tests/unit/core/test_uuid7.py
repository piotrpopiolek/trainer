"""UUID v7 helper, no database."""

from __future__ import annotations

import pytest

from app.core.ids import new_uuid7


@pytest.mark.asyncio
async def test_new_uuid7_is_version_7() -> None:
    assert new_uuid7().version == 7
