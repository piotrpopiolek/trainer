"""Auth session lifecycle (FR-005d)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.ids import new_uuid7
from app.core.security import hash_session_token, new_session_token
from app.models.auth import AuthSession
from app.models.user import User
from app.services.errors import AuthError
from app.services.oauth_google import GoogleIdTokenClaims

# Brief window where the pre-rotation cookie still authenticates (concurrent requests).
_ROTATION_GRACE = timedelta(seconds=60)


class AuthSessionService:
    async def upsert_user_from_google(
        self,
        db: AsyncSession,
        claims: GoogleIdTokenClaims,
    ) -> User:
        user = await db.scalar(select(User).where(User.google_sub == claims.sub))
        if user is None:
            user = User(
                id=new_uuid7(),
                google_sub=claims.sub,
                email=claims.email,
                display_name=claims.name,
            )
            db.add(user)
            await db.flush()
            return user

        # Snapshot email/name may change; identity stays google_sub.
        user.email = claims.email
        if claims.name:
            user.display_name = claims.name
        await db.flush()
        return user

    async def create_session(
        self,
        db: AsyncSession,
        *,
        user: User,
        user_agent: str | None,
    ) -> str:
        now = datetime.now(UTC)
        # Serialize per-user session limit (FR-005d).
        locked = await db.scalar(
            select(User.id).where(User.id == user.id).with_for_update()
        )
        if locked is None:
            raise AuthError("unauthorized", http_status=401)

        active = (
            await db.scalars(
                select(AuthSession)
                .where(
                    AuthSession.user_id == user.id,
                    AuthSession.revoked_at.is_(None),
                    AuthSession.expires_at > now,
                    AuthSession.created_at > now - timedelta(days=settings.session_hard_cap_days),
                )
                .order_by(AuthSession.created_at.asc())
                .with_for_update()
            )
        ).all()

        overflow = len(active) - settings.session_max_active + 1
        if overflow > 0:
            for old in active[:overflow]:
                old.revoked_at = now

        raw = new_session_token()
        row = AuthSession(
            id=new_uuid7(),
            user_id=user.id,
            token_hash=hash_session_token(raw),
            expires_at=now + timedelta(days=settings.session_sliding_days),
            user_agent=user_agent,
            last_seen_at=now,
        )
        db.add(row)
        await db.commit()
        return raw

    async def resolve_user(
        self,
        db: AsyncSession,
        raw_token: str | None,
        *,
        allow_bump: bool = True,
    ) -> tuple[User, AuthSession, str | None]:
        """Return user, session, and optional rotated raw token."""
        if not raw_token:
            raise AuthError("unauthorized", http_status=401)

        now = datetime.now(UTC)
        token_hash = hash_session_token(raw_token)
        row = await db.scalar(
            select(AuthSession)
            .where(AuthSession.token_hash == token_hash)
            .with_for_update()
        )
        if row is None:
            raise AuthError("unauthorized", http_status=401)

        if row.revoked_at is not None:
            row = await self._resolve_rotated_successor(db, row, now=now)
        elif row.expires_at <= now or row.created_at <= now - timedelta(
            days=settings.session_hard_cap_days
        ):
            raise AuthError("unauthorized", http_status=401)

        user = await db.scalar(
            select(User).where(User.id == row.user_id).with_for_update()
        )
        if user is None or user.deleted_at is not None:
            raise AuthError("unauthorized", http_status=401)

        rotated: str | None = None
        if allow_bump:
            rotated = await self._maybe_bump(db, row, user_agent=row.user_agent)
            if rotated is not None:
                new_hash = hash_session_token(rotated)
                row = await db.scalar(
                    select(AuthSession).where(AuthSession.token_hash == new_hash)
                )
                assert row is not None

        return user, row, rotated

    async def _resolve_rotated_successor(
        self,
        db: AsyncSession,
        revoked: AuthSession,
        *,
        now: datetime,
    ) -> AuthSession:
        """Accept pre-rotation cookie briefly while a successor row exists (FR-005d)."""
        revoked_at = revoked.revoked_at
        assert revoked_at is not None
        if revoked_at.tzinfo is None:
            revoked_at = revoked_at.replace(tzinfo=UTC)
        if now - revoked_at > _ROTATION_GRACE:
            raise AuthError("unauthorized", http_status=401)

        successor = await db.scalar(
            select(AuthSession)
            .where(
                AuthSession.user_id == revoked.user_id,
                AuthSession.created_at == revoked.created_at,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
                AuthSession.created_at > now - timedelta(days=settings.session_hard_cap_days),
            )
            .with_for_update()
        )
        if successor is None:
            raise AuthError("unauthorized", http_status=401)
        return successor

    async def _maybe_bump(
        self,
        db: AsyncSession,
        row: AuthSession,
        *,
        user_agent: str | None,
    ) -> str | None:
        now = datetime.now(UTC)
        last = row.last_seen_at or row.created_at
        min_gap = timedelta(hours=settings.session_bump_min_hours)
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        # last_seen_at = last sliding bump only — do not advance on every request (FR-005d).
        if now - last < min_gap:
            return None

        # Serialize with login path: user row already locked in resolve_user.
        # Revoke old + INSERT new in one TX (db-plan §1.2).
        row.revoked_at = now
        raw = new_session_token()
        new_row = AuthSession(
            id=new_uuid7(),
            user_id=row.user_id,
            token_hash=hash_session_token(raw),
            expires_at=now + timedelta(days=settings.session_sliding_days),
            user_agent=user_agent,
            last_seen_at=now,
            created_at=row.created_at,
        )
        db.add(new_row)
        await db.commit()
        return raw

    async def revoke_current(self, db: AsyncSession, raw_token: str | None) -> None:
        if not raw_token:
            return
        now = datetime.now(UTC)
        row = await db.scalar(
            select(AuthSession).where(
                AuthSession.token_hash == hash_session_token(raw_token)
            )
        )
        if row is not None and row.revoked_at is None:
            row.revoked_at = now
            await db.commit()

    async def revoke_all_for_user(
        self, db: AsyncSession, user_id: object, *, commit: bool = True
    ) -> None:
        now = datetime.now(UTC)
        rows = (
            await db.scalars(
                select(AuthSession).where(
                    AuthSession.user_id == user_id,
                    AuthSession.revoked_at.is_(None),
                )
            )
        ).all()
        for row in rows:
            row.revoked_at = now
        if commit:
            await db.commit()
        else:
            await db.flush()
