"""Account export includes satellite ledger (FR-006b / Stage 5)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.models.catalog import Program
from app.models.satellite_progress import SatelliteDailyOutcome
from app.models.user import User
from app.schemas.api import SatelliteCreateV1, SessionCreateV1, SessionLogCreateV1
from app.services.account import stream_account_export
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
    await db.refresh(user)
    return user


@pytest.mark.asyncio
async def test_export_includes_satellite_ledger_collections(db: AsyncSession) -> None:
    user = await _ready(db, "export-sat-ledger@ex.com")
    sat = await create_satellite(
        db,
        user=user,
        body=SatelliteCreateV1.model_validate(
            {
                "schema_version": 1,
                "name": "Export Hip",
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
                        "rules": {
                            "schema_version": 1,
                            "goal": {
                                "type": "reps",
                                "sets": 1,
                                "min_reps": 5,
                                "require_both_sides": False,
                                "min_weight_kg": None,
                            },
                        },
                    },
                    {
                        "step_number": 2,
                        "step_id": str(new_uuid7()),
                        "name": "Step B",
                        "rules": {
                            "schema_version": 1,
                            "goal": {
                                "type": "reps",
                                "sets": 1,
                                "min_reps": 5,
                                "require_both_sides": False,
                                "min_weight_kg": None,
                            },
                        },
                    },
                ],
                "client_mutation_id": str(new_uuid7()),
            }
        ),
        commit=True,
    )
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
    outcome = await db.scalar(
        select(SatelliteDailyOutcome).where(
            SatelliteDailyOutcome.user_id == user.id,
            SatelliteDailyOutcome.exercise_id == sat.id,
        )
    )
    assert outcome is not None

    lines: list[dict] = []
    async for chunk in stream_account_export(db, user_id=user.id):
        for raw in chunk.decode().splitlines():
            if raw.strip():
                lines.append(json.loads(raw))

    collections = {row["collection"] for row in lines}
    for required in (
        "satellites",
        "satellite_steps",
        "satellite_config_versions",
        "satellite_config_activations",
        "satellite_daily_outcomes",
        "session_exercise_logs",
    ):
        assert required in collections, f"missing collection {required}"

    sat_row = next(r for r in lines if r["collection"] == "satellites")
    assert sat_row["name"] == "Export Hip"
    assert sat_row["current_config_version_id"] == str(sat.current_config_version_id)

    cfg_row = next(r for r in lines if r["collection"] == "satellite_config_versions")
    assert "document" in cfg_row
    assert "config_hash" in cfg_row
    assert "rules_snapshot" not in json.dumps(lines)

    outcome_row = next(r for r in lines if r["collection"] == "satellite_daily_outcomes")
    assert outcome_row["id"] == str(outcome.id)
    assert outcome_row["status"] in {"pending", "finalized"}

    assert any(r["collection"] == "meta" and r.get("status") == "done" for r in lines)
