"""Satellite exercises create/list (FR-050 / FR-051a) — Stage 1 goal-only + config version."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, func, select, text, update
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
from app.models.satellite_progress import SatelliteRegressionRecommendation
from app.models.user import User
from app.models.workout import SessionExerciseLog
from app.schemas.api import SatelliteCreateV1, SatelliteReadV1, SatelliteStepCreateV1
from app.schemas.satellite import (
    ActiveMetricsV1,
    SatelliteConfigDocumentV1,
    SatelliteConfigStepV1,
    SatelliteProgressionPolicyV1,
    SatelliteRulesV1,
    parse_satellite_config_document,
    parse_satellite_rules,
)
from app.services.errors import DomainError

MAX_SATELLITES = 10


def _resolve_progression(body: SatelliteCreateV1) -> SatelliteProgressionPolicyV1:
    return body.progression


def _ensure_step_count_matches_policy(
    *,
    progression: SatelliteProgressionPolicyV1,
    step_count: int,
) -> None:
    if progression.mode == "goal_only" and step_count != 1:
        raise DomainError("goal_only_requires_one_step", http_status=422)
    if progression.mode == "steps" and not (2 <= step_count <= 5):
        raise DomainError("steps_mode_requires_2_to_5", http_status=422)


@dataclass(frozen=True, slots=True)
class ConfigRegistrationResult:
    config_version_id: UUID
    config_hash_hex: str
    activation_applied: bool
    exercise_revision: int
    pending_applied: bool = False


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


def _topology_fingerprint(doc: SatelliteConfigDocumentV1) -> tuple[str, tuple[str, ...]]:
    ordered = sorted(doc.steps, key=lambda s: (s.sort_order, str(s.step_id)))
    return (doc.progression.mode, tuple(str(s.step_id) for s in ordered))


def _local_date_in_tz(timezone_name: str) -> date:
    try:
        return datetime.now(ZoneInfo(timezone_name)).date()
    except ZoneInfoNotFoundError:
        return datetime.now(UTC).date()


def _local_tomorrow(timezone_name: str) -> date:
    return _local_date_in_tz(timezone_name) + timedelta(days=1)


async def _exercise_to_read(db: AsyncSession, ex: Exercise) -> SatelliteReadV1:
    steps = (
        await db.scalars(
            select(ExerciseStep)
            .where(ExerciseStep.exercise_id == ex.id)
            .order_by(ExerciseStep.step_number)
        )
    ).all()
    current_cfg = None
    if ex.current_config_version_id is not None:
        current_cfg = await db.get(SatelliteConfigVersion, ex.current_config_version_id)
    pending_cfg = None
    if ex.pending_config_version_id is not None:
        pending_cfg = await db.get(SatelliteConfigVersion, ex.pending_config_version_id)
    return SatelliteReadV1(
        id=ex.id,
        name=ex.name or "",
        exercise_type=ex.exercise_type,
        active_metrics=ex.active_metrics,
        equipment=list(ex.equipment or []),
        tags=list(ex.tags or []),
        schedule_kind=ex.schedule_kind,
        weekdays=ex.weekdays,
        schedule_category=ex.schedule_category,
        revision=ex.revision,
        current_config_version_id=ex.current_config_version_id,
        config_hash=current_cfg.config_hash.hex() if current_cfg is not None else None,
        pending_config_version_id=ex.pending_config_version_id,
        pending_config_hash=(
            pending_cfg.config_hash.hex() if pending_cfg is not None else None
        ),
        config_effective_on=ex.config_effective_on,
        config_status="pending" if ex.pending_config_version_id is not None else "current",
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
    return [await _exercise_to_read(db, ex) for ex in rows]


async def get_satellite(
    db: AsyncSession, *, user_id: UUID, exercise_id: UUID
) -> SatelliteReadV1:
    ex = await db.scalar(
        select(Exercise).where(
            Exercise.id == exercise_id,
            Exercise.user_id == user_id,
            Exercise.kind == "satellite",
            Exercise.deleted_at.is_(None),
        )
    )
    if ex is None:
        raise DomainError("not_found", http_status=404)
    return await _exercise_to_read(db, ex)


async def _has_historical_log(
    db: AsyncSession, *, user_id: UUID, exercise_id: UUID
) -> bool:
    row = await db.scalar(
        select(SessionExerciseLog.id)
        .where(
            SessionExerciseLog.user_id == user_id,
            SessionExerciseLog.exercise_id == exercise_id,
        )
        .limit(1)
    )
    return row is not None


async def _stale_pending_recommendations(
    db: AsyncSession, *, user_id: UUID, exercise_id: UUID
) -> None:
    now = datetime.now(UTC)
    await db.execute(
        update(SatelliteRegressionRecommendation)
        .where(
            SatelliteRegressionRecommendation.user_id == user_id,
            SatelliteRegressionRecommendation.exercise_id == exercise_id,
            SatelliteRegressionRecommendation.status == "pending",
        )
        .values(status="stale", decided_at=now)
    )


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
    progression = _resolve_progression(body)
    _ensure_step_count_matches_policy(
        progression=progression, step_count=len(body.steps)
    )

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
            progression=progression,
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
            updated_at=datetime.now(UTC),
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
    progression = _resolve_progression(body)
    _ensure_step_count_matches_policy(
        progression=progression, step_count=len(body.steps)
    )

    try:
        active_metrics = ActiveMetricsV1.model_validate(body.active_metrics)
    except Exception as exc:
        raise DomainError("invalid_active_metrics", http_status=422) from exc

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

    first_step_id = step_rows[0][0]
    db.add(
        UserExerciseProgress(
            id=new_uuid7(),
            user_id=user.id,
            exercise_id=ex.id,
            current_step_number=1,
            current_step_id=first_step_id,
            fail_streak=0,
            is_active=True,
        )
    )
    if commit:
        await db.commit()
    else:
        await db.flush()
    return await _exercise_to_read(db, ex)


async def _apply_activation_ledger(
    db: AsyncSession,
    *,
    user: User,
    locked: Exercise,
    cfg: SatelliteConfigVersion,
    effective_from: date,
) -> None:
    open_act = await db.scalar(
        select(SatelliteConfigActivation)
        .where(
            SatelliteConfigActivation.exercise_id == locked.id,
            SatelliteConfigActivation.effective_until_local_date.is_(None),
        )
        .with_for_update()
    )
    local_from = effective_from
    if open_act is not None and open_act.effective_from_local_date >= local_from:
        local_from = open_act.effective_from_local_date
    new_act_id = new_uuid7()
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
        open_act.effective_until_local_date = local_from
        open_act.superseded_by_activation_id = new_act_id
        await db.flush()


async def _sync_step_projection(
    db: AsyncSession,
    *,
    locked: Exercise,
    step_rows: list[tuple[UUID, SatelliteStepCreateV1, SatelliteRulesV1]],
    replace_steps: bool,
    user_id: UUID,
) -> None:
    schema_id = await _satellite_schema_id(db)
    if replace_steps:
        progress = await db.scalar(
            select(UserExerciseProgress)
            .where(
                UserExerciseProgress.user_id == user_id,
                UserExerciseProgress.exercise_id == locked.id,
            )
            .with_for_update()
        )
        first_step_id = step_rows[0][0]
        if progress is not None:
            # Clear FK before deleting old steps (topology replace pre-history).
            progress.current_step_id = None
            await db.flush()
        await db.execute(delete(ExerciseStep).where(ExerciseStep.exercise_id == locked.id))
        await db.flush()
        for step_id, step, rules in step_rows:
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
        if progress is not None:
            progress.current_step_number = 1
            progress.current_step_id = first_step_id
            progress.fail_streak = 0
        return

    for step_id, step, rules in step_rows:
        existing_step = await db.scalar(
            select(ExerciseStep).where(
                ExerciseStep.exercise_id == locked.id,
                ExerciseStep.id == step_id,
            )
        )
        if existing_step is None:
            raise DomainError("satellite_step_topology_locked", http_status=409)
        existing_step.name = step.name
        existing_step.description = step.description
        existing_step.rules = rules.model_dump(mode="json")
        existing_step.sort_order = step.step_number
        existing_step.step_number = step.step_number
        existing_step.progression_schema_id = schema_id


async def edit_satellite(
    db: AsyncSession,
    *,
    user: User,
    exercise_id: UUID,
    body: SatelliteCreateV1,
    revision: int,
    commit: bool = True,
) -> tuple[SatelliteReadV1, ConfigRegistrationResult]:
    """Edit satellite (Stage 4 Slice A): metadata now; config pending after history."""
    if not body.steps:
        raise DomainError("steps_required", http_status=422)
    progression = _resolve_progression(body)
    _ensure_step_count_matches_policy(
        progression=progression, step_count=len(body.steps)
    )
    try:
        active_metrics = ActiveMetricsV1.model_validate(body.active_metrics)
    except Exception as exc:
        raise DomainError("invalid_active_metrics", http_status=422) from exc

    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": f"{user.id}:{exercise_id}"},
    )
    locked = await db.scalar(
        select(Exercise)
        .where(
            Exercise.id == exercise_id,
            Exercise.user_id == user.id,
            Exercise.kind == "satellite",
            Exercise.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if locked is None:
        raise DomainError("not_found", http_status=404)

    if revision != locked.revision + 1:
        if revision <= locked.revision:
            raise DomainError("conflict_lost", http_status=409)
        raise DomainError("revision_jump", http_status=409)

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
    config_version_id = body.config_version_id or new_uuid7()

    expected = body.expected_current_config_version_id
    if expected is not None and expected != locked.current_config_version_id:
        db.add(
            SatelliteConfigVersion(
                id=config_version_id,
                exercise_id=locked.id,
                user_id=user.id,
                authored_revision=revision,
                schema_version=1,
                document=doc_dict,
                config_hash=config_hash,
                registered_by_mutation_id=body.client_mutation_id,
            )
        )
        await db.flush()
        if commit:
            await db.commit()
        return await _exercise_to_read(db, locked), ConfigRegistrationResult(
            config_version_id=config_version_id,
            config_hash_hex=config_hash.hex(),
            activation_applied=False,
            exercise_revision=locked.revision,
            pending_applied=False,
        )

    current_cfg = await db.get(SatelliteConfigVersion, locked.current_config_version_id)
    if current_cfg is None:
        raise DomainError("satellite_config_missing", http_status=500)
    current_doc = parse_satellite_config_document(current_cfg.document)
    has_history = await _has_historical_log(
        db, user_id=user.id, exercise_id=locked.id
    )
    if has_history and _topology_fingerprint(document) != _topology_fingerprint(
        current_doc
    ):
        raise DomainError("satellite_step_topology_locked", http_status=409)

    now = body.client_updated_at or datetime.now(UTC)
    locked.name = body.name
    locked.schedule_kind = body.schedule_kind
    locked.weekdays = body.weekdays
    locked.schedule_category = body.schedule_category
    locked.equipment = list(body.equipment)
    locked.tags = list(body.tags)
    locked.client_updated_at = now
    locked.updated_at = datetime.now(UTC)
    locked.revision = revision

    if config_hash == current_cfg.config_hash:
        if not has_history:
            locked.exercise_type = body.exercise_type
            locked.active_metrics = active_metrics.model_dump(mode="json")
        await _sync_step_projection(
            db,
            locked=locked,
            step_rows=step_rows,
            replace_steps=False,
            user_id=user.id,
        )
        await db.flush()
        if commit:
            await db.commit()
            await db.refresh(locked)
        return await _exercise_to_read(db, locked), ConfigRegistrationResult(
            config_version_id=current_cfg.id,
            config_hash_hex=current_cfg.config_hash.hex(),
            activation_applied=True,
            exercise_revision=locked.revision,
            pending_applied=False,
        )

    cfg = SatelliteConfigVersion(
        id=config_version_id,
        exercise_id=locked.id,
        user_id=user.id,
        authored_revision=revision,
        schema_version=1,
        document=doc_dict,
        config_hash=config_hash,
        registered_by_mutation_id=body.client_mutation_id,
    )
    db.add(cfg)
    await db.flush()

    if has_history:
        locked.pending_config_version_id = config_version_id
        locked.config_effective_on = _local_tomorrow(user.timezone)
        await _stale_pending_recommendations(
            db, user_id=user.id, exercise_id=locked.id
        )
        await db.flush()
        if commit:
            await db.commit()
            await db.refresh(locked)
        return await _exercise_to_read(db, locked), ConfigRegistrationResult(
            config_version_id=config_version_id,
            config_hash_hex=config_hash.hex(),
            activation_applied=False,
            exercise_revision=locked.revision,
            pending_applied=True,
        )

    locked.current_config_version_id = config_version_id
    locked.pending_config_version_id = None
    locked.config_effective_on = None
    locked.exercise_type = body.exercise_type
    locked.active_metrics = active_metrics.model_dump(mode="json")
    await _sync_step_projection(
        db,
        locked=locked,
        step_rows=step_rows,
        replace_steps=True,
        user_id=user.id,
    )
    await _apply_activation_ledger(
        db,
        user=user,
        locked=locked,
        cfg=cfg,
        effective_from=_local_date_in_tz(user.timezone),
    )
    await _stale_pending_recommendations(db, user_id=user.id, exercise_id=locked.id)
    await db.flush()
    if commit:
        await db.commit()
        await db.refresh(locked)
    return await _exercise_to_read(db, locked), ConfigRegistrationResult(
        config_version_id=config_version_id,
        config_hash_hex=config_hash.hex(),
        activation_applied=True,
        exercise_revision=locked.revision,
        pending_applied=False,
    )


async def promote_pending_satellite_configs(
    db: AsyncSession,
    *,
    user: User,
    local_date: date,
) -> int:
    """Promote due pending satellite configs (Today / FR-051b)."""
    rows = (
        await db.scalars(
            select(Exercise)
            .where(
                Exercise.user_id == user.id,
                Exercise.kind == "satellite",
                Exercise.deleted_at.is_(None),
                Exercise.pending_config_version_id.is_not(None),
                Exercise.config_effective_on.is_not(None),
                Exercise.config_effective_on <= local_date,
            )
            .order_by(Exercise.id)
            .with_for_update()
        )
    ).all()
    promoted = 0
    for locked in rows:
        pending_id = locked.pending_config_version_id
        if pending_id is None:
            continue
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
            {"k": f"{user.id}:{locked.id}"},
        )
        cfg = await db.get(SatelliteConfigVersion, pending_id)
        if cfg is None:
            locked.pending_config_version_id = None
            locked.config_effective_on = None
            continue
        document = parse_satellite_config_document(cfg.document)
        step_rows: list[tuple[UUID, SatelliteStepCreateV1, SatelliteRulesV1]] = []
        for step in sorted(document.steps, key=lambda s: s.sort_order):
            existing = await db.scalar(
                select(ExerciseStep).where(
                    ExerciseStep.exercise_id == locked.id,
                    ExerciseStep.id == step.step_id,
                )
            )
            step_rows.append(
                (
                    step.step_id,
                    SatelliteStepCreateV1(
                        step_number=step.sort_order,
                        step_id=step.step_id,
                        name=existing.name if existing is not None else None,
                        description=(
                            existing.description if existing is not None else None
                        ),
                        rules=step.rules.model_dump(mode="json"),
                    ),
                    step.rules,
                )
            )
        locked.current_config_version_id = cfg.id
        locked.pending_config_version_id = None
        locked.config_effective_on = None
        locked.exercise_type = document.exercise_type
        locked.active_metrics = document.active_metrics.model_dump(mode="json")
        locked.updated_at = datetime.now(UTC)
        await _sync_step_projection(
            db,
            locked=locked,
            step_rows=step_rows,
            replace_steps=False,
            user_id=user.id,
        )
        await _apply_activation_ledger(
            db,
            user=user,
            locked=locked,
            cfg=cfg,
            effective_from=local_date,
        )
        await _stale_pending_recommendations(
            db, user_id=user.id, exercise_id=locked.id
        )
        promoted += 1
    await db.flush()
    return promoted
