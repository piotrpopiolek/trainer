"""db-core: roles, users/auth/legal/onboarding, body_measurements + RLS.

Revision ID: 20260726_0001
Revises:
Create Date: 2026-07-26
"""

from __future__ import annotations

import os

from alembic import op

revision = "20260726_0001"
down_revision = None
branch_labels = None
depends_on = None


def _role_password(env_name: str) -> str:
    value = os.environ.get(env_name)
    if not value:
        raise RuntimeError(
            f"{env_name} must be set for role bootstrap (see .env.example)"
        )
    return value.replace("'", "''")


def _sql(statement: str) -> None:
    # Avoid SQLAlchemy bind parsing of JSON ':1' etc.
    op.get_bind().exec_driver_sql(statement)


def upgrade() -> None:
    app_pw = _role_password("TRAINER_APP_PASSWORD")
    migrator_pw = _role_password("TRAINER_MIGRATOR_PASSWORD")

    _sql("CREATE EXTENSION IF NOT EXISTS citext")

    _sql(
        f"""
        DO $$
        BEGIN
          CREATE ROLE trainer_migrator LOGIN PASSWORD '{migrator_pw}';
        EXCEPTION WHEN duplicate_object THEN
          ALTER ROLE trainer_migrator WITH LOGIN PASSWORD '{migrator_pw}';
        END
        $$
        """
    )
    _sql("ALTER ROLE trainer_migrator WITH BYPASSRLS")

    _sql(
        f"""
        DO $$
        BEGIN
          CREATE ROLE trainer_app LOGIN PASSWORD '{app_pw}';
        EXCEPTION WHEN duplicate_object THEN
          ALTER ROLE trainer_app WITH LOGIN PASSWORD '{app_pw}';
        END
        $$
        """
    )

    _sql("GRANT CONNECT ON DATABASE trainer TO trainer_migrator")
    _sql("GRANT CONNECT ON DATABASE trainer TO trainer_app")
    _sql("GRANT USAGE, CREATE ON SCHEMA public TO trainer_migrator")
    _sql("GRANT USAGE ON SCHEMA public TO trainer_app")

    _sql(
        """
        CREATE TABLE users (
          id UUID PRIMARY KEY,
          google_sub TEXT UNIQUE,
          email CITEXT,
          display_name TEXT,
          locale TEXT NOT NULL DEFAULT 'pl-PL',
          timezone TEXT NOT NULL DEFAULT 'Europe/Warsaw',
          pending_timezone TEXT,
          timezone_effective_on DATE,
          body_metric_prefs JSONB NOT NULL DEFAULT
            $json${"schema_version":1,"metrics":["weight_kg","waist_cm","biceps_cm"]}$json$::jsonb,
          onboarding_completed_at TIMESTAMPTZ,
          deleted_at TIMESTAMPTZ,
          purge_after DATE,
          purge_status TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT ck_users_locale_len CHECK (char_length(locale) BETWEEN 2 AND 35),
          CONSTRAINT ck_users_body_metric_prefs_schema CHECK (
            (body_metric_prefs ? 'schema_version')
            AND (body_metric_prefs->>'schema_version')::int >= 1
          ),
          CONSTRAINT ck_users_purge_status CHECK (
            purge_status IS NULL
            OR purge_status IN ('pending_grace', 'pending_job', 'done')
          )
        )
        """
    )
    _sql(
        """
        CREATE INDEX ix_users_purge_after_pending
          ON users (purge_after)
          WHERE deleted_at IS NOT NULL AND purge_status IS DISTINCT FROM 'done'
        """
    )

    _sql(
        """
        CREATE TABLE auth_sessions (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
          token_hash BYTEA NOT NULL UNIQUE,
          expires_at TIMESTAMPTZ NOT NULL,
          revoked_at TIMESTAMPTZ,
          user_agent TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          last_seen_at TIMESTAMPTZ
        )
        """
    )
    _sql(
        """
        CREATE INDEX ix_auth_sessions_user_active
          ON auth_sessions (user_id, expires_at)
          WHERE revoked_at IS NULL
        """
    )

    _sql(
        """
        CREATE TABLE oauth_states (
          state TEXT PRIMARY KEY,
          code_verifier TEXT NOT NULL,
          expires_at TIMESTAMPTZ NOT NULL,
          consumed_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    _sql(
        """
        CREATE TABLE legal_documents (
          id UUID PRIMARY KEY,
          slug TEXT NOT NULL,
          version TEXT NOT NULL,
          published_at TIMESTAMPTZ NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT uq_legal_documents_slug_version UNIQUE (slug, version)
        )
        """
    )

    _sql(
        """
        CREATE TABLE legal_document_translations (
          document_id UUID NOT NULL REFERENCES legal_documents(id) ON DELETE RESTRICT,
          locale TEXT NOT NULL,
          title TEXT NOT NULL,
          body TEXT NOT NULL,
          content_hash BYTEA NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY (document_id, locale),
          CONSTRAINT ck_legal_document_translations_locale_len
            CHECK (char_length(locale) BETWEEN 2 AND 35),
          CONSTRAINT uq_legal_document_translations_doc_locale_hash
            UNIQUE (document_id, locale, content_hash)
        )
        """
    )

    _sql(
        """
        CREATE TABLE user_legal_acceptances (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
          document_id UUID NOT NULL REFERENCES legal_documents(id) ON DELETE RESTRICT,
          accepted_locale TEXT NOT NULL,
          accepted_content_hash BYTEA NOT NULL,
          accepted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT uq_user_legal_acceptances_user_doc UNIQUE (user_id, document_id),
          CONSTRAINT fk_user_legal_acceptances_translation
            FOREIGN KEY (document_id, accepted_locale, accepted_content_hash)
            REFERENCES legal_document_translations (document_id, locale, content_hash)
            ON DELETE RESTRICT
        )
        """
    )
    _sql(
        """
        CREATE INDEX ix_user_legal_acceptances_user_accepted_at
          ON user_legal_acceptances (user_id, accepted_at DESC)
        """
    )

    _sql(
        """
        CREATE TABLE user_onboarding (
          user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
          questionnaire JSONB NOT NULL DEFAULT $json${"schema_version":1}$json$::jsonb,
          placement_test JSONB NOT NULL DEFAULT $json${"schema_version":1}$json$::jsonb,
          recommended_steps JSONB NOT NULL DEFAULT $json${"schema_version":1}$json$::jsonb,
          chosen_steps JSONB NOT NULL DEFAULT $json${"schema_version":1}$json$::jsonb,
          completed_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT ck_user_onboarding_questionnaire_schema CHECK (
            (questionnaire ? 'schema_version')
            AND (questionnaire->>'schema_version')::int >= 1
          ),
          CONSTRAINT ck_user_onboarding_placement_test_schema CHECK (
            (placement_test ? 'schema_version')
            AND (placement_test->>'schema_version')::int >= 1
          ),
          CONSTRAINT ck_user_onboarding_recommended_steps_schema CHECK (
            (recommended_steps ? 'schema_version')
            AND (recommended_steps->>'schema_version')::int >= 1
          ),
          CONSTRAINT ck_user_onboarding_chosen_steps_schema CHECK (
            (chosen_steps ? 'schema_version')
            AND (chosen_steps->>'schema_version')::int >= 1
          )
        )
        """
    )

    _sql(
        """
        CREATE TABLE body_measurements (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
          measured_at TIMESTAMPTZ NOT NULL,
          local_date DATE NOT NULL,
          metrics JSONB NOT NULL,
          notes TEXT,
          client_mutation_id UUID NOT NULL,
          revision INT NOT NULL DEFAULT 1,
          client_updated_at TIMESTAMPTZ NOT NULL,
          deleted_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT ck_body_measurements_metrics_schema CHECK (
            (metrics ? 'schema_version')
            AND (metrics->>'schema_version')::int >= 1
          ),
          CONSTRAINT ck_body_measurements_notes_len CHECK (
            notes IS NULL OR char_length(notes) <= 1000
          ),
          CONSTRAINT ck_body_measurements_revision CHECK (revision >= 1),
          CONSTRAINT uq_body_measurements_user_client_mutation
            UNIQUE (user_id, client_mutation_id)
        )
        """
    )
    _sql(
        """
        CREATE INDEX ix_body_measurements_user_measured_at_active
          ON body_measurements (user_id, measured_at DESC)
          WHERE deleted_at IS NULL
        """
    )
    _sql(
        """
        CREATE INDEX ix_body_measurements_user_updated_at
          ON body_measurements (user_id, updated_at)
        """
    )

    _sql("ALTER TABLE body_measurements ENABLE ROW LEVEL SECURITY")
    _sql(
        """
        CREATE POLICY body_measurements_owner ON body_measurements
          USING (
            user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
          )
          WITH CHECK (
            user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
          )
        """
    )

    for table in (
        "users",
        "auth_sessions",
        "oauth_states",
        "legal_documents",
        "legal_document_translations",
        "user_legal_acceptances",
        "user_onboarding",
        "body_measurements",
    ):
        _sql(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO trainer_app")

    _sql(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
          GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO trainer_app
        """
    )


def downgrade() -> None:
    _sql("DROP POLICY IF EXISTS body_measurements_owner ON body_measurements")
    _sql("DROP TABLE IF EXISTS body_measurements")
    _sql("DROP TABLE IF EXISTS user_onboarding")
    _sql("DROP TABLE IF EXISTS user_legal_acceptances")
    _sql("DROP TABLE IF EXISTS legal_document_translations")
    _sql("DROP TABLE IF EXISTS legal_documents")
    _sql("DROP TABLE IF EXISTS oauth_states")
    _sql("DROP TABLE IF EXISTS auth_sessions")
    _sql("DROP TABLE IF EXISTS users")
    # Keep roles/extension â€” may be shared across environments
