"""Override request schema accepts related_outcome_id."""

from __future__ import annotations

import pytest

from app.core.ids import new_uuid7
from app.schemas.api import ProgressOverrideRequestV1


@pytest.mark.asyncio
async def test_progress_override_request_accepts_related_outcome() -> None:
    body = ProgressOverrideRequestV1.model_validate(
        {
            "schema_version": 1,
            "to_step": 2,
            "related_outcome_id": str(new_uuid7()),
        }
    )
    assert body.to_step == 2
    assert body.related_outcome_id is not None
