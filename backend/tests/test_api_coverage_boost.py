"""Extra coverage for api-readwrite services (today, catalog, account, sessions)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.db.session import dispose_engine
from app.main import app
from app.models.body_measurement import BodyMeasurement
from app.models.catalog import Program
from app.models.user import User
from app.models.workout import WorkoutSession
from app.services.account import soft_delete_account, stream_account_export
from app.services.auth_session import AuthSessionService
from app.services.catalog import build_cc_catalog, catalog_etag
from app.services.errors import DomainError
from app.services.legal import record_legal_acceptance
from app.services.onboarding import complete_onboarding
from app.services.rate_limit import reset_memory_rate_limits
from app.services.today import build_today
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


@pytest.fixture
async def api_client() -> AsyncClient:
    await dispose_engine()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        yield client
    await dispose_engine()


async def _ready_user(db: AsyncSession, email: str) -> tuple[User, str]:
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
    raw = await AuthSessionService().create_session(db, user=user, user_agent="t")
    return user, raw


@pytest.mark.asyncio
async def test_build_today_rest_override(db: AsyncSession) -> None:
    user, _raw = await _ready_user(db, "today-rest@ex.com")
    dto = await build_today(
        db, user=user, local_date=date(2026, 7, 28), cc_day_override=2
    )
    assert dto.is_rest_day is True
    assert dto.cc_day_override == 2
    assert dto.split_day == 2
    assert len(dto.cc_exercises) == 2


@pytest.mark.asyncio
async def test_build_today_rejects_override_on_training_day(db: AsyncSession) -> None:
    user, _raw = await _ready_user(db, "today-ovr@ex.com")
    with pytest.raises(DomainError) as exc:
        await build_today(
            db, user=user, local_date=date(2026, 7, 27), cc_day_override=1
        )
    assert exc.value.error_code == "cc_day_override_not_allowed"


@pytest.mark.asyncio
async def test_catalog_unknown_locale_falls_back_to_pl(db: AsyncSession) -> None:
    user, _raw = await _ready_user(db, "cat-fb@ex.com")
    payload, etag = await build_cc_catalog(
        db, requested_locale="de-DE", user_locale=user.locale
    )
    assert payload.requested_locale == "de-DE"
    assert payload.resolved_locale == "pl-PL"
    assert len(payload.exercises) == 6
    assert etag == catalog_etag(
        program_slug=payload.program_slug,
        resolved_locale="pl-PL",
        catalog_version=payload.catalog_version,
    )


@pytest.mark.asyncio
async def test_stream_export_includes_session_and_measurement(db: AsyncSession) -> None:
    user, _raw = await _ready_user(db, "exp-full@ex.com")
    db.add(
        WorkoutSession(
            id=new_uuid7(),
            user_id=user.id,
            performed_at=datetime.now(UTC),
            local_date=date(2026, 7, 27),
            client_mutation_id=new_uuid7(),
            revision=1,
            client_updated_at=datetime.now(UTC),
        )
    )
    await db.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(user.id)},
    )
    db.add(
        BodyMeasurement(
            id=new_uuid7(),
            user_id=user.id,
            measured_at=datetime.now(UTC),
            local_date=date(2026, 7, 27),
            metrics={"schema_version": 1, "weight_kg": 70},
            client_mutation_id=new_uuid7(),
            revision=1,
            client_updated_at=datetime.now(UTC),
        )
    )
    await db.commit()

    chunks: list[bytes] = []
    async for chunk in stream_account_export(db, user_id=user.id):
        chunks.append(chunk)
    text_out = b"".join(chunks).decode()
    assert "workout_sessions" in text_out
    assert "body_measurements" in text_out
    assert "done" in text_out


@pytest.mark.asyncio
async def test_soft_delete_account_hard_deletes_measurements(db: AsyncSession) -> None:
    user, _raw = await _ready_user(db, "del-acc@ex.com")
    await db.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(user.id)},
    )
    mid = new_uuid7()
    db.add(
        BodyMeasurement(
            id=mid,
            user_id=user.id,
            measured_at=datetime.now(UTC),
            local_date=date(2026, 7, 27),
            metrics={"schema_version": 1, "weight_kg": 71},
            client_mutation_id=new_uuid7(),
            revision=1,
            client_updated_at=datetime.now(UTC),
        )
    )
    await db.commit()

    result = await soft_delete_account(
        db, user=user, auth_sessions=AuthSessionService()
    )
    assert result["status"] == "pending_grace"
    await db.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(user.id)},
    )
    gone = await db.scalar(select(BodyMeasurement).where(BodyMeasurement.id == mid))
    assert gone is None
    await db.refresh(user)
    assert user.deleted_at is not None
    assert user.email is None


@pytest.mark.asyncio
async def test_session_soft_delete_and_progress_list(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    user, raw = await _ready_user(db, "sess-del@ex.com")
    session = WorkoutSession(
        id=new_uuid7(),
        user_id=user.id,
        performed_at=datetime(2026, 7, 27, 10, 0, tzinfo=UTC),
        local_date=date(2026, 7, 27),
        client_mutation_id=new_uuid7(),
        revision=1,
        client_updated_at=datetime.now(UTC),
    )
    db.add(session)
    await db.commit()

    deleted = await api_client.delete(
        f"/api/sessions/{session.id}",
        cookies={settings.session_cookie_name: raw},
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_at"] is not None

    progress = await api_client.get(
        "/api/progress",
        cookies={settings.session_cookie_name: raw},
    )
    assert progress.status_code == 200
    assert len(progress.json()["items"]) >= 6

    detail = await api_client.get(
        f"/api/sessions/{session.id}",
        cookies={settings.session_cookie_name: raw},
    )
    assert detail.status_code == 200
