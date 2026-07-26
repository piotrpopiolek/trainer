"""Smoke checks for db-catalog-sync schema + triggers."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7


@pytest.fixture
async def engine():
    eng = create_async_engine(settings.resolved_database_url, pool_pre_ping=True)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.mark.asyncio
async def test_catalog_sync_tables_exist(engine) -> None:
    expected = {
        "programs",
        "program_translations",
        "program_days",
        "program_day_translations",
        "exercises",
        "exercise_translations",
        "program_day_exercises",
        "progression_schemas",
        "exercise_steps",
        "exercise_step_translations",
        "user_program_enrollments",
        "user_exercise_progress",
        "workout_sessions",
        "session_exercise_logs",
        "progression_events",
        "sync_conflict_logs",
        "sync_devices",
        "client_mutations",
        "rate_limit_buckets",
    }
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' ORDER BY 1"
            )
        )
        tables = {row[0] for row in rows}
    assert expected <= tables


@pytest.mark.asyncio
async def test_catalog_triggers_exist(engine) -> None:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT tgname FROM pg_trigger "
                "WHERE NOT tgisinternal AND tgname IN "
                "('trg_satellite_limit', 'trg_progress_exercise_owner')"
            )
        )
        names = {row[0] for row in rows}
    assert names == {"trg_satellite_limit", "trg_progress_exercise_owner"}


@pytest.mark.asyncio
async def test_progress_owner_rejects_foreign_satellite(engine) -> None:
    owner_id = new_uuid7()
    other_id = new_uuid7()
    exercise_id = new_uuid7()
    progress_id = new_uuid7()

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO users (id, locale, timezone) VALUES "
                "(:a, 'pl-PL', 'Europe/Warsaw'), (:b, 'pl-PL', 'Europe/Warsaw')"
            ),
            {"a": owner_id, "b": other_id},
        )
        await conn.execute(
            text(
                """
                INSERT INTO exercises (
                  id, user_id, kind, exercise_type, name, schedule_kind,
                  client_mutation_id, revision, client_updated_at
                ) VALUES (
                  :eid, :uid, 'satellite', 'B', 'Pull', 'daily',
                  :cmid, 1, now()
                )
                """
            ),
            {"eid": exercise_id, "uid": owner_id, "cmid": uuid4()},
        )

    async with engine.connect() as conn:
        with pytest.raises(DBAPIError):
            async with conn.begin():
                await conn.execute(
                    text(
                        """
                        INSERT INTO user_exercise_progress (
                          id, user_id, exercise_id, current_step_number
                        ) VALUES (:pid, :uid, :eid, 1)
                        """
                    ),
                    {"pid": progress_id, "uid": other_id, "eid": exercise_id},
                )
