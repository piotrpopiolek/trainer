"""Smoke checks for db-core schema (requires Compose Postgres + migrated DB)."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7


@pytest.mark.asyncio
async def test_new_uuid7_is_version_7() -> None:
    assert new_uuid7().version == 7


@pytest.mark.asyncio
async def test_db_core_tables_exist() -> None:
    expected = {
        "users",
        "auth_sessions",
        "oauth_states",
        "legal_documents",
        "legal_document_translations",
        "user_legal_acceptances",
        "user_onboarding",
        "body_measurements",
        "alembic_version",
    }
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' ORDER BY 1"
                )
            )
            tables = {row[0] for row in rows}
    finally:
        await engine.dispose()
    assert expected <= tables


@pytest.mark.asyncio
async def test_body_measurements_rls_enabled() -> None:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            row = await conn.execute(
                text(
                    "SELECT relrowsecurity FROM pg_class "
                    "WHERE relname = 'body_measurements'"
                )
            )
            enabled = row.scalar_one()
    finally:
        await engine.dispose()
    assert enabled is True
