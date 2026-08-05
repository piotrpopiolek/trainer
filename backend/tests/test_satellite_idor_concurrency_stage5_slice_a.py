"""Stage 5 Slice A — satellite IDOR gaps + concurrency races."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.db.session import dispose_engine
from app.main import app
from app.models.catalog import Program
from app.models.progression import ProgressionEvent, UserExerciseProgress
from app.models.satellite_progress import SatelliteDailyOutcome
from app.models.user import User
from app.models.workout import WorkoutSession
from app.schemas.api import SatelliteCreateV1, SessionCreateV1, SessionLogCreateV1
from app.schemas.sync import SyncPushItemV1, SyncPushRequestV1
from app.services.auth_session import AuthSessionService
from app.services.errors import DomainError
from app.services.legal import record_legal_acceptance
from app.services.onboarding import complete_onboarding
from app.services.rate_limit import reset_memory_rate_limits
from app.services.satellite_progression import SatelliteProgressionOrchestrator
from app.services.satellites import create_satellite
from app.services.sessions import create_session, soft_delete_user_session
from app.services.sync_push import push_batch
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


def _duration_rules(*, min_duration_sec: int) -> dict:
    return {
        "schema_version": 1,
        "goal": {
            "type": "duration",
            "sets": 3,
            "min_duration_sec": min_duration_sec,
            "min_weight_kg": None,
            "require_both_sides": True,
        },
    }


def _copenhagen_body(*, mutation_id, name: str = "Copenhagen Plank") -> SatelliteCreateV1:
    return SatelliteCreateV1.model_validate(
        {
            "schema_version": 1,
            "name": name,
            "exercise_type": "B",
            "active_metrics": {
                "schema_version": 1,
                "metrics": ["duration_sec", "sides"],
            },
            "schedule_kind": "category",
            "schedule_category": "post_workout",
            "equipment": ["bench"],
            "progression": {
                "mode": "steps",
                "regression": {
                    "mode": "suggest_after_failed_days",
                    "threshold": 2,
                },
            },
            "steps": [
                {
                    "step_number": 1,
                    "step_id": str(new_uuid7()),
                    "name": "Short lever hold",
                    "rules": _duration_rules(min_duration_sec=20),
                },
                {
                    "step_number": 2,
                    "step_id": str(new_uuid7()),
                    "name": "Long lever hold",
                    "rules": _duration_rules(min_duration_sec=20),
                },
                {
                    "step_number": 3,
                    "step_id": str(new_uuid7()),
                    "name": "Long lever lifted",
                    "rules": _duration_rules(min_duration_sec=15),
                },
            ],
            "client_mutation_id": str(mutation_id),
        }
    )


def _fail_sets() -> dict:
    return {
        "schema_version": 1,
        "sets": [
            {"duration_sec": 5, "sides": "left"},
            {"duration_sec": 5, "sides": "right"},
        ],
    }


def _success_sets() -> dict:
    return {
        "schema_version": 1,
        "sets": [
            {"duration_sec": 20, "sides": "left"},
            {"duration_sec": 20, "sides": "right"},
            {"duration_sec": 20, "sides": "left"},
            {"duration_sec": 20, "sides": "right"},
            {"duration_sec": 20, "sides": "left"},
            {"duration_sec": 20, "sides": "right"},
        ],
    }


async def _dual_factory():
    engine = create_async_engine(
        settings.resolved_database_url,
        pool_pre_ping=True,
        pool_size=4,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return engine, factory


# ── IDOR ─────────────────────────────────────────────────────────────────────


@pytest.mark.idor
@pytest.mark.asyncio
async def test_get_satellite_idor_404(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    owner = await _ready(db, "e5a-get-owner@ex.com")
    other = await _ready(db, "e5a-get-other@ex.com")
    sat = await create_satellite(
        db, user=owner, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    raw = await AuthSessionService().create_session(db, user=other, user_agent="t")
    api_client.cookies.set(settings.session_cookie_name, raw)
    res = await api_client.get(f"/api/satellites/{sat.id}")
    assert res.status_code == 404


@pytest.mark.idor
@pytest.mark.asyncio
async def test_sync_push_satellite_upsert_does_not_mutate_foreign(
    db: AsyncSession,
) -> None:
    from app.models.catalog import Exercise

    owner = await _ready(db, "e5a-sync-sat-owner@ex.com")
    other = await _ready(db, "e5a-sync-sat-other@ex.com")
    sat = await create_satellite(
        db, user=owner, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    owner_id = owner.id
    sat_id = sat.id
    owner_name = sat.name
    owner_rev = sat.revision
    payload = _copenhagen_body(mutation_id=new_uuid7(), name="Stolen").model_dump(
        mode="json"
    )
    payload["config_version_id"] = str(new_uuid7())
    out = await push_batch(
        db,
        user=other,
        body=SyncPushRequestV1(
            schema_version=1,
            device_id="dev-e5a-sat-idor",
            items=[
                SyncPushItemV1(
                    client_mutation_id=new_uuid7(),
                    entity_type="satellite",
                    entity_id=sat_id,
                    op="upsert",
                    revision=owner_rev + 1,
                    payload=payload,
                )
            ],
        ),
    )
    assert out.results[0].status == "rejected"
    assert out.results[0].error_code in ("revision_jump", "not_found", "schema_invalid")
    ex = await db.get(Exercise, sat_id)
    assert ex is not None
    assert ex.user_id == owner_id
    assert ex.name == owner_name
    assert ex.revision == owner_rev


@pytest.mark.idor
@pytest.mark.asyncio
async def test_session_create_foreign_satellite_exercise_idor(db: AsyncSession) -> None:
    owner = await _ready(db, "e5a-sess-owner@ex.com")
    other = await _ready(db, "e5a-sess-other@ex.com")
    sat = await create_satellite(
        db, user=owner, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    with pytest.raises(DomainError) as ei:
        await create_session(
            db,
            user=other,
            body=SessionCreateV1(
                schema_version=1,
                performed_at=datetime(2026, 8, 3, 10, 0, tzinfo=UTC),
                local_date=date(2026, 8, 3),
                client_mutation_id=new_uuid7(),
                client_timezone="Europe/Warsaw",
                logs=[
                    SessionLogCreateV1(
                        exercise_id=sat.id,
                        exercise_kind="satellite",
                        section="accessories",
                        sets=_fail_sets(),
                        satellite_config_version_id=sat.current_config_version_id,
                        satellite_config_hash=sat.config_hash,
                    )
                ],
            ),
            commit=False,
        )
    assert ei.value.error_code == "not_found"


@pytest.mark.idor
@pytest.mark.asyncio
async def test_session_create_foreign_config_version_idor(db: AsyncSession) -> None:
    owner = await _ready(db, "e5a-cfg-owner@ex.com")
    other = await _ready(db, "e5a-cfg-other@ex.com")
    sat_owner = await create_satellite(
        db, user=owner, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    sat_other = await create_satellite(
        db,
        user=other,
        body=_copenhagen_body(mutation_id=new_uuid7(), name="Other Sat"),
        commit=True,
    )
    with pytest.raises(DomainError) as ei:
        await create_session(
            db,
            user=other,
            body=SessionCreateV1(
                schema_version=1,
                performed_at=datetime(2026, 8, 3, 10, 0, tzinfo=UTC),
                local_date=date(2026, 8, 3),
                client_mutation_id=new_uuid7(),
                client_timezone="Europe/Warsaw",
                logs=[
                    SessionLogCreateV1(
                        exercise_id=sat_other.id,
                        exercise_kind="satellite",
                        section="accessories",
                        sets=_fail_sets(),
                        satellite_config_version_id=sat_owner.current_config_version_id,
                        satellite_config_hash=sat_owner.config_hash,
                    )
                ],
            ),
            commit=False,
        )
    assert ei.value.error_code in (
        "satellite_config_not_found",
        "satellite_config_mismatch",
        "not_found",
    )


@pytest.mark.idor
@pytest.mark.asyncio
async def test_recommendation_accept_mismatched_exercise_idor(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    user = await _ready(db, "e5a-rec-mismatch@ex.com")
    sat_a = await create_satellite(
        db,
        user=user,
        body=_copenhagen_body(mutation_id=new_uuid7(), name="A"),
        commit=True,
    )
    sat_b = await create_satellite(
        db,
        user=user,
        body=_copenhagen_body(mutation_id=new_uuid7(), name="B"),
        commit=True,
    )
    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == sat_a.id,
        )
    )
    assert progress is not None
    progress.current_step_number = 2
    progress.current_step_id = UUID(sat_a.steps[1]["step_id"])
    await db.commit()

    for d in (date(2026, 8, 3), date(2026, 8, 4)):
        await create_session(
            db,
            user=user,
            body=SessionCreateV1(
                schema_version=1,
                performed_at=datetime(d.year, d.month, d.day, 10, 0, tzinfo=UTC),
                local_date=d,
                client_mutation_id=new_uuid7(),
                client_timezone="Europe/Warsaw",
                logs=[
                    SessionLogCreateV1(
                        exercise_id=sat_a.id,
                        exercise_kind="satellite",
                        section="accessories",
                        sets=_fail_sets(),
                        satellite_config_version_id=sat_a.current_config_version_id,
                        satellite_config_hash=sat_a.config_hash,
                    )
                ],
            ),
            commit=True,
        )
        outcome = await db.scalar(
            select(SatelliteDailyOutcome).where(
                SatelliteDailyOutcome.user_id == user.id,
                SatelliteDailyOutcome.exercise_id == sat_a.id,
                SatelliteDailyOutcome.local_date == d,
            )
        )
        assert outcome is not None
        await db.execute(
            update(SatelliteDailyOutcome)
            .where(SatelliteDailyOutcome.id == outcome.id)
            .values(finalize_after=datetime(2026, 1, 1, tzinfo=UTC))
        )
        await db.commit()
        await SatelliteProgressionOrchestrator().finalize_due_outcomes(
            db, user_id=user.id, exercise_id=sat_a.id
        )
        await db.commit()

    from app.models.satellite_progress import SatelliteRegressionRecommendation

    rec = await db.scalar(
        select(SatelliteRegressionRecommendation).where(
            SatelliteRegressionRecommendation.user_id == user.id,
            SatelliteRegressionRecommendation.exercise_id == sat_a.id,
            SatelliteRegressionRecommendation.status == "pending",
        )
    )
    assert rec is not None

    raw = await AuthSessionService().create_session(db, user=user, user_agent="t")
    api_client.cookies.set(settings.session_cookie_name, raw)
    me = await api_client.get("/api/auth/me")
    csrf = me.json()["csrf_token"]
    res = await api_client.post(
        f"/api/satellites/{sat_b.id}/regression-recommendations/{rec.id}/accept",
        cookies={settings.csrf_cookie_name: csrf},
        headers={settings.csrf_header_name: csrf},
    )
    assert res.status_code == 404


# ── Concurrency ──────────────────────────────────────────────────────────────


@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_parallel_first_logs_single_daily_outcome(db: AsyncSession) -> None:
    user = await _ready(db, "e5a-par-first@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    user_id = user.id
    exercise_id = sat.id
    config_version_id = sat.current_config_version_id
    config_hash = sat.config_hash
    await db.commit()

    engine, factory = await _dual_factory()

    async def _log(hour: int) -> None:
        async with factory() as session:
            u = await session.get(User, user_id)
            assert u is not None
            await create_session(
                session,
                user=u,
                body=SessionCreateV1(
                    schema_version=1,
                    performed_at=datetime(2026, 8, 3, hour, 0, tzinfo=UTC),
                    local_date=date(2026, 8, 3),
                    client_mutation_id=new_uuid7(),
                    client_timezone="Europe/Warsaw",
                    logs=[
                        SessionLogCreateV1(
                            exercise_id=exercise_id,
                            exercise_kind="satellite",
                            section="accessories",
                            sets=_fail_sets(),
                            satellite_config_version_id=config_version_id,
                            satellite_config_hash=config_hash,
                        )
                    ],
                ),
                commit=True,
            )

    try:
        await asyncio.wait_for(asyncio.gather(_log(10), _log(11)), timeout=20)
    finally:
        await engine.dispose()

    db.expire_all()
    n = await db.scalar(
        select(func.count())
        .select_from(SatelliteDailyOutcome)
        .where(
            SatelliteDailyOutcome.user_id == user_id,
            SatelliteDailyOutcome.exercise_id == exercise_id,
            SatelliteDailyOutcome.local_date == date(2026, 8, 3),
        )
    )
    assert int(n or 0) == 1


@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_parallel_two_successes_one_advance_event(db: AsyncSession) -> None:
    user = await _ready(db, "e5a-par-success@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    user_id = user.id
    exercise_id = sat.id
    config_version_id = sat.current_config_version_id
    config_hash = sat.config_hash
    await db.commit()

    engine, factory = await _dual_factory()

    async def _ok(hour: int) -> None:
        async with factory() as session:
            u = await session.get(User, user_id)
            assert u is not None
            await create_session(
                session,
                user=u,
                body=SessionCreateV1(
                    schema_version=1,
                    performed_at=datetime(2026, 8, 3, hour, 0, tzinfo=UTC),
                    local_date=date(2026, 8, 3),
                    client_mutation_id=new_uuid7(),
                    client_timezone="Europe/Warsaw",
                    logs=[
                        SessionLogCreateV1(
                            exercise_id=exercise_id,
                            exercise_kind="satellite",
                            section="accessories",
                            sets=_success_sets(),
                            satellite_config_version_id=config_version_id,
                            satellite_config_hash=config_hash,
                        )
                    ],
                ),
                commit=True,
            )

    try:
        await asyncio.wait_for(asyncio.gather(_ok(10), _ok(11)), timeout=20)
    finally:
        await engine.dispose()

    db.expire_all()
    n_adv = await db.scalar(
        select(func.count())
        .select_from(ProgressionEvent)
        .where(
            ProgressionEvent.user_id == user_id,
            ProgressionEvent.exercise_id == exercise_id,
            ProgressionEvent.event_type == "satellite_advance",
        )
    )
    assert int(n_adv or 0) == 1
    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user_id,
            UserExerciseProgress.exercise_id == exercise_id,
        )
    )
    assert progress is not None
    assert progress.current_step_number == 2


@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_success_vs_finalizer_after_deadline(db: AsyncSession) -> None:
    user = await _ready(db, "e5a-fin-race@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == sat.id,
        )
    )
    assert progress is not None
    progress.current_step_number = 2
    progress.current_step_id = UUID(sat.steps[1]["step_id"])
    await db.commit()

    # Far-future local_date so create_session's lazy finalizer leaves it pending.
    day = date(2030, 1, 15)
    await create_session(
        db,
        user=user,
        body=SessionCreateV1(
            schema_version=1,
            performed_at=datetime(2030, 1, 15, 9, 0, tzinfo=UTC),
            local_date=day,
            client_mutation_id=new_uuid7(),
            client_timezone="Europe/Warsaw",
            logs=[
                SessionLogCreateV1(
                    exercise_id=sat.id,
                    exercise_kind="satellite",
                    section="accessories",
                    sets=_fail_sets(),
                    satellite_config_version_id=sat.current_config_version_id,
                    satellite_config_hash=sat.config_hash,
                )
            ],
        ),
        commit=True,
    )
    outcome = await db.scalar(
        select(SatelliteDailyOutcome).where(
            SatelliteDailyOutcome.user_id == user.id,
            SatelliteDailyOutcome.exercise_id == sat.id,
            SatelliteDailyOutcome.local_date == day,
        )
    )
    assert outcome is not None
    assert outcome.status == "pending"
    await db.execute(
        update(SatelliteDailyOutcome)
        .where(SatelliteDailyOutcome.id == outcome.id)
        .values(finalize_after=datetime(2026, 1, 1, tzinfo=UTC))
    )
    await db.commit()

    user_id = user.id
    exercise_id = sat.id
    config_version_id = sat.current_config_version_id
    config_hash = sat.config_hash
    engine, factory = await _dual_factory()

    async def _finalize() -> None:
        async with factory() as session:
            await SatelliteProgressionOrchestrator().finalize_due_outcomes(
                session, user_id=user_id, exercise_id=exercise_id
            )
            await session.commit()

    async def _success() -> None:
        async with factory() as session:
            u = await session.get(User, user_id)
            assert u is not None
            await create_session(
                session,
                user=u,
                body=SessionCreateV1(
                    schema_version=1,
                    performed_at=datetime(2030, 1, 15, 16, 0, tzinfo=UTC),
                    local_date=day,
                    client_mutation_id=new_uuid7(),
                    client_timezone="Europe/Warsaw",
                    logs=[
                        SessionLogCreateV1(
                            exercise_id=exercise_id,
                            exercise_kind="satellite",
                            section="accessories",
                            sets=_success_sets(),
                            satellite_config_version_id=config_version_id,
                            satellite_config_hash=config_hash,
                        )
                    ],
                ),
                commit=True,
            )

    try:
        await asyncio.wait_for(
            asyncio.gather(_finalize(), _success()), timeout=20
        )
    finally:
        await engine.dispose()

    db.expire_all()
    final = await db.scalar(
        select(SatelliteDailyOutcome).where(
            SatelliteDailyOutcome.user_id == user_id,
            SatelliteDailyOutcome.exercise_id == exercise_id,
            SatelliteDailyOutcome.local_date == day,
        )
    )
    assert final is not None
    assert final.status == "finalized"
    assert final.result in ("success", "failure")
    progress_after = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user_id,
            UserExerciseProgress.exercise_id == exercise_id,
        )
    )
    assert progress_after is not None
    if final.result == "success":
        assert progress_after.current_step_number == 3
    else:
        assert progress_after.current_step_number == 2


@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_session_soft_delete_vs_finalizer_race(db: AsyncSession) -> None:
    user = await _ready(db, "e5a-del-fin@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    progress = await db.scalar(
        select(UserExerciseProgress).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == sat.id,
        )
    )
    assert progress is not None
    progress.current_step_number = 2
    progress.current_step_id = UUID(sat.steps[1]["step_id"])
    await db.commit()

    day = date(2030, 2, 15)
    session_read = await create_session(
        db,
        user=user,
        body=SessionCreateV1(
            schema_version=1,
            performed_at=datetime(2030, 2, 15, 10, 0, tzinfo=UTC),
            local_date=day,
            client_mutation_id=new_uuid7(),
            client_timezone="Europe/Warsaw",
            logs=[
                SessionLogCreateV1(
                    exercise_id=sat.id,
                    exercise_kind="satellite",
                    section="accessories",
                    sets=_fail_sets(),
                    satellite_config_version_id=sat.current_config_version_id,
                    satellite_config_hash=sat.config_hash,
                )
            ],
        ),
        commit=True,
    )
    outcome = await db.scalar(
        select(SatelliteDailyOutcome).where(
            SatelliteDailyOutcome.user_id == user.id,
            SatelliteDailyOutcome.exercise_id == sat.id,
            SatelliteDailyOutcome.local_date == day,
        )
    )
    assert outcome is not None
    assert outcome.status == "pending"
    await db.execute(
        update(SatelliteDailyOutcome)
        .where(SatelliteDailyOutcome.id == outcome.id)
        .values(finalize_after=datetime(2026, 1, 1, tzinfo=UTC))
    )
    await db.commit()

    user_id = user.id
    exercise_id = sat.id
    session_id = session_read.id
    outcome_id = outcome.id
    engine, factory = await _dual_factory()

    async def _finalize() -> None:
        async with factory() as session:
            await SatelliteProgressionOrchestrator().finalize_due_outcomes(
                session, user_id=user_id, exercise_id=exercise_id
            )
            await session.commit()

    async def _delete() -> None:
        async with factory() as session:
            await soft_delete_user_session(
                session, user_id=user_id, session_id=session_id, commit=True
            )

    try:
        await asyncio.wait_for(asyncio.gather(_finalize(), _delete()), timeout=20)
    finally:
        await engine.dispose()

    db.expire_all()
    final = await db.get(SatelliteDailyOutcome, outcome_id)
    assert final is not None
    assert final.status in ("finalized", "cancelled")
    ws = await db.get(WorkoutSession, session_id)
    assert ws is not None
    assert ws.deleted_at is not None


@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_mixed_session_multiple_satellites_no_deadlock(db: AsyncSession) -> None:
    user = await _ready(db, "e5a-multi-sat@ex.com")
    sat_a = await create_satellite(
        db,
        user=user,
        body=_copenhagen_body(mutation_id=new_uuid7(), name="A"),
        commit=True,
    )
    sat_b = await create_satellite(
        db,
        user=user,
        body=_copenhagen_body(mutation_id=new_uuid7(), name="B"),
        commit=True,
    )
    user_id = user.id
    a_id, a_cfg, a_hash = sat_a.id, sat_a.current_config_version_id, sat_a.config_hash
    b_id, b_cfg, b_hash = sat_b.id, sat_b.current_config_version_id, sat_b.config_hash
    await db.commit()

    engine, factory = await _dual_factory()

    async def _mixed() -> None:
        async with factory() as session:
            u = await session.get(User, user_id)
            assert u is not None
            await create_session(
                session,
                user=u,
                body=SessionCreateV1(
                    schema_version=1,
                    performed_at=datetime(2026, 8, 3, 10, 0, tzinfo=UTC),
                    local_date=date(2026, 8, 3),
                    client_mutation_id=new_uuid7(),
                    client_timezone="Europe/Warsaw",
                    logs=[
                        SessionLogCreateV1(
                            exercise_id=a_id,
                            exercise_kind="satellite",
                            section="accessories",
                            sets=_fail_sets(),
                            satellite_config_version_id=a_cfg,
                            satellite_config_hash=a_hash,
                        ),
                        SessionLogCreateV1(
                            exercise_id=b_id,
                            exercise_kind="satellite",
                            section="accessories",
                            sets=_success_sets(),
                            satellite_config_version_id=b_cfg,
                            satellite_config_hash=b_hash,
                        ),
                    ],
                ),
                commit=True,
            )

    try:
        await asyncio.wait_for(
            asyncio.gather(_mixed(), _mixed()), timeout=20
        )
    finally:
        await engine.dispose()

    db.expire_all()
    for ex_id in (a_id, b_id):
        n = await db.scalar(
            select(func.count())
            .select_from(SatelliteDailyOutcome)
            .where(
                SatelliteDailyOutcome.user_id == user_id,
                SatelliteDailyOutcome.exercise_id == ex_id,
                SatelliteDailyOutcome.local_date == date(2026, 8, 3),
            )
        )
        assert int(n or 0) == 1


@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_expected_conflict_does_not_poison_async_session(
    db: AsyncSession,
) -> None:
    user = await _ready(db, "e5a-poison@ex.com")
    sat = await create_satellite(
        db, user=user, body=_copenhagen_body(mutation_id=new_uuid7()), commit=True
    )
    user_id = user.id
    sat_id = sat.id
    config_version_id = sat.current_config_version_id
    config_hash = sat.config_hash
    # First session ok.
    await create_session(
        db,
        user=user,
        body=SessionCreateV1(
            schema_version=1,
            performed_at=datetime(2030, 3, 3, 10, 0, tzinfo=UTC),
            local_date=date(2030, 3, 3),
            client_mutation_id=new_uuid7(),
            client_timezone="Europe/Warsaw",
            logs=[
                SessionLogCreateV1(
                    exercise_id=sat_id,
                    exercise_kind="satellite",
                    section="accessories",
                    sets=_fail_sets(),
                    satellite_config_version_id=config_version_id,
                    satellite_config_hash=config_hash,
                )
            ],
        ),
        commit=True,
    )
    # Expected domain conflict: foreign config on same session path.
    other = await _ready(db, "e5a-poison-other@ex.com")
    other_sat = await create_satellite(
        db,
        user=other,
        body=_copenhagen_body(mutation_id=new_uuid7(), name="Other"),
        commit=True,
    )
    other_cfg = other_sat.current_config_version_id
    other_hash = other_sat.config_hash
    with pytest.raises(DomainError):
        await create_session(
            db,
            user=user,
            body=SessionCreateV1(
                schema_version=1,
                performed_at=datetime(2030, 3, 4, 10, 0, tzinfo=UTC),
                local_date=date(2030, 3, 4),
                client_mutation_id=new_uuid7(),
                client_timezone="Europe/Warsaw",
                logs=[
                    SessionLogCreateV1(
                        exercise_id=sat_id,
                        exercise_kind="satellite",
                        section="accessories",
                        sets=_fail_sets(),
                        satellite_config_version_id=other_cfg,
                        satellite_config_hash=other_hash,
                    )
                ],
            ),
            commit=False,
        )
    await db.rollback()

    user = await db.get(User, user_id)
    assert user is not None
    # Same AsyncSession must still accept a valid write.
    again = await create_session(
        db,
        user=user,
        body=SessionCreateV1(
            schema_version=1,
            performed_at=datetime(2030, 3, 4, 11, 0, tzinfo=UTC),
            local_date=date(2030, 3, 4),
            client_mutation_id=new_uuid7(),
            client_timezone="Europe/Warsaw",
            logs=[
                SessionLogCreateV1(
                    exercise_id=sat_id,
                    exercise_kind="satellite",
                    section="accessories",
                    sets=_success_sets(),
                    satellite_config_version_id=config_version_id,
                    satellite_config_hash=config_hash,
                )
            ],
        ),
        commit=True,
    )
    assert again.id is not None
    outcome = await db.scalar(
        select(SatelliteDailyOutcome).where(
            SatelliteDailyOutcome.user_id == user_id,
            SatelliteDailyOutcome.exercise_id == sat_id,
            SatelliteDailyOutcome.local_date == date(2030, 3, 4),
        )
    )
    assert outcome is not None
    assert outcome.status == "finalized"
    assert outcome.result == "success"
