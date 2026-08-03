"""Satellite exercises create/list (FR-050 / FR-051a) — Stage 1 goal-only + config version."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_uuid7
from app.domain.canonical_json import sha256_jcs
from app.models.catalog import (
    Exercise,
    ExerciseStep,
    SatelliteConfigActivation,
    SatelliteConfigVersion,
)
from app.models.progression import ProgressionSchema, UserExerciseProgress
from app.models.user import User
from app.schemas.api import SatelliteCreateV1, SatelliteReadV1, SatelliteStepCreateV1
from app.schemas.satellite import (
    ActiveMetricsV1,
    SatelliteConfigDocumentV1,
    SatelliteConfigStepV1,
    SatelliteProgressionPolicyGoalOnlyV1,
    SatelliteRulesV1,
    parse_satellite_rules,
)
from app.services.errors import DomainError

MAX_SATELLITES = 10


@dataclass(frozen=True, slots=True)
class ConfigRegistrationResult:
    config_version_id: UUID
    config_hash_hex: str
    activation_applied: bool
    exercise_revision: int


async def _satellite_schema_id(db: AsyncSession) -> UUID:
    row = await db.scalar(
        select(ProgressionSchema)
        .where(ProgressionSchema.slug == "satellite_v1")
        .order_by(ProgressionSchema.schema_version.desc())
        .limit(1)
    )
    if row is None:
        raise DomainError("progression_schema_missing", http_status=503)
    return row.id


def _canonical_document_dict(doc: SatelliteConfigDocumentV1) -> dict[str, Any]:
    """Dump with explicit nulls for hashing (no exclude_none)."""
    return doc.model_dump(mode="json")


def _build_config_steps(
    steps: list[SatelliteStepCreateV1],
) -> tuple[list[tuple[UUID, SatelliteStepCreateV1, SatelliteRulesV1]], list[SatelliteConfigStepV1]]:
    step_rows: list[tuple[UUID, SatelliteStepCreateV1, SatelliteRulesV1]] = []
    config_steps: list[SatelliteConfigStepV1] = []
    seen_step_ids: set[UUID] = set()
    for step in sorted(steps, key=lambda s: s.step_number):
        try:
            rules = parse_satellite_rules(step.rules)
        except Exception as exc:
            raise DomainError("invalid_satellite_rules", http_status=422) from exc
        step_id = step.step_id or new_uuid7()
        if step_id in seen_step_ids:
            raise DomainError("duplicate_step_id", http_status=422)
        seen_step_ids.add(step_id)
        step_rows.append((step_id, step, rules))
        config_steps.append(
            SatelliteConfigStepV1(
                step_id=step_id,
                sort_order=step.step_number,
                rules=rules,
            )
        )
    return step_rows, config_steps


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
        cfg = None
        if ex.current_config_version_id is not None:
            cfg = await db.get(SatelliteConfigVersion, ex.current_config_version_id)
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
                current_config_version_id=ex.current_config_version_id,
                config_hash=cfg.config_hash.hex() if cfg is not None else None,
                steps=[
                    {
                        "step_id": str(s.id),
                        "step_number": s.step_number,
                        "sort_order": s.sort_order,
                        "rules": s.rules,
                        "name": s.name,
                        "description": s.description,
                    }
                    for s in steps
                ],
            )
        )
    return out


async def register_satellite_config_version(
    db: AsyncSession,
    *,
    user: User,
    exercise: Exercise,
    body: SatelliteCreateV1,
    effective_from: date | None = None,
) -> ConfigRegistrationResult:
    """Register immutable config version and CAS-activate as current (FR-072d / FR-073).

    Always persists the version. If the current-pointer CAS loses, the version stays
    detached (no activation interval) and ``activation_applied`` is False.
    """
    if exercise.user_id != user.id or exercise.kind != "satellite":
        raise DomainError("satellite_not_found", http_status=404)
    if not body.steps:
        raise DomainError("steps_required", http_status=422)
    if len(body.steps) != 1:
        raise DomainError("stage1_goal_only_one_step", http_status=422)

    try:
        active_metrics = ActiveMetricsV1.model_validate(body.active_metrics)
    except Exception as exc:
        raise DomainError("invalid_active_metrics", http_status=422) from exc

    step_rows, config_steps = _build_config_steps(body.steps)
    try:
        document = SatelliteConfigDocumentV1(
            schema_version=1,
            exercise_type=body.exercise_type,
            active_metrics=active_metrics,
            progression=SatelliteProgressionPolicyGoalOnlyV1(mode="goal_only"),
            steps=config_steps,
        )
    except Exception as exc:
        raise DomainError("invalid_satellite_config", http_status=422) from exc

    doc_dict = _canonical_document_dict(document)
    config_hash = sha256_jcs(doc_dict)
    config_version_id = body.config_version_id or new_uuid7()
    expected = body.expected_current_config_version_id

    locked = await db.scalar(
        select(Exercise)
        .where(Exercise.id == exercise.id, Exercise.user_id == user.id)
        .with_for_update()
    )
    if locked is None:
        raise DomainError("satellite_not_found", http_status=404)

    cfg = SatelliteConfigVersion(
        id=config_version_id,
        exercise_id=locked.id,
        user_id=user.id,
        authored_revision=locked.revision + 1,
        schema_version=1,
        document=doc_dict,
        config_hash=config_hash,
        registered_by_mutation_id=body.client_mutation_id,
    )
    db.add(cfg)
    await db.flush()

    cas = await db.execute(
        update(Exercise)
        .where(
            Exercise.id == locked.id,
            Exercise.user_id == user.id,
            Exercise.current_config_version_id.is_not_distinct_from(expected),
        )
        .values(
            current_config_version_id=config_version_id,
            revision=locked.revision + 1,
            active_metrics=active_metrics.model_dump(mode="json"),
        )
    )
    assert isinstance(cas, CursorResult)
    if cas.rowcount == 0:
        await db.refresh(locked)
        return ConfigRegistrationResult(
            config_version_id=config_version_id,
            config_hash_hex=config_hash.hex(),
            activation_applied=False,
            exercise_revision=locked.revision,
        )

    await db.refresh(locked)
    schema_id = await _satellite_schema_id(db)
    for step_id, step, rules in step_rows:
        existing_step = await db.scalar(
            select(ExerciseStep).where(
                ExerciseStep.exercise_id == locked.id,
                ExerciseStep.step_number == step.step_number,
            )
        )
        if existing_step is not None:
            existing_step.name = step.name
            existing_step.description = step.description
            existing_step.rules = rules.model_dump(mode="json")
            existing_step.sort_order = step.step_number
            existing_step.progression_schema_id = schema_id
        else:
            db.add(
                ExerciseStep(
                    id=step_id,
                    exercise_id=locked.id,
                    step_number=step.step_number,
                    name=step.name,
                    description=step.description,
                    rules=rules.model_dump(mode="json"),
                    progression_schema_id=schema_id,
                    sort_order=step.step_number,
                )
            )
    await db.flush()
    local_from = effective_from or date(2000, 1, 1)
    open_act = await db.scalar(
        select(SatelliteConfigActivation)
        .where(
            SatelliteConfigActivation.exercise_id == locked.id,
            SatelliteConfigActivation.effective_until_local_date.is_(None),
        )
        .with_for_update()
    )
    new_act_id = new_uuid7()
    if open_act is not None and open_act.effective_from_local_date >= local_from:
        local_from = open_act.effective_from_local_date
    db.add(
        SatelliteConfigActivation(
            id=new_act_id,
            exercise_id=locked.id,
            user_id=user.id,
            config_version_id=cfg.id,
            effective_from_local_date=local_from,
            effective_until_local_date=None,
        )
    )
    await db.flush()
    if open_act is not None:
        # Half-open interval: close previous only after successor row exists (FK).
        open_act.effective_until_local_date = local_from
        open_act.superseded_by_activation_id = new_act_id
        await db.flush()
    return ConfigRegistrationResult(
        config_version_id=config_version_id,
        config_hash_hex=config_hash.hex(),
        activation_applied=True,
        exercise_revision=locked.revision,
    )


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
    # Stage 1: goal-only only — multi-step / mode=steps deferred to Stage 3.
    if len(body.steps) != 1:
        raise DomainError("stage1_goal_only_one_step", http_status=422)

    try:
        active_metrics = ActiveMetricsV1.model_validate(body.active_metrics)
    except Exception as exc:
        raise DomainError("invalid_active_metrics", http_status=422) from exc

    progression = SatelliteProgressionPolicyGoalOnlyV1(mode="goal_only")

    # Serialize create vs concurrent (FR-050).
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

    schema_id = await _satellite_schema_id(db)
    now = body.client_updated_at or datetime.now(UTC)
    ex_id = exercise_id if exercise_id is not None else new_uuid7()
    config_version_id = body.config_version_id or new_uuid7()

    step_rows, config_steps = _build_config_steps(body.steps)

    try:
        document = SatelliteConfigDocumentV1(
            schema_version=1,
            exercise_type=body.exercise_type,
            active_metrics=active_metrics,
            progression=progression,
            steps=config_steps,
        )
    except Exception as exc:
        raise DomainError("invalid_satellite_config", http_status=422) from exc

    doc_dict = _canonical_document_dict(document)
    config_hash = sha256_jcs(doc_dict)

    ex = Exercise(
        id=ex_id,
        user_id=user.id,
        program_id=None,
        slug=None,
        name=body.name,
        kind="satellite",
        exercise_type=body.exercise_type,
        active_metrics=active_metrics.model_dump(mode="json"),
        equipment=body.equipment,
        tags=body.tags,
        schedule_kind=body.schedule_kind,
        weekdays=body.weekdays,
        schedule_category=body.schedule_category,
        client_mutation_id=body.client_mutation_id,
        revision=1,
        client_updated_at=now,
        # Pre-assign so NOT NULL CHECK passes; FK is DEFERRABLE until config INSERT.
        current_config_version_id=config_version_id,
    )
    db.add(ex)
    await db.flush()

    for step_id, step, rules in step_rows:
        db.add(
            ExerciseStep(
                id=step_id,
                exercise_id=ex.id,
                step_number=step.step_number,
                name=step.name,
                description=step.description,
                rules=rules.model_dump(mode="json"),
                progression_schema_id=schema_id,
                sort_order=step.step_number,
            )
        )

    cfg = SatelliteConfigVersion(
        id=config_version_id,
        exercise_id=ex.id,
        user_id=user.id,
        authored_revision=1,
        schema_version=1,
        document=doc_dict,
        config_hash=config_hash,
        registered_by_mutation_id=body.client_mutation_id,
    )
    db.add(cfg)
    await db.flush()

    # Initial activation covers any past log date for Stage 1 online; Stage 4
    # pending/effective_on will tighten promote semantics.
    local_from = date(2000, 1, 1)
    db.add(
        SatelliteConfigActivation(
            id=new_uuid7(),
            exercise_id=ex.id,
            user_id=user.id,
            config_version_id=cfg.id,
            effective_from_local_date=local_from,
            effective_until_local_date=None,
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
