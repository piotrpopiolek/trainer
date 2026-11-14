"""Dispatcher routes only by exercise_kind. Orchestrators are mocked."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.errors import DomainError
from app.services.progression_dispatcher import ProgressionDispatcher


@pytest.mark.asyncio
async def test_dispatcher_routes_only_by_exercise_kind() -> None:
    dispatcher = ProgressionDispatcher()
    cc_calls: list[str] = []
    sat_calls: list[str] = []

    async def cc_eval(db, log, *, session):
        cc_calls.append(log.exercise_kind)
        return (
            SimpleNamespace(is_tip=True, progression_skipped=None, goal_met=True),
            ["cc-event"],
        )

    async def sat_eval(db, log, *, session):
        sat_calls.append(log.exercise_kind)
        return (
            SimpleNamespace(is_tip=False, progression_skipped=None, goal_met=True),
            [],
        )

    dispatcher._cc.evaluate_log = AsyncMock(side_effect=cc_eval)  # type: ignore[method-assign]
    dispatcher._satellite.evaluate_log = AsyncMock(side_effect=sat_eval)  # type: ignore[method-assign]

    # Satellite-shaped payload must not divert a CC log.
    cc_log = SimpleNamespace(
        exercise_kind="cc",
        sets={"schema_version": 1, "completed": True, "sets": []},
    )
    sat_log = SimpleNamespace(
        exercise_kind="satellite",
        sets={"schema_version": 1, "sets": [{"reps": 10}]},
    )
    session = SimpleNamespace()

    cc_result = await dispatcher.evaluate_log(None, cc_log, session=session)
    sat_result = await dispatcher.evaluate_log(None, sat_log, session=session)

    assert cc_calls == ["cc"]
    assert sat_calls == ["satellite"]
    assert cc_result.events == ["cc-event"]
    assert sat_result.events == []

    with pytest.raises(DomainError) as exc:
        await dispatcher.evaluate_log(
            None, SimpleNamespace(exercise_kind="other"), session=session
        )
    assert exc.value.error_code == "exercise_kind_mismatch"
