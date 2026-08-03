from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
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


class SyncConflictLog(Base):
    __tablename__ = "sync_conflict_logs"
    __table_args__ = (
        CheckConstraint(
            "conflict_kind IN ("
            "'lost_push','tie_revision',"
            "'session_immutable_after_evaluate','session_date_immutable',"
            "'satellite_config_activation_lost'"
            ")",
            name="ck_sync_conflict_logs_kind",
        ),
        CheckConstraint(
            "(losing_payload ? 'schema_version')",
            name="ck_sync_conflict_logs_payload_schema",
        ),
        Index("ix_sync_conflict_logs_user_created_at", "user_id", desc("created_at")),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    winning_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    losing_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    winning_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    conflict_kind: Mapped[str] = mapped_column(Text, nullable=False)
    losing_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    device_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SyncDevice(Base):
    __tablename__ = "sync_devices"
    __table_args__ = (
        UniqueConstraint("user_id", "device_id", name="uq_sync_devices_user_device"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    device_id: Mapped[str] = mapped_column(Text, nullable=False)
    last_pull_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_push_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ClientMutation(Base):
    __tablename__ = "client_mutations"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "client_mutation_id",
            name="uq_client_mutations_user_mutation",
        ),
        CheckConstraint(
            "result_status IN ('applied','applied_detached')",
            name="ck_client_mutations_result_status",
        ),
        CheckConstraint(
            "(depends_on ? 'schema_version') AND (depends_on ? 'mutation_ids')",
            name="ck_client_mutations_depends_on_schema",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    client_mutation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    depends_on: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text(
            "jsonb_build_object('schema_version', 1, 'mutation_ids', '[]'::jsonb)"
        ),
    )
    content_hash: Mapped[str | None] = mapped_column(Text)
    result_status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'applied'"),
    )
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RateLimitBucket(Base):
    __tablename__ = "rate_limit_buckets"
    __table_args__ = (
        CheckConstraint("count >= 0", name="ck_rate_limit_buckets_count"),
    )

    bucket_key: Mapped[str] = mapped_column(Text, primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
