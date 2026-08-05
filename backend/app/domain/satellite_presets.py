"""Golden satellite presets from the independent satellite-engine plan.

Product create templates — not CC catalog rows. Each call mints fresh step IDs
and client_mutation_id so users get an owned copy.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from app.core.ids import new_uuid7

SatellitePresetId = Literal["sl_hip_thrust_db", "copenhagen_plank"]

PRESET_IDS: tuple[SatellitePresetId, ...] = ("sl_hip_thrust_db", "copenhagen_plank")

_PRESET_META: dict[SatellitePresetId, dict[str, str]] = {
    "sl_hip_thrust_db": {
        "default_name": "SL Hip Thrust (DB)",
        "summary": "goal_only · reps + weight + sides · Mon/Wed/Fri",
    },
    "copenhagen_plank": {
        "default_name": "Copenhagen Plank",
        "summary": "steps · duration + sides · post_workout",
    },
}


def list_satellite_presets() -> list[dict[str, str]]:
    return [
        {
            "id": preset_id,
            "default_name": _PRESET_META[preset_id]["default_name"],
            "summary": _PRESET_META[preset_id]["summary"],
        }
        for preset_id in PRESET_IDS
    ]


def build_satellite_preset_create(
    preset_id: SatellitePresetId,
    *,
    client_mutation_id: UUID | None = None,
    name: str | None = None,
    step_ids: list[UUID] | None = None,
    config_version_id: UUID | None = None,
) -> dict[str, Any]:
    """Return a SatelliteCreateV1-compatible dict for the given golden preset."""
    if preset_id == "sl_hip_thrust_db":
        return _hip_thrust_body(
            client_mutation_id=client_mutation_id or new_uuid7(),
            name=name,
            step_ids=step_ids,
            config_version_id=config_version_id,
        )
    if preset_id == "copenhagen_plank":
        return _copenhagen_body(
            client_mutation_id=client_mutation_id or new_uuid7(),
            name=name,
            step_ids=step_ids,
            config_version_id=config_version_id,
        )
    raise ValueError(f"unknown_satellite_preset:{preset_id}")


def _step_id(step_ids: list[UUID] | None, index: int) -> str:
    if step_ids is not None and index < len(step_ids):
        return str(step_ids[index])
    return str(new_uuid7())


def _hip_thrust_body(
    *,
    client_mutation_id: UUID,
    name: str | None,
    step_ids: list[UUID] | None,
    config_version_id: UUID | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": 1,
        "name": name or _PRESET_META["sl_hip_thrust_db"]["default_name"],
        "exercise_type": "B",
        "active_metrics": {
            "schema_version": 1,
            "metrics": ["reps", "sides", "weight_kg"],
        },
        "equipment": ["dumbbell", "bench"],
        "schedule_kind": "weekdays",
        "weekdays": [1, 3, 5],
        "progression": {"mode": "goal_only"},
        "steps": [
            {
                "step_number": 1,
                "step_id": _step_id(step_ids, 0),
                "name": "Working sets",
                "rules": {
                    "schema_version": 1,
                    "goal": {
                        "type": "reps",
                        "sets": 3,
                        "min_reps": 10,
                        "require_both_sides": True,
                        "min_weight_kg": None,
                    },
                },
            }
        ],
        "client_mutation_id": str(client_mutation_id),
    }
    if config_version_id is not None:
        body["config_version_id"] = str(config_version_id)
    return body


def _copenhagen_body(
    *,
    client_mutation_id: UUID,
    name: str | None,
    step_ids: list[UUID] | None,
    config_version_id: UUID | None,
) -> dict[str, Any]:
    def duration_goal(*, sets: int, min_duration_sec: int) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "goal": {
                "type": "duration",
                "sets": sets,
                "min_duration_sec": min_duration_sec,
                "require_both_sides": True,
            },
        }

    body: dict[str, Any] = {
        "schema_version": 1,
        "name": name or _PRESET_META["copenhagen_plank"]["default_name"],
        "exercise_type": "B",
        "active_metrics": {
            "schema_version": 1,
            "metrics": ["duration_sec", "sides"],
        },
        "equipment": ["bench"],
        "schedule_kind": "category",
        "schedule_category": "post_workout",
        "progression": {
            "mode": "steps",
            "regression": {
                "mode": "suggest_after_failed_days",
                "threshold": 2,
            },
        },
        "steps": [
            {
                "step_number": 1,
                "step_id": _step_id(step_ids, 0),
                "name": "Short lever hold",
                "rules": duration_goal(sets=3, min_duration_sec=20),
            },
            {
                "step_number": 2,
                "step_id": _step_id(step_ids, 1),
                "name": "Long lever hold",
                "rules": duration_goal(sets=3, min_duration_sec=20),
            },
            {
                "step_number": 3,
                "step_id": _step_id(step_ids, 2),
                "name": "Long lever with bottom leg lifted",
                "rules": duration_goal(sets=3, min_duration_sec=15),
            },
        ],
        "client_mutation_id": str(client_mutation_id),
    }
    if config_version_id is not None:
        body["config_version_id"] = str(config_version_id)
    return body
