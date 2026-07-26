"""db-catalog-sync: CC catalog, sessions/logs, progression, sync, triggers.

Revision ID: 20260726_0002
Revises: 20260726_0001
Create Date: 2026-07-26
"""

from __future__ import annotations

from alembic import op

revision = "20260726_0002"
down_revision = "20260726_0001"
branch_labels = None
depends_on = None


def _sql(statement: str) -> None:
    op.get_bind().exec_driver_sql(statement)


def upgrade() -> None:
    # --- programs / translations / days ---
    _sql(
        """
        CREATE TABLE programs (
          id UUID PRIMARY KEY,
          slug TEXT NOT NULL,
          is_system BOOLEAN NOT NULL DEFAULT true,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT uq_programs_slug UNIQUE (slug)
        )
        """
    )
    _sql(
        """
        CREATE TABLE program_translations (
          program_id UUID NOT NULL
            REFERENCES programs(id) ON DELETE CASCADE,
          locale TEXT NOT NULL,
          name TEXT NOT NULL,
          description TEXT,
          catalog_version INT NOT NULL DEFAULT 1,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY (program_id, locale),
          CONSTRAINT ck_program_translations_locale_len
            CHECK (char_length(locale) BETWEEN 2 AND 35),
          CONSTRAINT ck_program_translations_catalog_version
            CHECK (catalog_version >= 1)
        )
        """
    )
    _sql(
        """
        CREATE TABLE program_days (
          id UUID PRIMARY KEY,
          program_id UUID NOT NULL
            REFERENCES programs(id) ON DELETE RESTRICT,
          day_index SMALLINT NOT NULL,
          sort_order SMALLINT NOT NULL DEFAULT 0,
          CONSTRAINT ck_program_days_day_index
            CHECK (day_index BETWEEN 1 AND 3),
          CONSTRAINT uq_program_days_program_day_index
            UNIQUE (program_id, day_index)
        )
        """
    )
    _sql(
        """
        CREATE TABLE program_day_translations (
          program_day_id UUID NOT NULL
            REFERENCES program_days(id) ON DELETE CASCADE,
          locale TEXT NOT NULL,
          name TEXT NOT NULL,
          PRIMARY KEY (program_day_id, locale),
          CONSTRAINT ck_program_day_translations_locale_len
            CHECK (char_length(locale) BETWEEN 2 AND 35)
        )
        """
    )

    # --- progression_schemas (before exercise_steps) ---
    _sql(
        """
        CREATE TABLE progression_schemas (
          id UUID PRIMARY KEY,
          slug TEXT NOT NULL,
          schema_version INT NOT NULL,
          description TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT uq_progression_schemas_slug_version
            UNIQUE (slug, schema_version)
        )
        """
    )

    # --- exercises ---
    _sql(
        """
        CREATE TABLE exercises (
          id UUID PRIMARY KEY,
          user_id UUID REFERENCES users(id) ON DELETE RESTRICT,
          program_id UUID REFERENCES programs(id) ON DELETE RESTRICT,
          slug TEXT,
          name TEXT,
          kind TEXT NOT NULL,
          exercise_type TEXT NOT NULL,
          description TEXT,
          active_metrics JSONB NOT NULL DEFAULT
            $json${"schema_version":1,"metrics":["reps"]}$json$::jsonb,
          equipment TEXT[] NOT NULL DEFAULT '{}',
          tags TEXT[] NOT NULL DEFAULT '{}',
          schedule_kind TEXT,
          weekdays SMALLINT[],
          schedule_category TEXT,
          cloned_from_exercise_id UUID
            REFERENCES exercises(id) ON DELETE SET NULL,
          client_mutation_id UUID,
          revision INT NOT NULL DEFAULT 1,
          client_updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          deleted_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT ck_exercises_kind CHECK (kind IN ('cc','satellite')),
          CONSTRAINT ck_exercises_exercise_type
            CHECK (exercise_type IN ('A','B','C')),
          CONSTRAINT ck_exercises_schedule_kind
            CHECK (
              schedule_kind IS NULL
              OR schedule_kind IN ('daily','weekdays','category')
            ),
          CONSTRAINT ck_exercises_schedule_category
            CHECK (
              schedule_category IS NULL
              OR schedule_category IN ('anytime','post_workout','rest_day')
            ),
          CONSTRAINT ck_exercises_active_metrics_schema CHECK (
            (active_metrics ? 'schema_version')
          ),
          CONSTRAINT ck_exercises_revision CHECK (revision >= 1),
          CONSTRAINT ck_exercises_cc CHECK (
            kind <> 'cc'
            OR (
              user_id IS NULL
              AND program_id IS NOT NULL
              AND name IS NULL
              AND description IS NULL
              AND schedule_kind IS NULL
              AND client_mutation_id IS NULL
            )
          ),
          CONSTRAINT ck_exercises_satellite CHECK (
            kind <> 'satellite'
            OR (
              user_id IS NOT NULL
              AND name IS NOT NULL
              AND schedule_kind IS NOT NULL
              AND client_mutation_id IS NOT NULL
            )
          ),
          CONSTRAINT ck_exercises_schedule_weekdays CHECK (
            schedule_kind IS DISTINCT FROM 'weekdays'
            OR (weekdays IS NOT NULL AND cardinality(weekdays) > 0)
          ),
          CONSTRAINT ck_exercises_schedule_category_req CHECK (
            schedule_kind IS DISTINCT FROM 'category'
            OR schedule_category IS NOT NULL
          ),
          CONSTRAINT ck_exercises_schedule_daily CHECK (
            schedule_kind IS DISTINCT FROM 'daily'
            OR (weekdays IS NULL AND schedule_category IS NULL)
          )
        )
        """
    )
    _sql(
        """
        CREATE UNIQUE INDEX uq_exercises_cc_slug_active
          ON exercises (slug)
          WHERE kind = 'cc' AND deleted_at IS NULL
        """
    )
    _sql(
        """
        CREATE UNIQUE INDEX uq_exercises_satellite_client_mutation
          ON exercises (user_id, client_mutation_id)
          WHERE kind = 'satellite' AND client_mutation_id IS NOT NULL
        """
    )
    _sql(
        """
        CREATE INDEX ix_exercises_user_satellite_active
          ON exercises (user_id)
          WHERE kind = 'satellite' AND deleted_at IS NULL
        """
    )
    _sql(
        """
        CREATE INDEX ix_exercises_user_updated_at_satellite_active
          ON exercises (user_id, updated_at)
          WHERE kind = 'satellite' AND deleted_at IS NULL
        """
    )

    _sql(
        """
        CREATE TABLE exercise_translations (
          exercise_id UUID NOT NULL
            REFERENCES exercises(id) ON DELETE CASCADE,
          locale TEXT NOT NULL,
          name TEXT NOT NULL,
          description TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY (exercise_id, locale),
          CONSTRAINT ck_exercise_translations_locale_len
            CHECK (char_length(locale) BETWEEN 2 AND 35)
        )
        """
    )

    _sql(
        """
        CREATE TABLE program_day_exercises (
          id UUID PRIMARY KEY,
          program_day_id UUID NOT NULL
            REFERENCES program_days(id) ON DELETE CASCADE,
          exercise_id UUID NOT NULL
            REFERENCES exercises(id) ON DELETE RESTRICT,
          sort_order SMALLINT NOT NULL DEFAULT 0,
          CONSTRAINT uq_program_day_exercises_day_exercise
            UNIQUE (program_day_id, exercise_id)
        )
        """
    )
    _sql(
        """
        CREATE INDEX ix_program_day_exercises_day_sort
          ON program_day_exercises (program_day_id, sort_order)
        """
    )

    _sql(
        """
        CREATE TABLE exercise_steps (
          id UUID PRIMARY KEY,
          exercise_id UUID NOT NULL
            REFERENCES exercises(id) ON DELETE CASCADE,
          step_number SMALLINT NOT NULL,
          name TEXT,
          description TEXT,
          rules JSONB NOT NULL,
          progression_schema_id UUID NOT NULL
            REFERENCES progression_schemas(id) ON DELETE RESTRICT,
          sort_order SMALLINT NOT NULL DEFAULT 0,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT ck_exercise_steps_step_number CHECK (step_number >= 1),
          CONSTRAINT ck_exercise_steps_rules_schema CHECK (
            (rules ? 'schema_version')
            AND (rules->>'schema_version')::int >= 1
          ),
          CONSTRAINT uq_exercise_steps_exercise_step
            UNIQUE (exercise_id, step_number)
        )
        """
    )
    _sql(
        """
        CREATE INDEX ix_exercise_steps_exercise_step_number
          ON exercise_steps (exercise_id, step_number)
        """
    )

    _sql(
        """
        CREATE TABLE exercise_step_translations (
          exercise_step_id UUID NOT NULL
            REFERENCES exercise_steps(id) ON DELETE CASCADE,
          locale TEXT NOT NULL,
          name TEXT NOT NULL,
          description TEXT NOT NULL,
          content_status TEXT NOT NULL DEFAULT 'draft',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY (exercise_step_id, locale),
          CONSTRAINT ck_exercise_step_translations_locale_len
            CHECK (char_length(locale) BETWEEN 2 AND 35),
          CONSTRAINT ck_exercise_step_translations_content_status
            CHECK (content_status IN ('draft','ready'))
        )
        """
    )

    # --- enrollments / progress / sessions ---
    _sql(
        """
        CREATE TABLE user_program_enrollments (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL
            REFERENCES users(id) ON DELETE RESTRICT,
          program_id UUID NOT NULL
            REFERENCES programs(id) ON DELETE RESTRICT,
          started_on DATE NOT NULL,
          anchor_weekday SMALLINT NOT NULL DEFAULT 1,
          pending_anchor_weekday SMALLINT,
          schedule_effective_on DATE,
          rotation_offset SMALLINT NOT NULL DEFAULT 0,
          is_active BOOLEAN NOT NULL DEFAULT true,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT ck_enrollments_anchor_weekday
            CHECK (anchor_weekday BETWEEN 1 AND 7),
          CONSTRAINT ck_enrollments_pending_anchor
            CHECK (
              pending_anchor_weekday IS NULL
              OR pending_anchor_weekday BETWEEN 1 AND 7
            ),
          CONSTRAINT ck_enrollments_rotation_offset
            CHECK (rotation_offset BETWEEN 0 AND 2)
        )
        """
    )
    _sql(
        """
        CREATE UNIQUE INDEX uq_user_program_enrollments_one_active
          ON user_program_enrollments (user_id)
          WHERE is_active = true
        """
    )

    _sql(
        """
        CREATE TABLE user_exercise_progress (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL
            REFERENCES users(id) ON DELETE RESTRICT,
          exercise_id UUID NOT NULL
            REFERENCES exercises(id) ON DELETE RESTRICT,
          current_step_number SMALLINT NOT NULL,
          fail_streak INT NOT NULL DEFAULT 0,
          last_session_at TIMESTAMPTZ,
          is_active BOOLEAN NOT NULL DEFAULT true,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT ck_progress_current_step CHECK (current_step_number >= 1),
          CONSTRAINT ck_progress_fail_streak CHECK (fail_streak >= 0),
          CONSTRAINT uq_user_exercise_progress_user_exercise
            UNIQUE (user_id, exercise_id)
        )
        """
    )
    _sql(
        """
        CREATE INDEX ix_user_exercise_progress_user_updated_at
          ON user_exercise_progress (user_id, updated_at)
        """
    )

    _sql(
        """
        CREATE TABLE workout_sessions (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL
            REFERENCES users(id) ON DELETE RESTRICT,
          performed_at TIMESTAMPTZ NOT NULL,
          local_date DATE NOT NULL,
          notes TEXT,
          client_mutation_id UUID NOT NULL,
          revision INT NOT NULL DEFAULT 1,
          client_updated_at TIMESTAMPTZ NOT NULL,
          deleted_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT ck_workout_sessions_notes_len
            CHECK (notes IS NULL OR char_length(notes) <= 2000),
          CONSTRAINT ck_workout_sessions_revision CHECK (revision >= 1),
          CONSTRAINT uq_workout_sessions_user_client_mutation
            UNIQUE (user_id, client_mutation_id),
          CONSTRAINT uq_workout_sessions_id_user UNIQUE (id, user_id)
        )
        """
    )
    _sql(
        """
        CREATE INDEX ix_workout_sessions_user_performed_at_active
          ON workout_sessions (user_id, performed_at DESC)
          WHERE deleted_at IS NULL
        """
    )
    _sql(
        """
        CREATE INDEX ix_workout_sessions_user_local_date_active
          ON workout_sessions (user_id, local_date, performed_at)
          WHERE deleted_at IS NULL
        """
    )
    _sql(
        """
        CREATE INDEX ix_workout_sessions_user_updated_at
          ON workout_sessions (user_id, updated_at)
        """
    )

    _sql(
        """
        CREATE TABLE session_exercise_logs (
          id UUID PRIMARY KEY,
          session_id UUID NOT NULL,
          user_id UUID NOT NULL
            REFERENCES users(id) ON DELETE RESTRICT,
          exercise_id UUID NOT NULL
            REFERENCES exercises(id) ON DELETE RESTRICT,
          exercise_kind TEXT NOT NULL,
          section TEXT NOT NULL,
          step_number SMALLINT,
          local_date DATE NOT NULL,
          performed_at TIMESTAMPTZ NOT NULL,
          content_locale TEXT NOT NULL DEFAULT 'pl-PL',
          exercise_name_snapshot TEXT NOT NULL,
          step_label_snapshot TEXT,
          skipped BOOLEAN NOT NULL DEFAULT false,
          sets JSONB,
          rules_snapshot JSONB,
          progression_schema_version INT,
          goal_met BOOLEAN NOT NULL DEFAULT false,
          goal_evaluated_at TIMESTAMPTZ,
          counts_for_progression BOOLEAN NOT NULL DEFAULT true,
          notes TEXT,
          sort_order SMALLINT NOT NULL DEFAULT 0,
          client_mutation_id UUID,
          revision INT NOT NULL DEFAULT 1,
          client_updated_at TIMESTAMPTZ NOT NULL,
          superseded_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT ck_session_logs_exercise_kind
            CHECK (exercise_kind IN ('cc','satellite')),
          CONSTRAINT ck_session_logs_section
            CHECK (section IN ('main','accessories')),
          CONSTRAINT ck_session_logs_notes_len
            CHECK (notes IS NULL OR char_length(notes) <= 1000),
          CONSTRAINT ck_session_logs_revision CHECK (revision >= 1),
          CONSTRAINT ck_session_logs_progression_schema_version
            CHECK (
              progression_schema_version IS NULL
              OR progression_schema_version >= 1
            ),
          CONSTRAINT ck_session_logs_skipped_true CHECK (
            skipped = false
            OR (
              sets IS NULL
              AND goal_met = false
              AND rules_snapshot IS NULL
              AND progression_schema_version IS NULL
            )
          ),
          CONSTRAINT ck_session_logs_skipped_false CHECK (
            skipped = true
            OR (
              sets IS NOT NULL
              AND (sets ? 'schema_version')
              AND rules_snapshot IS NOT NULL
              AND (rules_snapshot ? 'schema_version')
              AND progression_schema_version IS NOT NULL
            )
          ),
          CONSTRAINT fk_session_logs_session_user
            FOREIGN KEY (session_id, user_id)
            REFERENCES workout_sessions (id, user_id)
            ON DELETE CASCADE
        )
        """
    )
    _sql(
        """
        CREATE UNIQUE INDEX uq_session_logs_client_mutation
          ON session_exercise_logs (user_id, client_mutation_id)
          WHERE client_mutation_id IS NOT NULL
        """
    )
    _sql(
        """
        CREATE UNIQUE INDEX uq_session_logs_cc_one_active_per_day
          ON session_exercise_logs (user_id, exercise_id, local_date)
          WHERE exercise_kind = 'cc'
            AND skipped = false
            AND superseded_at IS NULL
        """
    )
    _sql(
        """
        CREATE INDEX ix_session_logs_session_sort
          ON session_exercise_logs (session_id, sort_order)
        """
    )
    _sql(
        """
        CREATE INDEX ix_session_logs_progression_tip
          ON session_exercise_logs (
            user_id, exercise_id, local_date ASC, performed_at ASC, id ASC
          )
          WHERE exercise_kind = 'cc'
            AND skipped = false
            AND superseded_at IS NULL
            AND counts_for_progression = true
        """
    )
    _sql(
        """
        CREATE INDEX ix_session_logs_user_updated_at
          ON session_exercise_logs (user_id, updated_at)
        """
    )

    _sql(
        """
        CREATE TABLE progression_events (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL
            REFERENCES users(id) ON DELETE RESTRICT,
          exercise_id UUID NOT NULL
            REFERENCES exercises(id) ON DELETE RESTRICT,
          session_id UUID
            REFERENCES workout_sessions(id) ON DELETE SET NULL,
          event_type TEXT NOT NULL,
          from_step SMALLINT NOT NULL,
          to_step SMALLINT NOT NULL,
          reason TEXT,
          rules_snapshot JSONB,
          progression_schema_version INT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT ck_progression_events_type
            CHECK (event_type IN (
              'advance','regress','manual_override','initial'
            )),
          CONSTRAINT ck_progression_events_rules_snapshot
            CHECK (
              rules_snapshot IS NULL
              OR (rules_snapshot ? 'schema_version')
            )
        )
        """
    )
    _sql(
        """
        CREATE INDEX ix_progression_events_user_created_at
          ON progression_events (user_id, created_at DESC)
        """
    )
    _sql(
        """
        CREATE INDEX ix_progression_events_user_exercise_created_at
          ON progression_events (user_id, exercise_id, created_at DESC)
        """
    )

    # --- sync / rate limit ---
    _sql(
        """
        CREATE TABLE sync_conflict_logs (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL
            REFERENCES users(id) ON DELETE RESTRICT,
          entity_type TEXT NOT NULL,
          entity_id UUID NOT NULL,
          winning_revision INT NOT NULL,
          losing_revision INT NOT NULL,
          winning_updated_at TIMESTAMPTZ NOT NULL,
          conflict_kind TEXT NOT NULL,
          losing_payload JSONB NOT NULL,
          device_id TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT ck_sync_conflict_logs_kind CHECK (
            conflict_kind IN (
              'lost_push',
              'tie_revision',
              'session_immutable_after_evaluate',
              'session_date_immutable'
            )
          ),
          CONSTRAINT ck_sync_conflict_logs_payload_schema CHECK (
            (losing_payload ? 'schema_version')
          )
        )
        """
    )
    _sql(
        """
        CREATE INDEX ix_sync_conflict_logs_user_created_at
          ON sync_conflict_logs (user_id, created_at DESC)
        """
    )

    _sql(
        """
        CREATE TABLE sync_devices (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL
            REFERENCES users(id) ON DELETE RESTRICT,
          device_id TEXT NOT NULL,
          last_pull_at TIMESTAMPTZ,
          last_push_at TIMESTAMPTZ,
          user_agent TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT uq_sync_devices_user_device
            UNIQUE (user_id, device_id)
        )
        """
    )

    _sql(
        """
        CREATE TABLE client_mutations (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL
            REFERENCES users(id) ON DELETE RESTRICT,
          client_mutation_id UUID NOT NULL,
          entity_type TEXT NOT NULL,
          entity_id UUID NOT NULL,
          content_hash TEXT,
          processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT uq_client_mutations_user_mutation
            UNIQUE (user_id, client_mutation_id)
        )
        """
    )

    _sql(
        """
        CREATE TABLE rate_limit_buckets (
          bucket_key TEXT NOT NULL,
          window_start TIMESTAMPTZ NOT NULL,
          count INT NOT NULL DEFAULT 1,
          PRIMARY KEY (bucket_key, window_start),
          CONSTRAINT ck_rate_limit_buckets_count CHECK (count >= 0)
        )
        """
    )

    # --- triggers ---
    _sql(
        """
        CREATE OR REPLACE FUNCTION trg_satellite_limit_fn()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $fn$
        DECLARE
          cnt int;
        BEGIN
          IF NEW.kind = 'satellite' AND NEW.deleted_at IS NULL THEN
            PERFORM pg_advisory_xact_lock(
              hashtextextended('sat-limit:' || NEW.user_id::text, 0)
            );
            SELECT COUNT(*) INTO cnt
            FROM exercises
            WHERE user_id = NEW.user_id
              AND kind = 'satellite'
              AND deleted_at IS NULL
              AND id IS DISTINCT FROM NEW.id;
            IF cnt + 1 > 10 THEN
              RAISE EXCEPTION 'satellite_limit_exceeded'
                USING ERRCODE = 'check_violation';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $fn$
        """
    )
    _sql(
        """
        CREATE TRIGGER trg_satellite_limit
          BEFORE INSERT OR UPDATE ON exercises
          FOR EACH ROW
          EXECUTE FUNCTION trg_satellite_limit_fn()
        """
    )

    _sql(
        """
        CREATE OR REPLACE FUNCTION trg_progress_exercise_owner_fn()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $fn$
        DECLARE
          ex_kind text;
          ex_user uuid;
        BEGIN
          SELECT kind, user_id INTO ex_kind, ex_user
          FROM exercises
          WHERE id = NEW.exercise_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'progress_exercise_not_found'
              USING ERRCODE = 'foreign_key_violation';
          END IF;
          IF ex_kind = 'cc' AND ex_user IS NULL THEN
            RETURN NEW;
          END IF;
          IF ex_kind = 'satellite' AND ex_user = NEW.user_id THEN
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'progress_exercise_owner_mismatch'
            USING ERRCODE = 'check_violation';
        END;
        $fn$
        """
    )
    _sql(
        """
        CREATE TRIGGER trg_progress_exercise_owner
          BEFORE INSERT OR UPDATE OF user_id, exercise_id
          ON user_exercise_progress
          FOR EACH ROW
          EXECUTE FUNCTION trg_progress_exercise_owner_fn()
        """
    )

    for table in (
        "programs",
        "program_translations",
        "program_days",
        "program_day_translations",
        "progression_schemas",
        "exercises",
        "exercise_translations",
        "program_day_exercises",
        "exercise_steps",
        "exercise_step_translations",
        "user_program_enrollments",
        "user_exercise_progress",
        "workout_sessions",
        "session_exercise_logs",
        "progression_events",
        "sync_conflict_logs",
        "sync_devices",
        "client_mutations",
        "rate_limit_buckets",
    ):
        _sql(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO trainer_app")


def downgrade() -> None:
    _sql("DROP TRIGGER IF EXISTS trg_progress_exercise_owner ON user_exercise_progress")
    _sql("DROP TRIGGER IF EXISTS trg_satellite_limit ON exercises")
    _sql("DROP FUNCTION IF EXISTS trg_progress_exercise_owner_fn()")
    _sql("DROP FUNCTION IF EXISTS trg_satellite_limit_fn()")
    _sql("DROP TABLE IF EXISTS rate_limit_buckets")
    _sql("DROP TABLE IF EXISTS client_mutations")
    _sql("DROP TABLE IF EXISTS sync_devices")
    _sql("DROP TABLE IF EXISTS sync_conflict_logs")
    _sql("DROP TABLE IF EXISTS progression_events")
    _sql("DROP TABLE IF EXISTS session_exercise_logs")
    _sql("DROP TABLE IF EXISTS workout_sessions")
    _sql("DROP TABLE IF EXISTS user_exercise_progress")
    _sql("DROP TABLE IF EXISTS user_program_enrollments")
    _sql("DROP TABLE IF EXISTS exercise_step_translations")
    _sql("DROP TABLE IF EXISTS exercise_steps")
    _sql("DROP TABLE IF EXISTS program_day_exercises")
    _sql("DROP TABLE IF EXISTS exercise_translations")
    _sql("DROP TABLE IF EXISTS exercises")
    _sql("DROP TABLE IF EXISTS progression_schemas")
    _sql("DROP TABLE IF EXISTS program_day_translations")
    _sql("DROP TABLE IF EXISTS program_days")
    _sql("DROP TABLE IF EXISTS program_translations")
    _sql("DROP TABLE IF EXISTS programs")
