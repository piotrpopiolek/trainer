"""Satellite HTTP IDOR. Setup helpers stay in the service suite."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.db.session import dispose_engine
from app.main import app
from app.models.progression import UserExerciseProgress
from app.models.satellite_progress import SatelliteDailyOutcome
from app.schemas.api import SessionCreateV1, SessionLogCreateV1
from app.services.auth_session import AuthSessionService
from app.services.rate_limit import reset_memory_rate_limits
from app.services.satellite_progression import SatelliteProgressionOrchestrator
from app.services.satellites import create_satellite
from app.services.sessions import create_session
from tests.integration.services.test_satellite_idor_concurrency_stage5_slice_a import (
    _copenhagen_body,
    _fail_sets,
    _ready,
)


@pytest.fixture(autouse=True)
def _reset_limits() -> None:
    reset_memory_rate_limits()
    settings.rate_limit_store = "memory"
    yield
    reset_memory_rate_limits()

@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine(settings.resolved_database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()

@pytest.fixture
async def api_client() -> AsyncClient:
    await dispose_engine()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        yield client
    await dispose_engine()

@pytest.mark.idor
@pytest.mark.asyncio
async def test_get_satellite_idor_404(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    owner = await _ready(db, "e5a-get-owner@ex.com")
    other = await _ready(db, "e5a-get-other@ex.com")
    sat = await create_satellite(
        db, user=owner, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    raw = await AuthSessionService().create_session(db, user=other, user_agent="t")
    api_client.cookies.set(settings.session_cookie_name, raw)
    res = await api_client.get(f"/api/satellites/{sat.id}")
    assert res.status_code == 404
    from app.models.catalog import Exercise

    row = await db.get(Exercise, sat.id)
    assert row is not None
    assert row.user_id == owner.id
    assert row.deleted_at is None

@pytest.mark.idor
@pytest.mark.asyncio
async def test_recommendation_accept_mismatched_exercise_idor(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    user = await _ready(db, "e5a-rec-mismatch@ex.com")
    sat_a = await create_satellite(
        db,
        user=user,
        body=_copenhagen_body(mutation_id=new_uuid7(), name="A"),
        commit=True,
    )
    sat_b = await create_satellite(
        db,
        user=user,
        body=_copenhagen_body(mutation_id=new_uuid7(), name="B"),
        commit=True,
    )
    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == sat_a.id,
        )
    )
    assert progress is not None
    progress.current_step_number = 2
    progress.current_step_id = UUID(sat_a.steps[1]["step_id"])
    await db.commit()

    for d in (date(2026, 8, 3), date(2026, 8, 4)):
        await create_session(
            db,
            user=user,
            body=SessionCreateV1(
                schema_version=1,
                performed_at=datetime(d.year, d.month, d.day, 10, 0, tzinfo=UTC),
                local_date=d,
                client_mutation_id=new_uuid7(),
                client_timezone="Europe/Warsaw",
                logs=[
                    SessionLogCreateV1(
                        exercise_id=sat_a.id,
                        exercise_kind="satellite",
                        section="accessories",
                        sets=_fail_sets(),
                        satellite_config_version_id=sat_a.current_config_version_id,
                        satellite_config_hash=sat_a.config_hash,
                    )
                ],
            ),
            commit=True,
        )
        outcome = await db.scalar(
            select(SatelliteDailyOutcome).where(
                SatelliteDailyOutcome.user_id == user.id,
                SatelliteDailyOutcome.exercise_id == sat_a.id,
                SatelliteDailyOutcome.local_date == d,
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
            db, user_id=user.id, exercise_id=sat_a.id
        )
        await db.commit()

    from app.models.satellite_progress import SatelliteRegressionRecommendation

    rec = await db.scalar(
        select(SatelliteRegressionRecommendation).where(
            SatelliteRegressionRecommendation.user_id == user.id,
            SatelliteRegressionRecommendation.exercise_id == sat_a.id,
            SatelliteRegressionRecommendation.status == "pending",
        )
    )
    assert rec is not None

    raw = await AuthSessionService().create_session(db, user=user, user_agent="t")
    api_client.cookies.set(settings.session_cookie_name, raw)
    me = await api_client.get("/api/auth/me")
    csrf = me.json()["csrf_token"]
    res = await api_client.post(
        f"/api/satellites/{sat_b.id}/regression-recommendations/{rec.id}/accept",
        cookies={settings.csrf_cookie_name: csrf},
        headers={settings.csrf_header_name: csrf},
    )
    assert res.status_code == 404
    await db.refresh(progress)
    assert progress.current_step_number == 2
