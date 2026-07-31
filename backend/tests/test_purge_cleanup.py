"""Hard purge (FR-006c) + cleanup cron (FR-005c/d)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.models.auth import AuthSession, OAuthState
from app.models.catalog import Exercise, Program
from app.models.progression import (
    ProgressionEvent,
    UserExerciseProgress,
    UserProgramEnrollment,
)
from app.models.sync import RateLimitBucket
from app.models.user import User
from app.models.workout import SessionExerciseLog, WorkoutSession
from app.schemas.api import SatelliteCreateV1
from app.services.cleanup import run_cleanup_batch
from app.services.purge import (
    assert_user_training_gone,
    hard_purge_user,
    list_due_purge_users,
    run_purge_batch,
)
from app.services.satellites import create_satellite


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine(settings.resolved_database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _cc_exercise(db: AsyncSession) -> Exercise:
    ex = await db.scalar(select(Exercise).where(Exercise.slug == "push_ups", Exercise.kind == "cc"))
    if ex is None:
        pytest.skip("seed catalog required")
    return ex


async def _program(db: AsyncSession) -> Program:
    prog = await db.scalar(select(Program).where(Program.slug == "cc_big_six"))
    if prog is None:
        pytest.skip("seed catalog required")
    return prog


async def _build_purgeable_user(db: AsyncSession) -> User:
    """Full training graph + soft-delete markers due for purge."""
    prog = await _program(db)
    exercise = await _cc_exercise(db)
    now = datetime.now(UTC)
    user = User(
        id=new_uuid7(),
        google_sub=None,
        email=None,
        display_name=None,
        deleted_at=now - timedelta(days=31),
        purge_after=date.today() - timedelta(days=1),
        purge_status="pending_grace",
        locale="pl-PL",
        timezone="Europe/Warsaw",
    )
    db.add(user)
    await db.flush()

    db.add(
        AuthSession(
            id=new_uuid7(),
            user_id=user.id,
            token_hash=new_uuid7().bytes + new_uuid7().bytes[:8],
            expires_at=now - timedelta(days=1),
            revoked_at=now - timedelta(days=1),
        )
    )
    db.add(
        UserProgramEnrollment(
            id=new_uuid7(),
            user_id=user.id,
            program_id=prog.id,
            started_on=date.today() - timedelta(days=60),
            anchor_weekday=1,
            is_active=True,
        )
    )
    db.add(
        UserExerciseProgress(
            id=new_uuid7(),
            user_id=user.id,
            exercise_id=exercise.id,
            current_step_number=2,
            fail_streak=0,
        )
    )

    sat = await create_satellite(
        db,
        user=user,
        body=SatelliteCreateV1.model_validate(
            {
                "schema_version": 1,
                "name": "Plank hold",
                "exercise_type": "B",
                "active_metrics": {"schema_version": 1, "metrics": ["reps"]},
                "schedule_kind": "daily",
                "steps": [
                    {
                        "step_number": 1,
                        "name": "Hold",
                        "rules": {
                            "schema_version": 1,
                            "goal": {
                                "type": "reps",
                                "sets": 1,
                                "min_reps": 30,
                            },
                        },
                    }
                ],
                "client_mutation_id": str(new_uuid7()),
            }
        ),
        commit=False,
    )

    session = WorkoutSession(
        id=new_uuid7(),
        user_id=user.id,
        performed_at=now - timedelta(days=40),
        local_date=date.today() - timedelta(days=40),
        client_mutation_id=new_uuid7(),
        revision=1,
        client_updated_at=now - timedelta(days=40),
    )
    db.add(session)
    await db.flush()
    db.add(
        SessionExerciseLog(
            id=new_uuid7(),
            session_id=session.id,
            user_id=user.id,
            exercise_id=exercise.id,
            exercise_kind="cc",
            section="main",
            step_number=1,
            local_date=session.local_date,
            performed_at=session.performed_at,
            content_locale="pl-PL",
            exercise_name_snapshot="Push-ups",
            skipped=False,
            sets={"schema_version": 1, "sets": [{"reps": 10}]},
            rules_snapshot={"schema_version": 1},
            progression_schema_version=1,
            sort_order=0,
            client_mutation_id=new_uuid7(),
            revision=1,
            client_updated_at=session.performed_at,
        )
    )
    db.add(
        ProgressionEvent(
            id=new_uuid7(),
            user_id=user.id,
            exercise_id=exercise.id,
            event_type="advance",
            from_step=1,
            to_step=2,
            created_at=now - timedelta(days=39),
        )
    )
    await db.commit()
    assert sat.id is not None
    return user


@pytest.mark.asyncio
async def test_hard_purge_removes_training_graph(db: AsyncSession) -> None:
    user = await _build_purgeable_user(db)
    await hard_purge_user(db, user_id=user.id)
    await db.commit()

    await assert_user_training_gone(db, user_id=user.id)
    await db.refresh(user)
    assert user.purge_status == "done"
    assert await db.get(User, user.id) is not None


@pytest.mark.asyncio
async def test_purge_batch_claim_and_rerun_noop(db: AsyncSession) -> None:
    user = await _build_purgeable_user(db)
    due = await list_due_purge_users(db)
    assert any(u.id == user.id for u in due)

    first = await run_purge_batch(db)
    assert first["ok"] >= 1
    await db.refresh(user)
    assert user.purge_status == "done"
    await assert_user_training_gone(db, user_id=user.id)

    second = await run_purge_batch(db)
    assert second["due"] == 0 or not any(
        u.id == user.id for u in await list_due_purge_users(db)
    )


@pytest.mark.asyncio
async def test_purge_batch_skips_future_purge_after(db: AsyncSession) -> None:
    user = User(
        id=new_uuid7(),
        deleted_at=datetime.now(UTC),
        purge_after=date.today() + timedelta(days=10),
        purge_status="pending_grace",
    )
    db.add(user)
    await db.commit()

    due_ids = {u.id for u in await list_due_purge_users(db)}
    assert user.id not in due_ids


@pytest.mark.asyncio
async def test_cleanup_removes_stale_rows(db: AsyncSession) -> None:
    now = datetime.now(UTC)
    old = now - timedelta(days=10)
    recent = now - timedelta(days=1)
    user = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}")
    db.add(user)
    await db.flush()

    old_session = AuthSession(
        id=new_uuid7(),
        user_id=user.id,
        token_hash=new_uuid7().bytes + new_uuid7().bytes[:8],
        expires_at=old,
        revoked_at=old,
    )
    # Old account row, but revoke only yesterday — must stay (cutoff on revoked_at/expires_at).
    recent_revoke = AuthSession(
        id=new_uuid7(),
        user_id=user.id,
        token_hash=new_uuid7().bytes + new_uuid7().bytes[:8],
        expires_at=now + timedelta(days=20),
        revoked_at=recent,
    )
    db.add(old_session)
    db.add(recent_revoke)
    await db.flush()
    await db.execute(
        AuthSession.__table__.update()
        .where(AuthSession.id == recent_revoke.id)
        .values(created_at=now - timedelta(days=100))
    )

    db.add(
        OAuthState(
            state=f"stale-{new_uuid7()}",
            code_verifier="v" * 43,
            expires_at=now - timedelta(hours=48),
            consumed_at=now - timedelta(hours=48),
        )
    )
    db.add(
        RateLimitBucket(
            bucket_key="ip:test:oauth",
            window_start=now - timedelta(hours=5),
            count=3,
        )
    )
    await db.commit()

    result = await run_cleanup_batch(db)
    assert result["auth_sessions"] >= 1
    assert result["oauth_states"] >= 1
    assert result["rate_limit_buckets"] >= 1

    assert await db.get(AuthSession, old_session.id) is None
    assert await db.get(AuthSession, recent_revoke.id) is not None
    n_rl = await db.scalar(
        select(func.count())
        .select_from(RateLimitBucket)
        .where(RateLimitBucket.bucket_key == "ip:test:oauth")
    )
    assert int(n_rl or 0) == 0
