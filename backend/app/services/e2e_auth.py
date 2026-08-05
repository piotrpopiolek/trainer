"""E2E login harness — gated by ENABLE_E2E_LOGIN (dev/test only)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_uuid7
from app.models.catalog import Program
from app.models.user import User
from app.services.errors import DomainError
from app.services.legal import (
    HEALTH_DISCLAIMER_SLUG,
    get_translation,
    latest_published_document,
    record_legal_acceptance,
)
from app.services.onboarding import complete_onboarding


async def provision_e2e_ready_user(
    db: AsyncSession,
    *,
    email: str | None = None,
) -> User:
    if await db.scalar(select(Program).where(Program.slug == "cc_big_six")) is None:
        raise DomainError("enrollment_required", http_status=503)

    doc = await latest_published_document(db, slug=HEALTH_DISCLAIMER_SLUG)
    if doc is None:
        raise DomainError("legal_required", http_status=503)
    tr = await get_translation(db, document_id=doc.id, locale="pl-PL")
    if tr is None:
        raise DomainError("legal_required", http_status=503)

    user = User(
        id=new_uuid7(),
        google_sub=f"e2e-{new_uuid7()}",
        email=email or f"e2e-{new_uuid7()}@example.test",
        locale="pl-PL",
        timezone="Europe/Warsaw",
    )
    db.add(user)
    await db.flush()
    await complete_onboarding(
        db,
        user,
        questionnaire={
            "schema_version": 1,
            "experience_level": "beginner",
            "training_days_per_week": 3,
            "goals": ["strength"],
        },
        started_on=date(2026, 7, 1),
        anchor_weekday=1,
    )
    await record_legal_acceptance(
        db,
        user_id=user.id,
        payload={
            "schema_version": 1,
            "client_mutation_id": str(uuid4()),
            "document_slug": "health_disclaimer",
            "document_version": doc.version,
            "accepted_locale": "pl-PL",
            "accepted_content_hash": tr.content_hash.hex(),
            "accepted_at": datetime.now(UTC).isoformat(),
        },
    )
    await db.commit()
    await db.refresh(user)
    return user
