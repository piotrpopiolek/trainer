"""GET /today aggregator (FR-040b / FR-024a)."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import (
    Exercise,
    ExerciseStep,
    ExerciseStepTranslation,
    ExerciseTranslation,
    ProgramDay,
    ProgramDayExercise,
    SatelliteConfigVersion,
)
from app.models.progression import UserExerciseProgress
from app.models.satellite_progress import SatelliteRegressionRecommendation
from app.models.user import User
from app.models.workout import WorkoutSession
from app.schemas.api import (
    SatellitePendingRegressionV1,
    TodayCcExerciseV1,
    TodaySatelliteV1,
    TodaySessionDto,
)
from app.services.cc_day import get_active_enrollment, resolve_cc_day_for_user
from app.services.errors import DomainError
from app.services.locale import resolve_locale
from app.services.satellite_progression import SatelliteProgressionOrchestrator
from app.services.satellites import promote_pending_satellite_configs
from app.services.sessions import progress_to_read, session_to_read


def _local_today(timezone_name: str) -> date:
    try:
        return datetime.now(ZoneInfo(timezone_name)).date()
    except ZoneInfoNotFoundError as exc:
        raise DomainError("invalid_timezone", http_status=422) from exc


def _satellite_due_today(ex: Exercise, *, local_date: date, is_rest_day: bool) -> bool:
    if ex.schedule_kind == "daily":
        return True
    if ex.schedule_kind == "weekdays":
        wd = local_date.isoweekday()
        return bool(ex.weekdays and wd in ex.weekdays)
    if ex.schedule_kind == "category":
        if ex.schedule_category == "anytime":
            return True
        if ex.schedule_category == "rest_day":
            return is_rest_day
        if ex.schedule_category == "post_workout":
            return not is_rest_day
    return False


async def _build_cc_exercises(
    db: AsyncSession,
    *,
    user_id: UUID,
    program_day_id: UUID,
    resolved_locale: str,
) -> list[TodayCcExerciseV1]:
    links = (
        await db.scalars(
            select(ProgramDayExercise)
            .where(ProgramDayExercise.program_day_id == program_day_id)
            .order_by(ProgramDayExercise.sort_order)
        )
    ).all()
    if not links:
        return []

    exercise_ids = [link.exercise_id for link in links]
    exercises = {
        ex.id: ex
        for ex in (
            await db.scalars(select(Exercise).where(Exercise.id.in_(exercise_ids)))
        ).all()
    }
    translations = {
        tr.exercise_id: tr
        for tr in (
            await db.scalars(
                select(ExerciseTranslation).where(
                    ExerciseTranslation.exercise_id.in_(exercise_ids),
                    ExerciseTranslation.locale == resolved_locale,
                )
            )
        ).all()
    }
    progress_by_ex = {
        p.exercise_id: p
        for p in (
            await db.scalars(
                select(UserExerciseProgress).where(
                    UserExerciseProgress.user_id == user_id,
                    UserExerciseProgress.exercise_id.in_(exercise_ids),
                )
            )
        ).all()
    }
    step_numbers = {
        eid: (progress_by_ex[eid].current_step_number if eid in progress_by_ex else 1)
        for eid in exercise_ids
    }
    steps = (
        await db.scalars(
            select(ExerciseStep).where(ExerciseStep.exercise_id.in_(exercise_ids))
        )
    ).all()
    step_by_ex_num: dict[tuple[UUID, int], ExerciseStep] = {
        (s.exercise_id, s.step_number): s for s in steps
    }
    current_steps = [
        step_by_ex_num[(eid, step_numbers[eid])]
        for eid in exercise_ids
        if (eid, step_numbers[eid]) in step_by_ex_num
    ]
    step_ids = [s.id for s in current_steps]
    step_trs = {
        tr.exercise_step_id: tr
        for tr in (
            (
                await db.scalars(
                    select(ExerciseStepTranslation).where(
                        ExerciseStepTranslation.exercise_step_id.in_(step_ids),
                        ExerciseStepTranslation.locale == resolved_locale,
                    )
                )
            ).all()
            if step_ids
            else []
        )
    }

    out: list[TodayCcExerciseV1] = []
    for link in links:
        ex = exercises.get(link.exercise_id)
        if ex is None:
            continue
        tr = translations.get(ex.id)
        step_n = step_numbers[ex.id]
        step = step_by_ex_num.get((ex.id, step_n))
        rules = step.rules if step is not None else {}
        step_tr = step_trs.get(step.id) if step is not None else None
        standards = rules.get("standards") if isinstance(rules, dict) else None
        out.append(
            TodayCcExerciseV1(
                exercise_id=ex.id,
                slug=ex.slug,
                name=tr.name if tr else (ex.slug or str(ex.id)),
                current_step_number=step_n,
                advance=rules.get("advance") if isinstance(rules, dict) else None,
                regress=rules.get("regress") if isinstance(rules, dict) else None,
                standards=standards if isinstance(standards, dict) else None,
                step_name=step_tr.name if step_tr else None,
                description=step_tr.description if step_tr else None,
                execution=step_tr.execution if step_tr else None,
                rationale=step_tr.rationale if step_tr else None,
                technique=step_tr.technique if step_tr else None,
            )
        )
    return out


async def _build_satellites(
    db: AsyncSession,
    *,
    user_id: UUID,
    local_date: date,
    is_rest_day: bool,
) -> list[TodaySatelliteV1]:
    sats = (
        await db.scalars(
            select(Exercise).where(
                Exercise.user_id == user_id,
                Exercise.kind == "satellite",
                Exercise.deleted_at.is_(None),
            )
        )
    ).all()
    due = [
        s
        for s in sats
        if _satellite_due_today(s, local_date=local_date, is_rest_day=is_rest_day)
    ]
    if not due:
        return []

    sat_ids = [s.id for s in due]
    progress_by_ex = {
        p.exercise_id: p
        for p in (
            await db.scalars(
                select(UserExerciseProgress).where(
                    UserExerciseProgress.user_id == user_id,
                    UserExerciseProgress.exercise_id.in_(sat_ids),
                )
            )
        ).all()
    }
    step_numbers = {
        sid: (
            progress_by_ex[sid].current_step_number
            if sid in progress_by_ex
            else 1
        )
        for sid in sat_ids
    }
    steps = (
        await db.scalars(select(ExerciseStep).where(ExerciseStep.exercise_id.in_(sat_ids)))
    ).all()
    step_by_id: dict[UUID, ExerciseStep] = {s.id: s for s in steps}
    step_by_ex_num = {(s.exercise_id, s.step_number): s for s in steps}

    cfg_ids = [
        s.current_config_version_id
        for s in due
        if s.current_config_version_id is not None
    ]
    configs = {
        c.id: c
        for c in (
            (
                await db.scalars(
                    select(SatelliteConfigVersion).where(
                        SatelliteConfigVersion.id.in_(cfg_ids)
                    )
                )
            ).all()
            if cfg_ids
            else []
        )
    }

    recs = (
        await db.scalars(
            select(SatelliteRegressionRecommendation).where(
                SatelliteRegressionRecommendation.user_id == user_id,
                SatelliteRegressionRecommendation.exercise_id.in_(sat_ids),
                SatelliteRegressionRecommendation.status == "pending",
            )
        )
    ).all()
    rec_by_ex = {r.exercise_id: r for r in recs}

    out: list[TodaySatelliteV1] = []
    for sat in due:
        step_number = step_numbers[sat.id]
        step = step_by_ex_num.get((sat.id, step_number))
        cfg = (
            configs.get(sat.current_config_version_id)
            if sat.current_config_version_id is not None
            else None
        )
        goal = None
        if step is not None and isinstance(step.rules, dict):
            goal = step.rules.get("goal")
        pending_reg = None
        rec = rec_by_ex.get(sat.id)
        if rec is not None:
            from_step_row = step_by_id.get(rec.from_step_id)
            to_step_row = step_by_id.get(rec.to_step_id)
            if from_step_row is not None and to_step_row is not None:
                pending_reg = SatellitePendingRegressionV1(
                    id=rec.id,
                    from_step=from_step_row.step_number,
                    to_step=to_step_row.step_number,
                    status="pending",
                )
        out.append(
            TodaySatelliteV1(
                exercise_id=sat.id,
                name=sat.name or str(sat.id),
                exercise_type=sat.exercise_type,
                schedule_kind=sat.schedule_kind,
                schedule_category=sat.schedule_category,
                current_step_number=step_number,
                step_name=step.name if step is not None else None,
                active_metrics=sat.active_metrics,
                goal=goal if isinstance(goal, dict) else None,
                config_version_id=sat.current_config_version_id,
                config_hash=cfg.config_hash.hex() if cfg is not None else None,
                pending_regression=pending_reg,
            )
        )
    return out


async def build_today(
    db: AsyncSession,
    *,
    user: User,
    local_date: date | None = None,
    cc_day_override: int | None = None,
    locale: str | None = None,
) -> TodaySessionDto:
    day = local_date or _local_today(user.timezone)
    # Slice E: finalize overdue failed days before surfacing progress (FR-053).
    # Commit immediately so GET /today side-effects survive later read errors.
    await SatelliteProgressionOrchestrator().finalize_due_outcomes(
        db, user_id=user.id
    )
    await promote_pending_satellite_configs(db, user=user, local_date=day)
    await db.commit()
    requested, resolved = resolve_locale(requested=locale, user_locale=user.locale)
    cc = await resolve_cc_day_for_user(db, user, local_date=day)
    enrollment = await get_active_enrollment(db, user.id)
    if enrollment is None:
        raise DomainError("enrollment_required", http_status=422)

    override: int | None = None
    day_index = cc.day_index
    if cc_day_override is not None:
        if not cc.is_rest_day:
            raise DomainError("cc_day_override_not_allowed", http_status=422)
        if cc_day_override not in (1, 2, 3):
            raise DomainError("invalid_cc_day_override", http_status=422)
        override = cc_day_override
        day_index = override

    cc_exercises: list[TodayCcExerciseV1] = []
    if day_index is not None:
        program_day = await db.scalar(
            select(ProgramDay).where(
                ProgramDay.program_id == enrollment.program_id,
                ProgramDay.day_index == day_index,
            )
        )
        if program_day is not None:
            cc_exercises = await _build_cc_exercises(
                db,
                user_id=user.id,
                program_day_id=program_day.id,
                resolved_locale=resolved,
            )

    satellites_out = await _build_satellites(
        db,
        user_id=user.id,
        local_date=day,
        is_rest_day=cc.is_rest_day,
    )

    sessions_rows = (
        await db.scalars(
            select(WorkoutSession).where(
                WorkoutSession.user_id == user.id,
                WorkoutSession.local_date == day,
                WorkoutSession.deleted_at.is_(None),
            )
        )
    ).all()
    sessions = [await session_to_read(db, s) for s in sessions_rows]

    progress_rows = (
        await db.scalars(
            select(UserExerciseProgress)
            .join(Exercise, Exercise.id == UserExerciseProgress.exercise_id)
            .where(
                UserExerciseProgress.user_id == user.id,
                Exercise.kind == "cc",
                UserExerciseProgress.is_active.is_(True),
            )
        )
    ).all()

    await db.commit()  # persist promote_pending_schedule if any
    return TodaySessionDto(
        local_date=day,
        timezone=user.timezone,
        split_day=day_index,
        is_rest_day=cc.is_rest_day,
        cc_day_override=override,
        requested_locale=requested,
        resolved_locale=resolved,
        cc_exercises=cc_exercises,
        satellites=satellites_out,
        sessions=sessions,
        progress=[progress_to_read(p) for p in progress_rows],
    )
