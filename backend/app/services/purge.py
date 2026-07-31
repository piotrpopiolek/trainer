"""Hard purge of soft-deleted accounts (FR-006c)."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import AuthSession
from app.models.catalog import (
    Exercise,
    ExerciseStep,
    SatelliteConfigActivation,
    SatelliteConfigVersion,
)
from app.models.progression import (
    ProgressionEvent,
    UserExerciseProgress,
    UserProgramEnrollment,
)
from app.models.user import User
from app.models.workout import SessionExerciseLog, WorkoutSession

logger = logging.getLogger(__name__)


async def hard_purge_user(db: AsyncSession, *, user_id: UUID) -> None:
    """
    Delete training graph for one user (RESTRICT-safe order). Caller owns TX + claim.

    Leaves anonymized ``users`` row with ``purge_status='done'``.
    """
    await db.execute(
        delete(SessionExerciseLog).where(SessionExerciseLog.user_id == user_id)
    )
    await db.execute(delete(ProgressionEvent).where(ProgressionEvent.user_id == user_id))
    await db.execute(delete(WorkoutSession).where(WorkoutSession.user_id == user_id))
    await db.execute(
        delete(UserExerciseProgress).where(UserExerciseProgress.user_id == user_id)
    )
    await db.execute(
        delete(UserProgramEnrollment).where(UserProgramEnrollment.user_id == user_id)
    )

    sat_ids = (
        await db.scalars(
            select(Exercise.id).where(
                Exercise.user_id == user_id,
                Exercise.kind == "satellite",
            )
        )
    ).all()
    if sat_ids:
        # Break RESTRICT FKs: exercise → config_version → exercise.
        await db.execute(
            update(Exercise)
            .where(Exercise.id.in_(sat_ids))
            .values(
                current_config_version_id=None,
                pending_config_version_id=None,
                deleted_at=func.coalesce(Exercise.deleted_at, func.now()),
            )
        )
        await db.execute(
            delete(SatelliteConfigActivation).where(
                SatelliteConfigActivation.exercise_id.in_(sat_ids)
            )
        )
        await db.execute(
            delete(SatelliteConfigVersion).where(
                SatelliteConfigVersion.exercise_id.in_(sat_ids)
            )
        )
        await db.execute(delete(ExerciseStep).where(ExerciseStep.exercise_id.in_(sat_ids)))
        await db.execute(delete(Exercise).where(Exercise.id.in_(sat_ids)))

    await db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
    await db.execute(
        update(User).where(User.id == user_id).values(purge_status="done")
    )


async def claim_purge_user(db: AsyncSession, *, user_id: UUID) -> bool:
    """pending_grace → pending_job. False if already pending_job/done/missing."""
    claimed_id = await db.scalar(
        update(User)
        .where(
            User.id == user_id,
            User.deleted_at.is_not(None),
            User.purge_status == "pending_grace",
        )
        .values(purge_status="pending_job")
        .returning(User.id)
    )
    return claimed_id is not None


async def list_due_purge_users(db: AsyncSession, *, today: date | None = None) -> list[User]:
    day = today or datetime.now(UTC).date()
    rows = (
        await db.scalars(
            select(User)
            .where(
                User.deleted_at.is_not(None),
                User.purge_after.is_not(None),
                User.purge_after <= day,
                User.purge_status.is_distinct_from("done"),
            )
            .order_by(User.purge_after.asc(), User.id.asc())
        )
    ).all()
    return list(rows)


async def run_purge_batch(
    db: AsyncSession,
    *,
    today: date | None = None,
    heartbeat_path: str | None = None,
) -> dict[str, int]:
    """Claim + hard-purge each due user. Rerun-safe; fail leaves ``pending_job``."""
    due = await list_due_purge_users(db, today=today)
    ok = 0
    fail = 0
    skipped = 0

    for user in due:
        user_id = user.id
        try:
            if user.purge_status == "pending_grace":
                claimed = await claim_purge_user(db, user_id=user_id)
                await db.commit()
                if not claimed:
                    skipped += 1
                    continue
            elif user.purge_status != "pending_job":
                skipped += 1
                continue

            await hard_purge_user(db, user_id=user_id)
            await db.commit()
            ok += 1
            logger.info(
                "purge.ok user_id=%s",
                user_id,
                extra={"event": "purge.ok", "user_id": str(user_id)},
            )
        except Exception:
            await db.rollback()
            fail += 1
            logger.exception(
                "purge.fail user_id=%s",
                user_id,
                extra={"event": "purge.fail", "user_id": str(user_id)},
            )

    if heartbeat_path and fail == 0:
        try:
            with open(heartbeat_path, "w", encoding="utf-8") as fh:
                fh.write(datetime.now(UTC).isoformat() + "\n")
        except OSError:
            logger.warning("purge.heartbeat_write_failed path=%s", heartbeat_path)

    logger.info(
        "purge.batch ok=%s fail=%s skipped=%s due=%s",
        ok,
        fail,
        skipped,
        len(due),
        extra={"event": "purge.batch", "ok": ok, "fail": fail, "skipped": skipped},
    )
    return {"ok": ok, "fail": fail, "skipped": skipped, "due": len(due)}


async def assert_user_training_gone(db: AsyncSession, *, user_id: UUID) -> None:
    """Raise if any training / auth child rows remain (test helper)."""
    checks = [
        (
            "session_exercise_logs",
            select(func.count())
            .select_from(SessionExerciseLog)
            .where(SessionExerciseLog.user_id == user_id),
        ),
        (
            "progression_events",
            select(func.count())
            .select_from(ProgressionEvent)
            .where(ProgressionEvent.user_id == user_id),
        ),
        (
            "workout_sessions",
            select(func.count())
            .select_from(WorkoutSession)
            .where(WorkoutSession.user_id == user_id),
        ),
        (
            "user_exercise_progress",
            select(func.count())
            .select_from(UserExerciseProgress)
            .where(UserExerciseProgress.user_id == user_id),
        ),
        (
            "user_program_enrollments",
            select(func.count())
            .select_from(UserProgramEnrollment)
            .where(UserProgramEnrollment.user_id == user_id),
        ),
        (
            "auth_sessions",
            select(func.count())
            .select_from(AuthSession)
            .where(AuthSession.user_id == user_id),
        ),
    ]
    for label, stmt in checks:
        n = await db.scalar(stmt)
        if int(n or 0) > 0:
            raise AssertionError(f"{label} still has {n} rows for {user_id}")

    sats = await db.scalar(
        select(func.count())
        .select_from(Exercise)
        .where(Exercise.user_id == user_id, Exercise.kind == "satellite")
    )
    if int(sats or 0) > 0:
        raise AssertionError(f"satellites still present for {user_id}")

    cfg = await db.scalar(
        select(func.count())
        .select_from(SatelliteConfigVersion)
        .where(SatelliteConfigVersion.user_id == user_id)
    )
    if int(cfg or 0) > 0:
        raise AssertionError(f"satellite_config_versions still present for {user_id}")

    act = await db.scalar(
        select(func.count())
        .select_from(SatelliteConfigActivation)
        .where(SatelliteConfigActivation.user_id == user_id)
    )
    if int(act or 0) > 0:
        raise AssertionError(f"satellite_config_activations still present for {user_id}")
