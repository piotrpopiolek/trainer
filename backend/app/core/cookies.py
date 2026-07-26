"""Session / OAuth cookies (__Host-… / FR-005a, login CSRF bind)."""

from __future__ import annotations

from fastapi import Response

from app.core.config import settings

SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60


def set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        max_age=SESSION_MAX_AGE_SECONDS,
        expires=SESSION_MAX_AGE_SECONDS,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
        # no Domain — required for __Host- prefix
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )


def set_oauth_state_cookie(response: Response, state: str) -> None:
    """Bind OAuth state to the initiating browser (SameSite=Lax for Google redirect)."""
    max_age = settings.oauth_state_ttl_minutes * 60
    response.set_cookie(
        key=settings.oauth_state_cookie_name,
        value=state,
        max_age=max_age,
        expires=max_age,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


def clear_oauth_state_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.oauth_state_cookie_name,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
