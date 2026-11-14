"""get_for_user denies a foreign measurement."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.models.body_measurement import BodyMeasurement
from app.models.user import User
from app.repositories.access import get_for_user
from app.services.errors import NotFoundError


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine(settings.resolved_database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()

@pytest.mark.asyncio
async def test_get_for_user_foreign_is_not_found(db: AsyncSession) -> None:
    from sqlalchemy import text

    owner = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}", email="a@ex.com")
    other = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}", email="b@ex.com")
    db.add_all([owner, other])
    await db.commit()
    await db.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(owner.id)},
    )
    row = BodyMeasurement(
        id=new_uuid7(),
        user_id=owner.id,
        measured_at=datetime.now(UTC),
        local_date=datetime.now(UTC).date(),
        metrics={"schema_version": 1, "weight_kg": 80},
        client_mutation_id=new_uuid7(),
        revision=1,
        client_updated_at=datetime.now(UTC),
    )
    db.add(row)
    await db.commit()

    await db.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(other.id)},
    )
    with pytest.raises(NotFoundError):
        await get_for_user(db, BodyMeasurement, user_id=other.id, entity_id=row.id)

    await db.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(owner.id)},
    )
    found = await get_for_user(db, BodyMeasurement, user_id=owner.id, entity_id=row.id)
    assert found.id == row.id
