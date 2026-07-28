"""Session create / detail / soft-delete."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_current_user_rate_limited
from app.db.session import get_session
from app.schemas.api import SessionCreateV1, SessionReadV1
from app.services import sessions as session_service

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionReadV1)
async def create_session(
    body: SessionCreateV1,
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> SessionReadV1:
    return await session_service.create_session(db, user=ctx.user, body=body)


@router.get("/{session_id}", response_model=SessionReadV1)
async def read_session(
    session_id: UUID,
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> SessionReadV1:
    return await session_service.get_session(
        db, user_id=ctx.user.id, session_id=session_id
    )


@router.delete("/{session_id}", response_model=SessionReadV1)
async def delete_session(
    session_id: UUID,
    ctx: AuthContext = Depends(get_current_user_rate_limited),
    db: AsyncSession = Depends(get_session),
) -> SessionReadV1:
    return await session_service.soft_delete_user_session(
        db, user_id=ctx.user.id, session_id=session_id
    )
