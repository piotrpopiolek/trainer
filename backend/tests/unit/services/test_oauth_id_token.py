"""Google ID token checks and code exchange with a fake HTTP client."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import settings
from app.services.errors import AuthError
from app.services.oauth_google import GoogleOAuthService


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
