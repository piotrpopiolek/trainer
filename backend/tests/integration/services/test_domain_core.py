"""Domain-core: contracts, resolve_cc_day, legal gate, onboarding."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.models.progression import UserProgramEnrollment
from app.models.user import User
from app.services.cc_day import promote_pending_schedule
from app.services.errors import DomainError, LegalRequiredError
from app.services.legal import (
    record_legal_acceptance,
    require_health_disclaimer_for_session,
)
from app.services.onboarding import complete_onboarding
from app.services.rate_limit import reset_memory_rate_limits
from tests.legal_fixtures import latest_health_disclaimer


@pytest.fixture(autouse=True)
def _reset_limits() -> None:
    reset_memory_rate_limits()
    settings.rate_limit_store = "memory"
    yield
    reset_memory_rate_limits()


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine(settings.resolved_database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()




















@pytest.mark.asyncio
async def test_promote_pending_anchor(db: AsyncSession) -> None:
    user = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}", email="p@ex.com")
    db.add(user)
    await db.flush()
    # Need a program — use any from seed or skip if not seeded
    from app.models.catalog import Program

    program = await db.scalar(select(Program).where(Program.slug == "cc_big_six"))
    if program is None:
        pytest.skip("seed catalog required")
    enrollment = UserProgramEnrollment(
        id=new_uuid7(),
        user_id=user.id,
        program_id=program.id,
        started_on=date(2026, 7, 1),
        anchor_weekday=1,
        pending_anchor_weekday=2,
        schedule_effective_on=date(2026, 7, 27),
        rotation_offset=0,
        is_active=True,
    )
    db.add(enrollment)
    await db.commit()

    await promote_pending_schedule(
        db, user, enrollment, local_date=date(2026, 7, 27)
    )
    await db.commit()
    assert enrollment.anchor_weekday == 2
    assert enrollment.pending_anchor_weekday is None


@pytest.mark.asyncio
async def test_legal_gate_blocks_without_acceptance(db: AsyncSession) -> None:
    user = User(
        id=new_uuid7(),
        google_sub=f"sub-{new_uuid7()}",
        email="legal@ex.com",
        locale="pl-PL",
    )
    db.add(user)
    await db.commit()
    with pytest.raises(LegalRequiredError):
        await require_health_disclaimer_for_session(
            db, user_id=user.id, locale="pl-PL"
        )


@pytest.mark.asyncio
async def test_legal_acceptance_and_gate_pass(db: AsyncSession) -> None:
    doc, tr = await latest_health_disclaimer(db)
    user = User(
        id=new_uuid7(),
        google_sub=f"sub-{new_uuid7()}",
        email="ok@ex.com",
        locale="pl-PL",
    )
    db.add(user)
    await db.commit()

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
    await require_health_disclaimer_for_session(db, user_id=user.id, locale="pl-PL")


@pytest.mark.asyncio
async def test_onboarding_complete_creates_enrollment(db: AsyncSession) -> None:
    from app.models.catalog import Program

    if await db.scalar(select(Program).where(Program.slug == "cc_big_six")) is None:
        pytest.skip("seed catalog required")

    user = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}", email="ob@ex.com")
    db.add(user)
    await db.commit()

    row = await complete_onboarding(
        db,
        user,
        questionnaire={
            "schema_version": 1,
            "experience_level": "beginner",
            "training_days_per_week": 3,
            "goals": ["strength"],
        },
        anchor_weekday=1,
        started_on=date(2026, 7, 27),
    )
    assert row.completed_at is not None
    assert row.recommended_steps["steps"]["push_ups"] == 1
    enrollment = await db.scalar(
        select(UserProgramEnrollment).where(
            UserProgramEnrollment.user_id == user.id,
            UserProgramEnrollment.is_active.is_(True),
        )
    )
    assert enrollment is not None
    assert enrollment.anchor_weekday == 1


@pytest.mark.asyncio
async def test_onboarding_rejects_partial_chosen_steps(db: AsyncSession) -> None:
    from app.models.catalog import Program

    if await db.scalar(select(Program).where(Program.slug == "cc_big_six")) is None:
        pytest.skip("seed catalog required")

    user = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}", email="partial@ex.com")
    db.add(user)
    await db.commit()

    with pytest.raises(DomainError) as exc:
        await complete_onboarding(
            db,
            user,
            questionnaire={
                "schema_version": 1,
                "experience_level": "beginner",
                "training_days_per_week": 3,
            },
            chosen_steps={"schema_version": 1, "steps": {"push_ups": 2}},
            started_on=date(2026, 7, 27),
        )
    assert exc.value.error_code == "incomplete_chosen_steps"
