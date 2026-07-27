"""Session sets contract (FR-042)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import VersionedModel


class SessionSetV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reps: int | None = Field(default=None, ge=0)
    duration_sec: int | None = Field(default=None, ge=0)
    weight_kg: float | None = Field(default=None, ge=0)
    sides: str | None = Field(default=None, max_length=32)
    notes: str | None = Field(default=None, max_length=1000)


class SessionSetsV1(VersionedModel):
    schema_version: int = Field(1, ge=1)
    sets: list[SessionSetV1] = Field(default_factory=list)
