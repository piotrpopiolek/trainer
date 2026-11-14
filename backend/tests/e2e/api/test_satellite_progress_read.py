"""Satellite progress read API — list + IDOR + points aggregation."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.main import app
from app.models.catalog import Program
from app.models.user import User
from app.schemas.api import SatelliteCreateV1, SessionCreateV1, SessionLogCreateV1
from app.services.auth_session import AuthSessionService
from app.services.legal import record_legal_acceptance
from app.services.onboarding import complete_onboarding
from app.services.rate_limit import reset_memory_rate_limits
from app.services.satellites import create_satellite
from app.services.sessions import create_session
from tests.legal_fixtures import latest_health_disclaimer


@pytest.fixture(autouse=True)
def _reset_limits() -> None:
    reset_memory_rate_limits()
    settings.rate_limit_store = "memory"


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine(settings.resolved_database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def api_client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _ready(db: AsyncSession, email: str) -> tuple[User, str]:
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
    raw = await AuthSessionService().create_session(db, user=user, user_agent="t")
    return user, raw






@pytest.mark.asyncio
async def test_list_satellite_progress_and_idor(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    user_a, raw_a = await _ready(db, "sat-prog-a@ex.com")
    user_b, raw_b = await _ready(db, "sat-prog-b@ex.com")

    sat = await create_satellite(
        db,
        user=user_a,
        body=SatelliteCreateV1.model_validate(
            {
                "schema_version": 1,
                "name": "Curl Progress",
                "exercise_type": "B",
                "active_metrics": {
                    "schema_version": 1,
                    "metrics": ["reps", "weight_kg", "sides"],
                },
                "equipment": ["dumbbell"],
                "schedule_kind": "weekdays",
                "weekdays": [2, 4, 6],
                "steps": [
                    {
                        "step_number": 1,
                        "name": "Serie",
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
        ),
        commit=True,
    )

    performed_at = datetime.now(UTC)
    local_date = performed_at.astimezone(ZoneInfo("Europe/Warsaw")).date()
    await create_session(
        db,
        user=user_a,
        body=SessionCreateV1(
            schema_version=1,
            performed_at=performed_at,
            local_date=local_date,
            client_mutation_id=new_uuid7(),
            client_timezone="Europe/Warsaw",
            logs=[
                SessionLogCreateV1(
                    exercise_id=sat.id,
                    exercise_kind="satellite",
                    section="accessories",
                    sets={
                        "schema_version": 1,
                        "completed": None,
                        "sets": (
                            [{"reps": 10, "weight_kg": "12.000", "sides": "left"}] * 3
                            + [{"reps": 10, "weight_kg": "12.000", "sides": "right"}]
                            * 3
                        ),
                    },
                    satellite_config_version_id=sat.current_config_version_id,
                    satellite_config_hash=sat.config_hash,
                )
            ],
        ),
        commit=True,
    )

    listed = await api_client.get(
        "/api/progress/satellites",
        cookies={settings.session_cookie_name: raw_a},
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["schema_version"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["id"] == str(sat.id)
    assert item["name"] == "Curl Progress"
    assert item["weekdays"] == [2, 4, 6]
    assert len(item["points"]) == 1
    assert item["points"][0]["local_date"] == local_date.isoformat()
    assert item["points"][0]["best_reps"] == 10
    assert item["points"][0]["best_weight_kg"] == 12.0
    assert item["last_session_summary"] == "6×10"

    detail = await api_client.get(
        f"/api/progress/satellites/{sat.id}",
        cookies={settings.session_cookie_name: raw_a},
    )
    assert detail.status_code == 200
    assert detail.json()["id"] == str(sat.id)

    idor = await api_client.get(
        f"/api/progress/satellites/{sat.id}",
        cookies={settings.session_cookie_name: raw_b},
    )
    assert idor.status_code == 404

    empty_b = await api_client.get(
        "/api/progress/satellites",
        cookies={settings.session_cookie_name: raw_b},
    )
    assert empty_b.status_code == 200
    assert empty_b.json()["items"] == []
