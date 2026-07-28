"""Progression engine — tip/late, fail_streak, advance/regress (FR-034/034a/035/037/053)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_uuid7
from app.models.catalog import ExerciseStep
from app.models.progression import ProgressionEvent, ProgressionSchema, UserExerciseProgress
from app.models.user import User
from app.models.workout import SessionExerciseLog, WorkoutSession
from app.schemas.common import parse_versioned
from app.schemas.rules import AdvanceRuleV1, ProgressionRulesV1
from app.schemas.sets import SessionSetsV1, SessionSetV1
from app.services.errors import DomainError

OVERRIDE_DAILY_LIMIT = 10


@dataclass(slots=True)
class EvaluateResult:
    is_tip: bool
    progression_skipped: str | None
    goal_met: bool
    events: list[ProgressionEvent] = field(default_factory=list)


def _normalize_side(sides: str | None) -> str | None:
    if sides is None:
        return None
    s = sides.strip().lower()
    if s in {"l", "left"}:
        return "left"
    if s in {"r", "right"}:
        return "right"
    return s


def _set_meets_advance(s: SessionSetV1, adv: AdvanceRuleV1) -> bool:
    """A set qualifies when configured metric thresholds are met (AND if both set)."""
    if adv.min_reps is not None and adv.min_duration_sec is not None:
        return (s.reps or 0) >= adv.min_reps and (s.duration_sec or 0) >= adv.min_duration_sec
    if adv.min_reps is not None:
        return (s.reps or 0) >= adv.min_reps
    if adv.min_duration_sec is not None:
        return (s.duration_sec or 0) >= adv.min_duration_sec
    return False


def goal_met_from_sets(rules: ProgressionRulesV1, sets_payload: dict[str, Any] | None) -> bool:
    """Evaluate advance/goal thresholds against logged sets."""
    if sets_payload is None:
        return False
    sets_doc = parse_versioned(SessionSetsV1, sets_payload)
    sets = sets_doc.sets

    # Satellite / explicit goal (FR-051a).
    if rules.goal is not None:
        g = rules.goal
        if g.type == "completed":
            return len(sets) >= 1
        if g.type == "reps":
            need_sets = g.sets or 1
            min_reps = g.min_reps or 0
            qualifying = [s for s in sets if (s.reps or 0) >= min_reps]
            return len(qualifying) >= need_sets
        if g.type == "duration":
            need_sets = g.sets or 1
            min_dur = g.min_duration_sec or 0
            qualifying = [s for s in sets if (s.duration_sec or 0) >= min_dur]
            return len(qualifying) >= need_sets
        return False

    # CC / mini-progression type A: advance threshold (FR-034 / FR-053).
    if rules.advance is None:
        return False
    adv = rules.advance
    hits = [s for s in sets if _set_meets_advance(s, adv)]
    if not adv.require_both_sides:
        return len(hits) >= adv.sets
    left = [s for s in hits if _normalize_side(s.sides) == "left"]
    right = [s for s in hits if _normalize_side(s.sides) == "right"]
    return len(left) >= adv.sets and len(right) >= adv.sets


class ProgressionEngine:
    async def is_tip_log(
        self,
        db: AsyncSession,
        log: SessionExerciseLog,
    ) -> bool:
        """Tip iff no active evaluated log with strictly greater sort key (FR-035)."""
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
    ) -> tuple[ExerciseStep, ProgressionRulesV1, int]:
        step = await db.scalar(
            select(ExerciseStep).where(
                ExerciseStep.exercise_id == exercise_id,
                ExerciseStep.step_number == step_number,
            )
        )
        if step is None:
            raise DomainError("exercise_step_not_found", http_status=422)
        rules = parse_versioned(ProgressionRulesV1, step.rules)
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

    async def evaluate_log(
        self,
        db: AsyncSession,
        log: SessionExerciseLog,
        *,
        session: WorkoutSession,
    ) -> EvaluateResult:
        """Evaluate one log in the same TX as session persist (FR-035)."""
        if log.session_id != session.id or log.user_id != session.user_id:
            raise DomainError("session_log_mismatch", http_status=422)
        if session.deleted_at is not None or log.superseded_at is not None:
            raise DomainError("session_not_mutable", http_status=409)

        # Idempotent re-apply: do not fold progress / emit events twice (FR-072d).
        if log.goal_evaluated_at is not None:
            skipped: str | None = None
            if log.skipped:
                skipped = "skipped"
            elif not log.counts_for_progression and log.rules_snapshot is not None:
                # Tip path always sets counts_for_progression; goal-only leaves False
                # without late_log. Prefer late_log when snapshot had advance rules.
                snapshot = log.rules_snapshot if isinstance(log.rules_snapshot, dict) else {}
                if snapshot.get("advance") is not None or log.exercise_kind == "cc":
                    skipped = "late_log"
            return EvaluateResult(
                is_tip=bool(log.counts_for_progression),
                progression_skipped=skipped,
                goal_met=bool(log.goal_met),
            )

        if log.skipped:
            log.goal_met = False
            log.goal_evaluated_at = datetime.now(UTC)
            log.counts_for_progression = False
            await db.flush()
            return EvaluateResult(
                is_tip=False,
                progression_skipped="skipped",
                goal_met=False,
            )

        # FR-035: always evaluate against bieżący krok (never client log.step_number).
        progress = await self._get_or_create_progress(
            db,
            user_id=log.user_id,
            exercise_id=log.exercise_id,
            default_step=1,
        )
        step_number = progress.current_step_number
        _step, rules, schema_version = await self._load_step_and_rules(
            db, exercise_id=log.exercise_id, step_number=step_number
        )

        log.step_number = step_number
        log.rules_snapshot = rules.model_dump(mode="json")
        log.progression_schema_version = schema_version
        met = goal_met_from_sets(rules, log.sets)
        log.goal_met = met
        log.goal_evaluated_at = datetime.now(UTC)

        # Goal-only satellites (FR-051a): no tip fold / advance / regress.
        if rules.advance is None:
            log.counts_for_progression = False
            await db.flush()
            return EvaluateResult(is_tip=False, progression_skipped=None, goal_met=met)

        # CC + satellite mini-progression (FR-053): tip vs late fold.
        is_tip = await self.is_tip_log(db, log)
        if not is_tip:
            log.counts_for_progression = False
            await db.flush()
            return EvaluateResult(
                is_tip=False,
                progression_skipped="late_log",
                goal_met=met,
            )

        log.counts_for_progression = True
        events: list[ProgressionEvent] = []
        from_step = progress.current_step_number
        max_step = await self._max_step_number(db, log.exercise_id)

        if met:
            progress.fail_streak = 0
            if from_step < max_step:
                to_step = from_step + 1
                progress.current_step_number = to_step
                ev = ProgressionEvent(
                    id=new_uuid7(),
                    user_id=log.user_id,
                    exercise_id=log.exercise_id,
                    session_id=session.id,
                    event_type="advance",
                    from_step=from_step,
                    to_step=to_step,
                    reason="advance_threshold_met",
                    rules_snapshot=log.rules_snapshot,
                    progression_schema_version=schema_version,
                )
                db.add(ev)
                events.append(ev)
        elif rules.regress is not None:
            fail_needed = rules.regress.fail_sessions
            progress.fail_streak += 1
            if progress.fail_streak >= fail_needed and from_step > 1:
                to_step = from_step - 1
                progress.current_step_number = to_step
                progress.fail_streak = 0
                ev = ProgressionEvent(
                    id=new_uuid7(),
                    user_id=log.user_id,
                    exercise_id=log.exercise_id,
                    session_id=session.id,
                    event_type="regress",
                    from_step=from_step,
                    to_step=to_step,
                    reason="fail_streak_threshold",
                    rules_snapshot=log.rules_snapshot,
                    progression_schema_version=schema_version,
                )
                db.add(ev)
                events.append(ev)

        progress.last_session_at = log.performed_at
        await db.flush()
        return EvaluateResult(
            is_tip=True,
            progression_skipped=None,
            goal_met=met,
            events=events,
        )

    async def manual_override(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        exercise_id: UUID,
        to_step: int,
        reason: str | None = None,
    ) -> ProgressionEvent:
        """First-class step override (FR-038 / US-016b) — resets fail_streak."""
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
            rules_snapshot=rules.model_dump(mode="json"),
            progression_schema_version=schema_version,
        )
        db.add(ev)
        await db.flush()
        return ev
