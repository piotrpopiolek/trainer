"""HTTP recommendation accept/decline. Write helpers stay with the service suite."""

from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.db.session import dispose_engine
from app.main import app
from app.models.progression import UserExerciseProgress
from app.models.satellite_progress import SatelliteRegressionRecommendation
from app.services.auth_session import AuthSessionService
from app.services.rate_limit import reset_memory_rate_limits
from app.services.satellites import create_satellite
from tests.integration.services.test_satellite_regression_stage3_slice_d import (
    _copenhagen_body,
    _fail_and_finalize,
    _ready,
)


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
    await db.refresh(progress)
    assert progress.current_step_number == 2

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
    await db.refresh(progress)
    assert progress.current_step_number == 2

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
