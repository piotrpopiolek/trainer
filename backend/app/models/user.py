from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, Index, Text, func, text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "char_length(locale) BETWEEN 2 AND 35",
            name="ck_users_locale_len",
        ),
        CheckConstraint(
            "(body_metric_prefs ? 'schema_version') AND "
            "(body_metric_prefs->>'schema_version')::int >= 1",
            name="ck_users_body_metric_prefs_schema",
        ),
        CheckConstraint(
            "purge_status IS NULL OR purge_status IN "
            "('pending_grace', 'pending_job', 'done')",
            name="ck_users_purge_status",
        ),
        Index(
            "ix_users_purge_after_pending",
            "purge_after",
            postgresql_where=text(
                "deleted_at IS NOT NULL AND purge_status IS DISTINCT FROM 'done'"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    google_sub: Mapped[str | None] = mapped_column(Text, unique=True)
    email: Mapped[str | None] = mapped_column(CITEXT)
    display_name: Mapped[str | None] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pl-PL'"))
    timezone: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'Europe/Warsaw'")
    )
    pending_timezone: Mapped[str | None] = mapped_column(Text)
    timezone_effective_on: Mapped[date | None] = mapped_column(Date)
    body_metric_prefs: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text(
            '\'{"schema_version":1,"metrics":["weight_kg","waist_cm","biceps_cm"]}\'::jsonb'
        ),
    )
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_after: Mapped[date | None] = mapped_column(Date)
    purge_status: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
