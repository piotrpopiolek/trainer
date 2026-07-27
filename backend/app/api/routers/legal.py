"""Legal documents / acceptances (FR-014a)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_current_user_rate_limited
from app.db.session import get_session
from app.services import legal as legal_service
from app.services.errors import DomainError

router = APIRouter(prefix="/legal", tags=["legal"])


class DisclaimerResponse(BaseModel):
    schema_version: int = 1
    document_id: str
    slug: str
    version: str
    locale: str
    title: str
    body: str
    content_hash: str


class LegalAcceptanceRequest(BaseModel):
    schema_version: int = 1
    payload: dict[str, Any]


class LegalAcceptanceResponse(BaseModel):
    schema_version: int = 1
    accepted: bool = True
    document_id: str


@router.get("/health-disclaimer")
async def get_health_disclaimer(
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
    locale: str | None = None,
) -> DisclaimerResponse:
    resolved = locale or ctx.user.locale
    doc = await legal_service.latest_published_document(
        db, slug=legal_service.HEALTH_DISCLAIMER_SLUG
    )
    if doc is None:
        raise DomainError("legal_document_not_found", http_status=404)
    tr = await legal_service.get_translation(
        db, document_id=doc.id, locale=resolved
    )
    if tr is None:
        raise DomainError("legal_translation_not_found", http_status=404)
    return DisclaimerResponse(
        document_id=str(doc.id),
        slug=doc.slug,
        version=doc.version,
        locale=tr.locale,
        title=tr.title,
        body=tr.body,
        content_hash=tr.content_hash.hex(),
    )


@router.post("/acceptances")
async def post_legal_acceptance(
    body: LegalAcceptanceRequest,
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> LegalAcceptanceResponse:
    row = await legal_service.record_legal_acceptance(
        db, user_id=ctx.user.id, payload=body.payload
    )
    await db.commit()
    return LegalAcceptanceResponse(document_id=str(row.document_id))
