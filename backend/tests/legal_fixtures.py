"""Shared legal seed helpers for tests (FR-014a)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.legal import LegalDocument, LegalDocumentTranslation
from app.services.legal import HEALTH_DISCLAIMER_SLUG


async def latest_health_disclaimer(
    db: AsyncSession,
) -> tuple[LegalDocument, LegalDocumentTranslation]:
    doc = await db.scalar(
        select(LegalDocument)
        .where(LegalDocument.slug == HEALTH_DISCLAIMER_SLUG)
        .order_by(LegalDocument.published_at.desc())
        .limit(1)
    )
    if doc is None:
        pytest.skip("legal seed required")
    tr = await db.scalar(
        select(LegalDocumentTranslation).where(
            LegalDocumentTranslation.document_id == doc.id,
            LegalDocumentTranslation.locale == "pl-PL",
        )
    )
    if tr is None:
        pytest.skip("legal translation seed required")
    return doc, tr
