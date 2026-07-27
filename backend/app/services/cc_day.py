"""CC day resolution — fixed weekdays (FR-022a/022b / FR-040c)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.progression import UserProgramEnrollment
from app.models.user import User
from app.services.errors import DomainError


@dataclass(frozen=True, slots=True)
class CcDayResult:
    local_date: date
    day_index: int | None
    is_rest_day: bool
    before_started_on: bool
    anchor_weekday: int
    rotation_offset: int


def resolve_cc_day(
    local_date: date,
    *,
    anchor_weekday: int,
    rotation_offset: int = 0,
    started_on: date | None = None,
) -> CcDayResult:
    """Fixed weekdays: offset 0/2/4 → D1/D2/D3, else rest (FR-022a)."""
    if not 1 <= anchor_weekday <= 7:
        raise DomainError("invalid_anchor_weekday", http_status=422)
    if not 0 <= rotation_offset <= 2:
        raise DomainError("invalid_rotation_offset", http_status=422)

    if started_on is not None and local_date < started_on:
        return CcDayResult(
            local_date=local_date,
            day_index=None,
            is_rest_day=True,
            before_started_on=True,
            anchor_weekday=anchor_weekday,
            rotation_offset=rotation_offset,
        )

    wd = local_date.isoweekday()  # 1=Mon … 7=Sun
    offset = (wd - anchor_weekday + 7) % 7
    day_map = {0: 1, 2: 2, 4: 3}
    raw = day_map.get(offset)
    if raw is None:
        return CcDayResult(
            local_date=local_date,
            day_index=None,
            is_rest_day=True,
            before_started_on=False,
            anchor_weekday=anchor_weekday,
            rotation_offset=rotation_offset,
        )

    day_index = ((raw - 1 + rotation_offset) % 3) + 1
    return CcDayResult(
        local_date=local_date,
        day_index=day_index,
        is_rest_day=False,
        before_started_on=False,
        anchor_weekday=anchor_weekday,
        rotation_offset=rotation_offset,
    )


async def promote_pending_schedule(
    db: AsyncSession,
    user: User,
    enrollment: UserProgramEnrollment | None,
    *,
    local_date: date,
) -> None:
    """Promote pending TZ / anchor when local_date >= effective_on (FR-022b / FR-040c)."""
    changed = False
    if (
        user.pending_timezone is not None
        and user.timezone_effective_on is not None
        and local_date >= user.timezone_effective_on
    ):
        user.timezone = user.pending_timezone
        user.pending_timezone = None
        user.timezone_effective_on = None
        changed = True

    if (
        enrollment is not None
        and enrollment.pending_anchor_weekday is not None
        and enrollment.schedule_effective_on is not None
        and local_date >= enrollment.schedule_effective_on
    ):
        enrollment.anchor_weekday = enrollment.pending_anchor_weekday
        enrollment.pending_anchor_weekday = None
        enrollment.schedule_effective_on = None
        changed = True

    if changed:
        await db.flush()


async def get_active_enrollment(
    db: AsyncSession, user_id: object
) -> UserProgramEnrollment | None:
    row = await db.scalar(
        select(UserProgramEnrollment).where(
            UserProgramEnrollment.user_id == user_id,
            UserProgramEnrollment.is_active.is_(True),
        )
    )
    return row if isinstance(row, UserProgramEnrollment) else None


async def resolve_cc_day_for_user(
    db: AsyncSession,
    user: User,
    *,
    local_date: date,
) -> CcDayResult:
    enrollment = await get_active_enrollment(db, user.id)
    await promote_pending_schedule(db, user, enrollment, local_date=local_date)
    if enrollment is None:
        raise DomainError("enrollment_required", http_status=422)
    return resolve_cc_day(
        local_date,
        anchor_weekday=enrollment.anchor_weekday,
        rotation_offset=enrollment.rotation_offset,
        started_on=enrollment.started_on,
    )
