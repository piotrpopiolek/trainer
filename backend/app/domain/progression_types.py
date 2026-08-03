"""Neutral progression result types shared by CC and satellite orchestrators."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class EventProposal:
    event_type: str
    from_step: int
    to_step: int
    reason: str | None = None
    rules_snapshot: dict[str, Any] | None = None
    progression_schema_version: int | None = None


@dataclass(frozen=True, slots=True)
class ProgressStatePatch:
    current_step_number: int | None = None
    current_step_id: str | None = None
    fail_streak: int | None = None
    last_session_at_iso: str | None = None


@dataclass(frozen=True, slots=True)
class ProgressionEvaluation:
    goal_met: bool
    counts_for_progression: bool
    progression_skipped: str | None = None
    is_tip: bool = False
    rules_snapshot: dict[str, Any] | None = None
    progression_schema_version: int | None = None
    step_number: int | None = None
    progress_patch: ProgressStatePatch | None = None
    events: tuple[EventProposal, ...] = field(default_factory=tuple)
