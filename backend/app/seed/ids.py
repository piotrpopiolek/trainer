"""Deterministic UUIDs for seed entities (idempotent upserts)."""

from uuid import UUID, uuid5

# Fixed namespace — do not change (would rewrite all seed PKs).
SEED_NAMESPACE = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def seed_id(*parts: str) -> UUID:
    return uuid5(SEED_NAMESPACE, ":".join(parts))
