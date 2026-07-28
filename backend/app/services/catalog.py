"""CC catalog read + ETag (FR-075a / FR-007)."""

from __future__ import annotations

from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import (
    Exercise,
    ExerciseStep,
    ExerciseStepTranslation,
    ExerciseTranslation,
    Program,
    ProgramDay,
    ProgramDayExercise,
    ProgramDayTranslation,
    ProgramTranslation,
)
from app.schemas.api import (
    CatalogCcResponseV1,
    CatalogDayV1,
    CatalogExerciseV1,
    CatalogStepV1,
)
from app.services.locale import DEFAULT_LOCALE, resolve_locale


async def _locale_complete(db: AsyncSession, *, program_id: UUID, locale: str) -> bool:
    prog_tr = await db.scalar(
        select(ProgramTranslation).where(
            ProgramTranslation.program_id == program_id,
            ProgramTranslation.locale == locale,
        )
    )
    if prog_tr is None:
        return False
    ex_count = await db.scalar(
        select(func.count())
        .select_from(ExerciseTranslation)
        .join(Exercise, Exercise.id == ExerciseTranslation.exercise_id)
        .where(
            Exercise.program_id == program_id,
            Exercise.kind == "cc",
            Exercise.deleted_at.is_(None),
            ExerciseTranslation.locale == locale,
        )
    )
    step_count = await db.scalar(
        select(func.count())
        .select_from(ExerciseStepTranslation)
        .join(ExerciseStep, ExerciseStep.id == ExerciseStepTranslation.exercise_step_id)
        .join(Exercise, Exercise.id == ExerciseStep.exercise_id)
        .where(
            Exercise.program_id == program_id,
            Exercise.kind == "cc",
            ExerciseStepTranslation.locale == locale,
        )
    )
    return int(ex_count or 0) >= 6 and int(step_count or 0) >= 60


def catalog_etag(*, program_slug: str, resolved_locale: str, catalog_version: int) -> str:
    raw = f"{program_slug}:{resolved_locale}:{catalog_version}"
    digest = sha256(raw.encode()).hexdigest()[:32]
    return f'"{digest}"'


async def build_cc_catalog(
    db: AsyncSession,
    *,
    requested_locale: str | None,
    user_locale: str | None,
) -> tuple[CatalogCcResponseV1, str]:
    requested, resolved = resolve_locale(requested=requested_locale, user_locale=user_locale)
    program = await db.scalar(select(Program).where(Program.slug == "cc_big_six"))
    if program is None:
        program = await db.scalar(select(Program).where(Program.is_system.is_(True)).limit(1))
    if program is None:
        from app.services.errors import DomainError

        raise DomainError("catalog_unavailable", http_status=503)

    if not await _locale_complete(db, program_id=program.id, locale=resolved):
        resolved = DEFAULT_LOCALE

    prog_tr = await db.scalar(
        select(ProgramTranslation).where(
            ProgramTranslation.program_id == program.id,
            ProgramTranslation.locale == resolved,
        )
    )
    if prog_tr is None:
        from app.services.errors import DomainError

        raise DomainError("catalog_unavailable", http_status=503)

    days_out: list[CatalogDayV1] = []
    days = (
        await db.scalars(
            select(ProgramDay)
            .where(ProgramDay.program_id == program.id)
            .order_by(ProgramDay.day_index)
        )
    ).all()
    for day in days:
        dtr = await db.scalar(
            select(ProgramDayTranslation).where(
                ProgramDayTranslation.program_day_id == day.id,
                ProgramDayTranslation.locale == resolved,
            )
        )
        links = (
            await db.scalars(
                select(ProgramDayExercise)
                .where(ProgramDayExercise.program_day_id == day.id)
                .order_by(ProgramDayExercise.sort_order)
            )
        ).all()
        days_out.append(
            CatalogDayV1(
                day_index=day.day_index,
                name=dtr.name if dtr else f"D{day.day_index}",
                exercise_ids=[link.exercise_id for link in links],
            )
        )

    exercises_out: list[CatalogExerciseV1] = []
    exercises = (
        await db.scalars(
            select(Exercise)
            .where(
                Exercise.program_id == program.id,
                Exercise.kind == "cc",
                Exercise.deleted_at.is_(None),
            )
            .order_by(Exercise.slug)
        )
    ).all()
    for ex in exercises:
        etr = await db.scalar(
            select(ExerciseTranslation).where(
                ExerciseTranslation.exercise_id == ex.id,
                ExerciseTranslation.locale == resolved,
            )
        )
        steps = (
            await db.scalars(
                select(ExerciseStep)
                .where(ExerciseStep.exercise_id == ex.id)
                .order_by(ExerciseStep.step_number)
            )
        ).all()
        step_dtos: list[CatalogStepV1] = []
        for step in steps:
            strans = await db.scalar(
                select(ExerciseStepTranslation).where(
                    ExerciseStepTranslation.exercise_step_id == step.id,
                    ExerciseStepTranslation.locale == resolved,
                )
            )
            step_dtos.append(
                CatalogStepV1(
                    step_number=step.step_number,
                    name=strans.name if strans else (step.name or f"step-{step.step_number}"),
                    description=strans.description if strans else (step.description or ""),
                    content_status=strans.content_status if strans else "draft",
                    rules=step.rules,
                )
            )
        exercises_out.append(
            CatalogExerciseV1(
                id=ex.id,
                slug=ex.slug,
                name=etr.name if etr else (ex.slug or str(ex.id)),
                description=etr.description if etr else None,
                exercise_type=ex.exercise_type,
                steps=step_dtos,
            )
        )

    payload = CatalogCcResponseV1(
        program_slug=program.slug,
        program_name=prog_tr.name,
        program_description=prog_tr.description,
        catalog_version=prog_tr.catalog_version,
        requested_locale=requested,
        resolved_locale=resolved,
        days=days_out,
        exercises=exercises_out,
    )
    etag = catalog_etag(
        program_slug=program.slug,
        resolved_locale=resolved,
        catalog_version=prog_tr.catalog_version,
    )
    return payload, etag
