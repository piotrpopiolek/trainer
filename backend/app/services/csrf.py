"""CSRF double-submit helpers (FR-005a)."""

from __future__ import annotations

import secrets

from fastapi import Request, Response

from app.core.config import settings
from app.core.cookies import clear_csrf_cookie, set_csrf_cookie
from app.services.errors import CsrfError


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def ensure_csrf_cookie(request: Request, response: Response) -> str:
    existing = request.cookies.get(settings.csrf_cookie_name)
    if existing:
        return existing
    token = new_csrf_token()
    set_csrf_cookie(response, token)
    return token


def validate_csrf(request: Request) -> None:
    cookie = request.cookies.get(settings.csrf_cookie_name)
    header = request.headers.get(settings.csrf_header_name)
    if not cookie or not header or cookie != header:
        raise CsrfError()


def clear_csrf(response: Response) -> None:
    clear_csrf_cookie(response)
