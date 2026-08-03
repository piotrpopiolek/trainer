"""Stage 2 Slice A: client_mutations depends_on/result_status + conflict kind.

Revision ID: 20260803_0005
Revises: 20260731_0004
Create Date: 2026-08-03
"""

from __future__ import annotations

from alembic import op

revision = "20260803_0005"
down_revision = "20260731_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE client_mutations
          ADD COLUMN IF NOT EXISTS depends_on JSONB NOT NULL
            DEFAULT jsonb_build_object(
              'schema_version', 1,
              'mutation_ids', '[]'::jsonb
            )
        """
    )
    op.execute(
        """
        ALTER TABLE client_mutations
          ADD COLUMN IF NOT EXISTS result_status TEXT NOT NULL DEFAULT 'applied'
        """
    )
    op.execute(
        """
        ALTER TABLE client_mutations
          DROP CONSTRAINT IF EXISTS ck_client_mutations_result_status
        """
    )
    op.execute(
        """
        ALTER TABLE client_mutations
          ADD CONSTRAINT ck_client_mutations_result_status
          CHECK (result_status IN ('applied','applied_detached'))
        """
    )
    op.execute(
        """
        ALTER TABLE client_mutations
          DROP CONSTRAINT IF EXISTS ck_client_mutations_depends_on_schema
        """
    )
    op.execute(
        """
        ALTER TABLE client_mutations
          ADD CONSTRAINT ck_client_mutations_depends_on_schema
          CHECK (
            (depends_on ? 'schema_version')
            AND (depends_on ? 'mutation_ids')
          )
        """
    )

    op.execute(
        """
        ALTER TABLE sync_conflict_logs
          DROP CONSTRAINT IF EXISTS ck_sync_conflict_logs_kind
        """
    )
    op.execute(
        """
        ALTER TABLE sync_conflict_logs
          ADD CONSTRAINT ck_sync_conflict_logs_kind
          CHECK (
            conflict_kind IN (
              'lost_push',
              'tie_revision',
              'session_immutable_after_evaluate',
              'session_date_immutable',
              'satellite_config_activation_lost'
            )
          )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE sync_conflict_logs
          DROP CONSTRAINT IF EXISTS ck_sync_conflict_logs_kind
        """
    )
    op.execute(
        """
        ALTER TABLE sync_conflict_logs
          ADD CONSTRAINT ck_sync_conflict_logs_kind
          CHECK (
            conflict_kind IN (
              'lost_push',
              'tie_revision',
              'session_immutable_after_evaluate',
              'session_date_immutable'
            )
          )
        """
    )
    op.execute(
        """
        ALTER TABLE client_mutations
          DROP CONSTRAINT IF EXISTS ck_client_mutations_depends_on_schema
        """
    )
    op.execute(
        """
        ALTER TABLE client_mutations
          DROP CONSTRAINT IF EXISTS ck_client_mutations_result_status
        """
    )
    op.execute("ALTER TABLE client_mutations DROP COLUMN IF EXISTS result_status")
    op.execute("ALTER TABLE client_mutations DROP COLUMN IF EXISTS depends_on")
