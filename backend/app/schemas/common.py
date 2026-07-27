"""Versioned JSON contracts — every payload requires schema_version (FR-046)."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.services.errors import DomainError


class VersionedModel(BaseModel):
    """Base for JSON documents. Subclasses set SCHEMA_VERSION (exact match)."""

    model_config = ConfigDict(extra="forbid")

    SCHEMA_VERSION: ClassVar[int] = 1
    schema_version: int = Field(..., ge=1)


def parse_versioned[T: VersionedModel](
    model: type[T], payload: dict[str, Any] | None
) -> T:
    if not isinstance(payload, dict):
        raise DomainError("schema_invalid", http_status=422)
    if "schema_version" not in payload:
        raise DomainError("schema_version_required", http_status=422)
    expected = model.SCHEMA_VERSION
    if payload["schema_version"] != expected:
        raise DomainError("schema_version_unsupported", http_status=422)
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise DomainError("schema_invalid", http_status=422) from exc
