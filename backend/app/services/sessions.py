"""Online session create / read / soft-delete (FR-035/038/039/014a/040a)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_uuid7
from app.models.catalog import Exercise, ExerciseStep, ExerciseStepTranslation, ExerciseTranslation
from app.models.progression import ProgressionEvent, UserExerciseProgress
from app.models.user import User
from app.models.workout import SessionExerciseLog, WorkoutSession
from app.repositories.access import get_for_user
from app.schemas.api import (
    ProgressionEventReadV1,
    ProgressItemV1,
    SessionCreateV1,
    SessionLogReadV1,
    SessionReadV1,
)
from app.schemas.common import parse_versioned
from app.schemas.sets import SessionSetsV1
from app.services.errors import DomainError
from app.services.legal import require_health_disclaimer_for_session
from app.services.locale import resolve_locale
from app.services.progression import ProgressionEngine
from app.services.session_rules import (
    assert_no_active_cc_log_same_day,
    soft_delete_session,
)

_engine = ProgressionEngine()


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise DomainError("invalid_timezone", http_status=422) from exc


def validate_local_date(
    *,
    performed_at: datetime,
    local_date: date,
    timezone_name: str,
) -> None:
    """local_date must be within ±1 day of performed_at in the active TZ (FR-040a)."""
    if performed_at.tzinfo is None:
        performed_at = performed_at.replace(tzinfo=UTC)
    local_performed = performed_at.astimezone(_tz(timezone_name)).date()
    if abs((local_date - local_performed).days) > 1:
        raise DomainError("local_date_mismatch", http_status=422)


def log_to_read(log: SessionExerciseLog) -> SessionLogReadV1:
    return SessionLogReadV1(
        id=log.id,
        exercise_id=log.exercise_id,
        exercise_kind=log.exercise_kind,
        section=log.section,
        step_number=log.step_number,
        local_date=log.local_date,
        performed_at=log.performed_at,
        content_locale=log.content_locale,
        exercise_name_snapshot=log.exercise_name_snapshot,
        step_label_snapshot=log.step_label_snapshot,
        skipped=log.skipped,
        sets=log.sets,
        goal_met=log.goal_met,
        goal_evaluated_at=log.goal_evaluated_at,
        counts_for_progression=log.counts_for_progression,
        notes=log.notes,
        sort_order=log.sort_order,
        revision=log.revision,
    )


def progress_to_read(row: UserExerciseProgress) -> ProgressItemV1:
    return ProgressItemV1(
        exercise_id=row.exercise_id,
        current_step_number=row.current_step_number,
        fail_streak=row.fail_streak,
        last_session_at=row.last_session_at,
        is_active=row.is_active,
    )


def event_to_read(ev: ProgressionEvent) -> ProgressionEventReadV1:
    return ProgressionEventReadV1(
        id=ev.id,
        exercise_id=ev.exercise_id,
        session_id=ev.session_id,
        event_type=ev.event_type,
        from_step=ev.from_step,
        to_step=ev.to_step,
        reason=ev.reason,
        created_at=ev.created_at,
    )


async def _exercise_name_snapshot(
    db: AsyncSession,
    *,
    exercise: Exercise,
    locale: str,
) -> str:
    if exercise.kind == "satellite":
        return exercise.name or "satellite"
    row = await db.scalar(
        select(ExerciseTranslation).where(
            ExerciseTranslation.exercise_id == exercise.id,
            ExerciseTranslation.locale == locale,
        )
    )
    if row is not None:
        return row.name
    return exercise.slug or str(exercise.id)


async def _step_label(
    db: AsyncSession,
    *,
    exercise_id: UUID,
    step_number: int,
    locale: str,
) -> str | None:
    step = await db.scalar(
        select(ExerciseStep).where(
            ExerciseStep.exercise_id == exercise_id,
            ExerciseStep.step_number == step_number,
        )
    )
    if step is None:
        return None
    tr = await db.scalar(
        select(ExerciseStepTranslation).where(
            ExerciseStepTranslation.exercise_step_id == step.id,
            ExerciseStepTranslation.locale == locale,
        )
    )
    if tr is not None:
        return tr.name
    return step.name


async def _load_owned_exercise(
    db: AsyncSession,
    *,
    user_id: UUID,
    exercise_id: UUID,
    expected_kind: str,
) -> Exercise:
    exercise = await db.scalar(select(Exercise).where(Exercise.id == exercise_id))
    if exercise is None or exercise.deleted_at is not None:
        raise DomainError("not_found", http_status=404)
    if exercise.kind != expected_kind:
        raise DomainError("exercise_kind_mismatch", http_status=422)
    if expected_kind == "cc":
        if exercise.user_id is not None:
            raise DomainError("not_found", http_status=404)
    elif exercise.user_id != user_id:
        raise DomainError("not_found", http_status=404)
    return exercise


async def session_to_read(
    db: AsyncSession,
    session: WorkoutSession,
    *,
    include_events: bool = False,
    include_progress_for: set[UUID] | None = None,
) -> SessionReadV1:
    logs = (
        await db.scalars(
            select(SessionExerciseLog)
            .where(SessionExerciseLog.session_id == session.id)
            .order_by(SessionExerciseLog.sort_order, SessionExerciseLog.id)
        )
    ).all()
    events: list[ProgressionEventReadV1] = []
    if include_events:
        evs = (
            await db.scalars(
                select(ProgressionEvent).where(ProgressionEvent.session_id == session.id)
            )
        ).all()
        events = [event_to_read(e) for e in evs]
    progress: list[ProgressItemV1] = []
    if include_progress_for:
        rows = (
            await db.scalars(
                select(UserExerciseProgress).where(
                    UserExerciseProgress.user_id == session.user_id,
                    UserExerciseProgress.exercise_id.in_(include_progress_for),
                )
            )
        ).all()
        progress = [progress_to_read(r) for r in rows]
    return SessionReadV1(
        id=session.id,
        performed_at=session.performed_at,
        local_date=session.local_date,
        notes=session.notes,
        revision=session.revision,
        deleted_at=session.deleted_at,
        logs=[log_to_read(log) for log in logs],
        progression_events=events,
        progress=progress,
    )


async def create_session(
    db: AsyncSession,
    *,
    user: User,
    body: SessionCreateV1,
    session_id: UUID | None = None,
    commit: bool = True,
) -> SessionReadV1:
    await require_health_disclaimer_for_session(
        db, user_id=user.id, locale=user.locale or "pl-PL"
    )
    tz_name = body.client_timezone or user.timezone
    performed_at = body.performed_at
    if performed_at.tzinfo is None:
        performed_at = performed_at.replace(tzinfo=UTC)
    validate_local_date(
        performed_at=performed_at,
        local_date=body.local_date,
        timezone_name=tz_name,
    )
    _requested, resolved_locale = resolve_locale(requested=None, user_locale=user.locale)

    session = WorkoutSession(
        id=session_id if session_id is not None else new_uuid7(),
        user_id=user.id,
        performed_at=performed_at,
        local_date=body.local_date,
        notes=body.notes,
        client_mutation_id=body.client_mutation_id,
        revision=1,
        client_updated_at=body.client_updated_at or performed_at,
    )
    db.add(session)
    await db.flush()

    # Lock progress in exercise_id ASC order after session insert (FR-072d).
    sorted_logs = sorted(body.logs, key=lambda log: str(log.exercise_id))
    touched: set[UUID] = set()
    for item in sorted_logs:
        exercise = await _load_owned_exercise(
            db,
            user_id=user.id,
            exercise_id=item.exercise_id,
            expected_kind=item.exercise_kind,
        )
        if item.exercise_kind == "cc" and not item.skipped:
            await assert_no_active_cc_log_same_day(
                db,
                user_id=user.id,
                exercise_id=item.exercise_id,
                local_date=body.local_date,
            )
        if item.skipped:
            sets_payload = None
        else:
            if item.sets is None:
                raise DomainError("sets_required", http_status=422)
            parse_versioned(SessionSetsV1, item.sets)
            sets_payload = item.sets

        name = await _exercise_name_snapshot(db, exercise=exercise, locale=resolved_locale)
        # Provisional snapshot for ck_session_logs_skipped_false; engine overwrites.
        provisional_rules = {"schema_version": 1}
        log = SessionExerciseLog(
            id=new_uuid7(),
            session_id=session.id,
            user_id=user.id,
            exercise_id=item.exercise_id,
            exercise_kind=item.exercise_kind,
            section=item.section,
            step_number=None,
            local_date=body.local_date,
            performed_at=performed_at,
            content_locale=resolved_locale,
            exercise_name_snapshot=name,
            step_label_snapshot=None,
            skipped=item.skipped,
            sets=sets_payload,
            rules_snapshot=None if item.skipped else provisional_rules,
            progression_schema_version=None if item.skipped else 1,
            notes=item.notes,
            sort_order=item.sort_order,
            client_mutation_id=item.client_mutation_id or new_uuid7(),
            revision=1,
            client_updated_at=body.client_updated_at or performed_at,
        )
        db.add(log)
        try:
            await db.flush()
        except IntegrityError as exc:
            raise DomainError("duplicate_exercise_same_day", http_status=409) from exc

        result = await _engine.evaluate_log(db, log, session=session)
        if log.step_number is not None:
            log.step_label_snapshot = await _step_label(
                db,
                exercise_id=log.exercise_id,
                step_number=log.step_number,
                locale=resolved_locale,
            )
        del result
        touched.add(item.exercise_id)

    if commit:
        await db.commit()
        await db.refresh(session)
    else:
        await db.flush()
    return await session_to_read(
        db, session, include_events=True, include_progress_for=touched
    )


async def get_session(
    db: AsyncSession,
    *,
    user_id: UUID,
    session_id: UUID,
) -> SessionReadV1:
    session = await get_for_user(
        db, WorkoutSession, user_id=user_id, entity_id=session_id
    )
    return await session_to_read(db, session, include_events=True)


async def soft_delete_user_session(
    db: AsyncSession,
    *,
    user_id: UUID,
    session_id: UUID,
    commit: bool = True,
    revision: int | None = None,
) -> SessionReadV1:
    session = await get_for_user(
        db, WorkoutSession, user_id=user_id, entity_id=session_id
    )
    await soft_delete_session(db, session, revision=revision)
    if commit:
        await db.commit()
        await db.refresh(session)
    else:
        await db.flush()
    return await session_to_read(db, session)
