"""Legal acceptance outbox / API contract (FR-014a)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.common import VersionedModel


class LegalAcceptanceV1(VersionedModel):
    schema_version: int = Field(1, ge=1)
    client_mutation_id: UUID
    document_slug: str = Field(..., min_length=1, max_length=64)
    document_version: str | None = Field(default=None, max_length=32)
    document_id: UUID | None = None
    accepted_locale: str = Field(..., min_length=2, max_length=35)
    accepted_content_hash: str = Field(
        ...,
        description="Lowercase SHA-256 hex of title+body",
        min_length=64,
        max_length=64,
    )
    accepted_at: datetime

    @field_validator("accepted_content_hash")
    @classmethod
    def _lowercase_hex(cls, value: str) -> str:
        lowered = value.lower()
        if any(c not in "0123456789abcdef" for c in lowered):
            raise ValueError("accepted_content_hash must be lowercase hex")
        return lowered
