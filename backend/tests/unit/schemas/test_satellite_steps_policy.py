"""Steps-policy schema and Copenhagen golden hash."""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas.satellite import (
    ActiveMetricsV1,
    SatelliteConfigDocumentV1,
    SatelliteConfigStepV1,
    SatelliteGoalDurationV1,
    SatelliteProgressionPolicyGoalOnlyV1,
    SatelliteProgressionPolicyStepsV1,
    SatelliteRegressionPolicyV1,
    SatelliteRulesV1,
)

_STEP1 = UUID("01900000-0000-7000-8000-000000000011")

_STEP2 = UUID("01900000-0000-7000-8000-000000000012")

_STEP3 = UUID("01900000-0000-7000-8000-000000000013")

_COPENHAGEN_HASH = "1ee79f4670ef0aa87275554ae230c3e66bb14004bd1fbd15cf8ab2b2af2e2b85"

def _duration_rules(*, min_duration_sec: int) -> dict:
    return {
        "schema_version": 1,
        "goal": {
            "type": "duration",
            "sets": 3,
            "min_duration_sec": min_duration_sec,
            "min_weight_kg": None,
            "require_both_sides": True,
        },
    }

def test_steps_policy_requires_regression_threshold() -> None:
    with pytest.raises(ValidationError):
        SatelliteProgressionPolicyStepsV1.model_validate({"mode": "steps"})
    with pytest.raises(ValidationError):
        SatelliteProgressionPolicyStepsV1.model_validate(
            {
                "mode": "steps",
                "regression": {"mode": "suggest_after_failed_days", "threshold": 0},
            }
        )
    ok = SatelliteProgressionPolicyStepsV1(
        mode="steps",
        regression=SatelliteRegressionPolicyV1(
            mode="suggest_after_failed_days", threshold=2
        ),
    )
    assert ok.regression.threshold == 2

def test_document_rejects_step_count_mismatch() -> None:
    step = SatelliteConfigStepV1(
        step_id=_STEP1,
        sort_order=1,
        rules=SatelliteRulesV1(
            schema_version=1,
            goal=SatelliteGoalDurationV1(
                type="duration",
                sets=3,
                min_duration_sec=20,
                require_both_sides=True,
            ),
        ),
    )
    with pytest.raises(ValidationError):
        SatelliteConfigDocumentV1(
            schema_version=1,
            exercise_type="B",
            active_metrics=ActiveMetricsV1(
                schema_version=1, metrics=["duration_sec", "sides"]
            ),
            progression=SatelliteProgressionPolicyStepsV1(
                mode="steps",
                regression=SatelliteRegressionPolicyV1(
                    mode="suggest_after_failed_days", threshold=2
                ),
            ),
            steps=[step],
        )
    with pytest.raises(ValidationError):
        SatelliteConfigDocumentV1(
            schema_version=1,
            exercise_type="B",
            active_metrics=ActiveMetricsV1(
                schema_version=1, metrics=["duration_sec", "sides"]
            ),
            progression=SatelliteProgressionPolicyGoalOnlyV1(mode="goal_only"),
            steps=[
                step,
                SatelliteConfigStepV1(
                    step_id=_STEP2,
                    sort_order=2,
                    rules=step.rules,
                ),
            ],
        )

def test_copenhagen_golden_vector_hash() -> None:
    """Fixed-ID document matches shared fixture (no DB)."""
    from app.domain.canonical_json import sha256_jcs_hex
    from app.schemas.satellite import SatelliteConfigDocumentV1

    doc = SatelliteConfigDocumentV1.model_validate(
        {
            "schema_version": 1,
            "exercise_type": "B",
            "active_metrics": {
                "schema_version": 1,
                "metrics": ["duration_sec", "sides"],
            },
            "progression": {
                "mode": "steps",
                "regression": {
                    "mode": "suggest_after_failed_days",
                    "threshold": 2,
                },
            },
            "steps": [
                {
                    "step_id": str(_STEP1),
                    "sort_order": 1,
                    "rules": _duration_rules(min_duration_sec=20),
                },
                {
                    "step_id": str(_STEP2),
                    "sort_order": 2,
                    "rules": _duration_rules(min_duration_sec=20),
                },
                {
                    "step_id": str(_STEP3),
                    "sort_order": 3,
                    "rules": _duration_rules(min_duration_sec=15),
                },
            ],
        }
    )
    assert sha256_jcs_hex(doc.model_dump(mode="json")) == _COPENHAGEN_HASH
