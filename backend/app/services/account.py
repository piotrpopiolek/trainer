"""Account export stream + soft delete (FR-006a/b)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.body_measurement import BodyMeasurement
from app.models.catalog import Exercise
from app.models.legal import UserLegalAcceptance
from app.models.onboarding import UserOnboarding
from app.models.progression import ProgressionEvent, UserExerciseProgress
from app.models.sync import ClientMutation, SyncConflictLog, SyncDevice
from app.models.user import User
from app.models.workout import SessionExerciseLog, WorkoutSession
from app.services.auth_session import AuthSessionService
from app.services.errors import DomainError


def _line(collection: str, payload: dict[str, Any]) -> bytes:
    row = {"schema_version": 1, "collection": collection, **payload}
    return (json.dumps(row, default=str) + "\n").encode()


async def stream_account_export(
    db: AsyncSession,
    *,
    user_id: UUID,
) -> AsyncIterator[bytes]:
    """NDJSON cursor export — no secrets / rules_snapshot (FR-006b)."""
    user = await db.get(User, user_id)
    if user is None:
        raise DomainError("not_found", http_status=404)
    yield _line(
        "meta",
        {
            "exported_at": datetime.now(UTC).isoformat(),
            "user_id": str(user.id),
            "locale": user.locale,
            "timezone": user.timezone,
        },
    )

    sessions = (
        await db.scalars(
            select(WorkoutSession)
            .where(WorkoutSession.user_id == user_id)
            .order_by(WorkoutSession.performed_at.desc())
        )
    ).all()
    for session in sessions:
        yield _line(
            "workout_sessions",
            {
                "id": str(session.id),
                "performed_at": session.performed_at.isoformat(),
                "local_date": session.local_date.isoformat(),
                "notes": session.notes,
                "revision": session.revision,
                "deleted_at": session.deleted_at.isoformat() if session.deleted_at else None,
            },
        )
        logs = (
            await db.scalars(
                select(SessionExerciseLog).where(SessionExerciseLog.session_id == session.id)
            )
        ).all()
        for log in logs:
            yield _line(
                "session_exercise_logs",
                {
                    "id": str(log.id),
                    "session_id": str(log.session_id),
                    "exercise_id": str(log.exercise_id),
                    "exercise_kind": log.exercise_kind,
                    "step_number": log.step_number,
                    "local_date": log.local_date.isoformat(),
                    "content_locale": log.content_locale,
                    "exercise_name_snapshot": log.exercise_name_snapshot,
                    "skipped": log.skipped,
                    "sets": log.sets,
                    "goal_met": log.goal_met,
                    "counts_for_progression": log.counts_for_progression,
                },
            )

    progress = (
        await db.scalars(
            select(UserExerciseProgress).where(UserExerciseProgress.user_id == user_id)
        )
    ).all()
    for row in progress:
        yield _line(
            "user_exercise_progress",
            {
                "exercise_id": str(row.exercise_id),
                "current_step_number": row.current_step_number,
                "fail_streak": row.fail_streak,
                "last_session_at": (
                    row.last_session_at.isoformat() if row.last_session_at else None
                ),
            },
        )

    events = (
        await db.scalars(
            select(ProgressionEvent)
            .where(ProgressionEvent.user_id == user_id)
            .order_by(ProgressionEvent.created_at)
        )
    ).all()
    for ev in events:
        yield _line(
            "progression_events",
            {
                "id": str(ev.id),
                "exercise_id": str(ev.exercise_id),
                "event_type": ev.event_type,
                "from_step": ev.from_step,
                "to_step": ev.to_step,
                "created_at": ev.created_at.isoformat(),
            },
        )

    await db.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(user_id)},
    )
    measurements = (
        await db.scalars(select(BodyMeasurement).where(BodyMeasurement.user_id == user_id))
    ).all()
    for m in measurements:
        yield _line(
            "body_measurements",
            {
                "id": str(m.id),
                "measured_at": m.measured_at.isoformat(),
                "local_date": m.local_date.isoformat(),
                "metrics": m.metrics,
                "notes": m.notes,
            },
        )

    sats = (
        await db.scalars(
            select(Exercise).where(Exercise.user_id == user_id, Exercise.kind == "satellite")
        )
    ).all()
    for sat in sats:
        yield _line(
            "satellites",
            {
                "id": str(sat.id),
                "name": sat.name,
                "exercise_type": sat.exercise_type,
                "deleted_at": sat.deleted_at.isoformat() if sat.deleted_at else None,
            },
        )

    yield _line("meta", {"status": "done"})


async def soft_delete_account(
    db: AsyncSession,
    *,
    user: User,
    auth_sessions: AuthSessionService,
) -> dict[str, str]:
    """FR-006a: hard-delete PII meta + measurements; training grace 30d."""
    if user.deleted_at is not None:
        return {"status": "already_deleted", "purge_after": str(user.purge_after or "")}

    now = datetime.now(UTC)
    today = now.date()
    user.deleted_at = now
    user.purge_after = today + timedelta(days=30)
    user.purge_status = "pending_grace"
    user.email = None
    user.google_sub = None
    user.display_name = None

    await auth_sessions.revoke_all_for_user(db, user_id=user.id)
    # New TX after revoke commit — RLS requires app.user_id for measurements.
    await db.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(user.id)},
    )
    await db.execute(delete(BodyMeasurement).where(BodyMeasurement.user_id == user.id))
    await db.execute(delete(SyncConflictLog).where(SyncConflictLog.user_id == user.id))
    await db.execute(delete(SyncDevice).where(SyncDevice.user_id == user.id))
    await db.execute(delete(ClientMutation).where(ClientMutation.user_id == user.id))
    await db.execute(delete(UserOnboarding).where(UserOnboarding.user_id == user.id))
    await db.execute(delete(UserLegalAcceptance).where(UserLegalAcceptance.user_id == user.id))
    await db.commit()
    return {"status": "pending_grace", "purge_after": str(user.purge_after)}
