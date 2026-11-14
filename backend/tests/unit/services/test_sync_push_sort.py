"""FR-072a tie-break and depends_on sort without a database."""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.ids import new_uuid7
from app.schemas.sync import SyncPushItemV1
from app.services.sync_push import sort_push_items


def test_sort_push_items_tie_break_and_topo() -> None:
    """FR-072a: legal→satellite→session→measurement; depends_on overrides type order."""
    items = [
        SyncPushItemV1(
            client_mutation_id=new_uuid7(),
            entity_type="satellite",
            entity_id=new_uuid7(),
            op="upsert",
            revision=1,
            payload={},
        ),
        SyncPushItemV1(
            client_mutation_id=new_uuid7(),
            entity_type="workout_session",
            entity_id=new_uuid7(),
            op="upsert",
            revision=1,
            client_updated_at=datetime(2026, 7, 27, 12, 0, tzinfo=UTC),
            payload={"performed_at": "2026-07-27T12:00:00+00:00"},
        ),
        SyncPushItemV1(
            client_mutation_id=new_uuid7(),
            entity_type="body_measurement",
            entity_id=new_uuid7(),
            op="upsert",
            revision=1,
            payload={"measured_at": "2026-07-27T11:00:00+00:00"},
        ),
        SyncPushItemV1(
            client_mutation_id=new_uuid7(),
            entity_type="legal_acceptance",
            entity_id=new_uuid7(),
            op="upsert",
            revision=1,
            payload={"accepted_at": "2026-07-27T09:00:00+00:00"},
        ),
        SyncPushItemV1(
            client_mutation_id=new_uuid7(),
            entity_type="workout_session",
            entity_id=new_uuid7(),
            op="delete",
            revision=2,
            client_updated_at=datetime(2026, 7, 27, 11, 30, tzinfo=UTC),
        ),
    ]
    sorted_types = [i.entity_type for i in sort_push_items(items)]
    assert sorted_types == [
        "legal_acceptance",
        "satellite",
        "workout_session",
        "workout_session",
        "body_measurement",
    ]
    assert sort_push_items(items)[2].op == "delete"
    assert sort_push_items(items)[3].op == "upsert"

    meas_id = new_uuid7()
    sat_id = new_uuid7()
    reversed_edge = [
        SyncPushItemV1(
            client_mutation_id=sat_id,
            entity_type="satellite",
            entity_id=new_uuid7(),
            op="upsert",
            revision=1,
            payload={},
            depends_on=[meas_id],
        ),
        SyncPushItemV1(
            client_mutation_id=meas_id,
            entity_type="body_measurement",
            entity_id=new_uuid7(),
            op="upsert",
            revision=1,
            payload={"measured_at": "2026-07-27T11:00:00+00:00"},
        ),
    ]
    assert [i.client_mutation_id for i in sort_push_items(reversed_edge)] == [
        meas_id,
        sat_id,
    ]
