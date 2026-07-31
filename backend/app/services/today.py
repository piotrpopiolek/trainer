"""GET /today aggregator (FR-040b / FR-024a)."""

from __future__ import annotations

from datetime import date, datetime
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
from app.models.user import User
from app.models.workout import WorkoutSession
from app.schemas.api import (
    TodayCcExerciseV1,
    TodaySatelliteV1,
    TodaySessionDto,
)
from app.services.cc_day import get_active_enrollment, resolve_cc_day_for_user
from app.services.errors import DomainError
from app.services.locale import resolve_locale
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


async def build_today(
    db: AsyncSession,
    *,
    user: User,
    local_date: date | None = None,
    cc_day_override: int | None = None,
    locale: str | None = None,
) -> TodaySessionDto:
    day = local_date or _local_today(user.timezone)
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
            links = (
                await db.scalars(
                    select(ProgramDayExercise)
                    .where(ProgramDayExercise.program_day_id == program_day.id)
                    .order_by(ProgramDayExercise.sort_order)
                )
            ).all()
            for link in links:
                ex = await db.scalar(select(Exercise).where(Exercise.id == link.exercise_id))
                if ex is None:
                    continue
                tr = await db.scalar(
                    select(ExerciseTranslation).where(
                        ExerciseTranslation.exercise_id == ex.id,
                        ExerciseTranslation.locale == resolved,
                    )
                )
                progress = await db.scalar(
                    select(UserExerciseProgress).where(
                        UserExerciseProgress.user_id == user.id,
                        UserExerciseProgress.exercise_id == ex.id,
                    )
                )
                step_n = progress.current_step_number if progress else 1
                step = await db.scalar(
                    select(ExerciseStep).where(
                        ExerciseStep.exercise_id == ex.id,
                        ExerciseStep.step_number == step_n,
                    )
                )
                rules = step.rules if step is not None else {}
                step_tr = None
                if step is not None:
                    step_tr = await db.scalar(
                        select(ExerciseStepTranslation).where(
                            ExerciseStepTranslation.exercise_step_id == step.id,
                            ExerciseStepTranslation.locale == resolved,
                        )
                    )
                standards = None
                if isinstance(rules, dict):
                    standards = rules.get("standards")
                cc_exercises.append(
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

    satellites_out: list[TodaySatelliteV1] = []
    sats = (
        await db.scalars(
            select(Exercise).where(
                Exercise.user_id == user.id,
                Exercise.kind == "satellite",
                Exercise.deleted_at.is_(None),
            )
        )
    ).all()
    for sat in sats:
        if not _satellite_due_today(sat, local_date=day, is_rest_day=cc.is_rest_day):
            continue
        progress = await db.scalar(
            select(UserExerciseProgress).where(
                UserExerciseProgress.user_id == user.id,
                UserExerciseProgress.exercise_id == sat.id,
            )
        )
        step_number = progress.current_step_number if progress is not None else 1
        step = await db.scalar(
            select(ExerciseStep).where(
                ExerciseStep.exercise_id == sat.id,
                ExerciseStep.step_number == step_number,
            )
        )
        cfg = None
        if sat.current_config_version_id is not None:
            cfg = await db.get(SatelliteConfigVersion, sat.current_config_version_id)
        goal = None
        if step is not None and isinstance(step.rules, dict):
            goal = step.rules.get("goal")
        satellites_out.append(
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
            )
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
