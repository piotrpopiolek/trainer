"""POST /sync/push orchestration (FR-072a/c/d, FR-073, FR-035, FR-014a)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_uuid7
from app.models.body_measurement import BodyMeasurement
from app.models.catalog import Exercise
from app.models.progression import ProgressionEvent, UserExerciseProgress
from app.models.sync import ClientMutation, SyncConflictLog, SyncDevice
from app.models.user import User
from app.models.workout import WorkoutSession
from app.schemas.api import (
    MeasurementCreateV1,
    SatelliteCreateV1,
    SessionCreateV1,
)
from app.schemas.sync import (
    SyncPushItemResultV1,
    SyncPushItemV1,
    SyncPushRequestV1,
    SyncPushResponseV1,
)
from app.services import satellites as satellite_service
from app.services import sessions as session_service
from app.services.errors import DomainError, LegalRequiredError, NotFoundError
from app.services.legal import record_legal_acceptance
from app.services.measurements import soft_delete_measurement
from app.services.satellite_progression import SatelliteProgressionOrchestrator
from app.services.sessions import progress_to_read

_TYPE_ORDER = {
    "legal_acceptance": 0,
    "satellite": 1,
    "satellite_regression_decision": 2,
    "workout_session": 3,
    "body_measurement": 4,
}
_OP_ORDER = {"delete": 0, "upsert": 1}
MAX_BATCH = 20

_SUCCESS_DEP_STATUSES = frozenset({"applied", "applied_detached", "idempotent"})
_FAILED_DEP_STATUSES = frozenset(
    {
        "rejected",
        "conflict_lost",
        "conflict_tie",
        "session_immutable_after_evaluate",
    }
)


def _item_ts(item: SyncPushItemV1) -> datetime:
    if item.client_updated_at is not None:
        return item.client_updated_at
    payload = item.payload or {}
    for key in ("performed_at", "measured_at", "accepted_at", "client_updated_at"):
        raw = payload.get(key)
        if isinstance(raw, str):
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                pass
        if isinstance(raw, datetime):
            return raw
    return datetime.min.replace(tzinfo=UTC)


def _tie_key(item: SyncPushItemV1) -> tuple[int, int, datetime, str, str]:
    return (
        _TYPE_ORDER.get(item.entity_type, 99),
        _OP_ORDER.get(item.op, 99),
        _item_ts(item),
        str(item.entity_id),
        str(item.client_mutation_id),
    )


def topological_sort_push_items(
    items: list[SyncPushItemV1],
) -> tuple[list[SyncPushItemV1], list[UUID]]:
    """Stable Kahn sort over depends_on; returns (ordered DAG, cycle mutation IDs).

    Edges to mutation IDs absent from the batch are ignored (satisfied via DB later).
    """
    by_id = {it.client_mutation_id: it for it in items}
    indegree: dict[UUID, int] = {mid: 0 for mid in by_id}
    dependents: dict[UUID, list[UUID]] = {mid: [] for mid in by_id}

    for item in items:
        for dep in item.depends_on:
            if dep not in by_id or dep == item.client_mutation_id:
                continue
            indegree[item.client_mutation_id] += 1
            dependents[dep].append(item.client_mutation_id)

    ready = sorted(
        (it for it in items if indegree[it.client_mutation_id] == 0),
        key=_tie_key,
    )
    ordered: list[SyncPushItemV1] = []
    while ready:
        nxt = ready.pop(0)
        ordered.append(nxt)
        for child_id in dependents[nxt.client_mutation_id]:
            indegree[child_id] -= 1
            if indegree[child_id] == 0:
                ready.append(by_id[child_id])
                ready.sort(key=_tie_key)

    cycle_ids = sorted(
        (mid for mid, deg in indegree.items() if deg > 0),
        key=str,
    )
    return ordered, cycle_ids


def sort_push_items(items: list[SyncPushItemV1]) -> list[SyncPushItemV1]:
    """FR-072a: topo over depends_on; tie-break legal→satellite→session→measurement."""
    ordered, _cycle = topological_sort_push_items(items)
    return ordered


def content_hash(
    payload: dict[str, Any] | None,
    *,
    op: str,
    revision: int,
    depends_on: list[UUID] | None = None,
) -> str:
    """Hash op+revision+payload+canonical depends_on (FR-072d)."""
    deps = sorted(str(u) for u in (depends_on or []))
    blob = json.dumps(
        {
            "depends_on": deps,
            "op": op,
            "payload": payload or {},
            "revision": revision,
        },
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def resolve_item_dependencies(
    item: SyncPushItemV1,
    *,
    fulfilled: set[UUID],
    batch_ids: set[UUID],
    result_by_id: dict[UUID, SyncPushItemResultV1],
) -> SyncPushItemResultV1 | Literal["defer"] | None:
    """Return reject result, ``\"defer\"`` (no claim), or ``None`` when ready to claim."""
    for dep in item.depends_on:
        if dep in fulfilled:
            continue
        prior = result_by_id.get(dep)
        if prior is not None:
            if prior.status in _SUCCESS_DEP_STATUSES:
                fulfilled.add(dep)
                continue
            if prior.status in _FAILED_DEP_STATUSES:
                return SyncPushItemResultV1(
                    client_mutation_id=item.client_mutation_id,
                    status="rejected",
                    error_code="dependency_failed",
                    dependency_failed_mutation_id=dep,
                )
            return SyncPushItemResultV1(
                client_mutation_id=item.client_mutation_id,
                status="rejected",
                error_code="dependency_failed",
                dependency_failed_mutation_id=dep,
            )
        if dep in batch_ids:
            # Prereq in this batch but not yet terminal (deferred upstream).
            return "defer"
        return SyncPushItemResultV1(
            client_mutation_id=item.client_mutation_id,
            status="rejected",
            error_code="dependency_missing",
            dependency_failed_mutation_id=dep,
        )
    return None


