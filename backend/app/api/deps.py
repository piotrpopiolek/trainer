"""FastAPI dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.cookies import set_session_cookie
from app.db.session import get_session
from app.models.user import User
from app.services.auth_session import AuthSessionService
from app.services.csrf import validate_csrf
from app.services.errors import AuthError
from app.services.oauth_google import GoogleOAuthService
from app.services.rate_limit import (
    get_rate_limiter,
    oauth_bucket_key,
    user_api_bucket_key,
)


@dataclass(slots=True)
class AuthContext:
    user: User
    raw_token: str


def get_oauth_service() -> GoogleOAuthService:
    return GoogleOAuthService()


def get_auth_session_service() -> AuthSessionService:
    return AuthSessionService()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


async def enforce_oauth_rate_limit(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> None:
    limiter = get_rate_limiter()
    await limiter.hit(
        db,
        bucket_key=oauth_bucket_key(_client_ip(request)),
        limit=settings.oauth_rate_limit_per_minute,
    )


async def get_current_user(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    auth_sessions: AuthSessionService = Depends(get_auth_session_service),
) -> AuthContext:
    raw = request.cookies.get(settings.session_cookie_name)
    try:
        user, _session_row, rotated = await auth_sessions.resolve_user(db, raw)
    except AuthError:
        raise
    if rotated is not None:
        set_session_cookie(response, rotated)
        raw = rotated
    assert raw is not None
    return AuthContext(user=user, raw_token=raw)


async def get_current_user_rate_limited(
    ctx: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> AuthContext:
    limiter = get_rate_limiter()
    await limiter.hit(
        db,
        bucket_key=user_api_bucket_key(ctx.user.id),
        limit=settings.api_rate_limit_per_minute,
    )
    return ctx


def require_csrf(request: Request) -> None:
    validate_csrf(request)
