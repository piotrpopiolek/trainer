"""Direct service-level sync coverage (complements HTTP suite)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.models.body_measurement import BodyMeasurement
from app.models.catalog import Exercise, Program
from app.models.user import User
from app.models.workout import WorkoutSession
from app.schemas.sync import SyncPushItemV1, SyncPushRequestV1
from app.services.auth_session import AuthSessionService
from app.services.errors import DomainError
from app.services.legal import record_legal_acceptance
from app.services.onboarding import complete_onboarding
from app.services.sync_pull import pull
from app.services.sync_push import push_batch
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
    await AuthSessionService().create_session(db, user=user, user_agent="t")
    return user


@pytest.mark.asyncio
async def test_push_batch_session_measurement_satellite(db: AsyncSession) -> None:
    user = await _ready(db, "sync-direct@ex.com")
    push_ex = await db.scalar(select(Exercise).where(Exercise.slug == "push_ups"))
    assert push_ex is not None
    mut_s = new_uuid7()
    sid = new_uuid7()
    mut_m = new_uuid7()
    mid = new_uuid7()
    mut_sat = new_uuid7()
    sat_id = new_uuid7()
    measured = datetime.now(UTC)
    body = SyncPushRequestV1(
        schema_version=1,
        device_id="direct",
        items=[
            SyncPushItemV1(
                client_mutation_id=mut_s,
                entity_type="workout_session",
                entity_id=sid,
                op="upsert",
                revision=1,
                payload={
                    "schema_version": 1,
                    "performed_at": datetime(2026, 7, 27, 10, 0, tzinfo=UTC).isoformat(),
                    "local_date": "2026-07-27",
                    "client_mutation_id": str(mut_s),
                    "logs": [
                        {
                            "exercise_id": str(push_ex.id),
                            "exercise_kind": "cc",
                            "section": "main",
                            "sets": {
                                "schema_version": 1,
                                "sets": [{"reps": 50}, {"reps": 50}, {"reps": 50}],
                            },
                        }
                    ],
                },
            ),
            SyncPushItemV1(
                client_mutation_id=mut_m,
                entity_type="body_measurement",
                entity_id=mid,
                op="upsert",
                revision=1,
                payload={
                    "schema_version": 1,
                    "measured_at": measured.isoformat(),
                    "local_date": measured.date().isoformat(),
                    "metrics": {"schema_version": 1, "weight_kg": 81},
                    "client_mutation_id": str(mut_m),
                },
            ),
            SyncPushItemV1(
                client_mutation_id=mut_sat,
                entity_type="satellite",
                entity_id=sat_id,
                op="upsert",
                revision=1,
                payload={
                    "schema_version": 1,
                    "name": "Sync sat",
                    "exercise_type": "B",
                    "active_metrics": {"schema_version": 1, "metrics": ["reps"]},
                    "schedule_kind": "daily",
                    "steps": [
                        {
                            "step_number": 1,
                            "name": "Goal",
                            "rules": {
                                "schema_version": 1,
                                "goal": {"type": "reps", "sets": 3, "min_reps": 10},
                            },
                        }
                    ],
                    "client_mutation_id": str(mut_sat),
                },
            ),
        ],
    )
    out = await push_batch(db, user=user, body=body)
    assert [r.status for r in out.results] == ["applied", "applied", "applied"]

    # idempotent session claim
    again = await push_batch(
        db,
        user=user,
        body=SyncPushRequestV1(schema_version=1, items=[body.items[0]]),
    )
    assert again.results[0].status == "idempotent"

    # delete measurement + soft-delete session
    del_m = new_uuid7()
    del_s = new_uuid7()
    deleted = await push_batch(
        db,
        user=user,
        body=SyncPushRequestV1(
            schema_version=1,
            items=[
                SyncPushItemV1(
                    client_mutation_id=del_m,
                    entity_type="body_measurement",
                    entity_id=mid,
                    op="delete",
                    revision=2,
                ),
                SyncPushItemV1(
                    client_mutation_id=del_s,
                    entity_type="workout_session",
                    entity_id=sid,
                    op="delete",
                    revision=2,
                ),
            ],
        ),
    )
    assert all(r.status == "applied" for r in deleted.results)

    since = datetime.now(UTC) - timedelta(minutes=5)
    pulled = await pull(
        db, user=user, since=since, locale="pl-PL", device_id="direct"
    )
    assert pulled.resync_required is False
    assert any(
        t.entity_type == "body_measurement" and t.id == mid for t in pulled.tombstones
    )
    assert any(
        t.entity_type == "workout_session" and t.id == sid for t in pulled.tombstones
    )
    assert any(s.get("id") == str(sat_id) for s in pulled.satellites)


@pytest.mark.asyncio
async def test_push_batch_too_large_direct(db: AsyncSession) -> None:
    user = await _ready(db, "sync-direct-big@ex.com")
    items = [
        SyncPushItemV1(
            client_mutation_id=new_uuid7(),
            entity_type="body_measurement",
            entity_id=new_uuid7(),
            op="upsert",
            revision=1,
            payload={
                "schema_version": 1,
                "measured_at": datetime.now(UTC).isoformat(),
                "local_date": date.today().isoformat(),
                "metrics": {"schema_version": 1, "weight_kg": 70},
                "client_mutation_id": str(uuid4()),
            },
        )
        for _ in range(21)
    ]
    with pytest.raises(DomainError) as exc:
        await push_batch(
            db, user=user, body=SyncPushRequestV1(schema_version=1, items=items)
        )
    assert exc.value.error_code == "batch_too_large"


@pytest.mark.asyncio
async def test_push_session_conflict_lost(db: AsyncSession) -> None:
    user = await _ready(db, "sync-conflict@ex.com")
    sid = new_uuid7()
    now = datetime.now(UTC)
    db.add(
        WorkoutSession(
            id=sid,
            user_id=user.id,
            performed_at=now,
            local_date=date(2026, 7, 27),
            client_mutation_id=new_uuid7(),
            revision=3,
            client_updated_at=now,
        )
    )
    await db.commit()
    out = await push_batch(
        db,
        user=user,
        body=SyncPushRequestV1(
            schema_version=1,
            items=[
                SyncPushItemV1(
                    client_mutation_id=new_uuid7(),
                    entity_type="workout_session",
                    entity_id=sid,
                    op="upsert",
                    revision=1,
                    payload={
                        "schema_version": 1,
                        "performed_at": now.isoformat(),
                        "local_date": "2026-07-27",
                        "client_mutation_id": str(uuid4()),
                        "logs": [],
                    },
                )
            ],
        ),
    )
    assert out.results[0].status == "conflict_lost"


@pytest.mark.asyncio
async def test_push_legal_acceptance(db: AsyncSession) -> None:
    user = await _ready(db, "sync-legal@ex.com")
    doc, tr = await latest_health_disclaimer(db)
    mut = new_uuid7()
    out = await push_batch(
        db,
        user=user,
        body=SyncPushRequestV1(
            schema_version=1,
            items=[
                SyncPushItemV1(
                    client_mutation_id=mut,
                    entity_type="legal_acceptance",
                    entity_id=doc.id,
                    op="upsert",
                    revision=1,
                    payload={
                        "schema_version": 1,
                        "client_mutation_id": str(mut),
                        "document_slug": "health_disclaimer",
                        "document_version": doc.version,
                        "accepted_locale": "pl-PL",
                        "accepted_content_hash": tr.content_hash.hex(),
                        "accepted_at": datetime.now(UTC).isoformat(),
                    },
                )
            ],
        ),
    )
    assert out.results[0].status == "applied"


@pytest.mark.asyncio
async def test_pull_initial_windows(db: AsyncSession) -> None:
    user = await _ready(db, "sync-pull-init@ex.com")
    now = datetime.now(UTC)
    mid = new_uuid7()
    from sqlalchemy import text

    await db.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(user.id)},
    )
    db.add(
        BodyMeasurement(
            id=mid,
            user_id=user.id,
            measured_at=now,
            local_date=now.date(),
            metrics={"schema_version": 1, "weight_kg": 70},
            client_mutation_id=new_uuid7(),
            revision=1,
            client_updated_at=now,
        )
    )
    await db.commit()
    pulled = await pull(db, user=user, since=None, locale=None, device_id=None)
    assert any(m["id"] == str(mid) for m in pulled.measurements)
    assert pulled.catalog_version is not None
