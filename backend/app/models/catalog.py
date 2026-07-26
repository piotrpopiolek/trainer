from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Program(Base):
    __tablename__ = "programs"
    __table_args__ = (UniqueConstraint("slug", name="uq_programs_slug"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProgramTranslation(Base):
    __tablename__ = "program_translations"
    __table_args__ = (
        CheckConstraint(
            "char_length(locale) BETWEEN 2 AND 35",
            name="ck_program_translations_locale_len",
        ),
        CheckConstraint("catalog_version >= 1", name="ck_program_translations_catalog_version"),
    )

    program_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    locale: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    catalog_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProgramDay(Base):
    __tablename__ = "program_days"
    __table_args__ = (
        CheckConstraint("day_index BETWEEN 1 AND 3", name="ck_program_days_day_index"),
        UniqueConstraint("program_id", "day_index", name="uq_program_days_program_day_index"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    program_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    day_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))


class ProgramDayTranslation(Base):
    __tablename__ = "program_day_translations"
    __table_args__ = (
        CheckConstraint(
            "char_length(locale) BETWEEN 2 AND 35",
            name="ck_program_day_translations_locale_len",
        ),
    )

    program_day_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("program_days.id", ondelete="CASCADE"),
        primary_key=True,
    )
    locale: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class Exercise(Base):
    __tablename__ = "exercises"
    __table_args__ = (
        CheckConstraint("kind IN ('cc','satellite')", name="ck_exercises_kind"),
        CheckConstraint("exercise_type IN ('A','B','C')", name="ck_exercises_exercise_type"),
        CheckConstraint(
            "schedule_kind IS NULL OR schedule_kind IN ('daily','weekdays','category')",
            name="ck_exercises_schedule_kind",
        ),
        CheckConstraint(
            "schedule_category IS NULL OR schedule_category IN "
            "('anytime','post_workout','rest_day')",
            name="ck_exercises_schedule_category",
        ),
        CheckConstraint(
            "(active_metrics ? 'schema_version')",
            name="ck_exercises_active_metrics_schema",
        ),
        CheckConstraint("revision >= 1", name="ck_exercises_revision"),
        Index(
            "uq_exercises_cc_slug_active",
            "slug",
            unique=True,
            postgresql_where=text("kind = 'cc' AND deleted_at IS NULL"),
        ),
        Index(
            "uq_exercises_satellite_client_mutation",
            "user_id",
            "client_mutation_id",
            unique=True,
            postgresql_where=text("kind = 'satellite' AND client_mutation_id IS NOT NULL"),
        ),
        Index(
            "ix_exercises_user_satellite_active",
            "user_id",
            postgresql_where=text("kind = 'satellite' AND deleted_at IS NULL"),
        ),
        Index(
            "ix_exercises_user_updated_at_satellite_active",
            "user_id",
            "updated_at",
            postgresql_where=text("kind = 'satellite' AND deleted_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    program_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("programs.id", ondelete="RESTRICT")
    )
    slug: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    exercise_type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    active_metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text('\'{"schema_version":1,"metrics":["reps"]}\'::jsonb'),
    )
    equipment: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    schedule_kind: Mapped[str | None] = mapped_column(Text)
    weekdays: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger))
    schedule_category: Mapped[str | None] = mapped_column(Text)
    cloned_from_exercise_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("exercises.id", ondelete="SET NULL")
    )
    client_mutation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    client_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExerciseTranslation(Base):
    __tablename__ = "exercise_translations"
    __table_args__ = (
        CheckConstraint(
            "char_length(locale) BETWEEN 2 AND 35",
            name="ck_exercise_translations_locale_len",
        ),
    )

    exercise_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("exercises.id", ondelete="CASCADE"),
        primary_key=True,
    )
    locale: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProgramDayExercise(Base):
    __tablename__ = "program_day_exercises"
    __table_args__ = (
        UniqueConstraint(
            "program_day_id",
            "exercise_id",
            name="uq_program_day_exercises_day_exercise",
        ),
        Index("ix_program_day_exercises_day_sort", "program_day_id", "sort_order"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    program_day_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("program_days.id", ondelete="CASCADE"),
        nullable=False,
    )
    exercise_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("exercises.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))


class ExerciseStep(Base):
    __tablename__ = "exercise_steps"
    __table_args__ = (
        CheckConstraint("step_number >= 1", name="ck_exercise_steps_step_number"),
        CheckConstraint(
            "(rules ? 'schema_version') AND (rules->>'schema_version')::int >= 1",
            name="ck_exercise_steps_rules_schema",
        ),
        UniqueConstraint("exercise_id", "step_number", name="uq_exercise_steps_exercise_step"),
        Index("ix_exercise_steps_exercise_step_number", "exercise_id", "step_number"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    exercise_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("exercises.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    progression_schema_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("progression_schemas.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExerciseStepTranslation(Base):
    __tablename__ = "exercise_step_translations"
    __table_args__ = (
        CheckConstraint(
            "char_length(locale) BETWEEN 2 AND 35",
            name="ck_exercise_step_translations_locale_len",
        ),
        CheckConstraint(
            "content_status IN ('draft','ready')",
            name="ck_exercise_step_translations_content_status",
        ),
    )

    exercise_step_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("exercise_steps.id", ondelete="CASCADE"),
        primary_key=True,
    )
    locale: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    content_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'draft'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
