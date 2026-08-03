"""Slice A contract smoke: SyncPushItemV1 depends_on defaults + validation."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.sync import SyncPushItemV1


def test_depends_on_defaults_empty_and_sorts() -> None:
    a = uuid4()
    b = uuid4()
    item = SyncPushItemV1(
        client_mutation_id=uuid4(),
        entity_type="workout_session",
        entity_id=uuid4(),
        depends_on=[b, a],
    )
    assert item.depends_on == sorted([a, b], key=str)


def test_depends_on_rejects_duplicate_and_self() -> None:
    mid = uuid4()
    with pytest.raises(ValidationError):
        SyncPushItemV1(
            client_mutation_id=mid,
            entity_type="satellite",
            entity_id=uuid4(),
            depends_on=[mid],
        )
    with pytest.raises(ValidationError):
        SyncPushItemV1(
            client_mutation_id=uuid4(),
            entity_type="satellite",
            entity_id=uuid4(),
            depends_on=[mid, mid],
        )
