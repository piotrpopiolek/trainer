"""Stage 3 Slice D: progress_revision CAS for satellite regression decisions.

Revision ID: 20260803_0007
Revises: 20260803_0006
Create Date: 2026-08-03
"""

from __future__ import annotations

from alembic import op

revision = "20260803_0007"
down_revision = "20260803_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE user_exercise_progress
          ADD COLUMN IF NOT EXISTS progress_revision INT NOT NULL DEFAULT 0
        """
    )
    op.execute(
        """
        ALTER TABLE user_exercise_progress
          DROP CONSTRAINT IF EXISTS ck_user_exercise_progress_revision
        """
    )
    op.execute(
        """
        ALTER TABLE user_exercise_progress
          ADD CONSTRAINT ck_user_exercise_progress_revision
          CHECK (progress_revision >= 0)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
          uq_satellite_regression_recommendations_trigger
          ON satellite_regression_recommendations (trigger_outcome_id)
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS uq_satellite_regression_recommendations_trigger"
    )
    op.execute(
        """
        ALTER TABLE user_exercise_progress
          DROP CONSTRAINT IF EXISTS ck_user_exercise_progress_revision
        """
    )
    op.execute(
        """
        ALTER TABLE user_exercise_progress
          DROP COLUMN IF EXISTS progress_revision
        """
    )
