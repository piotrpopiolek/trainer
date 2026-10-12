"""Read-model for satellite progress charts (no re-evaluate; aggregate logged sets)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Exercise, ExerciseStep, SatelliteConfigVersion
from app.models.progression import UserExerciseProgress
from app.models.workout import SessionExerciseLog, WorkoutSession
from app.schemas.api import (
    SatelliteProgressItemV1,
    SatelliteProgressListV1,
    SatelliteProgressPointV1,
)
from app.schemas.satellite import parse_satellite_config_document
from app.services.errors import NotFoundError
from app.services.sessions import summarize_sets_payload


def _local_today(timezone_name: str) -> date:
    try:
        return datetime.now(ZoneInfo(timezone_name)).date()
    except ZoneInfoNotFoundError:
        return datetime.now(UTC).date()


def _parse_weight(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        d = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    if not d.is_finite() or d < 0:
        return None
    return float(d)


def aggregate_sets_point(
    *,
    local_date: date,
    goal_met: bool,
    sets_doc: dict[str, Any] | None,
) -> SatelliteProgressPointV1:
    """Max per metric for the day; L/P kept separately when sides are present."""
    completed: bool | None = None
    best_reps: int | None = None
    best_duration_sec: int | None = None
    best_weight_kg: float | None = None
    best_reps_left: int | None = None
    best_reps_right: int | None = None
    best_duration_left: int | None = None
    best_duration_right: int | None = None
    best_weight_left: float | None = None
    best_weight_right: float | None = None

    if not sets_doc or not isinstance(sets_doc, dict):
        return SatelliteProgressPointV1(
            local_date=local_date,
            goal_met=goal_met,
            completed=None,
        )

    if "completed" in sets_doc:
        raw_c = sets_doc.get("completed")
        if isinstance(raw_c, bool):
            completed = raw_c

    rows = sets_doc.get("sets")
    if not isinstance(rows, list):
        return SatelliteProgressPointV1(
            local_date=local_date,
            goal_met=goal_met,
            completed=completed,
        )

    for row in rows:
        if not isinstance(row, dict):
            continue
        side = row.get("sides")
        reps = row.get("reps")
        dur = row.get("duration_sec")
        weight = _parse_weight(row.get("weight_kg"))

        if isinstance(reps, (int, float)) and not isinstance(reps, bool):
            ri = int(reps)
            best_reps = ri if best_reps is None else max(best_reps, ri)
            if side == "left":
                best_reps_left = ri if best_reps_left is None else max(best_reps_left, ri)
            elif side == "right":
                best_reps_right = (
                    ri if best_reps_right is None else max(best_reps_right, ri)
                )

        if isinstance(dur, (int, float)) and not isinstance(dur, bool):
            di = int(dur)
            best_duration_sec = (
                di if best_duration_sec is None else max(best_duration_sec, di)
            )
            if side == "left":
                best_duration_left = (
                    di if best_duration_left is None else max(best_duration_left, di)
                )
            elif side == "right":
                best_duration_right = (
                    di if best_duration_right is None else max(best_duration_right, di)
                )

        if weight is not None:
            best_weight_kg = (
                weight if best_weight_kg is None else max(best_weight_kg, weight)
            )
            if side == "left":
                best_weight_left = (
                    weight if best_weight_left is None else max(best_weight_left, weight)
                )
            elif side == "right":
                best_weight_right = (
                    weight
                    if best_weight_right is None
                    else max(best_weight_right, weight)
                )

    return SatelliteProgressPointV1(
        local_date=local_date,
        goal_met=goal_met,
        completed=completed,
        best_reps=best_reps,
        best_duration_sec=best_duration_sec,
        best_weight_kg=best_weight_kg,
        best_reps_left=best_reps_left,
        best_reps_right=best_reps_right,
        best_duration_left=best_duration_left,
        best_duration_right=best_duration_right,
        best_weight_left=best_weight_left,
        best_weight_right=best_weight_right,
    )


async def list_satellite_progress(
    db: AsyncSession,
    *,
    user_id: UUID,
    timezone_name: str,
) -> SatelliteProgressListV1:
    exercises = (
        await db.scalars(
            select(Exercise).where(
                Exercise.user_id == user_id,
                Exercise.kind == "satellite",
                Exercise.deleted_at.is_(None),
            )
        )
    ).all()
    if not exercises:
        return SatelliteProgressListV1(items=[])

    today = _local_today(timezone_name)
    since = today - timedelta(days=89)
    exercise_ids = [ex.id for ex in exercises]

    progress_rows = (
        await db.scalars(
            select(UserExerciseProgress).where(
                UserExerciseProgress.user_id == user_id,
                UserExerciseProgress.exercise_id.in_(exercise_ids),
            )
        )
    ).all()
    progress_by_ex = {p.exercise_id: p for p in progress_rows}

    steps = (
        await db.scalars(
            select(ExerciseStep).where(ExerciseStep.exercise_id.in_(exercise_ids))
        )
    ).all()
    steps_by_ex: dict[UUID, list[ExerciseStep]] = {}
    for s in steps:
        steps_by_ex.setdefault(s.exercise_id, []).append(s)
    for sid in steps_by_ex:
        steps_by_ex[sid].sort(key=lambda x: x.step_number)

    cfg_ids = [
        ex.current_config_version_id
        for ex in exercises
        if ex.current_config_version_id is not None
    ]
    configs: dict[UUID, SatelliteConfigVersion] = {}
    if cfg_ids:
        for cfg in (
            await db.scalars(
                select(SatelliteConfigVersion).where(
                    SatelliteConfigVersion.id.in_(cfg_ids)
                )
            )
        ).all():
            configs[cfg.id] = cfg

    logs = (
        await db.scalars(
            select(SessionExerciseLog)
            .join(WorkoutSession, WorkoutSession.id == SessionExerciseLog.session_id)
            .where(
                SessionExerciseLog.user_id == user_id,
                SessionExerciseLog.exercise_id.in_(exercise_ids),
                SessionExerciseLog.exercise_kind == "satellite",
                SessionExerciseLog.skipped.is_(False),
                SessionExerciseLog.superseded_at.is_(None),
                WorkoutSession.deleted_at.is_(None),
                SessionExerciseLog.local_date >= since,
                SessionExerciseLog.local_date <= today,
            )
            .order_by(
                SessionExerciseLog.exercise_id,
                SessionExerciseLog.local_date.asc(),
                SessionExerciseLog.performed_at.desc(),
                SessionExerciseLog.id.desc(),
            )
        )
    ).all()

    # Newest log wins per (exercise, local_date).
    points_by_ex: dict[UUID, dict[date, SatelliteProgressPointV1]] = {}
    for log in logs:
        by_date = points_by_ex.setdefault(log.exercise_id, {})
        if log.local_date in by_date:
            continue
        sets_doc = log.sets if isinstance(log.sets, dict) else None
        by_date[log.local_date] = aggregate_sets_point(
            local_date=log.local_date,
            goal_met=bool(log.goal_met),
            sets_doc=sets_doc,
        )

    items: list[SatelliteProgressItemV1] = []
    for ex in sorted(exercises, key=lambda e: (e.name or "", str(e.id))):
        prog = progress_by_ex.get(ex.id)
        ex_steps = steps_by_ex.get(ex.id, [])
        current_n = prog.current_step_number if prog is not None else 1
        current_name: str | None = None
        for st in ex_steps:
            if st.step_number == current_n:
                current_name = st.name
                break

        progression: dict[str, Any] | None = None
        if ex.current_config_version_id is not None:
            config_version = configs.get(ex.current_config_version_id)
            if config_version is not None:
                try:
                    progression = parse_satellite_config_document(
                        config_version.document
                    ).progression.model_dump(mode="json")
                except Exception:
                    progression = None

        last_summary: str | None = None
        last_at = prog.last_session_at if prog is not None else None
        pts_map = points_by_ex.get(ex.id, {})
        if pts_map:
            # Re-load newest sets summary from most recent local_date in window.
            newest_date = max(pts_map.keys())
            newest_log = next(
                (
                    lg
                    for lg in logs
                    if lg.exercise_id == ex.id and lg.local_date == newest_date
                ),
                None,
            )
            if newest_log is not None:
                last_summary = summarize_sets_payload(
                    newest_log.sets if isinstance(newest_log.sets, dict) else None
                )

        points = [pts_map[d] for d in sorted(pts_map.keys())]
        items.append(
            SatelliteProgressItemV1(
                id=ex.id,
                name=ex.name or "",
                exercise_type=ex.exercise_type,
                schedule_kind=ex.schedule_kind,
                weekdays=list(ex.weekdays) if ex.weekdays is not None else None,
                schedule_category=ex.schedule_category,
                progression=progression,
                current_step_number=current_n,
                current_step_name=current_name,
                steps_count=len(ex_steps),
                active_metrics=ex.active_metrics if isinstance(ex.active_metrics, dict) else {},
                last_session_at=last_at,
                last_session_summary=last_summary,
                points=points,
                steps=[
                    {
                        "step_id": str(s.id),
                        "step_number": s.step_number,
                        "name": s.name,
                        "rules": s.rules,
                    }
                    for s in ex_steps
                ],
            )
        )

    return SatelliteProgressListV1(items=items)


async def get_satellite_progress_item(
    db: AsyncSession,
    *,
    user_id: UUID,
    exercise_id: UUID,
    timezone_name: str,
) -> SatelliteProgressItemV1:
    listed = await list_satellite_progress(
        db, user_id=user_id, timezone_name=timezone_name
    )
    for item in listed.items:
        if item.id == exercise_id:
            return item
    raise NotFoundError()
