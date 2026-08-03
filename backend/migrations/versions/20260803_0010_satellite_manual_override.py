"""Stage 4 Slice D: related_outcome_id + satellite_manual_override.

Revision ID: 20260803_0010
Revises: 20260803_0009
Create Date: 2026-08-03
"""

from __future__ import annotations

from alembic import op

revision = "20260803_0010"
down_revision = "20260803_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE progression_events
          ADD COLUMN IF NOT EXISTS related_outcome_id UUID NULL
          REFERENCES satellite_daily_outcomes(id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        ALTER TABLE progression_events
          DROP CONSTRAINT IF EXISTS ck_progression_events_type
        """
    )
    op.execute(
        """
        ALTER TABLE progression_events
          ADD CONSTRAINT ck_progression_events_type
          CHECK (event_type IN (
            'advance','regress','manual_override','initial',
            'satellite_advance','satellite_regress_suggested',
            'satellite_regress_confirmed','satellite_config_reset',
            'satellite_manual_override'
          ))
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE progression_events
          DROP CONSTRAINT IF EXISTS ck_progression_events_type
        """
    )
    op.execute(
        """
        ALTER TABLE progression_events
          ADD CONSTRAINT ck_progression_events_type
          CHECK (event_type IN (
            'advance','regress','manual_override','initial',
            'satellite_advance','satellite_regress_suggested',
            'satellite_regress_confirmed','satellite_config_reset'
          ))
        """
    )
    op.execute(
        """
        ALTER TABLE progression_events
          DROP COLUMN IF EXISTS related_outcome_id
        """
    )
