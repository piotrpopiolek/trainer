"""Dependency resolver without a claim or a database."""

from __future__ import annotations

from uuid import uuid4

from app.schemas.sync import SyncPushItemResultV1, SyncPushItemV1
from app.services.sync_push import resolve_item_dependencies


def test_resolve_item_dependencies_pure() -> None:
    mid = uuid4()
    dep = uuid4()
    item = SyncPushItemV1(
        client_mutation_id=mid,
        entity_type="workout_session",
        entity_id=uuid4(),
        depends_on=[dep],
    )
    assert (
        resolve_item_dependencies(
            item, fulfilled={dep}, batch_ids=set(), result_by_id={}
        )
        is None
    )

    missing = resolve_item_dependencies(
        item, fulfilled=set(), batch_ids=set(), result_by_id={}
    )
    assert isinstance(missing, SyncPushItemResultV1)
    assert missing.error_code == "dependency_missing"
    assert missing.dependency_failed_mutation_id == dep

    assert (
        resolve_item_dependencies(
            item, fulfilled=set(), batch_ids={dep}, result_by_id={}
        )
        == "defer"
    )

    failed = resolve_item_dependencies(
        item,
        fulfilled=set(),
        batch_ids={dep},
        result_by_id={
            dep: SyncPushItemResultV1(
                client_mutation_id=dep,
                status="rejected",
                error_code="schema_invalid",
            )
        },
    )
    assert isinstance(failed, SyncPushItemResultV1)
    assert failed.error_code == "dependency_failed"
