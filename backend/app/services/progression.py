"""Progression facade — CC/satellite engines live behind the dispatcher.

Keep `goal_met_from_sets` for CC advance thresholds used by unit tests.
Satellite goals use `app.domain.satellite_progression.satellite_goal_met`.
"""

from __future__ import annotations

from typing import Any

from app.domain.cc_progression import cc_goal_met
from app.schemas.rules import ProgressionRules
from app.services.progression_dispatcher import EvaluateResult, ProgressionEngine

__all__ = [
    "EvaluateResult",
    "ProgressionEngine",
    "goal_met_from_sets",
]


def goal_met_from_sets(rules: ProgressionRules, sets_payload: dict[str, Any] | None) -> bool:
    """CC advance evaluation only — satellites must not call this."""
    return cc_goal_met(rules, sets_payload)
