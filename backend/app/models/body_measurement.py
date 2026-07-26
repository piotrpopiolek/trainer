from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
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


class BodyMeasurement(Base):
    __tablename__ = "body_measurements"
    __table_args__ = (
        CheckConstraint(
            "(metrics ? 'schema_version') AND (metrics->>'schema_version')::int >= 1",
            name="ck_body_measurements_metrics_schema",
        ),
        CheckConstraint(
            "notes IS NULL OR char_length(notes) <= 1000",
            name="ck_body_measurements_notes_len",
        ),
        CheckConstraint("revision >= 1", name="ck_body_measurements_revision"),
        UniqueConstraint(
            "user_id",
            "client_mutation_id",
            name="uq_body_measurements_user_client_mutation",
        ),
        Index(
            "ix_body_measurements_user_measured_at_active",
            "user_id",
            desc("measured_at"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_body_measurements_user_updated_at", "user_id", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
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
