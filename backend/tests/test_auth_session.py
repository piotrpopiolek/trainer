"""Auth / session tests (FR-001, FR-005d)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.ids import new_uuid7
from app.core.security import hash_session_token
from app.db.session import dispose_engine
from app.main import app
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


@pytest.fixture
async def api_client() -> AsyncClient:
    await dispose_engine()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        yield client
    await dispose_engine()


def test_pkce_challenge_stable() -> None:
    from app.core.security import code_challenge_s256

    assert code_challenge_s256("verifier") == code_challenge_s256("verifier")
    assert code_challenge_s256("a") != code_challenge_s256("b")


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

def _signed_id_token(
    *,
    claims: dict[str, object] | None = None,
    aud: str = "test-client",
    iss: str = "https://accounts.google.com",
    exp: datetime | None = None,
    email_verified: bool = True,
) -> tuple[str, GoogleOAuthService]:
    settings.google_client_id = "test-client"
    settings.google_client_secret = "test-secret"
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    payload: dict[str, object] = {
        "sub": "google-sub-1",
        "email": "u@example.com",
        "email_verified": email_verified,
        "iss": iss,
        "aud": aud,
        "exp": exp or (datetime.now(UTC) + timedelta(hours=1)),
        "iat": datetime.now(UTC),
    }
    if claims:
        payload.update(claims)
    token = jwt.encode(
        payload,
        pem,
        algorithm="RS256",
        headers={"kid": "test-kid"},
    )
    oauth = GoogleOAuthService()
    signing = MagicMock()
    signing.key = private_key.public_key()
    oauth._jwks.get_signing_key_from_jwt = MagicMock(return_value=signing)  # type: ignore[method-assign]
    return token, oauth


@pytest.mark.asyncio
async def test_email_unverified_rejected() -> None:
    token, oauth = _signed_id_token(email_verified=False)
    with pytest.raises(AuthError) as exc:
        oauth.verify_id_token(token)
    assert exc.value.error_code == "oauth_email_unverified"


@pytest.mark.asyncio
async def test_id_token_rejects_bad_audience() -> None:
    token, oauth = _signed_id_token(aud="other-client")
    with pytest.raises(AuthError) as exc:
        oauth.verify_id_token(token)
    assert exc.value.error_code == "oauth_token_invalid"


@pytest.mark.asyncio
async def test_id_token_rejects_bad_issuer() -> None:
    token, oauth = _signed_id_token(iss="https://evil.example")
    with pytest.raises(AuthError) as exc:
        oauth.verify_id_token(token)
    assert exc.value.error_code == "oauth_token_invalid"


@pytest.mark.asyncio
async def test_id_token_rejects_expired() -> None:
    token, oauth = _signed_id_token(
        exp=datetime.now(UTC) - timedelta(hours=2),
    )
    with pytest.raises(AuthError) as exc:
        oauth.verify_id_token(token)
    assert exc.value.error_code == "oauth_token_invalid"

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
async def test_me_requires_session(api_client: AsyncClient) -> None:
    res = await api_client.get("/api/auth/me")
    assert res.status_code == 401
    assert res.json()["error_code"] == "unauthorized"


@pytest.mark.asyncio
async def test_me_with_session_cookie(api_client: AsyncClient, db: AsyncSession) -> None:
    svc = AuthSessionService()
    user = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}", email="me@ex.com")
    db.add(user)
    await db.commit()
    raw = await svc.create_session(db, user=user, user_agent="test")
    res = await api_client.get(
        "/api/auth/me",
        cookies={settings.session_cookie_name: raw},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["schema_version"] == 1
    assert body["email"] == "me@ex.com"


@pytest.mark.asyncio
async def test_logout_revokes_current(api_client: AsyncClient, db: AsyncSession) -> None:
    svc = AuthSessionService()
    user = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}", email="out@ex.com")
    db.add(user)
    await db.commit()
    raw = await svc.create_session(db, user=user, user_agent="test")
    res = await api_client.post(
        "/api/auth/logout",
        cookies={settings.session_cookie_name: raw},
    )
    assert res.status_code == 200
    me = await api_client.get(
        "/api/auth/me",
        cookies={settings.session_cookie_name: raw},
    )
    assert me.status_code == 401


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


@pytest.mark.asyncio
async def test_logout_all_revokes_other_sessions(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    svc = AuthSessionService()
    user = User(id=new_uuid7(), google_sub=f"sub-{new_uuid7()}", email="all@ex.com")
    db.add(user)
    await db.commit()
    raw_a = await svc.create_session(db, user=user, user_agent="a")
    raw_b = await svc.create_session(db, user=user, user_agent="b")

    res = await api_client.post(
        "/api/auth/logout-all",
        cookies={settings.session_cookie_name: raw_a},
    )
    assert res.status_code == 200

    for raw in (raw_a, raw_b):
        me = await api_client.get(
            "/api/auth/me",
            cookies={settings.session_cookie_name: raw},
        )
        assert me.status_code == 401

@pytest.mark.asyncio
async def test_oauth_exchange_code_success(monkeypatch: pytest.MonkeyPatch) -> None:
    settings.google_client_id = "cid"
    settings.google_client_secret = "sec"

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"id_token": "fake.jwt.token"}

    class _Client:
        async def post(self, *args: object, **kwargs: object) -> _Resp:
            return _Resp()

        async def aclose(self) -> None:
            return None

    oauth = GoogleOAuthService(http_client=_Client())  # type: ignore[arg-type]
    token = await oauth.exchange_code(code="abc", code_verifier="ver")
    assert token == "fake.jwt.token"
    settings.google_client_id = ""
    settings.google_client_secret = ""


@pytest.mark.asyncio
async def test_google_start_requires_config(api_client: AsyncClient) -> None:
    settings.google_client_id = ""
    settings.google_client_secret = ""
    res = await api_client.get("/api/auth/google/start", follow_redirects=False)
    assert res.status_code == 503
    assert res.json()["error_code"] == "oauth_not_configured"


@pytest.mark.asyncio
async def test_oauth_callback_rejects_missing_state_cookie(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    settings.google_client_id = "test-client"
    settings.google_client_secret = "test-secret"
    oauth = GoogleOAuthService()
    _url, state = await oauth.start(db)
    res = await api_client.get(
        "/api/auth/google/callback",
        params={"code": "fake-code", "state": state},
        follow_redirects=False,
    )
    assert res.status_code == 302
    assert "oauth_state_invalid" in res.headers["location"]


@pytest.mark.asyncio
async def test_oauth_callback_rejects_mismatched_state_cookie(
    api_client: AsyncClient, db: AsyncSession
) -> None:
    settings.google_client_id = "test-client"
    settings.google_client_secret = "test-secret"
    oauth = GoogleOAuthService()
    _url, state = await oauth.start(db)
    res = await api_client.get(
        "/api/auth/google/callback",
        params={"code": "fake-code", "state": state},
        cookies={settings.oauth_state_cookie_name: "other-state"},
        follow_redirects=False,
    )
    assert res.status_code == 302
    assert "oauth_state_invalid" in res.headers["location"]


@pytest.mark.asyncio
async def test_oauth_start_sets_state_cookie(api_client: AsyncClient) -> None:
    from app.services.rate_limit import reset_memory_rate_limits

    reset_memory_rate_limits()
    settings.google_client_id = "test-client"
    settings.google_client_secret = "test-secret"
    settings.rate_limit_store = "memory"
    res = await api_client.get("/api/auth/google/start", follow_redirects=False)
    assert res.status_code == 302
    assert settings.oauth_state_cookie_name in res.cookies
    cookie_state = res.cookies[settings.oauth_state_cookie_name]
    assert f"state={cookie_state}" in res.headers["location"]


@pytest.mark.asyncio
async def test_oauth_rate_limit_returns_429(api_client: AsyncClient) -> None:
    from app.services.rate_limit import reset_memory_rate_limits

    reset_memory_rate_limits()
    settings.google_client_id = "test-client"
    settings.google_client_secret = "test-secret"
    settings.rate_limit_store = "memory"
    settings.oauth_rate_limit_per_minute = 3
    try:
        for _ in range(3):
            res = await api_client.get("/api/auth/google/start", follow_redirects=False)
            assert res.status_code == 302
        limited = await api_client.get("/api/auth/google/start", follow_redirects=False)
        assert limited.status_code == 429
        assert limited.json()["error_code"] == "rate_limited"
        assert "Retry-After" in limited.headers
    finally:
        settings.oauth_rate_limit_per_minute = 10
        reset_memory_rate_limits()
