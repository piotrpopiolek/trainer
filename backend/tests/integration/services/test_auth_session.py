"""Auth / session tests (FR-001, FR-005d)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.core.security import hash_session_token
from app.models.auth import AuthSession
from app.models.user import User
from app.services.auth_session import AuthSessionService
from app.services.errors import AuthError
from app.services.oauth_google import GoogleIdTokenClaims, GoogleOAuthService


@pytest.fixture(autouse=True)
def _reset_rate_limits() -> None:
    from app.services.rate_limit import reset_memory_rate_limits

    reset_memory_rate_limits()
    settings.oauth_rate_limit_per_minute = 10
    settings.rate_limit_store = "memory"
    yield
    reset_memory_rate_limits()
    settings.oauth_rate_limit_per_minute = 10


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine(settings.resolved_database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()






@pytest.mark.asyncio
async def test_oauth_state_replay_rejected(db: AsyncSession) -> None:
    oauth = GoogleOAuthService()
    settings.google_client_id = "test-client"
    settings.google_client_secret = "test-secret"
    url, state = await oauth.start(db)
    assert "code_challenge" in url
    assert state in url
    verifier = await oauth.consume_state(db, state)
    assert verifier
    with pytest.raises(AuthError) as exc:
        await oauth.consume_state(db, state)
    assert exc.value.error_code == "oauth_state_invalid"










@pytest.mark.asyncio
async def test_same_google_sub_same_user(db: AsyncSession) -> None:
    svc = AuthSessionService()
    claims = GoogleIdTokenClaims(
        sub=f"sub-stable-{new_uuid7()}",
        email="a@example.com",
        email_verified=True,
        name="A",
    )
    u1 = await svc.upsert_user_from_google(db, claims)
    await db.commit()
    claims2 = GoogleIdTokenClaims(
        sub=claims.sub,
        email="b@example.com",
        email_verified=True,
        name="B",
    )
    u2 = await svc.upsert_user_from_google(db, claims2)
    await db.commit()
    assert u1.id == u2.id
    assert u2.email == "b@example.com"


@pytest.mark.asyncio
async def test_session_limit_ten(db: AsyncSession) -> None:
    svc = AuthSessionService()
    user = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}", email="x@ex.com")
    db.add(user)
    await db.commit()

    tokens = []
    for _ in range(11):
        tokens.append(await svc.create_session(db, user=user, user_agent="t"))

    active = await db.scalar(
        select(func.count())
        .select_from(AuthSession)
        .where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
        )
    )
    assert active == 10
    oldest_hash = hash_session_token(tokens[0])
    oldest = await db.scalar(
        select(AuthSession).where(AuthSession.token_hash == oldest_hash)
    )
    assert oldest is not None
    assert oldest.revoked_at is not None


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_parallel_logins_respect_session_cap(db: AsyncSession) -> None:
    svc = AuthSessionService()
    user = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}", email="p@ex.com")
    db.add(user)
    await db.commit()
    user_id = user.id

    for _ in range(9):
        await svc.create_session(db, user=user, user_agent="seed")

    async def _login() -> None:
        engine = create_async_engine(settings.resolved_database_url, pool_pre_ping=True)
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as session:
            u = await session.get(User, user_id)
            assert u is not None
            await AuthSessionService().create_session(session, user=u, user_agent="race")
        await engine.dispose()

    await asyncio.gather(_login(), _login())

    engine = create_async_engine(settings.resolved_database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        active = await session.scalar(
            select(func.count())
            .select_from(AuthSession)
            .where(
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
            )
        )
    await engine.dispose()
    assert active is not None
    assert active <= 10








@pytest.mark.asyncio
async def test_sliding_bump_rotates_token(db: AsyncSession) -> None:
    svc = AuthSessionService()
    user = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}", email="bump@ex.com")
    db.add(user)
    await db.commit()
    raw = await svc.create_session(db, user=user, user_agent="t")
    row = await db.scalar(
        select(AuthSession).where(AuthSession.token_hash == hash_session_token(raw))
    )
    assert row is not None
    row.last_seen_at = datetime.now(UTC) - timedelta(hours=25)
    await db.commit()

    user2, _sess, rotated = await svc.resolve_user(db, raw)
    assert user2.id == user.id
    assert rotated is not None
    assert rotated != raw


@pytest.mark.asyncio
async def test_sliding_no_rotate_within_24h(db: AsyncSession) -> None:
    svc = AuthSessionService()
    user = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}", email="nobump@ex.com")
    db.add(user)
    await db.commit()
    raw = await svc.create_session(db, user=user, user_agent="t")
    row = await db.scalar(
        select(AuthSession).where(AuthSession.token_hash == hash_session_token(raw))
    )
    assert row is not None
    last_seen_before = row.last_seen_at
    expires_before = row.expires_at

    user2, sess, rotated = await svc.resolve_user(db, raw)
    assert user2.id == user.id
    assert rotated is None
    assert sess.last_seen_at == last_seen_before
    assert sess.expires_at == expires_before


@pytest.mark.asyncio
async def test_old_token_valid_during_rotation_grace(db: AsyncSession) -> None:
    svc = AuthSessionService()
    user = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}", email="grace@ex.com")
    db.add(user)
    await db.commit()
    raw = await svc.create_session(db, user=user, user_agent="t")
    row = await db.scalar(
        select(AuthSession).where(AuthSession.token_hash == hash_session_token(raw))
    )
    assert row is not None
    row.last_seen_at = datetime.now(UTC) - timedelta(hours=25)
    await db.commit()

    _u, _s, rotated = await svc.resolve_user(db, raw)
    assert rotated is not None

    # Concurrent request still presenting the pre-rotation cookie.
    user2, sess, rotated2 = await svc.resolve_user(db, raw)
    assert user2.id == user.id
    assert rotated2 is None
    assert sess.token_hash == hash_session_token(rotated)


@pytest.mark.asyncio
async def test_hard_cap_rejects_session_after_90d(db: AsyncSession) -> None:
    svc = AuthSessionService()
    user = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}", email="cap@ex.com")
    db.add(user)
    await db.commit()
    raw = await svc.create_session(db, user=user, user_agent="t")
    row = await db.scalar(
        select(AuthSession).where(AuthSession.token_hash == hash_session_token(raw))
    )
    assert row is not None
    # Sliding window still valid, but hard cap exceeded (FR-005d).
    row.created_at = datetime.now(UTC) - timedelta(days=settings.session_hard_cap_days + 1)
    row.expires_at = datetime.now(UTC) + timedelta(days=7)
    await db.commit()

    with pytest.raises(AuthError) as exc:
        await svc.resolve_user(db, raw)
    assert exc.value.error_code == "unauthorized"
