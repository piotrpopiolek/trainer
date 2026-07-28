"""Satellite exercises create/list (FR-050 / FR-051a / FR-053)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_uuid7
from app.models.catalog import Exercise, ExerciseStep
from app.models.progression import ProgressionSchema, UserExerciseProgress
from app.models.user import User
from app.schemas.api import SatelliteCreateV1, SatelliteReadV1
from app.schemas.common import parse_versioned
from app.schemas.rules import ProgressionRulesV1
from app.services.errors import DomainError

MAX_SATELLITES = 10


async def _goal_schema_id(db: AsyncSession) -> UUID:
    row = await db.scalar(
        select(ProgressionSchema)
        .where(ProgressionSchema.slug == "cc_default")
        .order_by(ProgressionSchema.schema_version.desc())
        .limit(1)
    )
    if row is None:
        row = await db.scalar(select(ProgressionSchema).limit(1))
    if row is None:
        raise DomainError("progression_schema_missing", http_status=503)
    return row.id


async def list_satellites(db: AsyncSession, *, user_id: UUID) -> list[SatelliteReadV1]:
    rows = (
        await db.scalars(
            select(Exercise).where(
                Exercise.user_id == user_id,
                Exercise.kind == "satellite",
                Exercise.deleted_at.is_(None),
            )
        )
    ).all()
    out: list[SatelliteReadV1] = []
    for ex in rows:
        steps = (
            await db.scalars(
                select(ExerciseStep)
                .where(ExerciseStep.exercise_id == ex.id)
                .order_by(ExerciseStep.step_number)
            )
        ).all()
        out.append(
            SatelliteReadV1(
                id=ex.id,
                name=ex.name or "",
                exercise_type=ex.exercise_type,
                active_metrics=ex.active_metrics,
                schedule_kind=ex.schedule_kind,
                weekdays=ex.weekdays,
                schedule_category=ex.schedule_category,
                revision=ex.revision,
                steps=[
                    {
                        "step_number": s.step_number,
                        "rules": s.rules,
                        "name": s.name,
                        "description": s.description,
                    }
                    for s in steps
                ],
            )
        )
    return out


async def create_satellite(
    db: AsyncSession,
    *,
    user: User,
    body: SatelliteCreateV1,
    exercise_id: UUID | None = None,
    commit: bool = True,
) -> SatelliteReadV1:
    if not body.steps:
        raise DomainError("steps_required", http_status=422)
    if not (1 <= len(body.steps) <= 5):
        raise DomainError("invalid_step_count", http_status=422)
    for step in body.steps:
        rules = parse_versioned(ProgressionRulesV1, step.rules)
        if len(body.steps) == 1 and rules.goal is None:
            raise DomainError("goal_required", http_status=422)

    # Serialize create vs concurrent (FR-050): users FOR UPDATE + count.
    await db.execute(select(User).where(User.id == user.id).with_for_update())
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": str(user.id)})
    active = await db.scalar(
        select(func.count())
        .select_from(Exercise)
        .where(
            Exercise.user_id == user.id,
            Exercise.kind == "satellite",
            Exercise.deleted_at.is_(None),
        )
    )
    if int(active or 0) >= MAX_SATELLITES:
        raise DomainError("satellite_limit_reached", http_status=403)

    schema_id = await _goal_schema_id(db)
    now = body.client_updated_at or datetime.now(UTC)
    ex_id = exercise_id if exercise_id is not None else new_uuid7()
    ex = Exercise(
        id=ex_id,
        user_id=user.id,
        program_id=None,
        slug=None,
        name=body.name,
        kind="satellite",
        exercise_type=body.exercise_type,
        active_metrics=body.active_metrics,
        equipment=body.equipment,
        tags=body.tags,
        schedule_kind=body.schedule_kind,
        weekdays=body.weekdays,
        schedule_category=body.schedule_category,
        client_mutation_id=body.client_mutation_id,
        revision=1,
        client_updated_at=now,
    )
    db.add(ex)
    await db.flush()
    for step in sorted(body.steps, key=lambda s: s.step_number):
        parse_versioned(ProgressionRulesV1, step.rules)
        db.add(
            ExerciseStep(
                id=new_uuid7(),
                exercise_id=ex.id,
                step_number=step.step_number,
                name=step.name,
                description=step.description,
                rules=step.rules,
                progression_schema_id=schema_id,
                sort_order=step.step_number,
            )
        )
    db.add(
        UserExerciseProgress(
            id=new_uuid7(),
            user_id=user.id,
            exercise_id=ex.id,
            current_step_number=1,
            fail_streak=0,
            is_active=True,
        )
    )
    if commit:
        await db.commit()
    else:
        await db.flush()
    items = await list_satellites(db, user_id=user.id)
    for item in items:
        if item.id == ex.id:
            return item
    raise DomainError("satellite_create_failed", http_status=500)
