"""Seed runner applies the catalog twice against Postgres."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.seed.runner import run_seed


@pytest.mark.asyncio
async def test_seed_runner_idempotent() -> None:
    first = await run_seed()
    second = await run_seed()
    assert first["exercises"] == 6
    assert first["exercise_steps"] == 60
    assert first["legal_documents"] == 2
    assert second["exercises"] == 6
    assert second["exercise_steps"] == 60

    engine = create_async_engine(settings.resolved_database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            cc = await conn.scalar(
                text("SELECT COUNT(*) FROM exercises WHERE kind = 'cc'")
            )
            steps = await conn.scalar(
                text(
                    "SELECT COUNT(*) FROM exercise_steps es "
                    "JOIN exercises e ON e.id = es.exercise_id "
                    "WHERE e.kind = 'cc'"
                )
            )
            step_tr = await conn.scalar(
                text(
                    "SELECT COUNT(*) FROM exercise_step_translations est "
                    "JOIN exercise_steps es ON es.id = est.exercise_step_id "
                    "JOIN exercises e ON e.id = es.exercise_id "
                    "WHERE e.kind = 'cc' AND est.locale = 'pl-PL' "
                    "AND est.content_status = 'ready'"
                )
            )
            days = await conn.scalar(text("SELECT COUNT(*) FROM program_days"))
    finally:
        await engine.dispose()

    assert cc == 6
    assert steps == 60
    assert step_tr == 60
    assert days == 3
