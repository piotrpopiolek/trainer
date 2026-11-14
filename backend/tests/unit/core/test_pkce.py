"""PKCE S256 challenge is stable."""

from __future__ import annotations


def test_pkce_challenge_stable() -> None:
    from app.core.security import code_challenge_s256

    assert code_challenge_s256("verifier") == code_challenge_s256("verifier")
    assert code_challenge_s256("a") != code_challenge_s256("b")
