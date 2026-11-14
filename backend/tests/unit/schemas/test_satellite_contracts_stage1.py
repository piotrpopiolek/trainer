"""Stage 1 satellite contract rejection matrix + dispatcher + JCS golden vectors."""

from __future__ import annotations

import json
from pathlib import Path

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

_VECTORS = Path(__file__).resolve().parents[2] / "fixtures" / "satellite_jcs_vectors.json"


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
