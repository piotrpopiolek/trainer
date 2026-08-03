"""Transactional satellite progression orchestrator (goal-only + mini-progression)."""

from __future__ import annotations

import hmac
from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_uuid7
from app.domain.progression_types import EventProposal, ProgressionEvaluation
from app.domain.satellite_progression import (
    DailyOutcomeState,
    SatelliteEvaluationInput,
    SatelliteProgressionEvaluator,
    compute_finalize_after,
    finalize_pending_failure,
    fold_daily_outcome,
    propose_regression_suggestion,
)
from app.models.catalog import SatelliteConfigVersion
from app.models.progression import ProgressionEvent, UserExerciseProgress
from app.models.satellite_progress import (
    SatelliteDailyOutcome,
    SatelliteRegressionRecommendation,
)
from app.models.user import User
from app.models.workout import SessionExerciseLog, WorkoutSession
from app.schemas.satellite import SatelliteConfigStepV1, parse_satellite_config_document
from app.services.errors import DomainError


def _outcome_to_state(row: SatelliteDailyOutcome) -> DailyOutcomeState:
    return DailyOutcomeState(
        status=row.status,  # type: ignore[arg-type]
        has_attempt=row.has_attempt,
        has_success=row.has_success,
        result=row.result,  # type: ignore[arg-type]
        finalize_after=row.finalize_after,
        finalized_at=row.finalized_at,
        representative_log_id=(
            str(row.representative_log_id) if row.representative_log_id else None
        ),
        result_snapshot=row.result_snapshot,
    )


def _apply_state(row: SatelliteDailyOutcome, state: DailyOutcomeState) -> None:
    row.status = state.status
    row.has_attempt = state.has_attempt
    row.has_success = state.has_success
    row.result = state.result
    row.finalize_after = state.finalize_after
    row.finalized_at = state.finalized_at
    row.representative_log_id = (
        UUID(state.representative_log_id) if state.representative_log_id else None
    )
    row.result_snapshot = state.result_snapshot
    row.updated_at = datetime.now(UTC)


