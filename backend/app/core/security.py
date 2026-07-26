"""Crypto helpers for sessions and PKCE (FR-001 / FR-005a)."""

from __future__ import annotations

import base64
import hashlib
import secrets


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(raw_token: str) -> bytes:
    return hashlib.sha256(raw_token.encode("utf-8")).digest()


def new_oauth_state() -> str:
    # ≥128 bits entropy
    return secrets.token_urlsafe(32)


def new_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def code_challenge_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def hash_ip_for_rate_limit(ip: str) -> str:
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()
