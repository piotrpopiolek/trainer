"""GET /sync/pull — initial + incremental (FR-070 / FR-075)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_uuid7
from app.models.body_measurement import BodyMeasurement
from app.models.catalog import Exercise, Program, ProgramTranslation
from app.models.progression import ProgressionEvent, UserExerciseProgress
from app.models.sync import SyncConflictLog, SyncDevice
from app.models.user import User
from app.models.workout import WorkoutSession
from app.schemas.sync import SyncPullResponseV1, SyncTombstoneV1
from app.services import satellites as satellite_service
from app.services.locale import resolve_locale
from app.services.sessions import progress_to_read, session_to_read

SESSION_WINDOW = 30
MEASUREMENT_DAYS = 365
RESYNC_AFTER_DAYS = 30


async def _catalog_version(db: AsyncSession, *, locale: str) -> int | None:
    program = await db.scalar(select(Program).where(Program.slug == "cc_big_six"))
    if program is None:
        return None
    tr = await db.scalar(
        select(ProgramTranslation).where(
            ProgramTranslation.program_id == program.id,
            ProgramTranslation.locale == locale,
        )
    )
    return tr.catalog_version if tr is not None else None


async def pull(
    db: AsyncSession,
    *,
    user: User,
    since: datetime | None,
    locale: str | None,
    device_id: str | None,
) -> SyncPullResponseV1:
    server_time = datetime.now(UTC)
    requested, resolved = resolve_locale(requested=locale, user_locale=user.locale)
    resync_required = False
    effective_since = since

    if since is not None:
        if since.tzinfo is None:
            since = since.replace(tzinfo=UTC)
            effective_since = since
        if since < server_time - timedelta(days=RESYNC_AFTER_DAYS):
            resync_required = True
            effective_since = None

    # Sessions: initial ≤30 active by performed_at; incremental updated_at > since (+ tombstones)
    tombstones: list[SyncTombstoneV1] = []
    if effective_since is None:
        sessions_rows = (
            await db.scalars(
                select(WorkoutSession)
                .where(
                    WorkoutSession.user_id == user.id,
                    WorkoutSession.deleted_at.is_(None),
                )
                .order_by(WorkoutSession.performed_at.desc())
                .limit(SESSION_WINDOW)
            )
        ).all()
    else:
        sessions_rows = (
            await db.scalars(
                select(WorkoutSession).where(
                    WorkoutSession.user_id == user.id,
                    WorkoutSession.updated_at > effective_since,
                )
            )
        ).all()
        for s in sessions_rows:
            if s.deleted_at is not None:
                tombstones.append(
                    SyncTombstoneV1(
                        entity_type="workout_session",
                        id=s.id,
                        deleted_at=s.deleted_at,
                        revision=s.revision,
                    )
                )
        sessions_rows = [s for s in sessions_rows if s.deleted_at is None]

    sessions_out = [
        (await session_to_read(db, s)).model_dump(mode="json") for s in sessions_rows
    ]

    # Measurements window 365d
    from sqlalchemy import text

    await db.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(user.id)},
    )
    meas_cutoff = server_time - timedelta(days=MEASUREMENT_DAYS)
    if effective_since is None:
        meas_rows = (
            await db.scalars(
                select(BodyMeasurement).where(
                    BodyMeasurement.user_id == user.id,
                    BodyMeasurement.deleted_at.is_(None),
                    BodyMeasurement.measured_at >= meas_cutoff,
                )
            )
        ).all()
    else:
        meas_rows = (
            await db.scalars(
                select(BodyMeasurement).where(
                    BodyMeasurement.user_id == user.id,
                    BodyMeasurement.updated_at > effective_since,
                )
            )
        ).all()
        for m in meas_rows:
            if m.deleted_at is not None:
                tombstones.append(
                    SyncTombstoneV1(
                        entity_type="body_measurement",
                        id=m.id,
                        deleted_at=m.deleted_at,
                        revision=m.revision,
                    )
                )
        meas_rows = [m for m in meas_rows if m.deleted_at is None]

    measurements_out = [
        {
            "id": str(m.id),
            "measured_at": m.measured_at.isoformat(),
            "local_date": m.local_date.isoformat(),
            "metrics": m.metrics,
            "notes": m.notes,
            "revision": m.revision,
            "updated_at": m.updated_at.isoformat(),
        }
        for m in meas_rows
    ]

    if effective_since is None:
        sats = await satellite_service.list_satellites(db, user_id=user.id)
        satellites_out = [s.model_dump(mode="json") for s in sats]
    else:
        sat_rows = (
            await db.scalars(
                select(Exercise).where(
                    Exercise.user_id == user.id,
                    Exercise.kind == "satellite",
                    Exercise.updated_at > effective_since,
                )
            )
        ).all()
        for sat in sat_rows:
            if sat.deleted_at is not None:
                tombstones.append(
                    SyncTombstoneV1(
                        entity_type="satellite",
                        id=sat.id,
                        deleted_at=sat.deleted_at,
                        revision=sat.revision,
                    )
                )
        active_ids = {sat.id for sat in sat_rows if sat.deleted_at is None}
        all_sats = await satellite_service.list_satellites(db, user_id=user.id)
        satellites_out = [
            sat.model_dump(mode="json") for sat in all_sats if sat.id in active_ids
        ]

    progress_rows = (
        await db.scalars(
            select(UserExerciseProgress).where(UserExerciseProgress.user_id == user.id)
        )
    ).all()

    events = (
        await db.scalars(
            select(ProgressionEvent)
            .where(ProgressionEvent.user_id == user.id)
            .order_by(ProgressionEvent.created_at.desc())
            .limit(100)
        )
    ).all()

    conflicts = (
        await db.scalars(
            select(SyncConflictLog)
            .where(SyncConflictLog.user_id == user.id)
            .order_by(SyncConflictLog.created_at.desc())
            .limit(50)
        )
    ).all()

    if device_id:
        row = await db.scalar(
            select(SyncDevice).where(
                SyncDevice.user_id == user.id,
                SyncDevice.device_id == device_id,
            )
        )
        if row is None:
            db.add(
                SyncDevice(
                    id=new_uuid7(),
                    user_id=user.id,
                    device_id=device_id,
                    last_pull_at=server_time,
                )
            )
        else:
            row.last_pull_at = server_time
        await db.commit()

    return SyncPullResponseV1(
        server_time=server_time,
        requested_locale=requested,
        resolved_locale=resolved,
        catalog_version=await _catalog_version(db, locale=resolved),
        resync_required=resync_required,
        sessions=sessions_out,
        measurements=measurements_out,
        satellites=satellites_out,
        progress=[progress_to_read(p).model_dump(mode="json") for p in progress_rows],
        progression_events=[
            {
                "id": str(e.id),
                "exercise_id": str(e.exercise_id),
                "event_type": e.event_type,
                "from_step": e.from_step,
                "to_step": e.to_step,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
        conflicts=[
            {
                "id": str(c.id),
                "entity_type": c.entity_type,
                "entity_id": str(c.entity_id),
                "conflict_kind": c.conflict_kind,
                "created_at": c.created_at.isoformat(),
            }
            for c in conflicts
        ],
        tombstones=tombstones,
    )