async def _load_fulfilled_mutation_ids(
    db: AsyncSession,
    *,
    user_id: UUID,
    mutation_ids: set[UUID],
) -> set[UUID]:
    if not mutation_ids:
        return set()
    rows = await db.scalars(
        select(ClientMutation.client_mutation_id).where(
            ClientMutation.user_id == user_id,
            ClientMutation.client_mutation_id.in_(mutation_ids),
            ClientMutation.result_status.in_(("applied", "applied_detached")),
        )
    )
    return set(rows.all())


async def _claim(
    db: AsyncSession,
    *,
    user_id: UUID,
    item: SyncPushItemV1,
    digest: str,
) -> SyncPushItemResultV1 | None:
    """INSERT claim; return idempotent/mismatch result or None if claimed fresh."""
    row = ClientMutation(
        id=new_uuid7(),
        user_id=user_id,
        client_mutation_id=item.client_mutation_id,
        entity_type=item.entity_type,
        entity_id=item.entity_id,
        depends_on={
            "schema_version": 1,
            "mutation_ids": [str(u) for u in item.depends_on],
        },
        content_hash=digest,
        result_status="applied",
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        existing = await db.scalar(
            select(ClientMutation).where(
                ClientMutation.user_id == user_id,
                ClientMutation.client_mutation_id == item.client_mutation_id,
            )
        )
        if existing is None:
            raise
        if existing.content_hash == digest:
            return SyncPushItemResultV1(
                client_mutation_id=item.client_mutation_id,
                status="idempotent",
            )
        return SyncPushItemResultV1(
            client_mutation_id=item.client_mutation_id,
            status="rejected",
            error_code="mutation_payload_mismatch",
        )
    return None


async def _touch_device(
    db: AsyncSession,
    *,
    user_id: UUID,
    device_id: str | None,
) -> None:
    if not device_id:
        return
    now = datetime.now(UTC)
    row = await db.scalar(
        select(SyncDevice).where(
            SyncDevice.user_id == user_id,
            SyncDevice.device_id == device_id,
        )
    )
    if row is None:
        db.add(
            SyncDevice(
                id=new_uuid7(),
                user_id=user_id,
                device_id=device_id,
                last_push_at=now,
            )
        )
    else:
        row.last_push_at = now
    await db.flush()


async def _log_conflict(
    db: AsyncSession,
    *,
    user_id: UUID,
    item: SyncPushItemV1,
    kind: str,
    winning_revision: int,
    winning_updated_at: datetime,
    device_id: str | None,
) -> UUID:
    cid = new_uuid7()
    db.add(
        SyncConflictLog(
            id=cid,
            user_id=user_id,
            entity_type=item.entity_type,
            entity_id=item.entity_id,
            winning_revision=winning_revision,
            losing_revision=item.revision,
            winning_updated_at=winning_updated_at,
            conflict_kind=kind,
            losing_payload={
                "schema_version": 1,
                "payload": item.payload or {},
                "op": item.op,
                "revision": item.revision,
            },
            device_id=device_id,
        )
    )
    await db.flush()
    return cid


async def _apply_session_upsert(
    db: AsyncSession,
    *,
    user: User,
    item: SyncPushItemV1,
) -> SyncPushItemResultV1:
    existing = await db.scalar(
        select(WorkoutSession).where(
            WorkoutSession.id == item.entity_id,
            WorkoutSession.user_id == user.id,
        )
    )
    if existing is not None:
        if item.revision < existing.revision:
            cid = await _log_conflict(
                db,
                user_id=user.id,
                item=item,
                kind="lost_push",
                winning_revision=existing.revision,
                winning_updated_at=existing.updated_at,
                device_id=None,
            )
            return SyncPushItemResultV1(
                client_mutation_id=item.client_mutation_id,
                status="conflict_lost",
                conflict_id=cid,
                winning_revision=existing.revision,
                winning_updated_at=existing.updated_at,
            )
        if item.revision == existing.revision:
            cid = await _log_conflict(
                db,
                user_id=user.id,
                item=item,
                kind="tie_revision",
                winning_revision=existing.revision,
                winning_updated_at=existing.updated_at,
                device_id=None,
            )
            return SyncPushItemResultV1(
                client_mutation_id=item.client_mutation_id,
                status="conflict_tie",
                conflict_id=cid,
                winning_revision=existing.revision,
                winning_updated_at=existing.updated_at,
            )
        if item.revision > existing.revision + 1:
            return SyncPushItemResultV1(
                client_mutation_id=item.client_mutation_id,
                status="rejected",
                error_code="revision_jump",
            )
        # revision == existing + 1 → check immutability (FR-038)
        payload = item.payload or {}
        if "performed_at" in payload or "local_date" in payload:
            from app.services.session_rules import assert_dates_unchanged

            try:
                performed = existing.performed_at
                local = existing.local_date
                if "performed_at" in payload:
                    performed = datetime.fromisoformat(
                        str(payload["performed_at"]).replace("Z", "+00:00")
                    )
                if "local_date" in payload:
                    from datetime import date as date_cls

                    local = date_cls.fromisoformat(str(payload["local_date"]))
                assert_dates_unchanged(
                    existing, performed_at=performed, local_date=local
                )
            except DomainError as exc:
                cid = await _log_conflict(
                    db,
                    user_id=user.id,
                    item=item,
                    kind="session_date_immutable",
                    winning_revision=existing.revision,
                    winning_updated_at=existing.updated_at,
                    device_id=None,
                )
                return SyncPushItemResultV1(
                    client_mutation_id=item.client_mutation_id,
                    status="rejected",
                    error_code=exc.error_code,
                    conflict_id=cid,
                    winning_revision=existing.revision,
                    winning_updated_at=existing.updated_at,
                )
        from app.services.session_rules import assert_mutable_for_content_update

        try:
            await assert_mutable_for_content_update(db, existing)
        except DomainError:
            cid = await _log_conflict(
                db,
                user_id=user.id,
                item=item,
                kind="session_immutable_after_evaluate",
                winning_revision=existing.revision,
                winning_updated_at=existing.updated_at,
                device_id=None,
            )
            return SyncPushItemResultV1(
                client_mutation_id=item.client_mutation_id,
                status="session_immutable_after_evaluate",
                error_code="session_immutable_after_evaluate",
                conflict_id=cid,
                winning_revision=existing.revision,
                winning_updated_at=existing.updated_at,
            )
        return SyncPushItemResultV1(
            client_mutation_id=item.client_mutation_id,
            status="rejected",
            error_code="session_update_unsupported",
        )

    if item.revision != 1:
        return SyncPushItemResultV1(
            client_mutation_id=item.client_mutation_id,
            status="rejected",
            error_code="revision_jump",
        )
    if not item.payload:
        raise DomainError("payload_required", http_status=422)
    body = SessionCreateV1.model_validate(
        {**item.payload, "client_mutation_id": str(item.client_mutation_id)}
    )
    # Force client_mutation_id UUID from item
    body = body.model_copy(update={"client_mutation_id": item.client_mutation_id})
    try:
        read = await session_service.create_session(
            db, user=user, body=body, session_id=item.entity_id, commit=False
        )
    except LegalRequiredError:
        return SyncPushItemResultV1(
            client_mutation_id=item.client_mutation_id,
            status="rejected",
            error_code="legal_required",
        )
    except IntegrityError:
        return SyncPushItemResultV1(
            client_mutation_id=item.client_mutation_id,
            status="rejected",
            error_code="not_found",
        )
    skipped = None
    if read.logs:
        # Surface late_log if any log did not count
        for log in read.logs:
            if not log.counts_for_progression and not log.skipped and log.goal_evaluated_at:
                skipped = "late_log"
                break
    return SyncPushItemResultV1(
        client_mutation_id=item.client_mutation_id,
        status="applied",
        progression_skipped=skipped,
        winning_revision=read.revision,
        winning_updated_at=datetime.now(UTC),
    )


async def _apply_session_delete(
    db: AsyncSession,
    *,
    user: User,
    item: SyncPushItemV1,
) -> SyncPushItemResultV1:
    existing = await db.scalar(
        select(WorkoutSession).where(
            WorkoutSession.id == item.entity_id,
            WorkoutSession.user_id == user.id,
        )
    )
    if existing is None:
        return SyncPushItemResultV1(
            client_mutation_id=item.client_mutation_id,
            status="rejected",
            error_code="not_found",
        )
    if existing.deleted_at is not None:
        return SyncPushItemResultV1(
            client_mutation_id=item.client_mutation_id,
            status="idempotent",
            winning_revision=existing.revision,
            winning_updated_at=existing.deleted_at,
        )
    if item.revision != existing.revision + 1:
        if item.revision <= existing.revision:
            status = (
                "conflict_lost" if item.revision < existing.revision else "conflict_tie"
            )
            kind = "lost_push" if item.revision < existing.revision else "tie_revision"
            cid = await _log_conflict(
                db,
                user_id=user.id,
                item=item,
                kind=kind,
                winning_revision=existing.revision,
                winning_updated_at=existing.updated_at,
                device_id=None,
            )
            return SyncPushItemResultV1(
                client_mutation_id=item.client_mutation_id,
                status=status,  # type: ignore[arg-type]
                conflict_id=cid,
                winning_revision=existing.revision,
                winning_updated_at=existing.updated_at,
            )
        return SyncPushItemResultV1(
            client_mutation_id=item.client_mutation_id,
            status="rejected",
            error_code="revision_jump",
        )
    try:
        read = await session_service.soft_delete_user_session(
            db,
            user_id=user.id,
            session_id=item.entity_id,
            commit=False,
            revision=item.revision,
        )
    except NotFoundError:
        return SyncPushItemResultV1(
            client_mutation_id=item.client_mutation_id,
            status="rejected",
            error_code="not_found",
        )
    return SyncPushItemResultV1(
        client_mutation_id=item.client_mutation_id,
        status="applied",
        winning_revision=read.revision,
        winning_updated_at=read.deleted_at or datetime.now(UTC),
    )


async def _apply_measurement_upsert(
    db: AsyncSession,
    *,
    user: User,
    item: SyncPushItemV1,
) -> SyncPushItemResultV1:
    from sqlalchemy import text

    await db.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(user.id)},
    )
    existing = await db.scalar(
        select(BodyMeasurement).where(
            BodyMeasurement.id == item.entity_id,
            BodyMeasurement.user_id == user.id,
        )
    )
    if existing is not None:
        if item.revision != existing.revision + 1:
            if item.revision <= existing.revision:
                status = "conflict_lost" if item.revision < existing.revision else "conflict_tie"
                kind = "lost_push" if item.revision < existing.revision else "tie_revision"
                cid = await _log_conflict(
                    db,
                    user_id=user.id,
                    item=item,
                    kind=kind,
                    winning_revision=existing.revision,
                    winning_updated_at=existing.updated_at,
                    device_id=None,
                )
                return SyncPushItemResultV1(
                    client_mutation_id=item.client_mutation_id,
                    status=status,  # type: ignore[arg-type]
                    conflict_id=cid,
                    winning_revision=existing.revision,
                    winning_updated_at=existing.updated_at,
                )
            return SyncPushItemResultV1(
                client_mutation_id=item.client_mutation_id,
                status="rejected",
                error_code="revision_jump",
            )
        return SyncPushItemResultV1(
            client_mutation_id=item.client_mutation_id,
            status="rejected",
            error_code="measurement_update_unsupported",
        )

    if item.revision != 1 or not item.payload:
        return SyncPushItemResultV1(
            client_mutation_id=item.client_mutation_id,
            status="rejected",
            error_code="schema_invalid" if not item.payload else "revision_jump",
        )
    body = MeasurementCreateV1.model_validate(
        {**item.payload, "client_mutation_id": str(item.client_mutation_id)}
    )
    measured_at = body.measured_at
    if measured_at.tzinfo is None:
        measured_at = measured_at.replace(tzinfo=UTC)
    row = BodyMeasurement(
        id=item.entity_id,
        user_id=user.id,
        measured_at=measured_at,
        local_date=body.local_date,
        metrics=body.metrics,
        notes=body.notes,
        client_mutation_id=item.client_mutation_id,
        revision=1,
        client_updated_at=body.client_updated_at or measured_at,
    )
    db.add(row)
    await db.flush()
    return SyncPushItemResultV1(
        client_mutation_id=item.client_mutation_id,
        status="applied",
        winning_revision=1,
        winning_updated_at=datetime.now(UTC),
    )


