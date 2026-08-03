"""Satellite daily-outcome finalizer batch (FR-053 / Stage 3 Slice E).

Lazy callers use ``SatelliteProgressionOrchestrator.finalize_due_outcomes``.
Cron uses ``run_satellite_finalize_batch`` (Compose one-shot, no Redis/ARQ).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.satellite_progress import SatelliteDailyOutcome
from app.services.satellite_progression import SatelliteProgressionOrchestrator

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 500


async def list_due_finalize_pairs(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> list[tuple[UUID, UUID]]:
    """Candidates without durable lock — orchestrator re-validates under advisory."""
    moment = now or datetime.now(UTC)
    rows = (
        await db.execute(
            select(
                SatelliteDailyOutcome.user_id,
                SatelliteDailyOutcome.exercise_id,
            )
            .where(
                SatelliteDailyOutcome.status == "pending",
                SatelliteDailyOutcome.has_attempt.is_(True),
                SatelliteDailyOutcome.has_success.is_(False),
                SatelliteDailyOutcome.finalize_after.is_not(None),
                SatelliteDailyOutcome.finalize_after <= moment,
            )
            .distinct()
            .order_by(
                SatelliteDailyOutcome.user_id.asc(),
                SatelliteDailyOutcome.exercise_id.asc(),
            )
            .limit(limit)
        )
    ).all()
    return [(r[0], r[1]) for r in rows]


async def run_satellite_finalize_batch(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    heartbeat_path: str | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> dict[str, int]:
    """Finalize overdue satellite daily outcomes across users. Idempotent."""
    moment = now or datetime.now(UTC)
    pairs = await list_due_finalize_pairs(db, now=moment, limit=limit)
    orch = SatelliteProgressionOrchestrator()
    finalized = 0
    ok_pairs = 0
    fail = 0

    for user_id, exercise_id in pairs:
        try:
            n = await orch.finalize_due_outcomes(
                db,
                user_id=user_id,
                exercise_id=exercise_id,
                now=moment,
            )
            await db.commit()
            finalized += n
            ok_pairs += 1
            if n:
                logger.info(
                    "satellite_finalize.ok user_id=%s exercise_id=%s count=%s",
                    user_id,
                    exercise_id,
                    n,
                    extra={
                        "event": "satellite_finalize.ok",
                        "user_id": str(user_id),
                        "exercise_id": str(exercise_id),
                        "count": n,
                    },
                )
        except Exception:
            await db.rollback()
            fail += 1
            logger.exception(
                "satellite_finalize.fail user_id=%s exercise_id=%s",
                user_id,
                exercise_id,
                extra={
                    "event": "satellite_finalize.fail",
                    "user_id": str(user_id),
                    "exercise_id": str(exercise_id),
                },
            )

    if heartbeat_path and fail == 0:
        try:
            with open(heartbeat_path, "w", encoding="utf-8") as fh:
                fh.write(datetime.now(UTC).isoformat() + "\n")
        except OSError:
            logger.warning(
                "satellite_finalize.heartbeat_write_failed path=%s",
                heartbeat_path,
            )

    logger.info(
        "satellite_finalize.batch finalized=%s pairs_ok=%s fail=%s due_pairs=%s",
        finalized,
        ok_pairs,
        fail,
        len(pairs),
        extra={
            "event": "satellite_finalize.batch",
            "finalized": finalized,
            "pairs_ok": ok_pairs,
            "fail": fail,
            "due_pairs": len(pairs),
        },
    )
    return {
        "finalized": finalized,
        "pairs_ok": ok_pairs,
        "fail": fail,
        "due_pairs": len(pairs),
    }
