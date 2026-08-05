"""Unit tests for Settings DSN resolution (no DB required)."""

import pytest

from app.core.config import Settings, _asyncpg_dsn, validate_runtime_settings


def test_asyncpg_dsn_quotes_special_chars() -> None:
    dsn = _asyncpg_dsn(
        user="u",
        password="p@ss:word",
        host="db",
        port=5432,
        database="trainer",
    )
    assert dsn.startswith("postgresql+asyncpg://")
    assert "@db:5432/trainer" in dsn
    assert "p@ss:word" not in dsn  # must be percent-encoded


def test_resolved_database_url_prefers_explicit_override() -> None:
    s = Settings(
        database_url="postgresql+asyncpg://override:x@db:5432/trainer",
        trainer_app_password="ignored",
    )
    assert s.resolved_database_url.startswith("postgresql+asyncpg://override:")


def test_resolved_database_url_builds_from_password() -> None:
    s = Settings(
        database_url="",
        trainer_app_password="secret",
        postgres_host="db",
        postgres_db="trainer",
    )
    assert "trainer_app:" in s.resolved_database_url
    assert s.resolved_database_url.endswith("@db:5432/trainer")


def test_resolved_database_url_requires_password() -> None:
    s = Settings(database_url="", trainer_app_password="")
    with pytest.raises(RuntimeError, match="DATABASE_URL or TRAINER_APP_PASSWORD"):
        _ = s.resolved_database_url


def test_resolved_alembic_database_url_prefers_explicit_override() -> None:
    s = Settings(
        alembic_database_url="postgresql+asyncpg://mig:x@db:5432/trainer",
        postgres_password="ignored",
    )
    assert s.resolved_alembic_database_url.startswith("postgresql+asyncpg://mig:")


def test_resolved_alembic_database_url_builds_from_postgres_password() -> None:
    s = Settings(
        alembic_database_url="",
        postgres_user="trainer",
        postgres_password="rootsecret",
        postgres_host="db",
        postgres_db="trainer",
    )
    assert "trainer:" in s.resolved_alembic_database_url
    assert s.resolved_alembic_database_url.endswith("@db:5432/trainer")


def test_resolved_alembic_database_url_requires_password() -> None:
    s = Settings(alembic_database_url="", postgres_password="")
    with pytest.raises(RuntimeError, match="ALEMBIC_DATABASE_URL or POSTGRES_PASSWORD"):
        _ = s.resolved_alembic_database_url


def test_validate_runtime_settings_skips_development() -> None:
    validate_runtime_settings(
        Settings(
            app_env="development",
            rate_limit_store="memory",
            public_origin="https://localhost",
        )
    )


def test_validate_runtime_settings_rejects_prod_misconfig() -> None:
    s = Settings(
        app_env="production",
        rate_limit_store="memory",
        csrf_secret="",
        google_client_id="",
        google_client_secret="",
        public_origin="https://localhost",
        google_redirect_uri="https://localhost/api/auth/google/callback",
    )
    with pytest.raises(RuntimeError, match="Invalid production settings"):
        validate_runtime_settings(s)


def test_validate_runtime_settings_accepts_prod() -> None:
    # Explicit enable_e2e_login=False: CI/dev .env may set ENABLE_E2E_LOGIN=1,
    # and Settings() still merges env for fields not passed here.
    validate_runtime_settings(
        Settings(
            app_env="production",
            rate_limit_store="postgres",
            csrf_secret="x" * 32,
            google_client_id="cid",
            google_client_secret="csec",
            public_origin="https://app.example.com",
            google_redirect_uri="https://app.example.com/api/auth/google/callback",
            enable_e2e_login=False,
        )
    )


def test_validate_runtime_settings_rejects_e2e_login_in_prod() -> None:
    s = Settings(
        app_env="production",
        rate_limit_store="postgres",
        csrf_secret="x" * 32,
        google_client_id="cid",
        google_client_secret="csec",
        public_origin="https://app.example.com",
        google_redirect_uri="https://app.example.com/api/auth/google/callback",
        enable_e2e_login=True,
    )
    with pytest.raises(RuntimeError, match="ENABLE_E2E_LOGIN"):
        validate_runtime_settings(s)