async def _apply_measurement_delete(
    db: AsyncSession,
    *,
    user: User,
    item: SyncPushItemV1,
) -> SyncPushItemResultV1:
    from sqlalchemy import text

    await db.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(user.id)},
    )
    row = await db.scalar(
        select(BodyMeasurement).where(
            BodyMeasurement.id == item.entity_id,
            BodyMeasurement.user_id == user.id,
        )
    )
    if row is None:
        return SyncPushItemResultV1(
            client_mutation_id=item.client_mutation_id,
            status="rejected",
            error_code="not_found",
        )
    if row.deleted_at is not None:
        return SyncPushItemResultV1(
            client_mutation_id=item.client_mutation_id,
            status="idempotent",
            winning_revision=row.revision,
            winning_updated_at=row.deleted_at,
        )
    if item.revision != row.revision + 1:
        if item.revision <= row.revision:
            status = "conflict_lost" if item.revision < row.revision else "conflict_tie"
            kind = "lost_push" if item.revision < row.revision else "tie_revision"
            cid = await _log_conflict(
                db,
                user_id=user.id,
                item=item,
                kind=kind,
                winning_revision=row.revision,
                winning_updated_at=row.updated_at,
                device_id=None,
            )
            return SyncPushItemResultV1(
                client_mutation_id=item.client_mutation_id,
                status=status,  # type: ignore[arg-type]
                conflict_id=cid,
                winning_revision=row.revision,
                winning_updated_at=row.updated_at,
            )
        return SyncPushItemResultV1(
            client_mutation_id=item.client_mutation_id,
            status="rejected",
            error_code="revision_jump",
        )
    await soft_delete_measurement(db, row, revision=item.revision)
    return SyncPushItemResultV1(
        client_mutation_id=item.client_mutation_id,
        status="applied",
        winning_revision=row.revision,
        winning_updated_at=row.deleted_at,
    )


