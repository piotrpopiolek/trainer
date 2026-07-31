"""Dispatch progression by verified exercise_kind — never by JSON shape."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.progression_types import ProgressionEvaluation  # noqa: F401 — typing/docs
from app.models.workout import SessionExerciseLog, WorkoutSession
from app.services.cc_progression import CcProgressionOrchestrator
from app.services.errors import DomainError
from app.services.satellite_progression import SatelliteProgressionOrchestrator


@dataclass(slots=True)
class EvaluateResult:
    """Compatibility envelope used by SessionService / sync."""

    is_tip: bool
    progression_skipped: str | None
    goal_met: bool
    events: list = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.events is None:
            self.events = []


class ProgressionDispatcher:
    def __init__(self) -> None:
        self._cc = CcProgressionOrchestrator()
        self._satellite = SatelliteProgressionOrchestrator()

    @property
    def cc(self) -> CcProgressionOrchestrator:
        return self._cc

    async def evaluate_log(
        self,
        db: AsyncSession,
        log: SessionExerciseLog,
        *,
        session: WorkoutSession,
    ) -> EvaluateResult:
        kind = log.exercise_kind
        if kind == "cc":
            result, events = await self._cc.evaluate_log(db, log, session=session)
            return EvaluateResult(
                is_tip=result.is_tip,
                progression_skipped=result.progression_skipped,
                goal_met=result.goal_met,
                events=events,
            )
        if kind == "satellite":
            result = await self._satellite.evaluate_log(db, log, session=session)
            return EvaluateResult(
                is_tip=result.is_tip,
                progression_skipped=result.progression_skipped,
                goal_met=result.goal_met,
                events=[],
            )
        raise DomainError("exercise_kind_mismatch", http_status=422)

    async def manual_override(self, db: AsyncSession, **kwargs):
        return await self._cc.manual_override(db, **kwargs)


# Composition root used by SessionService / progress router.
_dispatcher = ProgressionDispatcher()


class ProgressionEngine:
    """Thin facade preserving existing call sites during Stage 1 split."""

    async def evaluate_log(self, db, log, *, session):
        return await _dispatcher.evaluate_log(db, log, session=session)

    async def manual_override(self, db, **kwargs):
        return await _dispatcher.manual_override(db, **kwargs)

    async def is_tip_log(self, db, log):
        return await _dispatcher.cc.is_tip_log(db, log)
