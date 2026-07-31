from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
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


class WorkoutSession(Base):
    __tablename__ = "workout_sessions"
    __table_args__ = (
        CheckConstraint(
            "notes IS NULL OR char_length(notes) <= 2000",
            name="ck_workout_sessions_notes_len",
        ),
        CheckConstraint("revision >= 1", name="ck_workout_sessions_revision"),
        UniqueConstraint(
            "user_id",
            "client_mutation_id",
            name="uq_workout_sessions_user_client_mutation",
        ),
        UniqueConstraint("id", "user_id", name="uq_workout_sessions_id_user"),
        Index(
            "ix_workout_sessions_user_performed_at_active",
            "user_id",
            desc("performed_at"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_workout_sessions_user_local_date_active",
            "user_id",
            "local_date",
            "performed_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_workout_sessions_user_updated_at", "user_id", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    client_mutation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    client_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SessionExerciseLog(Base):
    __tablename__ = "session_exercise_logs"
    __table_args__ = (
        CheckConstraint(
            "exercise_kind IN ('cc','satellite')",
            name="ck_session_logs_exercise_kind",
        ),
        CheckConstraint("section IN ('main','accessories')", name="ck_session_logs_section"),
        CheckConstraint(
            "notes IS NULL OR char_length(notes) <= 1000",
            name="ck_session_logs_notes_len",
        ),
        CheckConstraint("revision >= 1", name="ck_session_logs_revision"),
        CheckConstraint(
            "progression_schema_version IS NULL OR progression_schema_version >= 1",
            name="ck_session_logs_progression_schema_version",
        ),
        ForeignKeyConstraint(
            ["session_id", "user_id"],
            ["workout_sessions.id", "workout_sessions.user_id"],
            ondelete="CASCADE",
            name="fk_session_logs_session_user",
        ),
        Index(
            "uq_session_logs_client_mutation",
            "user_id",
            "client_mutation_id",
            unique=True,
            postgresql_where=text("client_mutation_id IS NOT NULL"),
        ),
        Index(
            "uq_session_logs_cc_one_active_per_day",
            "user_id",
            "exercise_id",
            "local_date",
            unique=True,
            postgresql_where=text(
                "exercise_kind = 'cc' AND skipped = false AND superseded_at IS NULL"
            ),
        ),
        Index("ix_session_logs_session_sort", "session_id", "sort_order"),
        Index(
            "ix_session_logs_progression_tip",
            "user_id",
            "exercise_id",
            "local_date",
            "performed_at",
            "id",
            postgresql_where=text(
                "exercise_kind = 'cc' AND skipped = false "
                "AND superseded_at IS NULL AND counts_for_progression = true"
            ),
        ),
        Index("ix_session_logs_user_updated_at", "user_id", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
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
    exercise_kind: Mapped[str] = mapped_column(Text, nullable=False)
    section: Mapped[str] = mapped_column(Text, nullable=False)
    step_number: Mapped[int | None] = mapped_column(SmallInteger)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_locale: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pl-PL'")
    )
    exercise_name_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    step_label_snapshot: Mapped[str | None] = mapped_column(Text)
    skipped: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    sets: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    rules_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    progression_schema_version: Mapped[int | None] = mapped_column(Integer)
    goal_met: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    goal_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    counts_for_progression: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    progression_skipped: Mapped[str | None] = mapped_column(Text)
    satellite_config_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("satellite_config_versions.id", ondelete="RESTRICT"),
    )
    satellite_config_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    notes: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    client_mutation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    client_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
