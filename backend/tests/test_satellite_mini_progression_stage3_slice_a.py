"""Stage 3 Slice A — steps policy contracts + Copenhagen create (no daily outcome yet)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.models.catalog import ExerciseStep, Program, SatelliteConfigVersion
from app.models.progression import UserExerciseProgress
from app.models.satellite_progress import (
    SatelliteDailyOutcome,
    SatelliteRegressionRecommendation,
)
from app.models.user import User
from app.schemas.api import SatelliteCreateV1, SessionCreateV1, SessionLogCreateV1
from app.schemas.satellite import (
    ActiveMetricsV1,
    SatelliteConfigDocumentV1,
    SatelliteConfigStepV1,
    SatelliteGoalDurationV1,
    SatelliteProgressionPolicyGoalOnlyV1,
    SatelliteProgressionPolicyStepsV1,
    SatelliteRegressionPolicyV1,
    SatelliteRulesV1,
)
from app.services.auth_session import AuthSessionService
from app.services.errors import DomainError
from app.services.legal import record_legal_acceptance
from app.services.onboarding import complete_onboarding
from app.services.satellites import create_satellite
from app.services.sessions import create_session
from tests.legal_fixtures import latest_health_disclaimer

_STEP1 = UUID("01900000-0000-7000-8000-000000000011")
_STEP2 = UUID("01900000-0000-7000-8000-000000000012")
_STEP3 = UUID("01900000-0000-7000-8000-000000000013")
_COPENHAGEN_HASH = "1ee79f4670ef0aa87275554ae230c3e66bb14004bd1fbd15cf8ab2b2af2e2b85"


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


def _duration_rules(*, min_duration_sec: int) -> dict:
    return {
        "schema_version": 1,
        "goal": {
            "type": "duration",
            "sets": 3,
            "min_duration_sec": min_duration_sec,
            "min_weight_kg": None,
            "require_both_sides": True,
        },
    }


def _copenhagen_body(
    *,
    mutation_id,
    step_ids: tuple[UUID, UUID, UUID] | None = None,
) -> SatelliteCreateV1:
    s1, s2, s3 = step_ids or (_STEP1, _STEP2, _STEP3)
    return SatelliteCreateV1.model_validate(
        {
            "schema_version": 1,
            "name": "Copenhagen Plank",
            "exercise_type": "B",
            "active_metrics": {
                "schema_version": 1,
                "metrics": ["duration_sec", "sides"],
            },
            "schedule_kind": "category",
            "schedule_category": "post_workout",
            "equipment": ["bench"],
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
                    "step_id": str(s1),
                    "name": "Short lever hold",
                    "rules": _duration_rules(min_duration_sec=20),
                },
                {
                    "step_number": 2,
                    "step_id": str(s2),
                    "name": "Long lever hold",
                    "rules": _duration_rules(min_duration_sec=20),
                },
                {
                    "step_number": 3,
                    "step_id": str(s3),
                    "name": "Long lever with bottom leg lifted",
                    "rules": _duration_rules(min_duration_sec=15),
                },
            ],
            "client_mutation_id": str(mutation_id),
        }
    )


def test_steps_policy_requires_regression_threshold() -> None:
    with pytest.raises(ValidationError):
        SatelliteProgressionPolicyStepsV1.model_validate({"mode": "steps"})
    with pytest.raises(ValidationError):
        SatelliteProgressionPolicyStepsV1.model_validate(
            {
                "mode": "steps",
                "regression": {"mode": "suggest_after_failed_days", "threshold": 0},
            }
        )
    ok = SatelliteProgressionPolicyStepsV1(
        mode="steps",
        regression=SatelliteRegressionPolicyV1(
            mode="suggest_after_failed_days", threshold=2
        ),
    )
    assert ok.regression.threshold == 2


def test_document_rejects_step_count_mismatch() -> None:
    step = SatelliteConfigStepV1(
        step_id=_STEP1,
        sort_order=1,
        rules=SatelliteRulesV1(
            schema_version=1,
            goal=SatelliteGoalDurationV1(
                type="duration",
                sets=3,
                min_duration_sec=20,
                require_both_sides=True,
            ),
        ),
    )
    with pytest.raises(ValidationError):
        SatelliteConfigDocumentV1(
            schema_version=1,
            exercise_type="B",
            active_metrics=ActiveMetricsV1(
                schema_version=1, metrics=["duration_sec", "sides"]
            ),
            progression=SatelliteProgressionPolicyStepsV1(
                mode="steps",
                regression=SatelliteRegressionPolicyV1(
                    mode="suggest_after_failed_days", threshold=2
                ),
            ),
            steps=[step],
        )
    with pytest.raises(ValidationError):
        SatelliteConfigDocumentV1(
            schema_version=1,
            exercise_type="B",
            active_metrics=ActiveMetricsV1(
                schema_version=1, metrics=["duration_sec", "sides"]
            ),
            progression=SatelliteProgressionPolicyGoalOnlyV1(mode="goal_only"),
            steps=[
                step,
                SatelliteConfigStepV1(
                    step_id=_STEP2,
                    sort_order=2,
                    rules=step.rules,
                ),
            ],
        )


@pytest.mark.asyncio
async def test_create_copenhagen_sets_current_step_and_hash(db: AsyncSession) -> None:
    from app.domain.canonical_json import sha256_jcs_hex

    user = await _ready(db, "copenhagen-create@ex.com")
    s1, s2, s3 = new_uuid7(), new_uuid7(), new_uuid7()
    sat = await create_satellite(
        db,
        user=user,
        body=_copenhagen_body(
            mutation_id=new_uuid7(),
            step_ids=(s1, s2, s3),
        ),
        commit=True,
    )
    assert sat.name == "Copenhagen Plank"
    assert len(sat.steps) == 3

    steps = (
        await db.scalars(
            select(ExerciseStep)
            .where(ExerciseStep.exercise_id == sat.id)
            .order_by(ExerciseStep.step_number)
        )
    ).all()
    assert [s.id for s in steps] == [s1, s2, s3]

    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == sat.id,
        )
    )
    assert progress is not None
    assert progress.current_step_number == 1
    assert progress.current_step_id == s1
    assert progress.fail_streak == 0

    cfg = await db.get(SatelliteConfigVersion, sat.current_config_version_id)
    assert cfg is not None
    assert cfg.document["progression"]["mode"] == "steps"
    assert cfg.document["progression"]["regression"]["threshold"] == 2
    assert sat.config_hash == sha256_jcs_hex(cfg.document)
    # Stable golden (fixed step IDs) stays in satellite_jcs_vectors.json.


def test_copenhagen_golden_vector_hash() -> None:
    """Fixed-ID document matches shared fixture (no DB)."""
    from app.domain.canonical_json import sha256_jcs_hex
    from app.schemas.satellite import SatelliteConfigDocumentV1

    doc = SatelliteConfigDocumentV1.model_validate(
        {
            "schema_version": 1,
            "exercise_type": "B",
            "active_metrics": {
                "schema_version": 1,
                "metrics": ["duration_sec", "sides"],
            },
            "progression": {
                "mode": "steps",
                "regression": {
                    "mode": "suggest_after_failed_days",
                    "threshold": 2,
                },
            },
            "steps": [
                {
                    "step_id": str(_STEP1),
                    "sort_order": 1,
                    "rules": _duration_rules(min_duration_sec=20),
                },
                {
                    "step_id": str(_STEP2),
                    "sort_order": 2,
                    "rules": _duration_rules(min_duration_sec=20),
                },
                {
                    "step_id": str(_STEP3),
                    "sort_order": 3,
                    "rules": _duration_rules(min_duration_sec=15),
                },
            ],
        }
    )
    assert sha256_jcs_hex(doc.model_dump(mode="json")) == _COPENHAGEN_HASH


@pytest.mark.asyncio
async def test_create_rejects_goal_only_with_multiple_steps(db: AsyncSession) -> None:
    user = await _ready(db, "goal-only-multi@ex.com")
    body = SatelliteCreateV1.model_validate(
        {
            "schema_version": 1,
            "name": "Bad",
            "exercise_type": "B",
            "active_metrics": {"schema_version": 1, "metrics": ["reps"]},
            "schedule_kind": "daily",
            "progression": {"mode": "goal_only"},
            "steps": [
                {
                    "step_number": 1,
                    "name": "A",
                    "rules": {
                        "schema_version": 1,
                        "goal": {"type": "reps", "sets": 1, "min_reps": 5},
                    },
                },
                {
                    "step_number": 2,
                    "name": "B",
                    "rules": {
                        "schema_version": 1,
                        "goal": {"type": "reps", "sets": 1, "min_reps": 5},
                    },
                },
            ],
            "client_mutation_id": str(new_uuid7()),
        }
    )
    with pytest.raises(DomainError) as exc:
        await create_satellite(db, user=user, body=body, commit=True)
    assert exc.value.error_code == "goal_only_requires_one_step"


@pytest.mark.asyncio
async def test_log_on_steps_satellite_does_not_write_outcomes_yet(
    db: AsyncSession,
) -> None:
    """Slice A boundary: create/hash/progress only — engine still goal_met-only."""
    user = await _ready(db, "copenhagen-log@ex.com")
    sat = await create_satellite(
        db,
        user=user,
        body=_copenhagen_body(
            mutation_id=new_uuid7(),
            step_ids=(new_uuid7(), new_uuid7(), new_uuid7()),
        ),
        commit=True,
    )
    progress_before = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == sat.id,
        )
    )
    assert progress_before is not None
    step_id_before = progress_before.current_step_id
    step_num_before = progress_before.current_step_number

    read = await create_session(
        db,
        user=user,
        body=SessionCreateV1(
            schema_version=1,
            performed_at=datetime(2026, 8, 3, 10, 0, tzinfo=UTC),
            local_date=date(2026, 8, 3),
            client_mutation_id=new_uuid7(),
            client_timezone="Europe/Warsaw",
            logs=[
                SessionLogCreateV1(
                    exercise_id=sat.id,
                    exercise_kind="satellite",
                    section="accessories",
                    sets={
                        "schema_version": 1,
                        "sets": [
                            {"duration_sec": 20, "sides": "left"},
                            {"duration_sec": 20, "sides": "right"},
                            {"duration_sec": 20, "sides": "left"},
                            {"duration_sec": 20, "sides": "right"},
                            {"duration_sec": 20, "sides": "left"},
                            {"duration_sec": 20, "sides": "right"},
                        ],
                    },
                    satellite_config_version_id=sat.current_config_version_id,
                    satellite_config_hash=sat.config_hash,
                )
            ],
        ),
        commit=True,
    )
    log = read.logs[0]
    assert log.goal_met is True
    # Slice A: still no daily-outcome fold — progress step unchanged, no ledger rows.

    await db.refresh(progress_before)
    assert progress_before.current_step_id == step_id_before
    assert progress_before.current_step_number == step_num_before

    outcomes = await db.scalar(select(func.count()).select_from(SatelliteDailyOutcome))
    recs = await db.scalar(
        select(func.count()).select_from(SatelliteRegressionRecommendation)
    )
    assert int(outcomes or 0) == 0
    assert int(recs or 0) == 0
