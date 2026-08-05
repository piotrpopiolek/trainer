"""Golden Hip Thrust + Copenhagen presets — validate + create smoke."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.domain.satellite_presets import (
    PRESET_IDS,
    build_satellite_preset_create,
    list_satellite_presets,
)
from app.models.catalog import Program
from app.models.user import User
from app.schemas.api import SatelliteCreateV1
from app.services.auth_session import AuthSessionService
from app.services.legal import record_legal_acceptance
from app.services.onboarding import complete_onboarding
from app.services.satellites import create_satellite
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


def test_preset_catalog_lists_plan_fixtures() -> None:
    catalog = list_satellite_presets()
    assert [p["id"] for p in catalog] == list(PRESET_IDS)
    assert catalog[0]["default_name"] == "SL Hip Thrust (DB)"
    assert catalog[1]["default_name"] == "Copenhagen Plank"


@pytest.mark.parametrize("preset_id", list(PRESET_IDS))
def test_preset_bodies_validate_as_create_v1(preset_id: str) -> None:
    body = SatelliteCreateV1.model_validate(
        build_satellite_preset_create(preset_id)  # type: ignore[arg-type]
    )
    assert body.schema_version == 1
    if preset_id == "sl_hip_thrust_db":
        assert body.progression.mode == "goal_only"
        assert len(body.steps) == 1
        assert body.schedule_kind == "weekdays"
        assert body.weekdays == [1, 3, 5]
        assert set(body.active_metrics["metrics"]) == {"reps", "weight_kg", "sides"}
    else:
        assert body.progression.mode == "steps"
        assert len(body.steps) == 3
        assert body.schedule_kind == "category"
        assert body.schedule_category == "post_workout"
        assert set(body.active_metrics["metrics"]) == {"duration_sec", "sides"}


@pytest.mark.asyncio
async def test_create_hip_thrust_and_copenhagen_from_presets(db: AsyncSession) -> None:
    user = await _ready(db, "presets@ex.com")
    hip = await create_satellite(
        db,
        user=user,
        body=SatelliteCreateV1.model_validate(
            build_satellite_preset_create(
                "sl_hip_thrust_db", client_mutation_id=new_uuid7()
            )
        ),
        commit=True,
    )
    cph = await create_satellite(
        db,
        user=user,
        body=SatelliteCreateV1.model_validate(
            build_satellite_preset_create(
                "copenhagen_plank", client_mutation_id=new_uuid7()
            )
        ),
        commit=True,
    )
    assert hip.name == "SL Hip Thrust (DB)"
    assert hip.current_config_version_id is not None
    assert hip.config_hash is not None
    assert len(hip.steps) == 1
    assert cph.name == "Copenhagen Plank"
    assert len(cph.steps) == 3
    assert cph.schedule_category == "post_workout"
