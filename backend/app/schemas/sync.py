"""Sync push/pull contracts (FR-072*/073/075)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SyncPushItemV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_mutation_id: UUID
    entity_type: Literal[
        "legal_acceptance",
        "workout_session",
        "body_measurement",
        "satellite",
    ]
    entity_id: UUID
    op: Literal["upsert", "delete"] = "upsert"
    revision: int = Field(1, ge=1)
    client_updated_at: datetime | None = None
    payload: dict[str, Any] | None = None
    # FR-072a: prerequisite client_mutation_id values (not entity_id).
    depends_on: list[UUID] = Field(default_factory=list, max_length=20)

    @field_validator("depends_on")
    @classmethod
    def unique_sorted_depends_on(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("depends_on_duplicate")
        return sorted(value, key=lambda u: str(u))

    @model_validator(mode="after")
    def no_self_dependency(self) -> SyncPushItemV1:
        if self.client_mutation_id in self.depends_on:
            raise ValueError("depends_on_self_reference")
        return self


class SyncPushRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(1, ge=1)
    device_id: str | None = Field(default=None, max_length=128)
    items: list[SyncPushItemV1] = Field(default_factory=list)


class SyncPushItemResultV1(BaseModel):
    schema_version: int = 1
    client_mutation_id: UUID
    status: Literal[
        "applied",
        "applied_detached",
        "idempotent",
        "conflict_lost",
        "conflict_tie",
        "session_immutable_after_evaluate",
        "rejected",
    ]
    error_code: str | None = None
    conflict_id: UUID | None = None
    progression_skipped: str | None = None
    winning_revision: int | None = None
    winning_updated_at: datetime | None = None
    # Stage 2 metadata (populated by later slices; optional for Slice A).
    registered_config_version_id: UUID | None = None
    activation_applied: bool | None = None
    dependency_failed_mutation_id: UUID | None = None


class SyncPushResponseV1(BaseModel):
    schema_version: int = 1
    truncated: bool = False
    results: list[SyncPushItemResultV1]
    progression_events: list[dict[str, Any]] = Field(default_factory=list)
    progress: list[dict[str, Any]] = Field(default_factory=list)


class SyncTombstoneV1(BaseModel):
    schema_version: int = 1
    entity_type: str
    id: UUID
    deleted_at: datetime
    revision: int


class SyncPullResponseV1(BaseModel):
    schema_version: int = 1
    server_time: datetime
    requested_locale: str
    resolved_locale: str
    catalog_version: int | None = None
    resync_required: bool = False
    sessions: list[dict[str, Any]] = Field(default_factory=list)
    measurements: list[dict[str, Any]] = Field(default_factory=list)
    satellites: list[dict[str, Any]] = Field(default_factory=list)
    progress: list[dict[str, Any]] = Field(default_factory=list)
    progression_events: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    tombstones: list[SyncTombstoneV1] = Field(default_factory=list)
