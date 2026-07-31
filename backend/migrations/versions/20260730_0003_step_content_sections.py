"""Add execution/rationale/technique on exercise_step_translations (FR-020a).

Revision ID: 20260730_0003
Revises: 20260726_0002
Create Date: 2026-07-30
"""

from __future__ import annotations

from alembic import op

revision = "20260730_0003"
down_revision = "20260726_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE exercise_step_translations
          ADD COLUMN IF NOT EXISTS execution TEXT NOT NULL DEFAULT '',
          ADD COLUMN IF NOT EXISTS rationale TEXT NOT NULL DEFAULT '',
          ADD COLUMN IF NOT EXISTS technique TEXT NOT NULL DEFAULT ''
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE exercise_step_translations
          DROP COLUMN IF EXISTS technique,
          DROP COLUMN IF EXISTS rationale,
          DROP COLUMN IF EXISTS execution
        """
    )
