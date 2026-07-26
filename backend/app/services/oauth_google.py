"""Google OAuth Authorization Code + PKCE + ID token JWKS (FR-001)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import code_challenge_s256, new_code_verifier, new_oauth_state
from app.models.auth import OAuthState
from app.services.errors import AuthError, OAuthNotConfiguredError

GOOGLE_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}


@dataclass(frozen=True, slots=True)
class GoogleIdTokenClaims:
    sub: str
    email: str | None
    email_verified: bool
    name: str | None


class GoogleOAuthService:
    def __init__(self, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._http = http_client
        self._jwks = PyJWKClient(settings.google_jwks_url, cache_keys=True)

    def _require_configured(self) -> None:
        if not settings.google_client_id or not settings.google_client_secret:
            raise OAuthNotConfiguredError()

    async def start(self, db: AsyncSession) -> tuple[str, str]:
        """Return (authorize_url, state) — caller must set state cookie on the browser."""
        self._require_configured()
        state = new_oauth_state()
        verifier = new_code_verifier()
        expires_at = datetime.now(UTC) + timedelta(minutes=settings.oauth_state_ttl_minutes)
        db.add(
            OAuthState(
                state=state,
                code_verifier=verifier,
                expires_at=expires_at,
            )
        )
        await db.commit()

        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "code_challenge": code_challenge_s256(verifier),
            "code_challenge_method": "S256",
            "access_type": "online",
            "prompt": "select_account",
        }
        return f"{settings.google_auth_url}?{urlencode(params)}", state

    def assert_browser_state(self, *, query_state: str, cookie_state: str | None) -> None:
        if not cookie_state or cookie_state != query_state:
            raise AuthError("oauth_state_invalid", http_status=400)

    async def consume_state(self, db: AsyncSession, state: str) -> str:
        """Return code_verifier; reject missing/expired/replayed state."""
        row = await db.scalar(
            select(OAuthState).where(OAuthState.state == state).with_for_update()
        )
        now = datetime.now(UTC)
        if row is None or row.consumed_at is not None or row.expires_at <= now:
            raise AuthError("oauth_state_invalid", http_status=400)
        row.consumed_at = now
        await db.commit()
        return row.code_verifier

    async def exchange_code(self, *, code: str, code_verifier: str) -> str:
        self._require_configured()
        client = self._http or httpx.AsyncClient(timeout=10.0)
        owns_client = self._http is None
        try:
            response = await client.post(
                settings.google_token_url,
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": settings.google_redirect_uri,
                    "grant_type": "authorization_code",
                    "code_verifier": code_verifier,
                },
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AuthError("oauth_token_exchange_failed", http_status=401) from exc
        finally:
            if owns_client:
                await client.aclose()

        id_token = payload.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise AuthError("oauth_token_invalid", http_status=401)
        return id_token

    def verify_id_token(self, id_token: str) -> GoogleIdTokenClaims:
        self._require_configured()
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(id_token)
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256"],
                audience=settings.google_client_id,
                issuer=list(GOOGLE_ISSUERS),
                leeway=60,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthError("oauth_token_invalid", http_status=401) from exc

        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub:
            raise AuthError("oauth_token_invalid", http_status=401)

        email_verified = bool(claims.get("email_verified") is True)
        if not email_verified:
            raise AuthError("oauth_email_unverified", http_status=403)

        email = claims.get("email")
        name = claims.get("name")
        return GoogleIdTokenClaims(
            sub=sub,
            email=email if isinstance(email, str) else None,
            email_verified=True,
            name=name if isinstance(name, str) else None,
        )
