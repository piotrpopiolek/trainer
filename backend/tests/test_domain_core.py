"""Domain-core: contracts, resolve_cc_day, legal gate, onboarding."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.db.session import dispose_engine
from app.main import app
from app.models.legal import LegalDocument, LegalDocumentTranslation
from app.models.progression import UserProgramEnrollment
from app.models.user import User
from app.schemas.common import parse_versioned
from app.schemas.rules import ProgressionRulesV1
from app.schemas.sets import SessionSetsV1
from app.services.auth_session import AuthSessionService
from app.services.cc_day import promote_pending_schedule, resolve_cc_day
from app.services.errors import DomainError, LegalRequiredError
from app.services.legal import (
    record_legal_acceptance,
    require_health_disclaimer_for_session,
)
from app.services.onboarding import complete_onboarding
from app.services.rate_limit import reset_memory_rate_limits


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


@pytest.fixture
async def api_client() -> AsyncClient:
    await dispose_engine()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        yield client
    await dispose_engine()


def test_parse_sets_requires_schema_version() -> None:
    with pytest.raises(DomainError) as exc:
        parse_versioned(SessionSetsV1, {"sets": []})
    assert exc.value.error_code == "schema_version_required"


def test_parse_rejects_unsupported_schema_version() -> None:
    with pytest.raises(DomainError) as exc:
        parse_versioned(SessionSetsV1, {"schema_version": 2, "sets": []})
    assert exc.value.error_code == "schema_version_unsupported"


def test_parse_rules_v1_from_seed_shape() -> None:
    rules = parse_versioned(
        ProgressionRulesV1,
        {
            "schema_version": 1,
            "advance": {"sets": 3, "min_reps": 10, "require_both_sides": False},
            "regress": {"fail_sessions": 2},
            "goal": None,
        },
    )
    assert rules.advance is not None
    assert rules.advance.min_reps == 10


def test_resolve_cc_day_mon_wed_fri_anchor_1() -> None:
    # 2026-07-27 is Monday
    mon = date(2026, 7, 27)
    assert resolve_cc_day(mon, anchor_weekday=1).day_index == 1
    assert resolve_cc_day(date(2026, 7, 28), anchor_weekday=1).is_rest_day
    assert resolve_cc_day(date(2026, 7, 29), anchor_weekday=1).day_index == 2
    assert resolve_cc_day(date(2026, 7, 31), anchor_weekday=1).day_index == 3


def test_resolve_cc_day_rotation_offset() -> None:
    mon = date(2026, 7, 27)
    r = resolve_cc_day(mon, anchor_weekday=1, rotation_offset=1)
    assert r.day_index == 2


def test_resolve_cc_day_before_started_on() -> None:
    r = resolve_cc_day(
        date(2026, 7, 27),
        anchor_weekday=1,
        started_on=date(2026, 8, 1),
    )
    assert r.before_started_on
    assert r.is_rest_day


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
    doc = await db.scalar(
        select(LegalDocument).where(LegalDocument.slug == "health_disclaimer")
    )
    if doc is None:
        pytest.skip("legal seed required")
    tr = await db.scalar(
        select(LegalDocumentTranslation).where(
            LegalDocumentTranslation.document_id == doc.id,
            LegalDocumentTranslation.locale == "pl-PL",
        )
    )
    assert tr is not None
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
            "document_version": "1",
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


@pytest.mark.asyncio
async def test_onboarding_api(api_client: AsyncClient, db: AsyncSession) -> None:
    from app.models.catalog import Program

    if await db.scalar(select(Program).where(Program.slug == "cc_big_six")) is None:
        pytest.skip("seed catalog required")

    svc = AuthSessionService()
    user = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}", email="apiob@ex.com")
    db.add(user)
    await db.commit()
    raw = await svc.create_session(db, user=user, user_agent="t")
    res = await api_client.post(
        "/api/onboarding/complete",
        cookies={settings.session_cookie_name: raw},
        json={
            "schema_version": 1,
            "questionnaire": {
                "schema_version": 1,
                "experience_level": "intermediate",
                "training_days_per_week": 3,
            },
            "anchor_weekday": 2,
            "started_on": "2026-07-27",
        },
    )
    assert res.status_code == 200
    assert res.json()["chosen_steps"]["steps"]["pull_ups"] == 3