async def _set_claim_result_status(
    db: AsyncSession,
    *,
    user_id: UUID,
    client_mutation_id: UUID,
    result_status: str,
) -> None:
    row = await db.scalar(
        select(ClientMutation).where(
            ClientMutation.user_id == user_id,
            ClientMutation.client_mutation_id == client_mutation_id,
        )
    )
    if row is not None:
        row.result_status = result_status
        await db.flush()


async def _delete_claim(
    db: AsyncSession,
    *,
    user_id: UUID,
    client_mutation_id: UUID,
) -> None:
    """Remove a non-success claim so dependents are not falsely fulfilled (FR-072d)."""
    row = await db.scalar(
        select(ClientMutation).where(
            ClientMutation.user_id == user_id,
            ClientMutation.client_mutation_id == client_mutation_id,
        )
    )
    if row is not None:
        await db.delete(row)
        await db.flush()


async def _apply_satellite_upsert(
    db: AsyncSession,
    *,
    user: User,
    item: SyncPushItemV1,
) -> SyncPushItemResultV1:
    existing = await db.scalar(
        select(Exercise).where(
            Exercise.id == item.entity_id,
            Exercise.user_id == user.id,
            Exercise.kind == "satellite",
        )
    )
    if existing is not None:
        # Slice F: register a new immutable config version on an existing satellite.
        if not item.payload or item.payload.get("config_version_id") is None:
            return SyncPushItemResultV1(
                client_mutation_id=item.client_mutation_id,
                status="rejected",
                error_code="satellite_update_unsupported",
            )
        body = SatelliteCreateV1.model_validate(
            {**item.payload, "client_mutation_id": str(item.client_mutation_id)}
        )
        body = body.model_copy(update={"client_mutation_id": item.client_mutation_id})
        outcome = await satellite_service.register_satellite_config_version(
            db, user=user, exercise=existing, body=body
        )
        if not outcome.activation_applied:
            conflict_id = await _log_conflict(
                db,
                user_id=user.id,
                item=item,
                kind="satellite_config_activation_lost",
                winning_revision=outcome.exercise_revision,
                winning_updated_at=datetime.now(UTC),
                device_id=None,
            )
            return SyncPushItemResultV1(
                client_mutation_id=item.client_mutation_id,
                status="applied_detached",
                registered_config_version_id=outcome.config_version_id,
                activation_applied=False,
                conflict_id=conflict_id,
                winning_revision=outcome.exercise_revision,
                winning_updated_at=datetime.now(UTC),
            )
        return SyncPushItemResultV1(
            client_mutation_id=item.client_mutation_id,
            status="applied",
            registered_config_version_id=outcome.config_version_id,
            activation_applied=True,
            winning_revision=outcome.exercise_revision,
            winning_updated_at=datetime.now(UTC),
        )
    if item.revision != 1 or not item.payload:
        return SyncPushItemResultV1(
            client_mutation_id=item.client_mutation_id,
            status="rejected",
            error_code="schema_invalid" if not item.payload else "revision_jump",
        )
    body = SatelliteCreateV1.model_validate(
        {**item.payload, "client_mutation_id": str(item.client_mutation_id)}
    )
    body = body.model_copy(update={"client_mutation_id": item.client_mutation_id})
    created = await satellite_service.create_satellite(
        db, user=user, body=body, exercise_id=item.entity_id, commit=False
    )
    return SyncPushItemResultV1(
        client_mutation_id=item.client_mutation_id,
        status="applied",
        registered_config_version_id=created.current_config_version_id,
        activation_applied=True,
        winning_revision=created.revision,
        winning_updated_at=datetime.now(UTC),
    )


