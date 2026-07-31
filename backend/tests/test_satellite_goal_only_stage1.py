"""Stage 1 — goal-only satellite online (Hip Thrust + type C)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.domain.canonical_json import sha256_jcs_hex
from app.domain.satellite_progression import satellite_goal_met
from app.models.catalog import Program
from app.models.user import User
from app.schemas.api import SatelliteCreateV1, SessionCreateV1, SessionLogCreateV1
from app.schemas.satellite import (
    ActiveMetricsV1,
    SatelliteConfigDocumentV1,
    SatelliteGoalCompletedV1,
    SatelliteGoalRepsV1,
    SatelliteLogResultV1,
    SatelliteRulesV1,
    SatelliteSetV1,
)
from app.services.auth_session import AuthSessionService
from app.services.legal import record_legal_acceptance
from app.services.onboarding import complete_onboarding
from app.services.satellites import create_satellite
from app.services.sessions import create_session
from tests.legal_fixtures import latest_health_disclaimer


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine(settings.resolved_database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _ready(db: AsyncSession, email: str) -> User:
    if await db.scalar(select(Program).where(Program.slug == "cc_big_six")) is None:
        pytest.skip("seed catalog required")
    doc, tr = await latest_health_disclaimer(db)
    user = User(
        id=new_uuid7(),
        google_sub=f"sub-{new_uuid7()}",
        email=email,
        locale="pl-PL",
        timezone="Europe/Warsaw",
    )
    db.add(user)
    await db.commit()
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
    await AuthSessionService().create_session(db, user=user, user_agent="t")
    return user


def test_satellite_goal_met_both_sides_and_weight() -> None:
    rules = SatelliteRulesV1(
        schema_version=1,
        goal=SatelliteGoalRepsV1(
            type="reps",
            sets=3,
            min_reps=10,
            require_both_sides=True,
            min_weight_kg=None,
        ),
    )
    active = ActiveMetricsV1(schema_version=1, metrics=["reps", "weight_kg", "sides"])
    ok = SatelliteLogResultV1(
        schema_version=1,
        completed=None,
        sets=[
            SatelliteSetV1(reps=10, weight_kg="20.000", sides="left"),
            SatelliteSetV1(reps=10, weight_kg="20.000", sides="left"),
            SatelliteSetV1(reps=10, weight_kg="20.000", sides="left"),
            SatelliteSetV1(reps=10, weight_kg="20.000", sides="right"),
            SatelliteSetV1(reps=10, weight_kg="20.000", sides="right"),
            SatelliteSetV1(reps=10, weight_kg="20.000", sides="right"),
        ],
    )
    assert satellite_goal_met(rules, ok, active_metrics=active)

    weak_right = SatelliteLogResultV1(
        schema_version=1,
        completed=None,
        sets=[
            SatelliteSetV1(reps=10, weight_kg="20.000", sides="left"),
            SatelliteSetV1(reps=10, weight_kg="20.000", sides="left"),
            SatelliteSetV1(reps=10, weight_kg="20.000", sides="left"),
            SatelliteSetV1(reps=10, weight_kg="20.000", sides="right"),
            SatelliteSetV1(reps=9, weight_kg="20.000", sides="right"),
            SatelliteSetV1(reps=10, weight_kg="20.000", sides="right"),
        ],
    )
    assert not satellite_goal_met(rules, weak_right, active_metrics=active)


def test_completed_requires_explicit_flag() -> None:
    rules = SatelliteRulesV1(
        schema_version=1, goal=SatelliteGoalCompletedV1(type="completed")
    )
    active = ActiveMetricsV1(schema_version=1, metrics=[])
    assert not satellite_goal_met(
        rules,
        SatelliteLogResultV1(schema_version=1, completed=None, sets=[]),
        active_metrics=active,
    )
    assert satellite_goal_met(
        rules,
        SatelliteLogResultV1(schema_version=1, completed=True, sets=[]),
        active_metrics=active,
    )


def test_jcs_hash_stable_for_key_order() -> None:
    a = {
        "schema_version": 1,
        "exercise_type": "B",
        "active_metrics": {"schema_version": 1, "metrics": ["reps", "sides", "weight_kg"]},
        "progression": {"mode": "goal_only"},
        "steps": [
            {
                "step_id": "01920000-0000-7000-8000-0000000000b1",
                "sort_order": 1,
                "rules": {
                    "schema_version": 1,
                    "goal": {
                        "type": "reps",
                        "sets": 3,
                        "min_reps": 10,
                        "min_weight_kg": None,
                        "require_both_sides": True,
                    },
                },
            }
        ],
    }
    b = {
        "steps": a["steps"],
        "progression": a["progression"],
        "active_metrics": {
            "metrics": ["weight_kg", "sides", "reps"],
            "schema_version": 1,
        },
        "exercise_type": "B",
        "schema_version": 1,
    }
    # After Pydantic normalize metrics are sorted; raw dicts differ until canonicalize sorts keys.
    assert sha256_jcs_hex(a) == sha256_jcs_hex(
        {
            **b,
            "active_metrics": {
                "schema_version": 1,
                "metrics": sorted(b["active_metrics"]["metrics"]),
            },
        }
    )


@pytest.mark.asyncio
async def test_hip_thrust_online_goal_met(db: AsyncSession) -> None:
    user = await _ready(db, "hip-thrust@ex.com")
    body = SatelliteCreateV1.model_validate(
        {
            "schema_version": 1,
            "name": "SL Hip Thrust (DB)",
            "exercise_type": "B",
            "active_metrics": {
                "schema_version": 1,
                "metrics": ["reps", "weight_kg", "sides"],
            },
            "equipment": ["dumbbell", "bench"],
            "schedule_kind": "weekdays",
            "weekdays": [1, 3, 5],
            "steps": [
                {
                    "step_number": 1,
                    "name": "Working sets",
                    "rules": {
                        "schema_version": 1,
                        "goal": {
                            "type": "reps",
                            "sets": 3,
                            "min_reps": 10,
                            "require_both_sides": True,
                            "min_weight_kg": None,
                        },
                    },
                }
            ],
            "client_mutation_id": str(new_uuid7()),
        }
    )
    sat = await create_satellite(db, user=user, body=body, commit=True)
    assert sat.config_hash is not None
    assert sat.current_config_version_id is not None

    sets = {
        "schema_version": 1,
        "completed": None,
        "sets": (
            [{"reps": 10, "weight_kg": "20.000", "sides": "left"}] * 3
            + [{"reps": 10, "weight_kg": "20.000", "sides": "right"}] * 3
        ),
    }
    read = await create_session(
        db,
        user=user,
        body=SessionCreateV1(
            schema_version=1,
            performed_at=datetime(2026, 7, 27, 10, 0, tzinfo=UTC),
            local_date=date(2026, 7, 27),
            client_mutation_id=new_uuid7(),
            client_timezone="Europe/Warsaw",
            logs=[
                SessionLogCreateV1(
                    exercise_id=sat.id,
                    exercise_kind="satellite",
                    section="accessories",
                    sets=sets,
                    satellite_config_version_id=sat.current_config_version_id,
                    satellite_config_hash=sat.config_hash,
                )
            ],
        ),
        commit=True,
    )
    assert read.logs[0].goal_met is True
    assert read.logs[0].counts_for_progression is False
    assert read.logs[0].progression_skipped in (None, "config_not_active_for_day")
    # With Stage 1 activation from epoch, eligibility should hold:
    assert read.logs[0].progression_skipped is None


@pytest.mark.asyncio
async def test_type_c_completed_online(db: AsyncSession) -> None:
    user = await _ready(db, "type-c@ex.com")
    sat = await create_satellite(
        db,
        user=user,
        body=SatelliteCreateV1.model_validate(
            {
                "schema_version": 1,
                "name": "Mobility C",
                "exercise_type": "C",
                "active_metrics": {"schema_version": 1, "metrics": []},
                "schedule_kind": "daily",
                "steps": [
                    {
                        "step_number": 1,
                        "name": "Done",
                        "rules": {
                            "schema_version": 1,
                            "goal": {"type": "completed"},
                        },
                    }
                ],
                "client_mutation_id": str(new_uuid7()),
            }
        ),
        commit=True,
    )
    read = await create_session(
        db,
        user=user,
        body=SessionCreateV1(
            schema_version=1,
            performed_at=datetime(2026, 7, 28, 10, 0, tzinfo=UTC),
            local_date=date(2026, 7, 28),
            client_mutation_id=new_uuid7(),
            client_timezone="Europe/Warsaw",
            logs=[
                SessionLogCreateV1(
                    exercise_id=sat.id,
                    exercise_kind="satellite",
                    sets={"schema_version": 1, "completed": True, "sets": []},
                    satellite_config_version_id=sat.current_config_version_id,
                    satellite_config_hash=sat.config_hash,
                )
            ],
        ),
        commit=True,
    )
    assert read.logs[0].goal_met is True


@pytest.mark.asyncio
async def test_evaluate_uses_config_document_not_divergent_step_rules(
    db: AsyncSession,
) -> None:
    """P1 regression: poisoned ExerciseStep.rules must not change goal_met."""
    from app.models.catalog import ExerciseStep
    from app.models.workout import SessionExerciseLog

    user = await _ready(db, "config-source@ex.com")
    sat = await create_satellite(
        db,
        user=user,
        body=SatelliteCreateV1.model_validate(
            {
                "schema_version": 1,
                "name": "Poisoned step",
                "exercise_type": "B",
                "active_metrics": {"schema_version": 1, "metrics": ["reps"]},
                "schedule_kind": "daily",
                "steps": [
                    {
                        "step_number": 1,
                        "name": "Working",
                        "rules": {
                            "schema_version": 1,
                            "goal": {"type": "reps", "sets": 1, "min_reps": 10},
                        },
                    }
                ],
                "client_mutation_id": str(new_uuid7()),
            }
        ),
        commit=True,
    )
    step = await db.scalar(
        select(ExerciseStep).where(ExerciseStep.exercise_id == sat.id)
    )
    assert step is not None
    step.rules = {
        "schema_version": 1,
        "goal": {"type": "reps", "sets": 1, "min_reps": 99},
    }
    await db.commit()

    read = await create_session(
        db,
        user=user,
        body=SessionCreateV1(
            schema_version=1,
            performed_at=datetime(2026, 7, 28, 10, 0, tzinfo=UTC),
            local_date=date(2026, 7, 28),
            client_mutation_id=new_uuid7(),
            client_timezone="Europe/Warsaw",
            logs=[
                SessionLogCreateV1(
                    exercise_id=sat.id,
                    exercise_kind="satellite",
                    sets={
                        "schema_version": 1,
                        "completed": None,
                        "sets": [{"reps": 10}],
                    },
                    satellite_config_version_id=sat.current_config_version_id,
                    satellite_config_hash=sat.config_hash,
                )
            ],
        ),
        commit=True,
    )
    assert read.logs[0].goal_met is True
    log_row = await db.scalar(
        select(SessionExerciseLog).where(SessionExerciseLog.id == read.logs[0].id)
    )
    assert log_row is not None
    assert log_row.rules_snapshot is not None
    assert log_row.rules_snapshot.get("goal", {}).get("min_reps") == 10
