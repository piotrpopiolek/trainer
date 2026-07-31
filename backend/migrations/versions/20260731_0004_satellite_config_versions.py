"""Satellite config versions + log refs + satellite_v1 schema (Stage 1).

Revision ID: 20260731_0004
Revises: 20260730_0003
Create Date: 2026-07-31
"""

from __future__ import annotations

from alembic import op

revision = "20260731_0004"
down_revision = "20260730_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Greenfield: drop any pre-release satellite rows before NOT NULL pointers.
    op.execute(
        """
        DELETE FROM session_exercise_logs
         WHERE exercise_id IN (SELECT id FROM exercises WHERE kind = 'satellite')
        """
    )
    op.execute(
        """
        DELETE FROM progression_events
         WHERE exercise_id IN (SELECT id FROM exercises WHERE kind = 'satellite')
        """
    )
    op.execute(
        """
        DELETE FROM user_exercise_progress
         WHERE exercise_id IN (SELECT id FROM exercises WHERE kind = 'satellite')
        """
    )
    op.execute(
        """
        DELETE FROM exercise_steps
         WHERE exercise_id IN (SELECT id FROM exercises WHERE kind = 'satellite')
        """
    )
    op.execute("DELETE FROM exercises WHERE kind = 'satellite'")
    op.execute(
        """
        INSERT INTO progression_schemas (id, slug, schema_version, created_at)
        SELECT '01920000-0000-7000-8000-0000000000a1'::uuid, 'satellite_v1', 1, now()
        WHERE NOT EXISTS (
          SELECT 1 FROM progression_schemas WHERE slug = 'satellite_v1'
        )
        """
    )
    op.execute(
        """
        CREATE TABLE satellite_config_versions (
          id UUID PRIMARY KEY,
          exercise_id UUID NOT NULL REFERENCES exercises(id) ON DELETE RESTRICT,
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
          authored_revision INT NOT NULL CHECK (authored_revision >= 1),
          schema_version INT NOT NULL DEFAULT 1 CHECK (schema_version >= 1),
          document JSONB NOT NULL CHECK (document ? 'schema_version'),
          config_hash BYTEA NOT NULL CHECK (octet_length(config_hash) = 32),
          registered_by_mutation_id UUID NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (exercise_id, id),
          UNIQUE (user_id, registered_by_mutation_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sat_config_exercise_hash
          ON satellite_config_versions (exercise_id, config_hash)
        """
    )
    op.execute(
        """
        CREATE TABLE satellite_config_activations (
          id UUID PRIMARY KEY,
          exercise_id UUID NOT NULL REFERENCES exercises(id) ON DELETE RESTRICT,
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
          config_version_id UUID NOT NULL
            REFERENCES satellite_config_versions(id) ON DELETE RESTRICT,
          effective_from_local_date DATE NOT NULL,
          effective_until_local_date DATE NULL,
          activated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          superseded_by_activation_id UUID NULL
            REFERENCES satellite_config_activations(id) ON DELETE RESTRICT,
          UNIQUE (exercise_id, effective_from_local_date)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_sat_activation_lookup
          ON satellite_config_activations
            (exercise_id, config_version_id, effective_from_local_date)
        """
    )
    op.execute(
        "ALTER TABLE exercises ADD COLUMN IF NOT EXISTS current_config_version_id UUID NULL"
    )
    op.execute(
        "ALTER TABLE exercises ADD COLUMN IF NOT EXISTS pending_config_version_id UUID NULL"
    )
    op.execute(
        """
        ALTER TABLE exercises
          ADD CONSTRAINT fk_exercises_current_config_version
            FOREIGN KEY (current_config_version_id)
            REFERENCES satellite_config_versions(id)
            ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
        """
    )
    op.execute(
        """
        ALTER TABLE exercises
          ADD CONSTRAINT fk_exercises_pending_config_version
            FOREIGN KEY (pending_config_version_id)
            REFERENCES satellite_config_versions(id)
            ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED
        """
    )
    op.execute(
        """
        ALTER TABLE exercises
          ADD CONSTRAINT ck_exercises_satellite_config_required
          CHECK (
            kind <> 'satellite'
            OR deleted_at IS NOT NULL
            OR current_config_version_id IS NOT NULL
          )
        """
    )
    op.execute(
        """
        ALTER TABLE session_exercise_logs
          ADD COLUMN IF NOT EXISTS progression_skipped TEXT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE session_exercise_logs
          ADD COLUMN IF NOT EXISTS satellite_config_version_id UUID NULL
            REFERENCES satellite_config_versions(id) ON DELETE RESTRICT
        """
    )
    op.execute(
        """
        ALTER TABLE session_exercise_logs
          ADD COLUMN IF NOT EXISTS satellite_config_hash BYTEA NULL
        """
    )
    op.execute(
        """
        ALTER TABLE session_exercise_logs
          ADD CONSTRAINT ck_session_logs_satellite_config
          CHECK (
            (exercise_kind = 'satellite'
              AND satellite_config_version_id IS NOT NULL
              AND satellite_config_hash IS NOT NULL
              AND octet_length(satellite_config_hash) = 32)
            OR
            (exercise_kind = 'cc'
              AND satellite_config_version_id IS NULL
              AND satellite_config_hash IS NULL)
          )
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE session_exercise_logs DROP CONSTRAINT IF EXISTS ck_session_logs_satellite_config"
    )
    op.execute(
        "ALTER TABLE session_exercise_logs DROP COLUMN IF EXISTS satellite_config_hash"
    )
    op.execute(
        "ALTER TABLE session_exercise_logs DROP COLUMN IF EXISTS satellite_config_version_id"
    )
    op.execute(
        "ALTER TABLE session_exercise_logs DROP COLUMN IF EXISTS progression_skipped"
    )
    op.execute(
        "ALTER TABLE exercises DROP CONSTRAINT IF EXISTS ck_exercises_satellite_config_required"
    )
    op.execute(
        "ALTER TABLE exercises DROP CONSTRAINT IF EXISTS fk_exercises_pending_config_version"
    )
    op.execute(
        "ALTER TABLE exercises DROP CONSTRAINT IF EXISTS fk_exercises_current_config_version"
    )
    op.execute("ALTER TABLE exercises DROP COLUMN IF EXISTS pending_config_version_id")
    op.execute("ALTER TABLE exercises DROP COLUMN IF EXISTS current_config_version_id")
    op.execute("DROP TABLE IF EXISTS satellite_config_activations")
    op.execute("DROP TABLE IF EXISTS satellite_config_versions")
    op.execute("DELETE FROM progression_schemas WHERE slug = 'satellite_v1'")