async def _apply_legal(
    db: AsyncSession,
    *,
    user: User,
    item: SyncPushItemV1,
) -> SyncPushItemResultV1:
    if not item.payload:
        return SyncPushItemResultV1(
            client_mutation_id=item.client_mutation_id,
            status="rejected",
            error_code="payload_required",
        )
    payload = dict(item.payload)
    payload.setdefault("client_mutation_id", str(item.client_mutation_id))
    await record_legal_acceptance(db, user_id=user.id, payload=payload)
    await db.flush()
    return SyncPushItemResultV1(
        client_mutation_id=item.client_mutation_id,
        status="applied",
        winning_revision=1,
        winning_updated_at=datetime.now(UTC),
    )


async def apply_push_item(
    db: AsyncSession,
    *,
    user: User,
    item: SyncPushItemV1,
) -> SyncPushItemResultV1:
    if item.entity_type == "legal_acceptance":
        return await _apply_legal(db, user=user, item=item)
    if item.entity_type == "workout_session":
        if item.op == "delete":
            return await _apply_session_delete(db, user=user, item=item)
        return await _apply_session_upsert(db, user=user, item=item)
    if item.entity_type == "body_measurement":
        if item.op == "delete":
            return await _apply_measurement_delete(db, user=user, item=item)
        return await _apply_measurement_upsert(db, user=user, item=item)
    if item.entity_type == "satellite":
        if item.op == "delete":
            return SyncPushItemResultV1(
                client_mutation_id=item.client_mutation_id,
                status="rejected",
                error_code="satellite_delete_unsupported",
            )
        return await _apply_satellite_upsert(db, user=user, item=item)
    if item.entity_type == "satellite_regression_decision":
        return await _apply_satellite_regression_decision(db, user=user, item=item)
    return SyncPushItemResultV1(
        client_mutation_id=item.client_mutation_id,
        status="rejected",
        error_code="unsupported_entity_type",
    )


