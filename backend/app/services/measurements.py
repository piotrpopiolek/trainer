"""Body measurement domain helpers (FR-060 / SyncPull tombstones)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.body_measurement import BodyMeasurement


async def soft_delete_measurement(
    db: AsyncSession,
    row: BodyMeasurement,
    *,
    revision: int | None = None,
) -> None:
    """Soft-delete and bump ``updated_at`` so incremental SyncPull emits a tombstone.

    Online HTTP delete bumps ``revision`` by 1 when ``revision`` is omitted.
    Sync push passes the client ``revision`` (must be ``existing + 1``).
    """
    if row.deleted_at is not None:
        return
    now = datetime.now(UTC)
    row.deleted_at = now
    row.updated_at = now
    row.revision = revision if revision is not None else row.revision + 1
    await db.flush()
