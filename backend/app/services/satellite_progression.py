"""Transactional satellite progression orchestrator (Stage 1: goal-only)."""

from __future__ import annotations

import hmac
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.progression_types import ProgressionEvaluation
from app.domain.satellite_progression import (
    SatelliteEvaluationInput,
    SatelliteProgressionEvaluator,
)
from app.models.catalog import SatelliteConfigVersion
from app.models.progression import UserExerciseProgress
from app.models.workout import SessionExerciseLog, WorkoutSession
from app.schemas.satellite import SatelliteConfigStepV1, parse_satellite_config_document
from app.services.errors import DomainError


class SatelliteProgressionOrchestrator:
    def __init__(self) -> None:
        self._evaluator = SatelliteProgressionEvaluator()

    async def _load_config_version(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        exercise_id: UUID,
        config_version_id: UUID | None,
        config_hash: bytes | None,
    ) -> SatelliteConfigVersion:
        if config_version_id is None or config_hash is None:
            raise DomainError("satellite_config_required", http_status=422)
        row = await db.scalar(
            select(SatelliteConfigVersion).where(
                SatelliteConfigVersion.id == config_version_id,
                SatelliteConfigVersion.user_id == user_id,
                SatelliteConfigVersion.exercise_id == exercise_id,
            )
        )
        if row is None:
            raise DomainError("satellite_config_not_found", http_status=404)
        if not hmac.compare_digest(bytes(row.config_hash), bytes(config_hash)):
            raise DomainError("satellite_config_mismatch", http_status=422)
        return row

    async def _is_active_for_day(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        exercise_id: UUID,
        config_version_id: UUID,
        local_date: date,
    ) -> bool:
        from app.models.catalog import SatelliteConfigActivation

        row = await db.scalar(
            select(SatelliteConfigActivation.id).where(
                SatelliteConfigActivation.user_id == user_id,
                SatelliteConfigActivation.exercise_id == exercise_id,
                SatelliteConfigActivation.config_version_id == config_version_id,
                SatelliteConfigActivation.effective_from_local_date <= local_date,
                or_(
                    SatelliteConfigActivation.effective_until_local_date.is_(None),
                    SatelliteConfigActivation.effective_until_local_date > local_date,
                ),
            )
        )
        return row is not None

    async def evaluate_log(
        self,
        db: AsyncSession,
        log: SessionExerciseLog,
        *,
        session: WorkoutSession,
    ) -> ProgressionEvaluation:
        if log.session_id != session.id or log.user_id != session.user_id:
            raise DomainError("session_log_mismatch", http_status=422)
        if session.deleted_at is not None or log.superseded_at is not None:
            raise DomainError("session_not_mutable", http_status=409)
        if log.exercise_kind != "satellite":
            raise DomainError("exercise_kind_mismatch", http_status=422)

        config = await self._load_config_version(
            db,
            user_id=log.user_id,
            exercise_id=log.exercise_id,
            config_version_id=log.satellite_config_version_id,
            config_hash=log.satellite_config_hash,
        )
        document = parse_satellite_config_document(config.document)
        progress = await db.scalar(
            select(UserExerciseProgress)
            .where(
                UserExerciseProgress.user_id == log.user_id,
                UserExerciseProgress.exercise_id == log.exercise_id,
            )
            .with_for_update()
        )
        step_number = progress.current_step_number if progress is not None else 1

        # Evaluate exclusively against the immutable hashed document — never
        # ExerciseStep.rules (those may diverge after edit/bug; hash would be inert).
        ordered = sorted(document.steps, key=lambda s: (s.sort_order, str(s.step_id)))
        cfg_step: SatelliteConfigStepV1
        if document.progression.mode == "goal_only":
            cfg_step = ordered[0]
        else:
            matched = next((s for s in ordered if s.sort_order == step_number), None)
            if matched is None:
                raise DomainError("satellite_step_not_in_config", http_status=422)
            cfg_step = matched

        eligible = await self._is_active_for_day(
            db,
            user_id=log.user_id,
            exercise_id=log.exercise_id,
            config_version_id=config.id,
            local_date=log.local_date,
        )
        try:
            evaluation = self._evaluator.evaluate(
                SatelliteEvaluationInput(
                    rules=cfg_step.rules,
                    active_metrics=document.active_metrics,
                    log_payload=log.sets,
                    skipped=log.skipped,
                    already_evaluated=log.goal_evaluated_at is not None,
                    persisted_goal_met=bool(log.goal_met),
                    progression_eligible=eligible,
                    step_number=step_number,
                    schema_version=config.schema_version,
                )
            )
        except ValueError as exc:
            code = str(exc).split(":", 1)[0]
            raise DomainError(code, http_status=422) from exc

        log.step_number = evaluation.step_number
        log.rules_snapshot = evaluation.rules_snapshot
        log.progression_schema_version = evaluation.progression_schema_version
        log.goal_met = evaluation.goal_met
        if log.goal_evaluated_at is None:
            log.goal_evaluated_at = datetime.now(UTC)
        log.counts_for_progression = False
        log.progression_skipped = evaluation.progression_skipped
        if progress is not None:
            progress.last_session_at = log.performed_at
        await db.flush()
        return evaluation
