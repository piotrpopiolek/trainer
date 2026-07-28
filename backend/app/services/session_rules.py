"""Session immutability and soft-delete helpers (FR-038 / FR-039)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workout import SessionExerciseLog, WorkoutSession
from app.services.errors import DomainError


class SessionDateImmutableError(DomainError):
    def __init__(self) -> None:
        super().__init__("session_date_immutable", http_status=409)


class SessionImmutableAfterEvaluateError(DomainError):
    def __init__(self) -> None:
        super().__init__("session_immutable_after_evaluate", http_status=409)


class DuplicateExerciseSameDayError(DomainError):
    def __init__(self) -> None:
        super().__init__("duplicate_exercise_same_day", http_status=409)


def assert_dates_unchanged(
    existing: WorkoutSession,
    *,
    performed_at: datetime,
    local_date: date,
) -> None:
    if existing.performed_at != performed_at or existing.local_date != local_date:
        raise SessionDateImmutableError()


async def session_is_evaluated(db: AsyncSession, session_id: UUID) -> bool:
    row = await db.scalar(
        select(SessionExerciseLog.id)
        .where(
            SessionExerciseLog.session_id == session_id,
            SessionExerciseLog.goal_evaluated_at.is_not(None),
        )
        .limit(1)
    )
    return row is not None


async def assert_mutable_for_content_update(db: AsyncSession, session: WorkoutSession) -> None:
    if await session_is_evaluated(db, session.id):
        raise SessionImmutableAfterEvaluateError()


async def soft_delete_session(db: AsyncSession, session: WorkoutSession) -> None:
    """Soft-delete session and supersede child logs in one TX (FR-038/039)."""
    now = datetime.now(UTC)
    if session.deleted_at is not None:
        return
    session.deleted_at = now
    logs = (
        await db.scalars(
            select(SessionExerciseLog).where(
                SessionExerciseLog.session_id == session.id,
                SessionExerciseLog.superseded_at.is_(None),
            )
        )
    ).all()
    for log in logs:
        log.superseded_at = now
    await db.flush()


async def assert_no_active_cc_log_same_day(
    db: AsyncSession,
    *,
    user_id: UUID,
    exercise_id: UUID,
    local_date: date,
    exclude_log_id: UUID | None = None,
) -> None:
    stmt = (
        select(SessionExerciseLog.id)
        .join(
            WorkoutSession,
            and_(
                WorkoutSession.id == SessionExerciseLog.session_id,
                WorkoutSession.user_id == SessionExerciseLog.user_id,
            ),
        )
        .where(
            SessionExerciseLog.user_id == user_id,
            SessionExerciseLog.exercise_id == exercise_id,
            SessionExerciseLog.local_date == local_date,
            SessionExerciseLog.exercise_kind == "cc",
            SessionExerciseLog.skipped.is_(False),
            SessionExerciseLog.superseded_at.is_(None),
            WorkoutSession.deleted_at.is_(None),
        )
    )
    if exclude_log_id is not None:
        stmt = stmt.where(SessionExerciseLog.id != exclude_log_id)
    existing = await db.scalar(stmt.limit(1))
    if existing is not None:
        raise DuplicateExerciseSameDayError()