async def _apply_satellite_regression_decision(
    db: AsyncSession,
    *,
    user: User,
    item: SyncPushItemV1,
) -> SyncPushItemResultV1:
    if item.op == "delete":
        return SyncPushItemResultV1(
            client_mutation_id=item.client_mutation_id,
            status="rejected",
            error_code="unsupported_op",
        )
    payload = item.payload or {}
    raw_decision = payload.get("decision")
    raw_rec = payload.get("recommendation_id")
    if raw_decision not in ("accept", "decline") or raw_rec is None:
        return SyncPushItemResultV1(
            client_mutation_id=item.client_mutation_id,
            status="rejected",
            error_code="invalid_payload",
        )
    try:
        recommendation_id = UUID(str(raw_rec))
    except (TypeError, ValueError):
        return SyncPushItemResultV1(
            client_mutation_id=item.client_mutation_id,
            status="rejected",
            error_code="invalid_payload",
        )
    from typing import Literal

    from app.services.satellite_progression import SatelliteProgressionOrchestrator

    decision: Literal["accept", "decline"] = raw_decision
    try:
        await SatelliteProgressionOrchestrator().decide_recommendation(
            db,
            user_id=user.id,
            exercise_id=item.entity_id,
            recommendation_id=recommendation_id,
            decision=decision,
            commit=False,
        )
    except DomainError as exc:
        return SyncPushItemResultV1(
            client_mutation_id=item.client_mutation_id,
            status="rejected",
            error_code=exc.error_code,
        )
    return SyncPushItemResultV1(
        client_mutation_id=item.client_mutation_id,
        status="applied",
    )


