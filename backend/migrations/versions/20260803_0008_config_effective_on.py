"""Stage 4 Slice A: exercises.config_effective_on for pending satellite config.

Revision ID: 20260803_0008
Revises: 20260803_0007
Create Date: 2026-08-03
"""

from __future__ import annotations

from alembic import op

revision = "20260803_0008"
down_revision = "20260803_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE exercises
          ADD COLUMN IF NOT EXISTS config_effective_on DATE NULL
        """
    )
    op.execute(
        """
        ALTER TABLE exercises
          DROP CONSTRAINT IF EXISTS ck_exercises_pending_effective_pair
        """
    )
    op.execute(
        """
        ALTER TABLE exercises
          ADD CONSTRAINT ck_exercises_pending_effective_pair
          CHECK (
            (pending_config_version_id IS NULL AND config_effective_on IS NULL)
            OR (pending_config_version_id IS NOT NULL AND config_effective_on IS NOT NULL)
          )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE exercises
          DROP CONSTRAINT IF EXISTS ck_exercises_pending_effective_pair
        """
    )
    op.execute("ALTER TABLE exercises DROP COLUMN IF EXISTS config_effective_on")
