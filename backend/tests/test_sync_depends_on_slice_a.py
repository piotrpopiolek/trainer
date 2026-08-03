"""Slice A–C: depends_on validation, content_hash, topological sort (FR-072a/d)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.sync import SyncPushItemV1
from app.services.sync_push import content_hash, topological_sort_push_items


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


def test_content_hash_includes_canonical_depends_on() -> None:
    a = uuid4()
    b = uuid4()
    payload = {"schema_version": 1, "x": 1}
    h_empty = content_hash(payload, op="upsert", revision=1, depends_on=[])
    h_ab = content_hash(payload, op="upsert", revision=1, depends_on=[a, b])
    h_ba = content_hash(payload, op="upsert", revision=1, depends_on=[b, a])
    assert h_empty != h_ab
    assert h_ab == h_ba
    h_other = content_hash(payload, op="upsert", revision=1, depends_on=[a])
    assert h_other != h_ab


def test_topo_detects_cycle() -> None:
    a = uuid4()
    b = uuid4()
    items = [
        SyncPushItemV1(
            client_mutation_id=a,
            entity_type="workout_session",
            entity_id=uuid4(),
            depends_on=[b],
        ),
        SyncPushItemV1(
            client_mutation_id=b,
            entity_type="workout_session",
            entity_id=uuid4(),
            depends_on=[a],
        ),
    ]
    ordered, cycle = topological_sort_push_items(items)
    assert ordered == []
    assert set(cycle) == {a, b}


def test_topo_ignores_external_depends_on() -> None:
    mid = uuid4()
    items = [
        SyncPushItemV1(
            client_mutation_id=mid,
            entity_type="workout_session",
            entity_id=uuid4(),
            depends_on=[uuid4()],
        )
    ]
    ordered, cycle = topological_sort_push_items(items)
    assert [i.client_mutation_id for i in ordered] == [mid]
    assert cycle == []
