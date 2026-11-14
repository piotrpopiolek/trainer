"""Stage 5 — GET /today satellite path is O(1) queries in sat count (no N+1)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.models.catalog import Program
from app.models.user import User
from app.schemas.api import SatelliteCreateV1
from app.services.legal import record_legal_acceptance
from app.services.onboarding import complete_onboarding
from app.services.satellites import create_satellite
from app.services.today import build_today
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


def _goal_only_body(*, name: str) -> SatelliteCreateV1:
    return SatelliteCreateV1.model_validate(
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
                }
            ],
            "client_mutation_id": str(new_uuid7()),
        }
    )


@pytest.mark.asyncio
async def test_today_satellite_queries_do_not_grow_with_sat_count(
    db: AsyncSession,
) -> None:
    async def _count_for(n: int) -> tuple[int, int]:
        user = await _ready(db, f"today-n1-{n}@ex.com")
        for i in range(n):
            await create_satellite(
                db, user=user, body=_goal_only_body(name=f"N+1 sat {n}-{i}"), commit=True
            )
        sync_engine = db.bind.sync_engine
        statements: list[str] = []

        def _before_cursor(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(sync_engine, "before_cursor_execute", _before_cursor)
        try:
            dto = await build_today(db, user=user, local_date=date(2030, 8, 5))
        finally:
            event.remove(sync_engine, "before_cursor_execute", _before_cursor)
        return len(dto.satellites), len(statements)

    n2, q2 = await _count_for(2)
    n5, q5 = await _count_for(5)
    assert n2 == 2 and n5 == 5
    # Batched path: query count must stay nearly flat vs satellite count.
    assert q5 - q2 <= 5, f"query growth too steep: 2→{q2}, 5→{q5}"
    assert q5 <= 45, f"too many SQL statements for 5 sats: {q5}"
