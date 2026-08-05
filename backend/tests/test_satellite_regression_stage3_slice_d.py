"""Stage 3 Slice D — regression recommendations (suggest / accept / decline / stale)."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.db.session import dispose_engine
from app.domain.satellite_progression import propose_regression_suggestion
from app.main import app
from app.models.catalog import Program
from app.models.progression import ProgressionEvent, UserExerciseProgress
from app.models.satellite_progress import (
    SatelliteDailyOutcome,
    SatelliteRegressionRecommendation,
)
from app.models.user import User
from app.schemas.api import SatelliteCreateV1, SessionCreateV1, SessionLogCreateV1
from app.services.auth_session import AuthSessionService
from app.services.errors import DomainError
from app.services.legal import record_legal_acceptance
from app.services.onboarding import complete_onboarding
from app.services.rate_limit import reset_memory_rate_limits
from app.services.satellite_progression import SatelliteProgressionOrchestrator
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


@pytest.fixture(autouse=True)
def _reset_limits() -> None:
    reset_memory_rate_limits()
    settings.rate_limit_store = "memory"
    yield
    reset_memory_rate_limits()


@pytest.fixture
async def api_client() -> AsyncClient:
    await dispose_engine()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        yield client
    await dispose_engine()


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


def _copenhagen_body(*, mutation_id) -> SatelliteCreateV1:
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
                    "step_id": str(new_uuid7()),
                    "name": "Short lever hold",
                    "rules": {
                        "schema_version": 1,
                        "goal": {
                            "type": "duration",
                            "sets": 3,
                            "min_duration_sec": 20,
                            "require_both_sides": True,
                        },
                    },
                },
                {
                    "step_number": 2,
                    "step_id": str(new_uuid7()),
                    "name": "Long lever hold",
                    "rules": {
                        "schema_version": 1,
                        "goal": {
                            "type": "duration",
                            "sets": 3,
                            "min_duration_sec": 20,
                            "require_both_sides": True,
                        },
                    },
                },
                {
                    "step_number": 3,
                    "step_id": str(new_uuid7()),
                    "name": "Long lever lifted",
                    "rules": {
                        "schema_version": 1,
                        "goal": {
                            "type": "duration",
                            "sets": 3,
                            "min_duration_sec": 15,
                            "require_both_sides": True,
                        },
                    },
                },
            ],
            "client_mutation_id": str(mutation_id),
        }
    )


def _fail_sets() -> dict:
    return {
        "schema_version": 1,
        "sets": [
            {"duration_sec": 5, "sides": "left"},
            {"duration_sec": 5, "sides": "right"},
        ],
    }


def _success_sets(*, min_duration: int = 20) -> dict:
    return {
        "schema_version": 1,
        "sets": [
            {"duration_sec": min_duration, "sides": "left"},
            {"duration_sec": min_duration, "sides": "right"},
            {"duration_sec": min_duration, "sides": "left"},
            {"duration_sec": min_duration, "sides": "right"},
            {"duration_sec": min_duration, "sides": "left"},
            {"duration_sec": min_duration, "sides": "right"},
        ],
    }


async def _fail_and_finalize(
    db: AsyncSession,
    *,
    user: User,
    sat,
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
                    sets=_fail_sets(),
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
    assert outcome is not None
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
        now=datetime(2026, 8, 10, tzinfo=UTC),
    )
    await db.commit()


def test_propose_regression_suggestion_threshold() -> None:
    ladder = [(1, "a"), (2, "b"), (3, "c")]
    assert (
        propose_regression_suggestion(
            step_number=2, fail_streak=1, threshold=2, step_ladder=ladder
        )
        is None
    )
    hit = propose_regression_suggestion(
        step_number=2, fail_streak=2, threshold=2, step_ladder=ladder
    )
    assert hit is not None
    assert hit.from_step == 2
    assert hit.to_step == 1
    assert hit.from_step_id == "b"
    assert hit.to_step_id == "a"
    assert (
        propose_regression_suggestion(
            step_number=1, fail_streak=5, threshold=2, step_ladder=ladder
        )
        is None
    )


@pytest.mark.asyncio
async def test_two_failed_days_create_pending_suggestion(db: AsyncSession) -> None:
    user = await _ready(db, "suggest-threshold@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == sat.id,
        )
    )
    assert progress is not None
    progress.current_step_number = 2
    progress.current_step_id = UUID(sat.steps[1]["step_id"])
    await db.commit()

    await _fail_and_finalize(db, user=user, sat=sat, local_date=date(2026, 8, 3))
    await db.refresh(progress)
    assert progress.fail_streak == 1
    assert (
        await db.scalar(
            select(func.count())
            .select_from(SatelliteRegressionRecommendation)
            .where(
                SatelliteRegressionRecommendation.user_id == user.id,
                SatelliteRegressionRecommendation.exercise_id == sat.id,
            )
        )
        or 0
    ) == 0

    await _fail_and_finalize(db, user=user, sat=sat, local_date=date(2026, 8, 4))
    await db.refresh(progress)
    assert progress.fail_streak == 2
    assert progress.current_step_number == 2

    rec = await db.scalar(
        select(SatelliteRegressionRecommendation).where(
            SatelliteRegressionRecommendation.user_id == user.id,
            SatelliteRegressionRecommendation.exercise_id == sat.id,
        )
    )
    assert rec is not None
    assert rec.status == "pending"
    assert rec.from_step_id == UUID(sat.steps[1]["step_id"])
    assert rec.to_step_id == UUID(sat.steps[0]["step_id"])
    assert rec.expected_progress_revision == progress.progress_revision

    n_suggested = await db.scalar(
        select(func.count())
        .select_from(ProgressionEvent)
        .where(
            ProgressionEvent.user_id == user.id,
            ProgressionEvent.event_type == "satellite_regress_suggested",
        )
    )
    assert int(n_suggested or 0) == 1


@pytest.mark.asyncio
async def test_accept_regresses_one_step(db: AsyncSession) -> None:
    user = await _ready(db, "suggest-accept@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == sat.id,
        )
    )
    assert progress is not None
    progress.current_step_number = 2
    progress.current_step_id = UUID(sat.steps[1]["step_id"])
    await db.commit()
    await _fail_and_finalize(db, user=user, sat=sat, local_date=date(2026, 8, 3))
    await _fail_and_finalize(db, user=user, sat=sat, local_date=date(2026, 8, 4))

    rec = await db.scalar(
        select(SatelliteRegressionRecommendation).where(
            SatelliteRegressionRecommendation.user_id == user.id,
            SatelliteRegressionRecommendation.status == "pending",
        )
    )
    assert rec is not None
    _rec, progress, event = await SatelliteProgressionOrchestrator().decide_recommendation(
        db,
        user_id=user.id,
        exercise_id=sat.id,
        recommendation_id=rec.id,
        decision="accept",
    )
    assert progress.current_step_number == 1
    assert progress.current_step_id == UUID(sat.steps[0]["step_id"])
    assert progress.fail_streak == 0
    assert event is not None
    assert event.event_type == "satellite_regress_confirmed"
    await db.refresh(rec)
    assert rec.status == "accepted"


@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_concurrent_session_create_and_decide_no_deadlock(
    db: AsyncSession,
) -> None:
    """Advisory→row lock order must hold across evaluate_log and decide (P1)."""
    user = await _ready(db, "suggest-concurrent@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == sat.id,
        )
    )
    assert progress is not None
    progress.current_step_number = 2
    progress.current_step_id = UUID(sat.steps[1]["step_id"])
    await db.commit()
    await _fail_and_finalize(db, user=user, sat=sat, local_date=date(2026, 8, 3))
    await _fail_and_finalize(db, user=user, sat=sat, local_date=date(2026, 8, 4))

    rec = await db.scalar(
        select(SatelliteRegressionRecommendation).where(
            SatelliteRegressionRecommendation.user_id == user.id,
            SatelliteRegressionRecommendation.status == "pending",
        )
    )
    assert rec is not None
    rec_id = rec.id
    user_id = user.id
    exercise_id = sat.id
    config_version_id = sat.current_config_version_id
    config_hash = sat.config_hash
    await db.commit()

    engine = create_async_engine(
        settings.resolved_database_url,
        pool_pre_ping=True,
        pool_size=4,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _create() -> None:
        async with factory() as session:
            u = await session.get(User, user_id)
            assert u is not None
            await create_session(
                session,
                user=u,
                body=SessionCreateV1(
                    schema_version=1,
                    performed_at=datetime(2026, 8, 5, 12, 0, tzinfo=UTC),
                    local_date=date(2026, 8, 5),
                    client_mutation_id=new_uuid7(),
                    client_timezone="Europe/Warsaw",
                    logs=[
                        SessionLogCreateV1(
                            exercise_id=exercise_id,
                            exercise_kind="satellite",
                            section="accessories",
                            sets=_fail_sets(),
                            satellite_config_version_id=config_version_id,
                            satellite_config_hash=config_hash,
                        )
                    ],
                ),
                commit=True,
            )

    async def _decide() -> None:
        async with factory() as session:
            try:
                await SatelliteProgressionOrchestrator().decide_recommendation(
                    session,
                    user_id=user_id,
                    exercise_id=exercise_id,
                    recommendation_id=rec_id,
                    decision="accept",
                    commit=True,
                )
            except DomainError as exc:
                # Session may bump progress_revision first → CAS stale (ok).
                if exc.error_code != "recommendation_stale":
                    raise

    try:
        await asyncio.wait_for(asyncio.gather(_create(), _decide()), timeout=15)
    finally:
        await engine.dispose()

    db.expire_all()
    rec_after = await db.get(SatelliteRegressionRecommendation, rec_id)
    assert rec_after is not None
    assert rec_after.status in ("accepted", "stale")
    progress_after = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user_id,
            UserExerciseProgress.exercise_id == exercise_id,
        )
    )
    assert progress_after is not None
    if rec_after.status == "accepted":
        assert progress_after.current_step_number == 1


@pytest.mark.asyncio
async def test_decline_keeps_step_resets_streak(db: AsyncSession) -> None:
    user = await _ready(db, "suggest-decline@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == sat.id,
        )
    )
    assert progress is not None
    progress.current_step_number = 2
    progress.current_step_id = UUID(sat.steps[1]["step_id"])
    await db.commit()
    await _fail_and_finalize(db, user=user, sat=sat, local_date=date(2026, 8, 3))
    await _fail_and_finalize(db, user=user, sat=sat, local_date=date(2026, 8, 4))
    rec = await db.scalar(
        select(SatelliteRegressionRecommendation).where(
            SatelliteRegressionRecommendation.user_id == user.id,
            SatelliteRegressionRecommendation.exercise_id == sat.id,
            SatelliteRegressionRecommendation.status == "pending",
        )
    )
    assert rec is not None
    await SatelliteProgressionOrchestrator().decide_recommendation(
        db,
        user_id=user.id,
        exercise_id=sat.id,
        recommendation_id=rec.id,
        decision="decline",
    )
    await db.refresh(progress)
    await db.refresh(rec)
    assert progress.current_step_number == 2
    assert progress.fail_streak == 0
    assert rec.status == "declined"


@pytest.mark.asyncio
async def test_success_stales_pending_recommendation(db: AsyncSession) -> None:
    user = await _ready(db, "suggest-stale@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == sat.id,
        )
    )
    assert progress is not None
    progress.current_step_number = 2
    progress.current_step_id = UUID(sat.steps[1]["step_id"])
    await db.commit()
    await _fail_and_finalize(db, user=user, sat=sat, local_date=date(2026, 8, 3))
    await _fail_and_finalize(db, user=user, sat=sat, local_date=date(2026, 8, 4))
    rec = await db.scalar(
        select(SatelliteRegressionRecommendation).where(
            SatelliteRegressionRecommendation.user_id == user.id,
            SatelliteRegressionRecommendation.exercise_id == sat.id,
            SatelliteRegressionRecommendation.status == "pending",
        )
    )
    assert rec is not None

    await create_session(
        db,
        user=user,
        body=SessionCreateV1(
            schema_version=1,
            performed_at=datetime(2026, 8, 5, 10, 0, tzinfo=UTC),
            local_date=date(2026, 8, 5),
            client_mutation_id=new_uuid7(),
            client_timezone="Europe/Warsaw",
            logs=[
                SessionLogCreateV1(
                    exercise_id=sat.id,
                    exercise_kind="satellite",
                    section="accessories",
                    sets=_success_sets(),
                    satellite_config_version_id=sat.current_config_version_id,
                    satellite_config_hash=sat.config_hash,
                )
            ],
        ),
        commit=True,
    )
    await db.refresh(rec)
    await db.refresh(progress)
    assert rec.status == "stale"
    assert progress.current_step_number == 3
    assert progress.fail_streak == 0

    with pytest.raises(DomainError) as exc:
        await SatelliteProgressionOrchestrator().decide_recommendation(
            db,
            user_id=user.id,
            exercise_id=sat.id,
            recommendation_id=rec.id,
            decision="accept",
            commit=False,
        )
    assert exc.value.error_code == "recommendation_not_pending"


@pytest.mark.idor
@pytest.mark.asyncio
async def test_recommendation_accept_idor_404(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    owner = await _ready(db, "rec-owner@ex.com")
    other = await _ready(db, "rec-other@ex.com")
    sat = await create_satellite(
        db, user=owner, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == owner.id,
            UserExerciseProgress.exercise_id == sat.id,
        )
    )
    assert progress is not None
    progress.current_step_number = 2
    progress.current_step_id = UUID(sat.steps[1]["step_id"])
    await db.commit()
    await _fail_and_finalize(db, user=owner, sat=sat, local_date=date(2026, 8, 3))
    await _fail_and_finalize(db, user=owner, sat=sat, local_date=date(2026, 8, 4))
    rec = await db.scalar(
        select(SatelliteRegressionRecommendation).where(
            SatelliteRegressionRecommendation.user_id == owner.id
        )
    )
    assert rec is not None

    raw = await AuthSessionService().create_session(db, user=other, user_agent="t")
    api_client.cookies.set(settings.session_cookie_name, raw)
    me = await api_client.get("/api/auth/me")
    assert me.status_code == 200
    csrf = me.json()["csrf_token"]
    res = await api_client.post(
        f"/api/satellites/{sat.id}/regression-recommendations/{rec.id}/accept",
        cookies={settings.csrf_cookie_name: csrf},
        headers={settings.csrf_header_name: csrf},
    )
    assert res.status_code == 404


@pytest.mark.idor
@pytest.mark.asyncio
async def test_recommendation_decline_idor_404(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    owner = await _ready(db, "rec-decline-owner@ex.com")
    other = await _ready(db, "rec-decline-other@ex.com")
    sat = await create_satellite(
        db, user=owner, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == owner.id,
            UserExerciseProgress.exercise_id == sat.id,
        )
    )
    assert progress is not None
    progress.current_step_number = 2
    progress.current_step_id = UUID(sat.steps[1]["step_id"])
    await db.commit()
    await _fail_and_finalize(db, user=owner, sat=sat, local_date=date(2026, 8, 3))
    await _fail_and_finalize(db, user=owner, sat=sat, local_date=date(2026, 8, 4))
    rec = await db.scalar(
        select(SatelliteRegressionRecommendation).where(
            SatelliteRegressionRecommendation.user_id == owner.id
        )
    )
    assert rec is not None

    raw = await AuthSessionService().create_session(db, user=other, user_agent="t")
    api_client.cookies.set(settings.session_cookie_name, raw)
    me = await api_client.get("/api/auth/me")
    assert me.status_code == 200
    csrf = me.json()["csrf_token"]
    res = await api_client.post(
        f"/api/satellites/{sat.id}/regression-recommendations/{rec.id}/decline",
        cookies={settings.csrf_cookie_name: csrf},
        headers={settings.csrf_header_name: csrf},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_recommendation_accept_requires_csrf(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    user = await _ready(db, "rec-csrf@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == sat.id,
        )
    )
    assert progress is not None
    progress.current_step_number = 2
    progress.current_step_id = UUID(sat.steps[1]["step_id"])
    await db.commit()
    await _fail_and_finalize(db, user=user, sat=sat, local_date=date(2026, 8, 3))
    await _fail_and_finalize(db, user=user, sat=sat, local_date=date(2026, 8, 4))
    rec = await db.scalar(
        select(SatelliteRegressionRecommendation).where(
            SatelliteRegressionRecommendation.user_id == user.id
        )
    )
    assert rec is not None
    raw = await AuthSessionService().create_session(db, user=user, user_agent="t")
    api_client.cookies.set(settings.session_cookie_name, raw)
    res = await api_client.post(
        f"/api/satellites/{sat.id}/regression-recommendations/{rec.id}/accept",
    )
    assert res.status_code == 403
    assert res.json()["error_code"] == "csrf_invalid"
