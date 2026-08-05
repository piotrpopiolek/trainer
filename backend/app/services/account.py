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
from app.models.catalog import (
    Exercise,
    ExerciseStep,
    SatelliteConfigActivation,
    SatelliteConfigVersion,
)
from app.models.legal import UserLegalAcceptance
from app.models.onboarding import UserOnboarding
from app.models.progression import ProgressionEvent, UserExerciseProgress
from app.models.satellite_progress import (
    SatelliteDailyOutcome,
    SatelliteRegressionRecommendation,
)
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
                    "satellite_config_version_id": (
                        str(log.satellite_config_version_id)
                        if log.satellite_config_version_id
                        else None
                    ),
                    "satellite_config_hash": (
                        log.satellite_config_hash.hex()
                        if log.satellite_config_hash
                        else None
                    ),
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
                "related_outcome_id": (
                    str(ev.related_outcome_id) if ev.related_outcome_id else None
                ),
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
                "schedule_kind": sat.schedule_kind,
                "revision": sat.revision,
                "current_config_version_id": (
                    str(sat.current_config_version_id)
                    if sat.current_config_version_id
                    else None
                ),
                "pending_config_version_id": (
                    str(sat.pending_config_version_id)
                    if sat.pending_config_version_id
                    else None
                ),
                "config_effective_on": (
                    sat.config_effective_on.isoformat()
                    if sat.config_effective_on
                    else None
                ),
                "deleted_at": sat.deleted_at.isoformat() if sat.deleted_at else None,
            },
        )
        steps = (
            await db.scalars(
                select(ExerciseStep)
                .where(ExerciseStep.exercise_id == sat.id)
                .order_by(ExerciseStep.step_number)
            )
        ).all()
        for step in steps:
            yield _line(
                "satellite_steps",
                {
                    "id": str(step.id),
                    "exercise_id": str(sat.id),
                    "step_number": step.step_number,
                    "name": step.name,
                    "rules": step.rules,
                },
            )

    configs = (
        await db.scalars(
            select(SatelliteConfigVersion)
            .where(SatelliteConfigVersion.user_id == user_id)
            .order_by(SatelliteConfigVersion.created_at)
        )
    ).all()
    for cfg in configs:
        yield _line(
            "satellite_config_versions",
            {
                "id": str(cfg.id),
                "exercise_id": str(cfg.exercise_id),
                "authored_revision": cfg.authored_revision,
                "schema_version": cfg.schema_version,
                "config_hash": cfg.config_hash.hex(),
                "document": cfg.document,
                "registered_by_mutation_id": str(cfg.registered_by_mutation_id),
                "created_at": cfg.created_at.isoformat(),
            },
        )

    activations = (
        await db.scalars(
            select(SatelliteConfigActivation)
            .where(SatelliteConfigActivation.user_id == user_id)
            .order_by(SatelliteConfigActivation.effective_from_local_date)
        )
    ).all()
    for act in activations:
        yield _line(
            "satellite_config_activations",
            {
                "id": str(act.id),
                "exercise_id": str(act.exercise_id),
                "config_version_id": str(act.config_version_id),
                "effective_from_local_date": act.effective_from_local_date.isoformat(),
                "effective_until_local_date": (
                    act.effective_until_local_date.isoformat()
                    if act.effective_until_local_date
                    else None
                ),
                "activated_at": act.activated_at.isoformat(),
            },
        )

    outcomes = (
        await db.scalars(
            select(SatelliteDailyOutcome)
            .where(SatelliteDailyOutcome.user_id == user_id)
            .order_by(SatelliteDailyOutcome.local_date)
        )
    ).all()
    for outcome in outcomes:
        yield _line(
            "satellite_daily_outcomes",
            {
                "id": str(outcome.id),
                "exercise_id": str(outcome.exercise_id),
                "local_date": outcome.local_date.isoformat(),
                "step_id": str(outcome.step_id),
                "config_version_id": str(outcome.config_version_id),
                "status": outcome.status,
                "result": outcome.result,
                "has_attempt": outcome.has_attempt,
                "has_success": outcome.has_success,
                "result_snapshot": outcome.result_snapshot,
                "finalize_after": (
                    outcome.finalize_after.isoformat() if outcome.finalize_after else None
                ),
                "finalized_at": (
                    outcome.finalized_at.isoformat() if outcome.finalized_at else None
                ),
                "source_log_deleted_at": (
                    outcome.source_log_deleted_at.isoformat()
                    if outcome.source_log_deleted_at
                    else None
                ),
            },
        )

    recommendations = (
        await db.scalars(
            select(SatelliteRegressionRecommendation)
            .where(SatelliteRegressionRecommendation.user_id == user_id)
            .order_by(SatelliteRegressionRecommendation.created_at)
        )
    ).all()
    for rec in recommendations:
        yield _line(
            "satellite_regression_recommendations",
            {
                "id": str(rec.id),
                "exercise_id": str(rec.exercise_id),
                "trigger_outcome_id": str(rec.trigger_outcome_id),
                "config_version_id": str(rec.config_version_id),
                "from_step_id": str(rec.from_step_id),
                "to_step_id": str(rec.to_step_id),
                "status": rec.status,
                "expected_progress_revision": rec.expected_progress_revision,
                "created_at": rec.created_at.isoformat(),
                "decided_at": rec.decided_at.isoformat() if rec.decided_at else None,
            },
        )

    yield _line("meta", {"status": "done"})


async def _hard_delete_immediate_pii(db: AsyncSession, *, user_id: UUID) -> None:
    """FR-006a immediate hard-delete (measurements + sync/legal meta). Requires RLS user_id."""
    await db.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(user_id)},
    )
    await db.execute(delete(BodyMeasurement).where(BodyMeasurement.user_id == user_id))
    await db.execute(delete(SyncConflictLog).where(SyncConflictLog.user_id == user_id))
    await db.execute(delete(SyncDevice).where(SyncDevice.user_id == user_id))
    await db.execute(delete(ClientMutation).where(ClientMutation.user_id == user_id))
    await db.execute(delete(UserOnboarding).where(UserOnboarding.user_id == user_id))
    await db.execute(delete(UserLegalAcceptance).where(UserLegalAcceptance.user_id == user_id))


async def soft_delete_account(
    db: AsyncSession,
    *,
    user: User,
    auth_sessions: AuthSessionService,
) -> dict[str, str]:
    """FR-006a: hard-delete PII meta + measurements; training grace 30d.

    Single TX for anonymize + revoke + immediate hard-delete. If a prior attempt left
    residuals (legacy two-commit path), ``already_deleted`` resumes cleanup.
    """
    if user.deleted_at is not None:
        await auth_sessions.revoke_all_for_user(db, user_id=user.id, commit=False)
        await _hard_delete_immediate_pii(db, user_id=user.id)
        await db.commit()
        return {"status": "already_deleted", "purge_after": str(user.purge_after or "")}

    now = datetime.now(UTC)
    today = now.date()
    user.deleted_at = now
    user.purge_after = today + timedelta(days=30)
    user.purge_status = "pending_grace"
    user.email = None
    user.google_sub = None
    user.display_name = None

    await auth_sessions.revoke_all_for_user(db, user_id=user.id, commit=False)
    await _hard_delete_immediate_pii(db, user_id=user.id)
    await db.commit()
    return {"status": "pending_grace", "purge_after": str(user.purge_after)}
