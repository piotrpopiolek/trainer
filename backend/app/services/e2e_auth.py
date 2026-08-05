"""E2E login harness — gated by ENABLE_E2E_LOGIN (dev/test only)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_uuid7
from app.models.catalog import Program
from app.models.progression import UserExerciseProgress
from app.models.satellite_progress import (
    SatelliteDailyOutcome,
    SatelliteRegressionRecommendation,
)
from app.models.user import User
from app.schemas.api import SatelliteCreateV1, SessionCreateV1, SessionLogCreateV1
from app.services.errors import DomainError
from app.services.legal import (
    HEALTH_DISCLAIMER_SLUG,
    get_translation,
    latest_published_document,
    record_legal_acceptance,
)
from app.services.onboarding import complete_onboarding
from app.services.satellite_progression import SatelliteProgressionOrchestrator
from app.services.satellites import create_satellite, edit_satellite
from app.services.sessions import create_session

E2eSeedScenario = Literal[
    "mini_progression", "pending_regression", "pending_config"
]


def _reps_rules(*, min_reps: int = 5) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "goal": {
            "type": "reps",
            "sets": 1,
            "min_reps": min_reps,
            "require_both_sides": False,
            "min_weight_kg": None,
        },
    }


def _mini_progression_body(*, name: str, mutation_id: UUID) -> SatelliteCreateV1:
    """Daily multi-step type B — simple 1×reps for Playwright logging."""
    return SatelliteCreateV1.model_validate(
        {
            "schema_version": 1,
            "name": name,
            "exercise_type": "B",
            "active_metrics": {"schema_version": 1, "metrics": ["reps"]},
            "schedule_kind": "daily",
            "progression": {
                "mode": "steps",
                "regression": {
                    "mode": "suggest_after_failed_days",
                    "threshold": 2,
                },
            },
            "steps": [
                {
                    "step_number": 1,
                    "step_id": str(new_uuid7()),
                    "name": "Step A",
                    "rules": _reps_rules(min_reps=5),
                },
                {
                    "step_number": 2,
                    "step_id": str(new_uuid7()),
                    "name": "Step B",
                    "rules": _reps_rules(min_reps=5),
                },
                {
                    "step_number": 3,
                    "step_id": str(new_uuid7()),
                    "name": "Step C",
                    "rules": _reps_rules(min_reps=5),
                },
            ],
            "client_mutation_id": str(mutation_id),
        }
    )


async def provision_e2e_ready_user(
    db: AsyncSession,
    *,
    email: str | None = None,
) -> User:
    if await db.scalar(select(Program).where(Program.slug == "cc_big_six")) is None:
        raise DomainError("enrollment_required", http_status=503)

    doc = await latest_published_document(db, slug=HEALTH_DISCLAIMER_SLUG)
    if doc is None:
        raise DomainError("legal_required", http_status=503)
    tr = await get_translation(db, document_id=doc.id, locale="pl-PL")
    if tr is None:
        raise DomainError("legal_required", http_status=503)

    user = User(
        id=new_uuid7(),
        google_sub=f"e2e-{new_uuid7()}",
        email=email or f"e2e-{new_uuid7()}@example.test",
        locale="pl-PL",
        timezone="Europe/Warsaw",
    )
    db.add(user)
    await db.flush()
    await complete_onboarding(
        db,
        user,
        questionnaire={
            "schema_version": 1,
            "experience_level": "beginner",
            "training_days_per_week": 3,
            "goals": ["strength"],
        },
        started_on=date(2026, 7, 1),
        anchor_weekday=1,
    )
    await record_legal_acceptance(
        db,
        user_id=user.id,
        payload={
            "schema_version": 1,
            "client_mutation_id": str(uuid4()),
            "document_slug": "health_disclaimer",
            "document_version": doc.version,
            "accepted_locale": "pl-PL",
            "accepted_content_hash": tr.content_hash.hex(),
            "accepted_at": datetime.now(UTC).isoformat(),
        },
    )
    await db.commit()
    await db.refresh(user)
    return user


async def _fail_and_finalize(
    db: AsyncSession,
    *,
    user: User,
    sat: Any,
    local_date: date,
) -> None:
    await create_session(
        db,
        user=user,
        body=SessionCreateV1(
            schema_version=1,
            performed_at=datetime(
                local_date.year, local_date.month, local_date.day, 10, 0, tzinfo=UTC
            ),
            local_date=local_date,
            client_mutation_id=new_uuid7(),
            client_timezone="Europe/Warsaw",
            logs=[
                SessionLogCreateV1(
                    exercise_id=sat.id,
                    exercise_kind="satellite",
                    section="accessories",
                    sets={"schema_version": 1, "sets": [{"reps": 1}]},
                    satellite_config_version_id=sat.current_config_version_id,
                    satellite_config_hash=sat.config_hash,
                )
            ],
        ),
        commit=True,
    )
    outcome = await db.scalar(
        select(SatelliteDailyOutcome).where(
            SatelliteDailyOutcome.user_id == user.id,
            SatelliteDailyOutcome.exercise_id == sat.id,
            SatelliteDailyOutcome.local_date == local_date,
        )
    )
    if outcome is None:
        raise DomainError("internal_error", http_status=500)
    await db.execute(
        update(SatelliteDailyOutcome)
        .where(SatelliteDailyOutcome.id == outcome.id)
        .values(finalize_after=datetime(2026, 1, 1, tzinfo=UTC))
    )
    await db.commit()
    await SatelliteProgressionOrchestrator().finalize_due_outcomes(
        db,
        user_id=user.id,
        exercise_id=sat.id,
        now=datetime(2030, 8, 15, tzinfo=UTC),
    )
    await db.commit()


async def seed_e2e_scenario(
    db: AsyncSession,
    *,
    user: User,
    scenario: E2eSeedScenario,
) -> dict[str, Any]:
    """Seed satellite fixtures for Playwright matrix (ENABLE_E2E_LOGIN only)."""
    suffix = str(new_uuid7())[:8]
    name = f"E2E Ladder {suffix}"

    if scenario == "mini_progression":
        sat = await create_satellite(
            db,
            user=user,
            body=_mini_progression_body(name=name, mutation_id=new_uuid7()),
            commit=True,
        )
        return {
            "schema_version": 1,
            "scenario": scenario,
            "satellite_id": str(sat.id),
            "name": sat.name,
            "current_step_number": 1,
        }

    if scenario == "pending_regression":
        sat = await create_satellite(
            db,
            user=user,
            body=_mini_progression_body(name=name, mutation_id=new_uuid7()),
            commit=True,
        )
        progress = await db.scalar(
            select(UserExerciseProgress).where(
                UserExerciseProgress.user_id == user.id,
                UserExerciseProgress.exercise_id == sat.id,
            )
        )
        if progress is None:
            raise DomainError("internal_error", http_status=500)
        step2_id = UUID(str(sat.steps[1]["step_id"]))
        progress.current_step_number = 2
        progress.current_step_id = step2_id
        await db.commit()

        await _fail_and_finalize(db, user=user, sat=sat, local_date=date(2030, 8, 3))
        await _fail_and_finalize(db, user=user, sat=sat, local_date=date(2030, 8, 4))

        rec = await db.scalar(
            select(SatelliteRegressionRecommendation).where(
                SatelliteRegressionRecommendation.user_id == user.id,
                SatelliteRegressionRecommendation.exercise_id == sat.id,
                SatelliteRegressionRecommendation.status == "pending",
            )
        )
        if rec is None:
            raise DomainError("internal_error", http_status=500)

        await db.refresh(progress)
        return {
            "schema_version": 1,
            "scenario": scenario,
            "satellite_id": str(sat.id),
            "name": sat.name,
            "current_step_number": progress.current_step_number,
            "recommendation_id": str(rec.id),
            "from_step": 2,
            "to_step": 1,
        }

    if scenario == "pending_config":
        # Goal-only type B with history, then bump min_reps → pending from tomorrow.
        create_body = SatelliteCreateV1.model_validate(
            {
                "schema_version": 1,
                "name": name,
                "exercise_type": "B",
                "active_metrics": {"schema_version": 1, "metrics": ["reps"]},
                "schedule_kind": "daily",
                "steps": [
                    {
                        "step_number": 1,
                        "step_id": str(new_uuid7()),
                        "name": "Cel",
                        "rules": _reps_rules(min_reps=5),
                    }
                ],
                "client_mutation_id": str(new_uuid7()),
            }
        )
        sat = await create_satellite(db, user=user, body=create_body, commit=True)
        await create_session(
            db,
            user=user,
            body=SessionCreateV1(
                schema_version=1,
                performed_at=datetime(2030, 8, 3, 12, 0, tzinfo=UTC),
                local_date=date(2030, 8, 3),
                client_mutation_id=new_uuid7(),
                client_timezone="Europe/Warsaw",
                logs=[
                    SessionLogCreateV1(
                        exercise_id=sat.id,
                        exercise_kind="satellite",
                        section="accessories",
                        sets={"schema_version": 1, "sets": [{"reps": 5}]},
                        satellite_config_version_id=sat.current_config_version_id,
                        satellite_config_hash=sat.config_hash,
                    )
                ],
            ),
            commit=True,
        )
        step0 = sat.steps[0]
        edit_body = SatelliteCreateV1.model_validate(
            {
                "schema_version": 1,
                "name": sat.name,
                "exercise_type": "B",
                "active_metrics": {"schema_version": 1, "metrics": ["reps"]},
                "schedule_kind": "daily",
                "steps": [
                    {
                        "step_number": 1,
                        "step_id": step0["step_id"],
                        "name": step0.get("name") or "Cel",
                        "rules": _reps_rules(min_reps=8),
                    }
                ],
                "client_mutation_id": str(new_uuid7()),
                "expected_current_config_version_id": sat.current_config_version_id,
            }
        )
        updated, reg = await edit_satellite(
            db,
            user=user,
            exercise_id=sat.id,
            body=edit_body,
            revision=sat.revision + 1,
            commit=True,
        )
        if not reg.pending_applied:
            raise DomainError("internal_error", http_status=500)
        return {
            "schema_version": 1,
            "scenario": scenario,
            "satellite_id": str(updated.id),
            "name": updated.name,
            "config_effective_on": (
                str(updated.config_effective_on)
                if updated.config_effective_on is not None
                else None
            ),
        }

    raise DomainError("validation_error", http_status=422)
