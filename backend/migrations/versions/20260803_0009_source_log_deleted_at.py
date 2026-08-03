"""Stage 4 Slice C: source_log_deleted_at on satellite daily outcomes.

Revision ID: 20260803_0009
Revises: 20260803_0008
Create Date: 2026-08-03
"""

from __future__ import annotations

from alembic import op

revision = "20260803_0009"
down_revision = "20260803_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE satellite_daily_outcomes
          ADD COLUMN IF NOT EXISTS source_log_deleted_at TIMESTAMPTZ NULL
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE satellite_daily_outcomes DROP COLUMN IF EXISTS source_log_deleted_at"
    )
