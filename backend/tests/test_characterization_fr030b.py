"""FR-030b characterization gate — locks *current* production behavior before engine split.

Do not rewrite these expectations to match the future satellite engine. Stage 1+ may
add parallel suites with new contracts; CC tip/late and mixed-session rollback must stay.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.models.catalog import Exercise, Program
from app.models.progression import ProgressionEvent, UserExerciseProgress
from app.models.user import User
from app.models.workout import SessionExerciseLog, WorkoutSession
from app.schemas.api import SatelliteCreateV1, SessionCreateV1, SessionLogCreateV1
from app.schemas.rules import ProgressionRulesV1
from app.schemas.sync import SyncPushItemV1, SyncPushRequestV1
from app.services.auth_session import AuthSessionService
from app.services.errors import DomainError
from app.services.legal import record_legal_acceptance
from app.services.onboarding import complete_onboarding
from app.services.progression import ProgressionEngine, goal_met_from_sets
from app.services.satellites import create_satellite
from app.services.sessions import create_session
from app.services.sync_push import push_batch, sort_push_items
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
        doc, tr = await latest_health_disclaimer(db)
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


async def _cc_push(db: AsyncSession) -> Exercise:
    ex = await db.scalar(select(Exercise).where(Exercise.slug == "push_ups", Exercise.kind == "cc"))
    if ex is None:
        pytest.skip("seed catalog required")
    return ex


async def _make_goal_satellite(
    db: AsyncSession,
    user: User,
    *,
    name: str,
    goal: dict,
    metrics: list[str] | None = None,
    exercise_type: str = "B",
) -> Exercise:
    body = SatelliteCreateV1.model_validate(
        {
            "schema_version": 1,
            "name": name,
            "exercise_type": exercise_type,
            "active_metrics": {
                "schema_version": 1,
                "metrics": metrics or (["reps"] if exercise_type == "B" else []),
            },
            "schedule_kind": "daily",
            "steps": [
                {
                    "step_number": 1,
                    "name": "Goal",
                    "rules": {"schema_version": 1, "goal": goal},
                }
            ],
            "client_mutation_id": str(new_uuid7()),
        }
    )
    read = await create_satellite(db, user=user, body=body, commit=True)
    ex = await db.get(Exercise, read.id)
    assert ex is not None
    return ex


def _session_body(
    *,
    mutation_id,
    local_date: date,
    performed_at: datetime,
    logs: list[SessionLogCreateV1],
) -> SessionCreateV1:
    return SessionCreateV1(
        schema_version=1,
        performed_at=performed_at,
        local_date=local_date,
        client_mutation_id=mutation_id,
        client_timezone="Europe/Warsaw",
        logs=logs,
    )


# ---------------------------------------------------------------------------
# A. Legacy goal_met_from_sets (document behaviors Stage 1 will replace)
# ---------------------------------------------------------------------------


def test_legacy_goal_reps_duration_completed_semantics() -> None:
    """Legacy: completed ≡ len(sets)>=1; reps/duration use or-0 fallbacks."""
    reps = ProgressionRulesV1.model_validate(
        {"schema_version": 1, "goal": {"type": "reps", "sets": 3, "min_reps": 10}}
    )
    assert goal_met_from_sets(
        reps, {"schema_version": 1, "sets": [{"reps": 10}, {"reps": 10}, {"reps": 10}]}
    )
    assert not goal_met_from_sets(
        reps, {"schema_version": 1, "sets": [{"reps": 10}, {"reps": 10}, {"reps": 9}]}
    )

    duration = ProgressionRulesV1.model_validate(
        {
            "schema_version": 1,
            "goal": {"type": "duration", "sets": 2, "min_duration_sec": 20},
        }
    )
    assert goal_met_from_sets(
        duration,
        {"schema_version": 1, "sets": [{"duration_sec": 20}, {"duration_sec": 25}]},
    )
    assert not goal_met_from_sets(
        duration,
        {"schema_version": 1, "sets": [{"duration_sec": 20}, {"duration_sec": 19}]},
    )

    completed = ProgressionRulesV1.model_validate(
        {"schema_version": 1, "goal": {"type": "completed"}}
    )
    assert not goal_met_from_sets(completed, {"schema_version": 1, "sets": []})
    assert goal_met_from_sets(completed, {"schema_version": 1, "sets": [{"reps": None}]})
    # Legacy accepts a structurally empty object inside sets[] as "completed".
    assert goal_met_from_sets(completed, {"schema_version": 1, "sets": [{}]})


# ---------------------------------------------------------------------------
# B. Goal-only satellite evaluate path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_goal_only_satellite_sets_goal_met_without_progress_events(
    db: AsyncSession,
) -> None:
    user = await _ready(db, "char-sat-goal@ex.com")
    sat = await _make_goal_satellite(
        db,
        user,
        name="Hip Thrust legacy",
        goal={"type": "reps", "sets": 3, "min_reps": 10},
    )
    before = await db.scalar(
        select(UserExerciseProgress.current_step_number).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == sat.id,
        )
    )
    mut = new_uuid7()
    read = await create_session(
        db,
        user=user,
        body=_session_body(
            mutation_id=mut,
            local_date=date(2026, 7, 27),
            performed_at=datetime(2026, 7, 27, 10, 0, tzinfo=UTC),
            logs=[
                SessionLogCreateV1(
                    exercise_id=sat.id,
                    exercise_kind="satellite",
                    section="accessories",
                    sets={
                        "schema_version": 1,
                        "sets": [{"reps": 10}, {"reps": 10}, {"reps": 10}],
                    },
                )
            ],
        ),
        commit=True,
    )
    assert len(read.logs) == 1
    log = read.logs[0]
    assert log.goal_met is True
    assert log.counts_for_progression is False
    assert log.goal_evaluated_at is not None
    persisted = await db.get(SessionExerciseLog, log.id)
    assert persisted is not None
    assert persisted.rules_snapshot is not None
    assert persisted.rules_snapshot.get("goal") is not None
    assert persisted.rules_snapshot.get("advance") is None

    after = await db.scalar(
        select(UserExerciseProgress.current_step_number).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == sat.id,
        )
    )
    assert after == before == 1
    events = await db.scalar(
        select(func.count())
        .select_from(ProgressionEvent)
        .where(
            ProgressionEvent.user_id == user.id,
            ProgressionEvent.exercise_id == sat.id,
        )
    )
    assert int(events or 0) == 0


@pytest.mark.asyncio
async def test_goal_only_satellite_fail_and_completed_type(db: AsyncSession) -> None:
    user = await _ready(db, "char-sat-fail@ex.com")
    reps_sat = await _make_goal_satellite(
        db,
        user,
        name="Reps fail",
        goal={"type": "reps", "sets": 3, "min_reps": 10},
    )
    type_c = await _make_goal_satellite(
        db,
        user,
        name="Mobility C",
        goal={"type": "completed"},
        metrics=[],
        exercise_type="C",
    )

    fail_read = await create_session(
        db,
        user=user,
        body=_session_body(
            mutation_id=new_uuid7(),
            local_date=date(2026, 7, 27),
            performed_at=datetime(2026, 7, 27, 9, 0, tzinfo=UTC),
            logs=[
                SessionLogCreateV1(
                    exercise_id=reps_sat.id,
                    exercise_kind="satellite",
                    sets={
                        "schema_version": 1,
                        "sets": [{"reps": 10}, {"reps": 10}, {"reps": 5}],
                    },
                )
            ],
        ),
        commit=True,
    )
    assert fail_read.logs[0].goal_met is False
    assert fail_read.logs[0].counts_for_progression is False

    ok_c = await create_session(
        db,
        user=user,
        body=_session_body(
            mutation_id=new_uuid7(),
            local_date=date(2026, 7, 28),
            performed_at=datetime(2026, 7, 28, 9, 0, tzinfo=UTC),
            logs=[
                SessionLogCreateV1(
                    exercise_id=type_c.id,
                    exercise_kind="satellite",
                    # Legacy completed: any non-empty sets list.
                    sets={"schema_version": 1, "sets": [{}]},
                )
            ],
        ),
        commit=True,
    )
    assert ok_c.logs[0].goal_met is True
    assert ok_c.logs[0].counts_for_progression is False


@pytest.mark.asyncio
async def test_goal_only_evaluate_log_idempotent(db: AsyncSession) -> None:
    user = await _ready(db, "char-sat-idem@ex.com")
    sat = await _make_goal_satellite(
        db,
        user,
        name="Idem sat",
        goal={"type": "reps", "sets": 1, "min_reps": 5},
    )
    read = await create_session(
        db,
        user=user,
        body=_session_body(
            mutation_id=new_uuid7(),
            local_date=date(2026, 7, 27),
            performed_at=datetime(2026, 7, 27, 10, 0, tzinfo=UTC),
            logs=[
                SessionLogCreateV1(
                    exercise_id=sat.id,
                    exercise_kind="satellite",
                    sets={"schema_version": 1, "sets": [{"reps": 8}]},
                )
            ],
        ),
        commit=True,
    )
    log = await db.get(SessionExerciseLog, read.logs[0].id)
    session = await db.get(WorkoutSession, read.id)
    assert log is not None and session is not None
    first_evaluated = log.goal_evaluated_at
    engine = ProgressionEngine()
    again = await engine.evaluate_log(db, log, session=session)
    await db.commit()
    assert again.goal_met is True
    assert again.progression_skipped is None
    assert log.goal_evaluated_at == first_evaluated
    assert int(
        await db.scalar(
            select(func.count())
            .select_from(ProgressionEvent)
            .where(ProgressionEvent.exercise_id == sat.id)
        )
        or 0
    ) == 0


# ---------------------------------------------------------------------------
# C. Mixed session atomicity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mixed_cc_satellite_session_happy_path(db: AsyncSession) -> None:
    user = await _ready(db, "char-mixed-ok@ex.com")
    cc = await _cc_push(db)
    sat = await _make_goal_satellite(
        db,
        user,
        name="Mixed sat",
        goal={"type": "reps", "sets": 3, "min_reps": 10},
    )
    read = await create_session(
        db,
        user=user,
        body=_session_body(
            mutation_id=new_uuid7(),
            local_date=date(2026, 7, 27),
            performed_at=datetime(2026, 7, 27, 10, 0, tzinfo=UTC),
            logs=[
                SessionLogCreateV1(
                    exercise_id=cc.id,
                    exercise_kind="cc",
                    sets={
                        "schema_version": 1,
                        "sets": [{"reps": 50}, {"reps": 50}, {"reps": 50}],
                    },
                ),
                SessionLogCreateV1(
                    exercise_id=sat.id,
                    exercise_kind="satellite",
                    section="accessories",
                    sets={
                        "schema_version": 1,
                        "sets": [{"reps": 10}, {"reps": 10}, {"reps": 10}],
                    },
                ),
            ],
        ),
        commit=True,
    )
    by_kind = {log.exercise_kind: log for log in read.logs}
    assert by_kind["cc"].goal_met is True
    assert by_kind["cc"].counts_for_progression is True
    assert by_kind["satellite"].goal_met is True
    assert by_kind["satellite"].counts_for_progression is False


@pytest.mark.asyncio
async def test_mixed_session_rolls_back_when_satellite_log_invalid(
    db: AsyncSession,
) -> None:
    user = await _ready(db, "char-mixed-rb@ex.com")
    other = await _ready(db, "char-mixed-other@ex.com")
    cc = await _cc_push(db)
    foreign = await _make_goal_satellite(
        db,
        other,
        name="Foreign",
        goal={"type": "reps", "sets": 1, "min_reps": 1},
    )
    user_id = user.id
    cc_id = cc.id

    with pytest.raises(DomainError) as exc:
        await create_session(
            db,
            user=user,
            body=_session_body(
                mutation_id=new_uuid7(),
                local_date=date(2026, 7, 27),
                performed_at=datetime(2026, 7, 27, 10, 0, tzinfo=UTC),
                logs=[
                    SessionLogCreateV1(
                        exercise_id=cc.id,
                        exercise_kind="cc",
                        sets={
                            "schema_version": 1,
                            "sets": [{"reps": 50}, {"reps": 50}, {"reps": 50}],
                        },
                    ),
                    SessionLogCreateV1(
                        exercise_id=foreign.id,
                        exercise_kind="satellite",
                        sets={"schema_version": 1, "sets": [{"reps": 10}]},
                    ),
                ],
            ),
            commit=True,
        )
    assert exc.value.error_code == "not_found"
    await db.rollback()

    sessions = await db.scalar(
        select(func.count())
        .select_from(WorkoutSession)
        .where(WorkoutSession.user_id == user_id)
    )
    assert int(sessions or 0) == 0
    cc_events = await db.scalar(
        select(func.count())
        .select_from(ProgressionEvent)
        .where(
            ProgressionEvent.user_id == user_id,
            ProgressionEvent.exercise_id == cc_id,
        )
    )
    assert int(cc_events or 0) == 0
    cc_progress = await db.scalar(
        select(UserExerciseProgress.current_step_number).where(
            UserExerciseProgress.user_id == user_id,
            UserExerciseProgress.exercise_id == cc_id,
        )
    )
    assert cc_progress in (None, 1)


# ---------------------------------------------------------------------------
# D. Online ≡ sync for the same payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_online_and_sync_same_payload_cc_and_goal_satellite(
    db: AsyncSession,
) -> None:
    user_online = await _ready(db, "char-parity-on@ex.com")
    user_sync = await _ready(db, "char-parity-sy@ex.com")
    cc = await _cc_push(db)
    sat_on = await _make_goal_satellite(
        db,
        user_online,
        name="Parity sat on",
        goal={"type": "reps", "sets": 3, "min_reps": 10},
    )
    sat_sy = await _make_goal_satellite(
        db,
        user_sync,
        name="Parity sat sy",
        goal={"type": "reps", "sets": 3, "min_reps": 10},
    )
    local_date = date(2026, 7, 27)
    performed = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    sets_cc = {"schema_version": 1, "sets": [{"reps": 50}, {"reps": 50}, {"reps": 50}]}
    sets_sat = {"schema_version": 1, "sets": [{"reps": 10}, {"reps": 10}, {"reps": 10}]}

    online = await create_session(
        db,
        user=user_online,
        body=_session_body(
            mutation_id=new_uuid7(),
            local_date=local_date,
            performed_at=performed,
            logs=[
                SessionLogCreateV1(
                    exercise_id=cc.id, exercise_kind="cc", sets=sets_cc
                ),
                SessionLogCreateV1(
                    exercise_id=sat_on.id,
                    exercise_kind="satellite",
                    section="accessories",
                    sets=sets_sat,
                ),
            ],
        ),
        commit=True,
    )

    mut = new_uuid7()
    sid = new_uuid7()
    sync_out = await push_batch(
        db,
        user=user_sync,
        body=SyncPushRequestV1(
            schema_version=1,
            device_id="char",
            items=[
                SyncPushItemV1(
                    client_mutation_id=mut,
                    entity_type="workout_session",
                    entity_id=sid,
                    op="upsert",
                    revision=1,
                    payload={
                        "schema_version": 1,
                        "performed_at": performed.isoformat(),
                        "local_date": local_date.isoformat(),
                        "client_mutation_id": str(mut),
                        "client_timezone": "Europe/Warsaw",
                        "logs": [
                            {
                                "exercise_id": str(cc.id),
                                "exercise_kind": "cc",
                                "sets": sets_cc,
                            },
                            {
                                "exercise_id": str(sat_sy.id),
                                "exercise_kind": "satellite",
                                "section": "accessories",
                                "sets": sets_sat,
                            },
                        ],
                    },
                )
            ],
        ),
    )
    assert sync_out.results[0].status == "applied"

    online_by = {log.exercise_kind: log for log in online.logs}
    sync_logs = (
        await db.scalars(
            select(SessionExerciseLog).where(SessionExerciseLog.session_id == sid)
        )
    ).all()
    sync_by = {log.exercise_kind: log for log in sync_logs}

    for kind in ("cc", "satellite"):
        assert online_by[kind].goal_met == sync_by[kind].goal_met
        assert (
            online_by[kind].counts_for_progression
            == sync_by[kind].counts_for_progression
        )
        online_row = await db.get(SessionExerciseLog, online_by[kind].id)
        assert online_row is not None
        assert (online_row.rules_snapshot or {}).get("goal") == (
            sync_by[kind].rules_snapshot or {}
        ).get("goal")

    online_cc_step = await db.scalar(
        select(UserExerciseProgress.current_step_number).where(
            UserExerciseProgress.user_id == user_online.id,
            UserExerciseProgress.exercise_id == cc.id,
        )
    )
    sync_cc_step = await db.scalar(
        select(UserExerciseProgress.current_step_number).where(
            UserExerciseProgress.user_id == user_sync.id,
            UserExerciseProgress.exercise_id == cc.id,
        )
    )
    assert online_cc_step == sync_cc_step == 2


# ---------------------------------------------------------------------------
# E. Legal / tombstone / legacy batch order
# ---------------------------------------------------------------------------


def test_legacy_sort_push_items_type_order() -> None:
    """Current production order until depends_on lands: legal→session→meas→sat."""
    items = [
        SyncPushItemV1(
            client_mutation_id=new_uuid7(),
            entity_type="satellite",
            entity_id=new_uuid7(),
            op="upsert",
            revision=1,
            payload={},
        ),
        SyncPushItemV1(
            client_mutation_id=new_uuid7(),
            entity_type="workout_session",
            entity_id=new_uuid7(),
            op="upsert",
            revision=1,
            client_updated_at=datetime(2026, 7, 27, 12, 0, tzinfo=UTC),
            payload={"performed_at": "2026-07-27T12:00:00+00:00"},
        ),
        SyncPushItemV1(
            client_mutation_id=new_uuid7(),
            entity_type="body_measurement",
            entity_id=new_uuid7(),
            op="upsert",
            revision=1,
            payload={"measured_at": "2026-07-27T11:00:00+00:00"},
        ),
        SyncPushItemV1(
            client_mutation_id=new_uuid7(),
            entity_type="legal_acceptance",
            entity_id=new_uuid7(),
            op="upsert",
            revision=1,
            payload={"accepted_at": "2026-07-27T09:00:00+00:00"},
        ),
        SyncPushItemV1(
            client_mutation_id=new_uuid7(),
            entity_type="workout_session",
            entity_id=new_uuid7(),
            op="delete",
            revision=2,
            client_updated_at=datetime(2026, 7, 27, 11, 30, tzinfo=UTC),
        ),
    ]
    sorted_types = [i.entity_type for i in sort_push_items(items)]
    assert sorted_types == [
        "legal_acceptance",
        "workout_session",
        "workout_session",
        "body_measurement",
        "satellite",
    ]
    assert sort_push_items(items)[1].op == "delete"
    assert sort_push_items(items)[2].op == "upsert"


@pytest.mark.asyncio
async def test_sync_session_without_legal_rejected(db: AsyncSession) -> None:
    user = await _ready(db, "char-legal-miss@ex.com", accept_legal=False)
    cc = await _cc_push(db)
    mut = new_uuid7()
    out = await push_batch(
        db,
        user=user,
        body=SyncPushRequestV1(
            schema_version=1,
            items=[
                SyncPushItemV1(
                    client_mutation_id=mut,
                    entity_type="workout_session",
                    entity_id=new_uuid7(),
                    op="upsert",
                    revision=1,
                    payload={
                        "schema_version": 1,
                        "performed_at": datetime(2026, 7, 27, 10, 0, tzinfo=UTC).isoformat(),
                        "local_date": "2026-07-27",
                        "client_mutation_id": str(mut),
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
    assert out.results[0].status == "rejected"
    assert out.results[0].error_code == "legal_required"


@pytest.mark.asyncio
async def test_same_batch_legal_then_session_applies_under_type_order(
    db: AsyncSession,
) -> None:
    user = await _ready(db, "char-legal-batch@ex.com", accept_legal=False)
    cc = await _cc_push(db)
    doc, tr = await latest_health_disclaimer(db)
    legal_mut = new_uuid7()
    sess_mut = new_uuid7()
    # Intentionally unordered: session listed before legal; sort must fix it.
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
                    op="upsert",
                    revision=1,
                    payload={
                        "schema_version": 1,
                        "performed_at": datetime(2026, 7, 27, 10, 0, tzinfo=UTC).isoformat(),
                        "local_date": "2026-07-27",
                        "client_mutation_id": str(sess_mut),
                        "client_timezone": "Europe/Warsaw",
                        "logs": [
                            {
                                "exercise_id": str(cc.id),
                                "exercise_kind": "cc",
                                "sets": {
                                    "schema_version": 1,
                                    "sets": [{"reps": 50}, {"reps": 50}, {"reps": 50}],
                                },
                            }
                        ],
                    },
                ),
                SyncPushItemV1(
                    client_mutation_id=legal_mut,
                    entity_type="legal_acceptance",
                    entity_id=doc.id,
                    op="upsert",
                    revision=1,
                    payload={
                        "schema_version": 1,
                        "client_mutation_id": str(legal_mut),
                        "document_slug": "health_disclaimer",
                        "document_version": doc.version,
                        "accepted_locale": "pl-PL",
                        "accepted_content_hash": tr.content_hash.hex(),
                        "accepted_at": datetime.now(UTC).isoformat(),
                    },
                ),
            ],
        ),
    )
    by_mut = {r.client_mutation_id: r for r in out.results}
    assert by_mut[legal_mut].status == "applied"
    assert by_mut[sess_mut].status == "applied"


@pytest.mark.asyncio
async def test_soft_delete_then_replacement_same_day_via_sync(db: AsyncSession) -> None:
    user = await _ready(db, "char-tombstone@ex.com")
    cc = await _cc_push(db)
    sid1 = new_uuid7()
    mut1 = new_uuid7()
    first = await push_batch(
        db,
        user=user,
        body=SyncPushRequestV1(
            schema_version=1,
            items=[
                SyncPushItemV1(
                    client_mutation_id=mut1,
                    entity_type="workout_session",
                    entity_id=sid1,
                    op="upsert",
                    revision=1,
                    payload={
                        "schema_version": 1,
                        "performed_at": datetime(2026, 7, 27, 10, 0, tzinfo=UTC).isoformat(),
                        "local_date": "2026-07-27",
                        "client_mutation_id": str(mut1),
                        "client_timezone": "Europe/Warsaw",
                        "logs": [
                            {
                                "exercise_id": str(cc.id),
                                "exercise_kind": "cc",
                                "sets": {
                                    "schema_version": 1,
                                    "sets": [{"reps": 50}, {"reps": 50}, {"reps": 50}],
                                },
                            }
                        ],
                    },
                )
            ],
        ),
    )
    assert first.results[0].status == "applied"
    step_after_first = await db.scalar(
        select(UserExerciseProgress.current_step_number).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == cc.id,
        )
    )
    assert step_after_first == 2

    del_mut = new_uuid7()
    repl_mut = new_uuid7()
    sid2 = new_uuid7()
    # Legacy type-order: both sessions; delete before upsert by op order.
    second = await push_batch(
        db,
        user=user,
        body=SyncPushRequestV1(
            schema_version=1,
            items=[
                SyncPushItemV1(
                    client_mutation_id=repl_mut,
                    entity_type="workout_session",
                    entity_id=sid2,
                    op="upsert",
                    revision=1,
                    payload={
                        "schema_version": 1,
                        "performed_at": datetime(2026, 7, 27, 11, 0, tzinfo=UTC).isoformat(),
                        "local_date": "2026-07-27",
                        "client_mutation_id": str(repl_mut),
                        "client_timezone": "Europe/Warsaw",
                        "logs": [
                            {
                                "exercise_id": str(cc.id),
                                "exercise_kind": "cc",
                                "sets": {
                                    "schema_version": 1,
                                    "sets": [{"reps": 10}, {"reps": 10}, {"reps": 10}],
                                },
                            }
                        ],
                    },
                ),
                SyncPushItemV1(
                    client_mutation_id=del_mut,
                    entity_type="workout_session",
                    entity_id=sid1,
                    op="delete",
                    revision=2,
                ),
            ],
        ),
    )
    by_mut = {r.client_mutation_id: r for r in second.results}
    assert by_mut[del_mut].status == "applied"
    assert by_mut[repl_mut].status == "applied"

    # Soft-delete does not rewind the earlier advance (no-rewind characterization).
    step_after = await db.scalar(
        select(UserExerciseProgress.current_step_number).where(
            UserExerciseProgress.user_id == user.id,
            UserExerciseProgress.exercise_id == cc.id,
        )
    )
    assert step_after == 2

    old = await db.get(WorkoutSession, sid1)
    assert old is not None and old.deleted_at is not None


@pytest.mark.asyncio
async def test_sync_retry_same_mutation_idempotent_for_satellite_session(
    db: AsyncSession,
) -> None:
    user = await _ready(db, "char-retry@ex.com")
    sat = await _make_goal_satellite(
        db,
        user,
        name="Retry sat",
        goal={"type": "reps", "sets": 1, "min_reps": 8},
    )
    mut = new_uuid7()
    sid = new_uuid7()
    item = SyncPushItemV1(
        client_mutation_id=mut,
        entity_type="workout_session",
        entity_id=sid,
        op="upsert",
        revision=1,
        payload={
            "schema_version": 1,
            "performed_at": datetime(2026, 7, 27, 10, 0, tzinfo=UTC).isoformat(),
            "local_date": "2026-07-27",
            "client_mutation_id": str(mut),
            "client_timezone": "Europe/Warsaw",
            "logs": [
                {
                    "exercise_id": str(sat.id),
                    "exercise_kind": "satellite",
                    "sets": {"schema_version": 1, "sets": [{"reps": 10}]},
                }
            ],
        },
    )
    first = await push_batch(
        db, user=user, body=SyncPushRequestV1(schema_version=1, items=[item])
    )
    assert first.results[0].status == "applied"
    second = await push_batch(
        db, user=user, body=SyncPushRequestV1(schema_version=1, items=[item])
    )
    assert second.results[0].status == "idempotent"
    log_count = await db.scalar(
        select(func.count())
        .select_from(SessionExerciseLog)
        .where(
            SessionExerciseLog.user_id == user.id,
            SessionExerciseLog.exercise_id == sat.id,
        )
    )
    assert int(log_count or 0) == 1