async def push_batch(
    db: AsyncSession,
    *,
    user: User,
    body: SyncPushRequestV1,
) -> SyncPushResponseV1:
    if len(body.items) > MAX_BATCH:
        raise DomainError("batch_too_large", http_status=422)

    mutation_ids = [item.client_mutation_id for item in body.items]
    if len(mutation_ids) != len(set(mutation_ids)):
        raise DomainError("batch_duplicate_mutation_id", http_status=422)

    await _touch_device(db, user_id=user.id, device_id=body.device_id)
    await db.commit()

    # Slice E: finalize overdue failed days before applying outbox (FR-053).
    await SatelliteProgressionOrchestrator().finalize_due_outcomes(
        db, user_id=user.id
    )
    await db.commit()

    user_id = user.id
    results: list[SyncPushItemResultV1] = []
    result_by_id: dict[UUID, SyncPushItemResultV1] = {}
    truncated = False

    ordered, cycle_ids = topological_sort_push_items(body.items)
    batch_ids = set(mutation_ids)
    for mid in cycle_ids:
        rejected = SyncPushItemResultV1(
            client_mutation_id=mid,
            status="rejected",
            error_code="dependency_cycle",
        )
        results.append(rejected)
        result_by_id[mid] = rejected

    all_deps = {dep for item in ordered for dep in item.depends_on}
    fulfilled = await _load_fulfilled_mutation_ids(
        db, user_id=user_id, mutation_ids=all_deps
    )

    for item in ordered:
        decision = resolve_item_dependencies(
            item,
            fulfilled=fulfilled,
            batch_ids=batch_ids,
            result_by_id=result_by_id,
        )
        if decision == "defer":
            truncated = True
            continue
        if decision is not None:
            results.append(decision)
            result_by_id[item.client_mutation_id] = decision
            continue

        digest = content_hash(
            item.payload,
            op=item.op,
            revision=item.revision,
            depends_on=item.depends_on,
        )
        try:
            # Rollback of a prior rejected item detaches ORM state — re-load user.
            loaded_user = await db.get(User, user_id)
            if loaded_user is None:
                failed = SyncPushItemResultV1(
                    client_mutation_id=item.client_mutation_id,
                    status="rejected",
                    error_code="not_found",
                )
                results.append(failed)
                result_by_id[item.client_mutation_id] = failed
                continue
            claim = await _claim(
                db, user_id=user_id, item=item, digest=digest
            )
            if claim is not None:
                await db.commit()
                results.append(claim)
                result_by_id[item.client_mutation_id] = claim
                if claim.status in _SUCCESS_DEP_STATUSES:
                    fulfilled.add(item.client_mutation_id)
                continue
            result = await apply_push_item(db, user=loaded_user, item=item)
            # Rejected items must not keep the claim (FR-072b: legal_required /
            # revision_jump quarantine may retry after user fix with same id).
            if result.status == "rejected":
                await db.rollback()
                results.append(result)
                result_by_id[item.client_mutation_id] = result
                continue
            # Conflict / immutable are terminal for this mutation but are not
            # success — drop the claim, keep sync_conflict_logs (FR-072d).
            if result.status in _FAILED_DEP_STATUSES:
                await _delete_claim(
                    db,
                    user_id=user_id,
                    client_mutation_id=item.client_mutation_id,
                )
                await db.commit()
                results.append(result)
                result_by_id[item.client_mutation_id] = result
                continue
            if result.status == "applied_detached":
                await _set_claim_result_status(
                    db,
                    user_id=user_id,
                    client_mutation_id=item.client_mutation_id,
                    result_status="applied_detached",
                )
            await db.commit()
            results.append(result)
            result_by_id[item.client_mutation_id] = result
            if result.status in _SUCCESS_DEP_STATUSES:
                fulfilled.add(item.client_mutation_id)
        except DomainError as exc:
            await db.rollback()
            failed = SyncPushItemResultV1(
                client_mutation_id=item.client_mutation_id,
                status="rejected",
                error_code=exc.error_code,
            )
            results.append(failed)
            result_by_id[item.client_mutation_id] = failed
        except NotFoundError:
            await db.rollback()
            failed = SyncPushItemResultV1(
                client_mutation_id=item.client_mutation_id,
                status="rejected",
                error_code="not_found",
            )
            results.append(failed)
            result_by_id[item.client_mutation_id] = failed
        except Exception:
            await db.rollback()
            failed = SyncPushItemResultV1(
                client_mutation_id=item.client_mutation_id,
                status="rejected",
                error_code="apply_failed",
            )
            results.append(failed)
            result_by_id[item.client_mutation_id] = failed

    # Aggregate tip progression surface (FR-074)
    progress_rows = (
        await db.scalars(
            select(UserExerciseProgress).where(UserExerciseProgress.user_id == user_id)
        )
    ).all()
    events = (
        await db.scalars(
            select(ProgressionEvent)
            .where(ProgressionEvent.user_id == user_id)
            .order_by(ProgressionEvent.created_at.desc())
            .limit(50)
        )
    ).all()
    return SyncPushResponseV1(
        truncated=truncated,
        results=results,
        progress=[progress_to_read(p).model_dump(mode="json") for p in progress_rows],
        progression_events=[
            {
                "id": str(e.id),
                "exercise_id": str(e.exercise_id),
                "session_id": str(e.session_id) if e.session_id else None,
                "event_type": e.event_type,
                "from_step": e.from_step,
                "to_step": e.to_step,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
    )
