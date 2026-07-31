"""Stage 1 satellite contract rejection matrix + dispatcher + JCS golden vectors."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.domain.canonical_json import canonicalize, sha256_jcs_hex
from app.schemas.satellite import (
    ActiveMetricsV1,
    SatelliteConfigDocumentV1,
    SatelliteConfigStepV1,
    SatelliteGoalRepsV1,
    SatelliteLogResultV1,
    SatelliteProgressionPolicyGoalOnlyV1,
    SatelliteRulesV1,
    SatelliteSetV1,
    parse_satellite_rules,
)
from app.services.errors import DomainError
from app.services.progression_dispatcher import ProgressionDispatcher

_VECTORS = Path(__file__).resolve().parent / "fixtures" / "satellite_jcs_vectors.json"


def test_jcs_golden_vectors_match_shared_fixture() -> None:
    payload = json.loads(_VECTORS.read_text(encoding="utf-8"))
    assert payload["vectors"], "expected at least one golden vector"
    for vector in payload["vectors"]:
        doc = vector["document"]
        assert canonicalize(doc) == vector["jcs"]
        assert sha256_jcs_hex(doc) == vector["sha256_hex"]


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "reps", "sets": 0, "min_reps": 10},
        {"type": "reps", "sets": 1, "min_reps": 0},
        {"type": "duration", "sets": 1, "min_duration_sec": 0},
    ],
)
def test_rejects_zero_goal_thresholds(payload: dict) -> None:
    with pytest.raises(ValidationError):
        if payload["type"] == "reps":
            SatelliteGoalRepsV1.model_validate(payload)
        else:
            SatelliteRulesV1.model_validate(
                {"schema_version": 1, "goal": payload}
            )


def test_rejects_float_weight_kg() -> None:
    with pytest.raises(ValidationError):
        SatelliteSetV1.model_validate({"reps": 10, "weight_kg": 20.0})


def test_rejects_bad_sides() -> None:
    with pytest.raises(ValidationError):
        SatelliteSetV1.model_validate({"reps": 10, "sides": "L"})


def test_rejects_empty_set() -> None:
    with pytest.raises(ValidationError):
        SatelliteSetV1.model_validate({})


@pytest.mark.parametrize("banned", ["advance", "regress", "standards", "fail_sessions"])
def test_rejects_cc_fields_on_satellite_rules(banned: str) -> None:
    payload = {
        "schema_version": 1,
        "goal": {"type": "reps", "sets": 3, "min_reps": 10},
        banned: {"sets": 3},
    }
    with pytest.raises((ValidationError, DomainError)):
        parse_satellite_rules(payload)


def test_rejects_missing_active_metric_sides_for_both_sides_goal() -> None:
    with pytest.raises(ValidationError):
        SatelliteConfigDocumentV1(
            schema_version=1,
            exercise_type="B",
            active_metrics=ActiveMetricsV1(schema_version=1, metrics=["reps"]),
            progression=SatelliteProgressionPolicyGoalOnlyV1(mode="goal_only"),
            steps=[
                SatelliteConfigStepV1(
                    step_id="01900000-0000-7000-8000-000000000001",
                    sort_order=1,
                    rules=SatelliteRulesV1(
                        schema_version=1,
                        goal=SatelliteGoalRepsV1(
                            type="reps",
                            sets=3,
                            min_reps=10,
                            require_both_sides=True,
                        ),
                    ),
                )
            ],
        )


def test_rejects_type_c_with_reps_goal() -> None:
    with pytest.raises(ValidationError):
        SatelliteConfigDocumentV1(
            schema_version=1,
            exercise_type="C",
            active_metrics=ActiveMetricsV1(schema_version=1, metrics=[]),
            progression=SatelliteProgressionPolicyGoalOnlyV1(mode="goal_only"),
            steps=[
                SatelliteConfigStepV1(
                    step_id="01900000-0000-7000-8000-000000000002",
                    sort_order=1,
                    rules=SatelliteRulesV1(
                        schema_version=1,
                        goal=SatelliteGoalRepsV1(type="reps", sets=1, min_reps=1),
                    ),
                )
            ],
        )


def test_log_result_accepts_completed_without_sets() -> None:
    parsed = SatelliteLogResultV1.model_validate(
        {"schema_version": 1, "completed": True, "sets": []}
    )
    assert parsed.completed is True
    assert parsed.sets == []


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
        return SimpleNamespace(is_tip=False, progression_skipped=None, goal_met=True)

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
