"""Google OAuth + session endpoints (FR-001, FR-004, FR-005a/c/d)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    AuthContext,
    enforce_oauth_rate_limit,
    get_auth_session_service,
    get_current_user,
    get_oauth_service,
)
from app.core.config import settings
from app.core.cookies import (
    clear_csrf_cookie,
    clear_oauth_state_cookie,
    clear_session_cookie,
    set_csrf_cookie,
    set_oauth_state_cookie,
    set_session_cookie,
)
from app.db.session import get_session
from app.services.auth_session import AuthSessionService
from app.services.csrf import ensure_csrf_cookie, new_csrf_token
from app.services.errors import AuthError
from app.services.legal import user_has_current_health_disclaimer
from app.services.oauth_google import GoogleOAuthService

router = APIRouter(prefix="/auth", tags=["auth"])


class MeResponse(BaseModel):
    schema_version: int = 1
    id: str
    email: str | None
    display_name: str | None
    locale: str
    timezone: str
    onboarding_completed: bool
    health_disclaimer_accepted: bool
    csrf_token: str


@router.get("/google/start")
async def google_start(
    db: AsyncSession = Depends(get_session),
    oauth: GoogleOAuthService = Depends(get_oauth_service),
    _rate: None = Depends(enforce_oauth_rate_limit),
) -> RedirectResponse:
    url, state = await oauth.start(db)
    redirect = RedirectResponse(url=url, status_code=302)
    set_oauth_state_cookie(redirect, state)
    return redirect


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: AsyncSession = Depends(get_session),
    oauth: GoogleOAuthService = Depends(get_oauth_service),
    auth_sessions: AuthSessionService = Depends(get_auth_session_service),
    _rate: None = Depends(enforce_oauth_rate_limit),
) -> RedirectResponse:
    if not code or not state:
        redirect = RedirectResponse(
            url=f"{settings.public_origin}/login?error=oauth_state_invalid",
            status_code=302,
        )
        clear_oauth_state_cookie(redirect)
        return redirect
    try:
        oauth.assert_browser_state(
            query_state=state,
            cookie_state=request.cookies.get(settings.oauth_state_cookie_name),
        )
        verifier = await oauth.consume_state(db, state)
        id_token = await oauth.exchange_code(code=code, code_verifier=verifier)
        claims = oauth.verify_id_token(id_token)
        user = await auth_sessions.upsert_user_from_google(db, claims)
        raw = await auth_sessions.create_session(
            db,
            user=user,
            user_agent=request.headers.get("user-agent"),
        )
    except AuthError as exc:
        redirect = RedirectResponse(
            url=f"{settings.public_origin}/login?error={exc.error_code}",
            status_code=302,
        )
        clear_oauth_state_cookie(redirect)
        return redirect

    redirect = RedirectResponse(url=f"{settings.public_origin}/", status_code=302)
    set_session_cookie(redirect, raw)
    set_csrf_cookie(redirect, new_csrf_token())
    clear_oauth_state_cookie(redirect)
    return redirect


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    auth_sessions: AuthSessionService = Depends(get_auth_session_service),
) -> dict[str, bool]:
    raw = request.cookies.get(settings.session_cookie_name)
    await auth_sessions.revoke_current(db, raw)
    clear_session_cookie(response)
    clear_csrf_cookie(response)
    return {"ok": True}


@router.post("/logout-all")
async def logout_all(
    response: Response,
    ctx: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    auth_sessions: AuthSessionService = Depends(get_auth_session_service),
) -> dict[str, bool]:
    await auth_sessions.revoke_all_for_user(db, ctx.user.id)
    clear_session_cookie(response)
    clear_csrf_cookie(response)
    return {"ok": True}


@router.get("/me")
async def me(
    request: Request,
    response: Response,
    ctx: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> MeResponse:
    token = ensure_csrf_cookie(request, response)
    accepted = await user_has_current_health_disclaimer(
        db, user_id=ctx.user.id, locale=ctx.user.locale or "pl-PL"
    )
    return MeResponse(
        id=str(ctx.user.id),
        email=ctx.user.email,
        display_name=ctx.user.display_name,
        locale=ctx.user.locale,
        timezone=ctx.user.timezone,
        onboarding_completed=ctx.user.onboarding_completed_at is not None,
        health_disclaimer_accepted=accepted,
        csrf_token=token,
    )
