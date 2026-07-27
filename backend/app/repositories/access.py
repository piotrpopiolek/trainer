"""Deny-by-default access helpers (FR-005b)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.services.errors import NotFoundError


async def get_for_user[T: Base](
    db: AsyncSession,
    model: type[T],
    *,
    user_id: UUID,
    entity_id: UUID,
) -> T:
    """Load a user-owned row by id; missing or foreign → not_found (404)."""
    row = await db.scalar(
        select(model).where(
            model.id == entity_id,  # type: ignore[attr-defined]
            model.user_id == user_id,  # type: ignore[attr-defined]
        )
    )
    if row is None:
        raise NotFoundError()
    return row
