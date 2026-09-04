"""Today read-model: all active satellites with due_today schedule flag."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.models.catalog import Exercise, Program
from app.models.user import User
from app.schemas.api import SatelliteCreateV1
from app.services.legal import record_legal_acceptance
from app.services.onboarding import complete_onboarding
from app.services.satellites import create_satellite
from app.services.today import _build_satellites, _satellite_due_today, build_today
from tests.legal_fixtures import latest_health_disclaimer


def test_satellite_due_today_weekdays_and_categories() -> None:
    monday = date(2026, 9, 7)  # ISO Monday
    sat = Exercise(
        id=uuid4(),
        kind="satellite",
        name="WD",
        exercise_type="B",
        schedule_kind="weekdays",
        weekdays=[1, 3, 5],
        active_metrics={"schema_version": 1, "metrics": ["reps"]},
    )
    assert _satellite_due_today(sat, local_date=monday, is_rest_day=True) is True
    assert (
        _satellite_due_today(sat, local_date=date(2026, 9, 8), is_rest_day=False)
        is False
    )

    post = Exercise(
        id=uuid4(),
        kind="satellite",
        name="Post",
        exercise_type="B",
        schedule_kind="category",
        schedule_category="post_workout",
        active_metrics={"schema_version": 1, "metrics": ["reps"]},
    )
    assert _satellite_due_today(post, local_date=monday, is_rest_day=True) is False
    assert _satellite_due_today(post, local_date=monday, is_rest_day=False) is True

    rest = Exercise(
        id=uuid4(),
        kind="satellite",
        name="Rest",
        exercise_type="C",
        schedule_kind="category",
        schedule_category="rest_day",
        active_metrics={"schema_version": 1, "metrics": []},
    )
    assert _satellite_due_today(rest, local_date=monday, is_rest_day=True) is True
    assert _satellite_due_today(rest, local_date=monday, is_rest_day=False) is False


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


def _goal_body(*, name: str, weekdays: list[int] | None = None) -> SatelliteCreateV1:
    body: dict = {
        "schema_version": 1,
        "name": name,
        "exercise_type": "B",
        "active_metrics": {"schema_version": 1, "metrics": ["reps"]},
        "schedule_kind": "daily" if weekdays is None else "weekdays",
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
    if weekdays is not None:
        body["weekdays"] = weekdays
    return SatelliteCreateV1.model_validate(body)


@pytest.mark.asyncio
async def test_build_satellites_includes_off_schedule(db: AsyncSession) -> None:
    user = await _ready(db, f"due-flag-{uuid4().hex[:8]}@example.com")
    await create_satellite(
        db, user=user, body=_goal_body(name="Due Daily"), commit=True
    )
    await create_satellite(
        db,
        user=user,
        body=_goal_body(name="Off Weekdays", weekdays=[2, 4, 6]),
        commit=True,
    )

    items = await _build_satellites(
        db,
        user_id=user.id,
        local_date=date(2026, 9, 7),  # Monday
        is_rest_day=True,
    )
    by_name = {i.name: i for i in items}
    assert "Due Daily" in by_name
    assert "Off Weekdays" in by_name
    assert by_name["Due Daily"].due_today is True
    assert by_name["Off Weekdays"].due_today is False
    assert items[0].due_today is True

    dto = await build_today(db, user=user, local_date=date(2026, 9, 7))
    assert len(dto.satellites) == 2
    assert any(s.due_today for s in dto.satellites)
    assert any(not s.due_today for s in dto.satellites)
