"""Transactional CC progression orchestrator."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_uuid7
from app.domain.cc_progression import CcEvaluationInput, CcProgressionEvaluator
from app.domain.progression_types import ProgressionEvaluation
from app.models.catalog import ExerciseStep
from app.models.progression import ProgressionEvent, ProgressionSchema, UserExerciseProgress
from app.models.user import User
from app.models.workout import SessionExerciseLog, WorkoutSession
from app.schemas.rules import parse_progression_rules
from app.services.errors import DomainError

OVERRIDE_DAILY_LIMIT = 10


class CcProgressionOrchestrator:
    def __init__(self) -> None:
        self._evaluator = CcProgressionEvaluator()

    async def is_tip_log(self, db: AsyncSession, log: SessionExerciseLog) -> bool:
        newer = await db.scalar(
            select(SessionExerciseLog.id)
            .join(
                WorkoutSession,
                and_(
                    WorkoutSession.id == SessionExerciseLog.session_id,
                    WorkoutSession.user_id == SessionExerciseLog.user_id,
                ),
            )
            .where(
                SessionExerciseLog.user_id == log.user_id,
                SessionExerciseLog.exercise_id == log.exercise_id,
                SessionExerciseLog.skipped.is_(False),
                SessionExerciseLog.superseded_at.is_(None),
                WorkoutSession.deleted_at.is_(None),
                SessionExerciseLog.goal_evaluated_at.is_not(None),
                SessionExerciseLog.id != log.id,
                or_(
                    SessionExerciseLog.local_date > log.local_date,
                    and_(
                        SessionExerciseLog.local_date == log.local_date,
                        SessionExerciseLog.performed_at > log.performed_at,
                    ),
                    and_(
                        SessionExerciseLog.local_date == log.local_date,
                        SessionExerciseLog.performed_at == log.performed_at,
                        SessionExerciseLog.id > log.id,
                    ),
                ),
            )
            .limit(1)
        )
        return newer is None

    async def _load_step_and_rules(
        self,
        db: AsyncSession,
        *,
        exercise_id: UUID,
        step_number: int,
    ) -> tuple[ExerciseStep, object, int]:
        step = await db.scalar(
            select(ExerciseStep).where(
                ExerciseStep.exercise_id == exercise_id,
                ExerciseStep.step_number == step_number,
            )
        )
        if step is None:
            raise DomainError("exercise_step_not_found", http_status=422)
        rules = parse_progression_rules(step.rules)
        schema = await db.scalar(
            select(ProgressionSchema).where(ProgressionSchema.id == step.progression_schema_id)
        )
        schema_version = schema.schema_version if schema is not None else rules.schema_version
        return step, rules, schema_version

    async def _max_step_number(self, db: AsyncSession, exercise_id: UUID) -> int:
        value = await db.scalar(
            select(func.max(ExerciseStep.step_number)).where(
                ExerciseStep.exercise_id == exercise_id
            )
        )
        return int(value) if value is not None else 1

    async def _get_or_create_progress(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        exercise_id: UUID,
        default_step: int,
    ) -> UserExerciseProgress:
        progress = await db.scalar(
            select(UserExerciseProgress)
            .where(
                UserExerciseProgress.user_id == user_id,
                UserExerciseProgress.exercise_id == exercise_id,
            )
            .with_for_update()
        )
        if progress is not None:
            return progress
        progress = UserExerciseProgress(
            id=new_uuid7(),
            user_id=user_id,
            exercise_id=exercise_id,
            current_step_number=default_step,
            fail_streak=0,
            is_active=True,
        )
        try:
            async with db.begin_nested():
                db.add(progress)
                await db.flush()
        except IntegrityError:
            progress = await db.scalar(
                select(UserExerciseProgress)
                .where(
                    UserExerciseProgress.user_id == user_id,
                    UserExerciseProgress.exercise_id == exercise_id,
                )
                .with_for_update()
            )
            if progress is None:
                raise
        return progress

    async def _count_overrides_today(self, db: AsyncSession, user_id: UUID) -> int:
        user = await db.get(User, user_id)
        tz_name = user.timezone if user is not None else "UTC"
        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("UTC")
        now_local = datetime.now(UTC).astimezone(tz)
        start_local = datetime.combine(now_local.date(), time.min, tzinfo=tz)
        end_local = start_local + timedelta(days=1)
        count = await db.scalar(
            select(func.count())
            .select_from(ProgressionEvent)
            .where(
                ProgressionEvent.user_id == user_id,
                ProgressionEvent.event_type == "manual_override",
                ProgressionEvent.created_at >= start_local.astimezone(UTC),
                ProgressionEvent.created_at < end_local.astimezone(UTC),
            )
        )
        return int(count or 0)

    def _apply(
        self,
        db: AsyncSession,
        *,
        log: SessionExerciseLog,
        session: WorkoutSession,
        progress: UserExerciseProgress,
        evaluation: ProgressionEvaluation,
    ) -> ProgressionEvaluation:
        log.step_number = evaluation.step_number
        log.rules_snapshot = evaluation.rules_snapshot
        log.progression_schema_version = evaluation.progression_schema_version
        log.goal_met = evaluation.goal_met
        if log.goal_evaluated_at is None:
            log.goal_evaluated_at = datetime.now(UTC)
        log.counts_for_progression = evaluation.counts_for_progression
        if evaluation.progress_patch is not None:
            patch = evaluation.progress_patch
            if patch.current_step_number is not None:
                progress.current_step_number = patch.current_step_number
            if patch.fail_streak is not None:
                progress.fail_streak = patch.fail_streak
            progress.last_session_at = log.performed_at
        for proposal in evaluation.events:
            db.add(
                ProgressionEvent(
                    id=new_uuid7(),
                    user_id=log.user_id,
                    exercise_id=log.exercise_id,
                    session_id=session.id,
                    event_type=proposal.event_type,
                    from_step=proposal.from_step,
                    to_step=proposal.to_step,
                    reason=proposal.reason,
                    rules_snapshot=proposal.rules_snapshot,
                    progression_schema_version=proposal.progression_schema_version,
                )
            )
        return evaluation

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
        if log.exercise_kind != "cc":
            raise DomainError("exercise_kind_mismatch", http_status=422)

        progress = await self._get_or_create_progress(
            db, user_id=log.user_id, exercise_id=log.exercise_id, default_step=1
        )
        step_number = progress.current_step_number
        _step, rules, schema_version = await self._load_step_and_rules(
            db, exercise_id=log.exercise_id, step_number=step_number
        )
        is_tip = True
        if log.goal_evaluated_at is None and not log.skipped:
            is_tip = await self.is_tip_log(db, log)

        evaluation = self._evaluator.evaluate(
            CcEvaluationInput(
                rules=rules,  # type: ignore[arg-type]
                sets_payload=log.sets,
                skipped=log.skipped,
                already_evaluated=log.goal_evaluated_at is not None,
                persisted_goal_met=bool(log.goal_met),
                persisted_counts_for_progression=bool(log.counts_for_progression),
                persisted_progression_skipped=(
                    "late_log"
                    if (
                        log.goal_evaluated_at is not None
                        and not log.counts_for_progression
                        and not log.skipped
                    )
                    else ("skipped" if log.skipped else None)
                ),
                is_tip=is_tip,
                current_step_number=step_number,
                max_step_number=await self._max_step_number(db, log.exercise_id),
                fail_streak=progress.fail_streak,
                schema_version=schema_version,
            )
        )
        self._apply(db, log=log, session=session, progress=progress, evaluation=evaluation)
        await db.flush()
        return evaluation

    async def manual_override(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        exercise_id: UUID,
        to_step: int,
        reason: str | None = None,
    ) -> ProgressionEvent:
        if await self._count_overrides_today(db, user_id) >= OVERRIDE_DAILY_LIMIT:
            raise DomainError("override_rate_limited", http_status=429)
        _step, rules, schema_version = await self._load_step_and_rules(
            db, exercise_id=exercise_id, step_number=to_step
        )
        progress = await self._get_or_create_progress(
            db, user_id=user_id, exercise_id=exercise_id, default_step=1
        )
        from_step = progress.current_step_number
        progress.current_step_number = to_step
        progress.fail_streak = 0
        ev = ProgressionEvent(
            id=new_uuid7(),
            user_id=user_id,
            exercise_id=exercise_id,
            session_id=None,
            event_type="manual_override",
            from_step=from_step,
            to_step=to_step,
            reason=reason or "manual_override",
            rules_snapshot=rules.model_dump(mode="json"),  # type: ignore[union-attr]
            progression_schema_version=schema_version,
        )
        db.add(ev)
        await db.flush()
        return ev
