"""Slice E: server dependency resolver + claim-after-deps (FR-072a/d)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.models.catalog import Exercise, Program
from app.models.sync import ClientMutation
from app.models.user import User
from app.schemas.sync import SyncPushItemResultV1, SyncPushItemV1, SyncPushRequestV1
from app.services.auth_session import AuthSessionService
from app.services.errors import DomainError
from app.services.legal import record_legal_acceptance
from app.services.onboarding import complete_onboarding
from app.services.sync_push import push_batch, resolve_item_dependencies
from tests.legal_fixtures import latest_health_disclaimer


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine(settings.resolved_database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _ready(db: AsyncSession, email: str, *, accept_legal: bool = True) -> User:
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
    if accept_legal:
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


async def _cc(db: AsyncSession) -> Exercise:
    row = await db.scalar(
        select(Exercise).where(Exercise.slug == "push_ups", Exercise.kind == "cc")
    )
    if row is None:
        pytest.skip("seed catalog required")
    return row


def test_resolve_item_dependencies_pure() -> None:
    mid = uuid4()
    dep = uuid4()
    item = SyncPushItemV1(
        client_mutation_id=mid,
        entity_type="workout_session",
        entity_id=uuid4(),
        depends_on=[dep],
    )
    assert (
        resolve_item_dependencies(
            item, fulfilled={dep}, batch_ids=set(), result_by_id={}
        )
        is None
    )

    missing = resolve_item_dependencies(
        item, fulfilled=set(), batch_ids=set(), result_by_id={}
    )
    assert isinstance(missing, SyncPushItemResultV1)
    assert missing.error_code == "dependency_missing"
    assert missing.dependency_failed_mutation_id == dep

    assert (
        resolve_item_dependencies(
            item, fulfilled=set(), batch_ids={dep}, result_by_id={}
        )
        == "defer"
    )

    failed = resolve_item_dependencies(
        item,
        fulfilled=set(),
        batch_ids={dep},
        result_by_id={
            dep: SyncPushItemResultV1(
                client_mutation_id=dep,
                status="rejected",
                error_code="schema_invalid",
            )
        },
    )
    assert isinstance(failed, SyncPushItemResultV1)
    assert failed.error_code == "dependency_failed"


@pytest.mark.asyncio
async def test_dependency_missing_rejects_without_claim(db: AsyncSession) -> None:
    user = await _ready(db, "dep-missing@ex.com")
    cc = await _cc(db)
    sess_mut = new_uuid7()
    missing = new_uuid7()
    out = await push_batch(
        db,
        user=user,
        body=SyncPushRequestV1(
            schema_version=1,
            items=[
                SyncPushItemV1(
                    client_mutation_id=sess_mut,
                    entity_type="workout_session",
                    entity_id=new_uuid7(),
                    depends_on=[missing],
                    payload={
                        "schema_version": 1,
                        "performed_at": datetime(2026, 8, 3, 10, 0, tzinfo=UTC).isoformat(),
                        "local_date": "2026-08-03",
                        "client_mutation_id": str(sess_mut),
                        "client_timezone": "Europe/Warsaw",
                        "logs": [
                            {
                                "exercise_id": str(cc.id),
                                "exercise_kind": "cc",
                                "sets": {
                                    "schema_version": 1,
                                    "sets": [{"reps": 10}],
                                },
                            }
                        ],
                    },
                )
            ],
        ),
    )
    assert len(out.results) == 1
    assert out.results[0].status == "rejected"
    assert out.results[0].error_code == "dependency_missing"
    assert out.results[0].dependency_failed_mutation_id == missing
    user_id = user.id
    await db.rollback()
    claimed = await db.scalar(
        select(ClientMutation).where(
            ClientMutation.user_id == user_id,
            ClientMutation.client_mutation_id == sess_mut,
        )
    )
    assert claimed is None


@pytest.mark.asyncio
async def test_dependency_failed_when_prereq_rejects(db: AsyncSession) -> None:
    user = await _ready(db, "dep-failed@ex.com")
    user_id = user.id
    cc = await _cc(db)
    bad_mut = new_uuid7()
    sess_mut = new_uuid7()
    # Satellite upsert with empty payload → rejected; session depends_on it.
    out = await push_batch(
        db,
        user=user,
        body=SyncPushRequestV1(
            schema_version=1,
            items=[
                SyncPushItemV1(
                    client_mutation_id=bad_mut,
                    entity_type="satellite",
                    entity_id=new_uuid7(),
                    payload=None,
                ),
                SyncPushItemV1(
                    client_mutation_id=sess_mut,
                    entity_type="workout_session",
                    entity_id=new_uuid7(),
                    depends_on=[bad_mut],
                    payload={
                        "schema_version": 1,
                        "performed_at": datetime(2026, 8, 3, 10, 0, tzinfo=UTC).isoformat(),
                        "local_date": "2026-08-03",
                        "client_mutation_id": str(sess_mut),
                        "client_timezone": "Europe/Warsaw",
                        "logs": [
                            {
                                "exercise_id": str(cc.id),
                                "exercise_kind": "cc",
                                "sets": {
                                    "schema_version": 1,
                                    "sets": [{"reps": 10}],
                                },
                            }
                        ],
                    },
                ),
            ],
        ),
    )
    by_mut = {r.client_mutation_id: r for r in out.results}
    assert by_mut[bad_mut].status == "rejected"
    assert by_mut[sess_mut].status == "rejected"
    assert by_mut[sess_mut].error_code == "dependency_failed"
    assert by_mut[sess_mut].dependency_failed_mutation_id == bad_mut
    await db.rollback()
    claimed = await db.scalar(
        select(ClientMutation).where(
            ClientMutation.user_id == user_id,
            ClientMutation.client_mutation_id == sess_mut,
        )
    )
    assert claimed is None


@pytest.mark.asyncio
async def test_dependency_cycle_rejects_without_claim(db: AsyncSession) -> None:
    user = await _ready(db, "dep-cycle@ex.com")
    a = new_uuid7()
    b = new_uuid7()
    out = await push_batch(
        db,
        user=user,
        body=SyncPushRequestV1(
            schema_version=1,
            items=[
                SyncPushItemV1(
                    client_mutation_id=a,
                    entity_type="body_measurement",
                    entity_id=new_uuid7(),
                    depends_on=[b],
                    payload={
                        "schema_version": 1,
                        "measured_at": datetime(2026, 8, 3, tzinfo=UTC).isoformat(),
                        "local_date": "2026-08-03",
                        "metrics": {"schema_version": 1, "weight_kg": "80.000"},
                        "client_mutation_id": str(a),
                    },
                ),
                SyncPushItemV1(
                    client_mutation_id=b,
                    entity_type="body_measurement",
                    entity_id=new_uuid7(),
                    depends_on=[a],
                    payload={
                        "schema_version": 1,
                        "measured_at": datetime(2026, 8, 3, tzinfo=UTC).isoformat(),
                        "local_date": "2026-08-03",
                        "metrics": {"schema_version": 1, "weight_kg": "81.000"},
                        "client_mutation_id": str(b),
                    },
                ),
            ],
        ),
    )
    assert {r.error_code for r in out.results} == {"dependency_cycle"}
    assert len(out.results) == 2
    for mid in (a, b):
        claimed = await db.scalar(
            select(ClientMutation).where(
                ClientMutation.user_id == user.id,
                ClientMutation.client_mutation_id == mid,
            )
        )
        assert claimed is None


@pytest.mark.asyncio
async def test_batch_duplicate_mutation_id_422(db: AsyncSession) -> None:
    user = await _ready(db, "dep-dup@ex.com")
    mid = new_uuid7()
    with pytest.raises(DomainError) as exc:
        await push_batch(
            db,
            user=user,
            body=SyncPushRequestV1(
                schema_version=1,
                items=[
                    SyncPushItemV1(
                        client_mutation_id=mid,
                        entity_type="body_measurement",
                        entity_id=new_uuid7(),
                        payload={
                            "schema_version": 1,
                            "measured_at": datetime(2026, 8, 3, tzinfo=UTC).isoformat(),
                            "local_date": "2026-08-03",
                            "metrics": {"schema_version": 1, "weight_kg": "80.000"},
                            "client_mutation_id": str(mid),
                        },
                    ),
                    SyncPushItemV1(
                        client_mutation_id=mid,
                        entity_type="body_measurement",
                        entity_id=new_uuid7(),
                        payload={
                            "schema_version": 1,
                            "measured_at": datetime(2026, 8, 3, tzinfo=UTC).isoformat(),
                            "local_date": "2026-08-03",
                            "metrics": {"schema_version": 1, "weight_kg": "81.000"},
                            "client_mutation_id": str(mid),
                        },
                    ),
                ],
            ),
        )
    assert exc.value.error_code == "batch_duplicate_mutation_id"


@pytest.mark.asyncio
async def test_depends_on_fulfilled_by_prior_client_mutation(db: AsyncSession) -> None:
    user = await _ready(db, "dep-prior@ex.com", accept_legal=False)
    cc = await _cc(db)
    doc, tr = await latest_health_disclaimer(db)
    legal_mut = new_uuid7()
    first = await push_batch(
        db,
        user=user,
        body=SyncPushRequestV1(
            schema_version=1,
            items=[
                SyncPushItemV1(
                    client_mutation_id=legal_mut,
                    entity_type="legal_acceptance",
                    entity_id=doc.id,
                    payload={
                        "schema_version": 1,
                        "client_mutation_id": str(legal_mut),
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
    assert first.results[0].status == "applied"

    sess_mut = new_uuid7()
    second = await push_batch(
        db,
        user=user,
        body=SyncPushRequestV1(
            schema_version=1,
            items=[
                SyncPushItemV1(
                    client_mutation_id=sess_mut,
                    entity_type="workout_session",
                    entity_id=new_uuid7(),
                    depends_on=[legal_mut],
                    payload={
                        "schema_version": 1,
                        "performed_at": datetime(2026, 8, 3, 10, 0, tzinfo=UTC).isoformat(),
                        "local_date": "2026-08-03",
                        "client_mutation_id": str(sess_mut),
                        "client_timezone": "Europe/Warsaw",
                        "logs": [
                            {
                                "exercise_id": str(cc.id),
                                "exercise_kind": "cc",
                                "sets": {
                                    "schema_version": 1,
                                    "sets": [{"reps": 10}],
                                },
                            }
                        ],
                    },
                )
            ],
        ),
    )
    assert second.results[0].status == "applied"
