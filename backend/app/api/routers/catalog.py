"""GET /catalog/cc with ETag (FR-075a)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_current_user_rate_limited
from app.db.session import get_session
from app.schemas.api import CatalogCcResponseV1
from app.services.catalog import build_cc_catalog

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/cc", response_model=CatalogCcResponseV1)
async def get_cc_catalog(
    response: Response,
    locale: str | None = Query(default=None),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> CatalogCcResponseV1 | Response:
    payload, etag = await build_cc_catalog(
        db, requested_locale=locale, user_locale=ctx.user.locale
    )
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, must-revalidate"
    if if_none_match and if_none_match.strip() == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return payload
