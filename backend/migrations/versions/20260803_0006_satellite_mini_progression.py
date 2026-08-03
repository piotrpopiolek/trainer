"""Stage 3 Slice A: mini-progression tables + current_step_id + satellite event types.

Revision ID: 20260803_0006
Revises: 20260803_0005
Create Date: 2026-08-03
"""

from __future__ import annotations

from alembic import op

revision = "20260803_0006"
down_revision = "20260803_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE user_exercise_progress
          ADD COLUMN IF NOT EXISTS current_step_id UUID NULL
        """
    )
    # Backfill satellite progress → step 1 (dev/CI DBs may already have goal-only rows).
    op.execute(
        """
        UPDATE user_exercise_progress AS uep
           SET current_step_id = es.id
          FROM exercises AS e
          JOIN exercise_steps AS es
            ON es.exercise_id = e.id
           AND es.step_number = 1
         WHERE uep.exercise_id = e.id
           AND e.kind = 'satellite'
           AND uep.current_step_id IS NULL
        """
    )
    op.execute(
        """
        ALTER TABLE user_exercise_progress
          DROP CONSTRAINT IF EXISTS fk_progress_current_step
        """
    )
    op.execute(
        """
        ALTER TABLE user_exercise_progress
          ADD CONSTRAINT fk_progress_current_step
          FOREIGN KEY (current_step_id)
          REFERENCES exercise_steps(id)
          ON DELETE RESTRICT
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
            'satellite_regress_confirmed','satellite_config_reset'
          ))
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS satellite_daily_outcomes (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL
            REFERENCES users(id) ON DELETE RESTRICT,
          exercise_id UUID NOT NULL
            REFERENCES exercises(id) ON DELETE RESTRICT,
          local_date DATE NOT NULL,
          step_id UUID NOT NULL
            REFERENCES exercise_steps(id) ON DELETE RESTRICT,
          config_version_id UUID NOT NULL
            REFERENCES satellite_config_versions(id) ON DELETE RESTRICT,
          has_attempt BOOLEAN NOT NULL DEFAULT false,
          has_success BOOLEAN NOT NULL DEFAULT false,
          status TEXT NOT NULL,
          result TEXT NULL,
          representative_log_id UUID NULL
            REFERENCES session_exercise_logs(id) ON DELETE SET NULL,
          result_snapshot JSONB NULL,
          applied_progress_revision INT NULL,
          finalize_after TIMESTAMPTZ NULL,
          finalized_at TIMESTAMPTZ NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT uq_satellite_daily_outcomes_user_ex_date
            UNIQUE (user_id, exercise_id, local_date),
          CONSTRAINT ck_satellite_daily_outcomes_status
            CHECK (status IN ('pending','finalized','cancelled')),
          CONSTRAINT ck_satellite_daily_outcomes_result
            CHECK (result IS NULL OR result IN ('success','failure')),
          CONSTRAINT ck_satellite_daily_outcomes_result_snapshot
            CHECK (
              result_snapshot IS NULL
              OR (result_snapshot ? 'schema_version')
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_satellite_daily_outcomes_pending_finalize
          ON satellite_daily_outcomes (status, finalize_after)
          WHERE status = 'pending'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_satellite_daily_outcomes_user_exercise
          ON satellite_daily_outcomes (user_id, exercise_id, local_date DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS satellite_regression_recommendations (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL
            REFERENCES users(id) ON DELETE RESTRICT,
          exercise_id UUID NOT NULL
            REFERENCES exercises(id) ON DELETE RESTRICT,
          trigger_outcome_id UUID NOT NULL
            REFERENCES satellite_daily_outcomes(id) ON DELETE RESTRICT,
          config_version_id UUID NOT NULL
            REFERENCES satellite_config_versions(id) ON DELETE RESTRICT,
          from_step_id UUID NOT NULL
            REFERENCES exercise_steps(id) ON DELETE RESTRICT,
          to_step_id UUID NOT NULL
            REFERENCES exercise_steps(id) ON DELETE RESTRICT,
          expected_progress_revision INT NOT NULL,
          status TEXT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          decided_at TIMESTAMPTZ NULL,
          CONSTRAINT ck_satellite_regression_recommendations_status
            CHECK (status IN (
              'pending','accepted','declined','cancelled','stale'
            ))
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
          uq_satellite_regression_recommendations_pending
          ON satellite_regression_recommendations (user_id, exercise_id)
          WHERE status = 'pending'
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS satellite_regression_recommendations")
    op.execute("DROP TABLE IF EXISTS satellite_daily_outcomes")
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
            'advance','regress','manual_override','initial'
          ))
        """
    )
    op.execute(
        """
        ALTER TABLE user_exercise_progress
          DROP CONSTRAINT IF EXISTS fk_progress_current_step
        """
    )
    op.execute(
        """
        ALTER TABLE user_exercise_progress
          DROP COLUMN IF EXISTS current_step_id
        """
    )
