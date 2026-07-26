"""UUID helpers — UUID v7 for offline-capable primary keys (docs/db-plan.md)."""

from uuid import UUID

from uuid6 import uuid7


def new_uuid7() -> UUID:
    return uuid7()
