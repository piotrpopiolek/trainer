"""Preset catalog bodies, no persistence."""

from __future__ import annotations

import pytest

from app.domain.satellite_presets import (
    PRESET_IDS,
    build_satellite_preset_create,
    list_satellite_presets,
)
from app.schemas.api import SatelliteCreateV1


def test_preset_catalog_lists_plan_fixtures() -> None:
    catalog = list_satellite_presets()
    assert [p["id"] for p in catalog] == list(PRESET_IDS)
    assert catalog[0]["default_name"] == "SL Hip Thrust (DB)"
    assert catalog[1]["default_name"] == "Copenhagen Plank"
    assert catalog[2]["default_name"] == "Zginanie przedramion siedząc"

@pytest.mark.parametrize("preset_id", list(PRESET_IDS))
def test_preset_bodies_validate_as_create_v1(preset_id: str) -> None:
    body = SatelliteCreateV1.model_validate(
        build_satellite_preset_create(preset_id)  # type: ignore[arg-type]
    )
    assert body.schema_version == 1
    if preset_id == "sl_hip_thrust_db":
        assert body.progression.mode == "goal_only"
        assert len(body.steps) == 1
        assert body.schedule_kind == "weekdays"
        assert body.weekdays == [1, 3, 5]
        assert set(body.active_metrics["metrics"]) == {"reps", "weight_kg", "sides"}
    elif preset_id == "seated_db_curl":
        assert body.name == "Zginanie przedramion siedząc"
        assert body.progression.mode == "goal_only"
        assert len(body.steps) == 1
        assert body.schedule_kind == "weekdays"
        assert body.weekdays == [2, 4, 6]
        assert body.steps[0].rules["goal"]["require_both_sides"] is True
        assert set(body.active_metrics["metrics"]) == {"reps", "weight_kg", "sides"}
    else:
        assert body.progression.mode == "steps"
        assert len(body.steps) == 3
        assert body.schedule_kind == "category"
        assert body.schedule_category == "post_workout"
        assert set(body.active_metrics["metrics"]) == {"duration_sec", "sides"}
