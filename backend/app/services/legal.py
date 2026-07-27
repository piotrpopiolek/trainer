"""Legal acceptance + session gate (FR-014a)."""

from __future__ import annotations

from datetime import UTC
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_uuid7
from app.models.legal import LegalDocument, LegalDocumentTranslation, UserLegalAcceptance
from app.schemas.common import parse_versioned
from app.schemas.legal import LegalAcceptanceV1
from app.services.errors import DomainError, LegalRequiredError

HEALTH_DISCLAIMER_SLUG = "health_disclaimer"


def content_hash_from_hex(hex_digest: str) -> bytes:
    return bytes.fromhex(hex_digest.lower())


async def latest_published_document(
    db: AsyncSession, *, slug: str
) -> LegalDocument | None:
    row = await db.scalar(
        select(LegalDocument)
        .where(LegalDocument.slug == slug)
        .order_by(LegalDocument.published_at.desc())
        .limit(1)
    )
    return row if isinstance(row, LegalDocument) else None


async def get_translation(
    db: AsyncSession,
    *,
    document_id: UUID,
    locale: str,
    content_hash: bytes | None = None,
) -> LegalDocumentTranslation | None:
    stmt = select(LegalDocumentTranslation).where(
        LegalDocumentTranslation.document_id == document_id,
        LegalDocumentTranslation.locale == locale,
    )
    if content_hash is not None:
        stmt = stmt.where(LegalDocumentTranslation.content_hash == content_hash)
    row = await db.scalar(stmt)
    return row if isinstance(row, LegalDocumentTranslation) else None


async def user_has_current_health_disclaimer(
    db: AsyncSession,
    *,
    user_id: UUID,
    locale: str,
) -> bool:
    doc = await latest_published_document(db, slug=HEALTH_DISCLAIMER_SLUG)
    if doc is None:
        return False
    translation = await get_translation(db, document_id=doc.id, locale=locale)
    if translation is None:
        return False
    acceptance = await db.scalar(
        select(UserLegalAcceptance).where(
            UserLegalAcceptance.user_id == user_id,
            UserLegalAcceptance.document_id == doc.id,
            UserLegalAcceptance.accepted_locale == locale,
            UserLegalAcceptance.accepted_content_hash == translation.content_hash,
        )
    )
    return acceptance is not None


async def require_health_disclaimer_for_session(
    db: AsyncSession,
    *,
    user_id: UUID,
    locale: str,
) -> None:
    """Block session apply/create without current disclaimer (FR-014a)."""
    if not await user_has_current_health_disclaimer(db, user_id=user_id, locale=locale):
        raise LegalRequiredError()


async def record_legal_acceptance(
    db: AsyncSession,
    *,
    user_id: UUID,
    payload: dict[str, Any],
) -> UserLegalAcceptance:
    acceptance = parse_versioned(LegalAcceptanceV1, payload)
    doc: LegalDocument | None = None
    if acceptance.document_id is not None:
        doc = await db.scalar(
            select(LegalDocument).where(LegalDocument.id == acceptance.document_id)
        )
    elif acceptance.document_slug:
        stmt = select(LegalDocument).where(LegalDocument.slug == acceptance.document_slug)
        if acceptance.document_version:
            stmt = stmt.where(LegalDocument.version == acceptance.document_version)
        else:
            stmt = stmt.order_by(LegalDocument.published_at.desc())
        doc = await db.scalar(stmt.limit(1))

    if doc is None:
        raise DomainError("legal_document_not_found", http_status=404)

    digest = content_hash_from_hex(acceptance.accepted_content_hash)
    translation = await get_translation(
        db,
        document_id=doc.id,
        locale=acceptance.accepted_locale,
        content_hash=digest,
    )
    if translation is None:
        raise DomainError("legal_hash_mismatch", http_status=422)

    existing = await db.scalar(
        select(UserLegalAcceptance).where(
            UserLegalAcceptance.user_id == user_id,
            UserLegalAcceptance.document_id == doc.id,
        )
    )
    accepted_at = acceptance.accepted_at
    if accepted_at.tzinfo is None:
        accepted_at = accepted_at.replace(tzinfo=UTC)

    if existing is None:
        row = UserLegalAcceptance(
            id=new_uuid7(),
            user_id=user_id,
            document_id=doc.id,
            accepted_locale=acceptance.accepted_locale,
            accepted_content_hash=digest,
            accepted_at=accepted_at,
        )
        db.add(row)
        await db.flush()
        return row

    existing.accepted_locale = acceptance.accepted_locale
    existing.accepted_content_hash = digest
    existing.accepted_at = accepted_at
    await db.flush()
    return existing