class SatelliteProgressionOrchestrator:
    def __init__(self) -> None:
        self._evaluator = SatelliteProgressionEvaluator()

    @staticmethod
    def _bump_revision(progress: UserExerciseProgress) -> int:
        progress.progress_revision = int(progress.progress_revision) + 1
        progress.updated_at = datetime.now(UTC)
        return progress.progress_revision

    async def _advisory_lock(
        self, db: AsyncSession, *, user_id: UUID, exercise_id: UUID
    ) -> None:
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
            {"k": f"{user_id}:{exercise_id}"},
        )

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

    async def _get_or_create_outcome(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        exercise_id: UUID,
        local_date: date,
        step_id: UUID,
        config_version_id: UUID,
        finalize_after: datetime,
    ) -> SatelliteDailyOutcome:
        del finalize_after  # set by fold on first attempt
        values = {
            "id": new_uuid7(),
            "user_id": user_id,
            "exercise_id": exercise_id,
            "local_date": local_date,
            "step_id": step_id,
            "config_version_id": config_version_id,
            "has_attempt": False,
            "has_success": False,
            "status": "pending",
        }
        stmt = (
            insert(SatelliteDailyOutcome)
            .values(**values)
            .on_conflict_do_nothing(
                constraint="uq_satellite_daily_outcomes_user_ex_date"
            )
        )
        await db.execute(stmt)
        row = await db.scalar(
            select(SatelliteDailyOutcome)
            .where(
                SatelliteDailyOutcome.user_id == user_id,
                SatelliteDailyOutcome.exercise_id == exercise_id,
                SatelliteDailyOutcome.local_date == local_date,
            )
            .with_for_update()
        )
        if row is None:
            raise DomainError("satellite_outcome_create_failed", http_status=500)
        return row

    async def _stale_pending_recommendations(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        exercise_id: UUID,
        now: datetime,
    ) -> int:
        result = await db.execute(
            update(SatelliteRegressionRecommendation)
            .where(
                SatelliteRegressionRecommendation.user_id == user_id,
                SatelliteRegressionRecommendation.exercise_id == exercise_id,
                SatelliteRegressionRecommendation.status == "pending",
            )
            .values(status="stale", decided_at=now)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def _maybe_create_suggestion(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        exercise_id: UUID,
        progress: UserExerciseProgress,
        outcome: SatelliteDailyOutcome,
        config_version_id: UUID,
        threshold: int,
        step_ladder: list[tuple[int, str]],
        rules_snapshot: dict[str, Any] | None,
        schema_version: int | None,
        session_id: UUID | None,
    ) -> ProgressionEvent | None:
        proposal = propose_regression_suggestion(
            step_number=progress.current_step_number,
            fail_streak=progress.fail_streak,
            threshold=threshold,
            step_ladder=step_ladder,
        )
        if proposal is None:
            return None
        existing = await db.scalar(
            select(SatelliteRegressionRecommendation.id).where(
                SatelliteRegressionRecommendation.user_id == user_id,
                SatelliteRegressionRecommendation.exercise_id == exercise_id,
                SatelliteRegressionRecommendation.status == "pending",
            )
        )
        if existing is not None:
            return None
        rec = SatelliteRegressionRecommendation(
            id=new_uuid7(),
            user_id=user_id,
            exercise_id=exercise_id,
            trigger_outcome_id=outcome.id,
            config_version_id=config_version_id,
            from_step_id=UUID(proposal.from_step_id),
            to_step_id=UUID(proposal.to_step_id),
            expected_progress_revision=progress.progress_revision,
            status="pending",
        )
        try:
            async with db.begin_nested():
                db.add(rec)
                await db.flush()
        except IntegrityError:
            return None
        snapshot = rules_snapshot
        if snapshot is None or "schema_version" not in snapshot:
            snapshot = {"schema_version": schema_version or 1}
        ev = ProgressionEvent(
            id=new_uuid7(),
            user_id=user_id,
            exercise_id=exercise_id,
            session_id=session_id,
            event_type="satellite_regress_suggested",
            from_step=proposal.from_step,
            to_step=proposal.to_step,
            reason=f"failed_days>={proposal.threshold}",
            rules_snapshot=snapshot,
            progression_schema_version=schema_version or 1,
        )
        db.add(ev)
        return ev

    async def decide_recommendation(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        exercise_id: UUID,
        recommendation_id: UUID,
        decision: Literal["accept", "decline"],
        commit: bool = True,
    ) -> tuple[
        SatelliteRegressionRecommendation,
        UserExerciseProgress,
        ProgressionEvent | None,
    ]:
        await self._advisory_lock(db, user_id=user_id, exercise_id=exercise_id)
        rec = await db.scalar(
            select(SatelliteRegressionRecommendation)
            .where(
                SatelliteRegressionRecommendation.id == recommendation_id,
                SatelliteRegressionRecommendation.user_id == user_id,
                SatelliteRegressionRecommendation.exercise_id == exercise_id,
            )
            .with_for_update()
        )
        if rec is None:
            raise DomainError("not_found", http_status=404)

        progress = await db.scalar(
            select(UserExerciseProgress)
            .where(
                UserExerciseProgress.user_id == user_id,
                UserExerciseProgress.exercise_id == exercise_id,
            )
            .with_for_update()
        )
        if progress is None:
            raise DomainError("not_found", http_status=404)

        now = datetime.now(UTC)
        if rec.status == "accepted" and decision == "accept":
            return rec, progress, None
        if rec.status == "declined" and decision == "decline":
            return rec, progress, None
        if rec.status != "pending":
            raise DomainError("recommendation_not_pending", http_status=409)

        cas_ok = (
            progress.progress_revision == rec.expected_progress_revision
            and progress.current_step_id == rec.from_step_id
        )
        if not cas_ok:
            rec.status = "stale"
            rec.decided_at = now
            await db.flush()
            if commit:
                await db.commit()
            raise DomainError("recommendation_stale", http_status=409)

        event: ProgressionEvent | None = None
        if decision == "accept":
            to_number = progress.current_step_number - 1
            if to_number < 1:
                rec.status = "stale"
                rec.decided_at = now
                await db.flush()
                if commit:
                    await db.commit()
                raise DomainError("recommendation_stale", http_status=409)
            from_number = progress.current_step_number
            progress.current_step_number = to_number
            progress.current_step_id = rec.to_step_id
            progress.fail_streak = 0
            self._bump_revision(progress)
            rec.status = "accepted"
            rec.decided_at = now
            event = ProgressionEvent(
                id=new_uuid7(),
                user_id=user_id,
                exercise_id=exercise_id,
                session_id=None,
                event_type="satellite_regress_confirmed",
                from_step=from_number,
                to_step=to_number,
                reason="recommendation_accepted",
                rules_snapshot={"schema_version": 1},
                progression_schema_version=1,
            )
            db.add(event)
        else:
            progress.fail_streak = 0
            self._bump_revision(progress)
            rec.status = "declined"
            rec.decided_at = now

        await db.flush()
        if commit:
            await db.commit()
            await db.refresh(rec)
            await db.refresh(progress)
            if event is not None:
                await db.refresh(event)
        return rec, progress, event

    async def finalize_due_outcomes(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        exercise_id: UUID | None = None,
        now: datetime | None = None,
    ) -> int:
        """Lazy finalizer for pending failed days (Today / session / sync / cron)."""
        moment = now or datetime.now(UTC)
        q = select(SatelliteDailyOutcome).where(
            SatelliteDailyOutcome.user_id == user_id,
            SatelliteDailyOutcome.status == "pending",
        )
        if exercise_id is not None:
            q = q.where(SatelliteDailyOutcome.exercise_id == exercise_id)
        rows = (
            await db.scalars(
                q.order_by(
                    SatelliteDailyOutcome.exercise_id,
                    SatelliteDailyOutcome.local_date,
                ).execution_options(populate_existing=True)
            )
        ).all()
        finalized = 0
        for row in rows:
            if row.has_success or not row.has_attempt:
                continue
            if row.finalize_after is None or row.finalize_after > moment:
                continue
            await self._advisory_lock(
                db, user_id=user_id, exercise_id=row.exercise_id
            )
            locked = await db.scalar(
                select(SatelliteDailyOutcome)
                .where(SatelliteDailyOutcome.id == row.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if locked is None:
                continue
            progress = await db.scalar(
                select(UserExerciseProgress)
                .where(
                    UserExerciseProgress.user_id == user_id,
                    UserExerciseProgress.exercise_id == locked.exercise_id,
                )
                .with_for_update()
            )
            step_number = progress.current_step_number if progress is not None else 1
            fail_streak = progress.fail_streak if progress is not None else 0
            new_state, streak, did = finalize_pending_failure(
                _outcome_to_state(locked),
                now=moment,
                step_number=step_number,
                fail_streak=fail_streak,
            )
            if not did:
                continue
            _apply_state(locked, new_state)
            if progress is not None and streak is not None:
                progress.fail_streak = streak
                locked.applied_progress_revision = self._bump_revision(progress)
                cfg = await db.get(SatelliteConfigVersion, locked.config_version_id)
                if cfg is not None:
                    document = parse_satellite_config_document(cfg.document)
                    if document.progression.mode == "steps":
                        ordered = sorted(
                            document.steps, key=lambda s: (s.sort_order, str(s.step_id))
                        )
                        ladder = [(s.sort_order, str(s.step_id)) for s in ordered]
                        await self._maybe_create_suggestion(
                            db,
                            user_id=user_id,
                            exercise_id=locked.exercise_id,
                            progress=progress,
                            outcome=locked,
                            config_version_id=cfg.id,
                            threshold=document.progression.regression.threshold,
                            step_ladder=ladder,
                            rules_snapshot=None,
                            schema_version=cfg.schema_version,
                            session_id=None,
                        )
            finalized += 1
        await db.flush()
        return finalized

    async def _fold_steps_outcome(
        self,
        db: AsyncSession,
        *,
        log: SessionExerciseLog,
        progress: UserExerciseProgress,
        config: SatelliteConfigVersion,
        cfg_step: SatelliteConfigStepV1,
        evaluation: ProgressionEvaluation,
        eligible: bool,
        already_evaluated: bool,
        step_ladder: list[tuple[int, str]],
        session: WorkoutSession,
        threshold: int,
    ) -> tuple[ProgressionEvaluation, list[ProgressionEvent]]:
        user = await db.get(User, log.user_id)
        tz_name = user.timezone if user is not None else "UTC"
        now = datetime.now(UTC)
        deadline = compute_finalize_after(log.local_date, timezone_name=tz_name)

        await self._advisory_lock(
            db, user_id=log.user_id, exercise_id=log.exercise_id
        )
        progress_locked = await db.scalar(
            select(UserExerciseProgress)
            .where(
                UserExerciseProgress.user_id == log.user_id,
                UserExerciseProgress.exercise_id == log.exercise_id,
            )
            .with_for_update()
        )
        if progress_locked is None:
            progress_locked = progress

        if not eligible or log.skipped:
            # Load existing pending day (do not create) so overdue failures still
            # finalize under the same advisory→row lock order.
            existing = await db.scalar(
                select(SatelliteDailyOutcome)
                .where(
                    SatelliteDailyOutcome.user_id == log.user_id,
                    SatelliteDailyOutcome.exercise_id == log.exercise_id,
                    SatelliteDailyOutcome.local_date == log.local_date,
                )
                .with_for_update()
            )
            fold = fold_daily_outcome(
                _outcome_to_state(existing) if existing is not None else None,
                goal_met=evaluation.goal_met,
                skipped=log.skipped,
                eligible=eligible,
                already_evaluated=already_evaluated,
                log_id=str(log.id),
                now=now,
                finalize_after=deadline,
                step_number=progress_locked.current_step_number,
                fail_streak=progress_locked.fail_streak,
                step_ladder=step_ladder,
            )
            events: list[ProgressionEvent] = []
            if existing is not None:
                _apply_state(existing, fold.state)
                if (
                    fold.newly_finalized
                    and fold.state.result == "failure"
                    and fold.fail_streak is not None
                ):
                    progress_locked.fail_streak = fold.fail_streak
                    existing.applied_progress_revision = self._bump_revision(
                        progress_locked
                    )
                    suggested = await self._maybe_create_suggestion(
                        db,
                        user_id=log.user_id,
                        exercise_id=log.exercise_id,
                        progress=progress_locked,
                        outcome=existing,
                        config_version_id=config.id,
                        threshold=threshold,
                        step_ladder=step_ladder,
                        rules_snapshot=evaluation.rules_snapshot,
                        schema_version=evaluation.progression_schema_version,
                        session_id=session.id,
                    )
                    if suggested is not None:
                        events.append(suggested)
            return (
                ProgressionEvaluation(
                    goal_met=evaluation.goal_met,
                    counts_for_progression=fold.counts_for_progression,
                    progression_skipped=fold.progression_skipped
                    or evaluation.progression_skipped,
                    rules_snapshot=evaluation.rules_snapshot,
                    progression_schema_version=evaluation.progression_schema_version,
                    step_number=evaluation.step_number,
                    events=tuple(
                        EventProposal(
                            event_type=e.event_type,
                            from_step=e.from_step,
                            to_step=e.to_step,
                            reason=e.reason,
                            rules_snapshot=e.rules_snapshot,
                            progression_schema_version=e.progression_schema_version,
                        )
                        for e in events
                    ),
                ),
                events,
            )

        outcome = await self._get_or_create_outcome(
            db,
            user_id=log.user_id,
            exercise_id=log.exercise_id,
            local_date=log.local_date,
            step_id=cfg_step.step_id,
            config_version_id=config.id,
            finalize_after=deadline,
        )
        fold = fold_daily_outcome(
            _outcome_to_state(outcome),
            goal_met=evaluation.goal_met,
            skipped=False,
            eligible=True,
            already_evaluated=already_evaluated,
            log_id=str(log.id),
            now=now,
            finalize_after=deadline,
            step_number=progress_locked.current_step_number,
            fail_streak=progress_locked.fail_streak,
            step_ladder=step_ladder,
        )
        _apply_state(outcome, fold.state)

        events: list[ProgressionEvent] = []
        if fold.newly_finalized and fold.state.result == "success":
            await self._stale_pending_recommendations(
                db,
                user_id=log.user_id,
                exercise_id=log.exercise_id,
                now=now,
            )
            if fold.fail_streak is not None:
                progress_locked.fail_streak = fold.fail_streak
            if (
                fold.advance_to is not None
                and fold.advance_to_step_id is not None
                and fold.advance_from is not None
            ):
                progress_locked.current_step_number = fold.advance_to
                progress_locked.current_step_id = UUID(fold.advance_to_step_id)
                ev = ProgressionEvent(
                    id=new_uuid7(),
                    user_id=log.user_id,
                    exercise_id=log.exercise_id,
                    session_id=session.id,
                    event_type="satellite_advance",
                    from_step=fold.advance_from,
                    to_step=fold.advance_to,
                    reason="daily_outcome_success",
                    rules_snapshot=evaluation.rules_snapshot,
                    progression_schema_version=evaluation.progression_schema_version,
                )
                db.add(ev)
                events.append(ev)
            outcome.applied_progress_revision = self._bump_revision(progress_locked)
        elif fold.newly_finalized and fold.state.result == "failure":
            if fold.fail_streak is not None:
                progress_locked.fail_streak = fold.fail_streak
                outcome.applied_progress_revision = self._bump_revision(progress_locked)
                suggested = await self._maybe_create_suggestion(
                    db,
                    user_id=log.user_id,
                    exercise_id=log.exercise_id,
                    progress=progress_locked,
                    outcome=outcome,
                    config_version_id=config.id,
                    threshold=threshold,
                    step_ladder=step_ladder,
                    rules_snapshot=evaluation.rules_snapshot,
                    schema_version=evaluation.progression_schema_version,
                    session_id=session.id,
                )
                if suggested is not None:
                    events.append(suggested)
        elif fold.fail_streak is not None:
            progress_locked.fail_streak = fold.fail_streak

        return (
            ProgressionEvaluation(
                goal_met=evaluation.goal_met,
                counts_for_progression=fold.counts_for_progression,
                progression_skipped=fold.progression_skipped,
                rules_snapshot=evaluation.rules_snapshot,
                progression_schema_version=evaluation.progression_schema_version,
                step_number=evaluation.step_number,
                events=tuple(
                    EventProposal(
                        event_type=e.event_type,
                        from_step=e.from_step,
                        to_step=e.to_step,
                        reason=e.reason,
                        rules_snapshot=e.rules_snapshot,
                        progression_schema_version=e.progression_schema_version,
                    )
                    for e in events
                ),
            ),
            events,
        )

    async def evaluate_log(
        self,
        db: AsyncSession,
        log: SessionExerciseLog,
        *,
        session: WorkoutSession,
    ) -> tuple[ProgressionEvaluation, list[ProgressionEvent]]:
        if log.session_id != session.id or log.user_id != session.user_id:
            raise DomainError("session_log_mismatch", http_status=422)
        if session.deleted_at is not None or log.superseded_at is not None:
            raise DomainError("session_not_mutable", http_status=409)
        if log.exercise_kind != "satellite":
            raise DomainError("exercise_kind_mismatch", http_status=422)

        already_evaluated = log.goal_evaluated_at is not None
        config = await self._load_config_version(
            db,
            user_id=log.user_id,
            exercise_id=log.exercise_id,
            config_version_id=log.satellite_config_version_id,
            config_hash=log.satellite_config_hash,
        )
        document = parse_satellite_config_document(config.document)
        # Advisory lock before row lock — same order as decide_recommendation /
        # finalize_due_outcomes (avoids ABBA deadlock with concurrent decide).
        await self._advisory_lock(
            db, user_id=log.user_id, exercise_id=log.exercise_id
        )
        progress = await db.scalar(
            select(UserExerciseProgress)
            .where(
                UserExerciseProgress.user_id == log.user_id,
                UserExerciseProgress.exercise_id == log.exercise_id,
            )
            .with_for_update()
        )
        step_number = progress.current_step_number if progress is not None else 1

        ordered = sorted(document.steps, key=lambda s: (s.sort_order, str(s.step_id)))
        step_ladder = [(s.sort_order, str(s.step_id)) for s in ordered]
        cfg_step: SatelliteConfigStepV1
        if document.progression.mode == "goal_only":
            cfg_step = ordered[0]
        elif progress is not None and progress.current_step_id is not None:
            matched = next(
                (s for s in ordered if s.step_id == progress.current_step_id), None
            )
            if matched is None:
                raise DomainError("satellite_step_not_in_config", http_status=422)
            cfg_step = matched
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
                    already_evaluated=already_evaluated,
                    persisted_goal_met=bool(log.goal_met),
                    progression_eligible=eligible,
                    step_number=step_number,
                    schema_version=config.schema_version,
                )
            )
        except ValueError as exc:
            code = str(exc).split(":", 1)[0]
            raise DomainError(code, http_status=422) from exc

        events: list[ProgressionEvent] = []
        if document.progression.mode == "steps" and progress is not None:
            evaluation, events = await self._fold_steps_outcome(
                db,
                log=log,
                progress=progress,
                config=config,
                cfg_step=cfg_step,
                evaluation=evaluation,
                eligible=eligible,
                already_evaluated=already_evaluated,
                step_ladder=step_ladder,
                session=session,
                threshold=document.progression.regression.threshold,
            )

        log.step_number = evaluation.step_number
        log.rules_snapshot = evaluation.rules_snapshot
        log.progression_schema_version = evaluation.progression_schema_version
        log.goal_met = evaluation.goal_met
        if log.goal_evaluated_at is None:
            log.goal_evaluated_at = datetime.now(UTC)
        log.counts_for_progression = (
            False
            if document.progression.mode == "goal_only"
            else evaluation.counts_for_progression
        )
        log.progression_skipped = evaluation.progression_skipped
        if progress is not None:
            progress.last_session_at = log.performed_at
        await db.flush()
        return evaluation, events
