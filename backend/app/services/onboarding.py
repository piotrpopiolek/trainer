"""Onboarding completion + CC enrollment (FR-010–013, FR-022a)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_uuid7
from app.models.catalog import Program
from app.models.onboarding import UserOnboarding
from app.models.progression import UserExerciseProgress, UserProgramEnrollment
from app.models.user import User
from app.schemas.common import parse_versioned
from app.schemas.onboarding import (
    OnboardingPlacementTestV1,
    OnboardingQuestionnaireV1,
    OnboardingStepsMapV1,
)
from app.services.errors import DomainError

CC_PROGRAM_SLUG = "cc_big_six"
CC_EXERCISE_SLUGS = (
    "push_ups",
    "squats",
    "pull_ups",
    "leg_raises",
    "bridges",
    "handstand_push_ups",
)


def recommend_steps_from_questionnaire(
    questionnaire: OnboardingQuestionnaireV1,
    placement: OnboardingPlacementTestV1 | None = None,
) -> OnboardingStepsMapV1:
    base = {"beginner": 1, "intermediate": 3, "advanced": 5}[
        questionnaire.experience_level
    ]
    steps: dict[str, int] = {slug: base for slug in CC_EXERCISE_SLUGS}
    if placement:
        for entry in placement.entries:
            if entry.exercise_slug not in steps:
                continue
            # Simple placement bump: higher max reps → higher start step (cap 8).
            bump = min(entry.max_reps // 10, 3)
            steps[entry.exercise_slug] = min(base + bump, 8)
    return OnboardingStepsMapV1(schema_version=1, steps=steps)


async def complete_onboarding(
    db: AsyncSession,
    user: User,
    *,
    questionnaire: dict[str, Any],
    placement_test: dict[str, Any] | None = None,
    chosen_steps: dict[str, Any] | None = None,
    anchor_weekday: int = 1,
    timezone: str | None = None,
    started_on: date | None = None,
) -> UserOnboarding:
    if user.onboarding_completed_at is not None:
        raise DomainError("onboarding_already_completed", http_status=409)

    q = parse_versioned(OnboardingQuestionnaireV1, questionnaire)
    placement_model: OnboardingPlacementTestV1 | None = None
    if placement_test is not None:
        placement_model = parse_versioned(OnboardingPlacementTestV1, placement_test)

    recommended = recommend_steps_from_questionnaire(q, placement_model)
    if chosen_steps is None:
        chosen = recommended
    else:
        chosen = parse_versioned(OnboardingStepsMapV1, chosen_steps)
        provided = set(chosen.steps)
        expected = set(CC_EXERCISE_SLUGS)
        if provided != expected:
            if provided - expected:
                raise DomainError("unknown_exercise_slug", http_status=422)
            raise DomainError("incomplete_chosen_steps", http_status=422)
        for step in chosen.steps.values():
            if not 1 <= step <= 10:
                raise DomainError("invalid_step_number", http_status=422)

    if anchor_weekday not in {1, 2}:
        raise DomainError("invalid_anchor_weekday", http_status=422)

    if timezone is not None:
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise DomainError("invalid_timezone", http_status=422) from exc
        user.timezone = timezone

    program = await db.scalar(select(Program).where(Program.slug == CC_PROGRAM_SLUG))
    if program is None:
        raise DomainError("program_not_seeded", http_status=503)

    today = started_on
    if today is None:
        today = datetime.now(ZoneInfo(user.timezone)).date()

    row = await db.scalar(select(UserOnboarding).where(UserOnboarding.user_id == user.id))
    now = datetime.now(UTC)
    if row is None:
        row = UserOnboarding(user_id=user.id)
        db.add(row)

    row.questionnaire = q.model_dump(mode="json")
    row.placement_test = (
        placement_model.model_dump(mode="json")
        if placement_model
        else {"schema_version": 1, "entries": []}
    )
    row.recommended_steps = recommended.model_dump(mode="json")
    row.chosen_steps = chosen.model_dump(mode="json")
    row.completed_at = now

    existing_enrollment = await db.scalar(
        select(UserProgramEnrollment).where(
            UserProgramEnrollment.user_id == user.id,
            UserProgramEnrollment.is_active.is_(True),
        )
    )
    if existing_enrollment is None:
        db.add(
            UserProgramEnrollment(
                id=new_uuid7(),
                user_id=user.id,
                program_id=program.id,
                started_on=today,
                anchor_weekday=anchor_weekday,
                rotation_offset=0,
                is_active=True,
            )
        )

    # Seed progress rows for CC exercises from chosen steps.
    from app.models.catalog import Exercise

    exercises = (
        await db.scalars(
            select(Exercise).where(
                Exercise.slug.in_(CC_EXERCISE_SLUGS),
                Exercise.kind == "cc",
            )
        )
    ).all()
    by_slug = {e.slug: e for e in exercises}
    for slug, step in chosen.steps.items():
        exercise = by_slug.get(slug)
        if exercise is None:
            continue
        progress = await db.scalar(
            select(UserExerciseProgress).where(
                UserExerciseProgress.user_id == user.id,
                UserExerciseProgress.exercise_id == exercise.id,
            )
        )
        if progress is None:
            db.add(
                UserExerciseProgress(
                    id=new_uuid7(),
                    user_id=user.id,
                    exercise_id=exercise.id,
                    current_step_number=step,
                    fail_streak=0,
                    is_active=True,
                )
            )
        else:
            progress.current_step_number = step
            progress.fail_streak = 0

    user.onboarding_completed_at = now
    await db.commit()
    await db.refresh(row)
    return row
