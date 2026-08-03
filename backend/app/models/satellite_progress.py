"""Satellite mini-progression persistence (FR-053 / Stage 3)."""

from __future__ import annotations

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


class SatelliteDailyOutcome(Base):
    __tablename__ = "satellite_daily_outcomes"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "exercise_id",
            "local_date",
            name="uq_satellite_daily_outcomes_user_ex_date",
        ),
        CheckConstraint(
            "status IN ('pending','finalized','cancelled')",
            name="ck_satellite_daily_outcomes_status",
        ),
        CheckConstraint(
            "result IS NULL OR result IN ('success','failure')",
            name="ck_satellite_daily_outcomes_result",
        ),
        CheckConstraint(
            "result_snapshot IS NULL OR (result_snapshot ? 'schema_version')",
            name="ck_satellite_daily_outcomes_result_snapshot",
        ),
        Index(
            "ix_satellite_daily_outcomes_pending_finalize",
            "status",
            "finalize_after",
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "ix_satellite_daily_outcomes_user_exercise",
            "user_id",
            "exercise_id",
            desc("local_date"),
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
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    step_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("exercise_steps.id", ondelete="RESTRICT"),
        nullable=False,
    )
    config_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("satellite_config_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    has_attempt: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    has_success: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[str | None] = mapped_column(Text)
    representative_log_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("session_exercise_logs.id", ondelete="SET NULL"),
    )
    result_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    applied_progress_revision: Mapped[int | None] = mapped_column(Integer)
    finalize_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SatelliteRegressionRecommendation(Base):
    __tablename__ = "satellite_regression_recommendations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','accepted','declined','cancelled','stale')",
            name="ck_satellite_regression_recommendations_status",
        ),
        Index(
            "uq_satellite_regression_recommendations_pending",
            "user_id",
            "exercise_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
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
    trigger_outcome_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("satellite_daily_outcomes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    config_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("satellite_config_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    from_step_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("exercise_steps.id", ondelete="RESTRICT"),
        nullable=False,
    )
    to_step_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("exercise_steps.id", ondelete="RESTRICT"),
        nullable=False,
    )
    expected_progress_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
