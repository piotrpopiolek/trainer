from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    desc,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProgressionSchema(Base):
    __tablename__ = "progression_schemas"
    __table_args__ = (
        UniqueConstraint("slug", "schema_version", name="uq_progression_schemas_slug_version"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UserProgramEnrollment(Base):
    __tablename__ = "user_program_enrollments"
    __table_args__ = (
        CheckConstraint(
            "anchor_weekday BETWEEN 1 AND 7",
            name="ck_enrollments_anchor_weekday",
        ),
        CheckConstraint(
            "pending_anchor_weekday IS NULL OR pending_anchor_weekday BETWEEN 1 AND 7",
            name="ck_enrollments_pending_anchor",
        ),
        CheckConstraint(
            "rotation_offset BETWEEN 0 AND 2",
            name="ck_enrollments_rotation_offset",
        ),
        Index(
            "uq_user_program_enrollments_one_active",
            "user_id",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    program_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    started_on: Mapped[date] = mapped_column(Date, nullable=False)
    anchor_weekday: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("1")
    )
    pending_anchor_weekday: Mapped[int | None] = mapped_column(SmallInteger)
    schedule_effective_on: Mapped[date | None] = mapped_column(Date)
    rotation_offset: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UserExerciseProgress(Base):
    __tablename__ = "user_exercise_progress"
    __table_args__ = (
        CheckConstraint("current_step_number >= 1", name="ck_progress_current_step"),
        CheckConstraint("fail_streak >= 0", name="ck_progress_fail_streak"),
        UniqueConstraint(
            "user_id",
            "exercise_id",
            name="uq_user_exercise_progress_user_exercise",
        ),
        Index("ix_user_exercise_progress_user_updated_at", "user_id", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    exercise_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("exercises.id", ondelete="RESTRICT"),
        nullable=False,
    )
    current_step_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    current_step_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("exercise_steps.id", ondelete="RESTRICT"),
    )
    fail_streak: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    progress_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    last_session_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProgressionEvent(Base):
    __tablename__ = "progression_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ("
            "'advance','regress','manual_override','initial',"
            "'satellite_advance','satellite_regress_suggested',"
            "'satellite_regress_confirmed','satellite_config_reset',"
            "'satellite_manual_override'"
            ")",
            name="ck_progression_events_type",
        ),
        CheckConstraint(
            "rules_snapshot IS NULL OR (rules_snapshot ? 'schema_version')",
            name="ck_progression_events_rules_snapshot",
        ),
        Index("ix_progression_events_user_created_at", "user_id", desc("created_at")),
        Index(
            "ix_progression_events_user_exercise_created_at",
            "user_id",
            "exercise_id",
            desc("created_at"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    exercise_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("exercises.id", ondelete="RESTRICT"),
        nullable=False,
    )
    session_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workout_sessions.id", ondelete="SET NULL"),
    )
    related_outcome_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("satellite_daily_outcomes.id", ondelete="SET NULL"),
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    from_step: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    to_step: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    rules_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    progression_schema_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
