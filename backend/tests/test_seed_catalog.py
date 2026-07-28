"""Seed catalog structure + idempotent DB apply."""

import json

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.seed.content_gate import run_content_gate
from app.seed.ids import seed_id
from app.seed.loader import SEED_ROOT, load_json
from app.seed.runner import legal_content_hash, run_seed


def test_seed_json_structure() -> None:
    entities = load_json("cc", "entities.json")
    pl = load_json("cc", "pl-PL", "catalog.json")
    assert entities["program"]["slug"] == "cc_big_six"
    assert len(entities["exercises"]) == 6
    assert entities["steps_per_exercise"] == 10
    assert len(entities["days"]) == 3
    assert len(pl["steps"]) == 60
    assert all(s.get("content_status") == "draft" for s in pl["steps"])
    legal = load_json("legal", "documents.json")
    assert {d["slug"] for d in legal["documents"]} >= {
        "health_disclaimer",
        "privacy_policy",
    }


def test_seed_ids_stable() -> None:
    assert seed_id("program", "cc_big_six") == seed_id("program", "cc_big_six")
    assert seed_id("exercise", "push_ups") != seed_id("exercise", "squats")


def test_legal_content_hash_deterministic() -> None:
    a = legal_content_hash("T", "B")
    b = legal_content_hash("T", "B")
    assert a == b
    assert isinstance(a, bytes)
    assert len(a) == 32


def test_content_gate_soft_passes_with_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRAINER_CONTENT_GATE_STRICT", "0")
    code, _msg = run_content_gate()
    assert code == 0


def test_content_gate_strict_fails_on_drafts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRAINER_CONTENT_GATE_STRICT", "1")
    code, msg = run_content_gate()
    assert code == 1
    assert "strict gate failed" in msg


@pytest.mark.asyncio
async def test_seed_runner_idempotent() -> None:
    first = await run_seed()
    second = await run_seed()
    assert first["exercises"] == 6
    assert first["exercise_steps"] == 60
    assert first["legal_documents"] == 2
    assert second["exercises"] == 6
    assert second["exercise_steps"] == 60

    engine = create_async_engine(settings.resolved_database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            cc = await conn.scalar(
                text("SELECT COUNT(*) FROM exercises WHERE kind = 'cc'")
            )
            steps = await conn.scalar(
                text(
                    "SELECT COUNT(*) FROM exercise_steps es "
                    "JOIN exercises e ON e.id = es.exercise_id "
                    "WHERE e.kind = 'cc'"
                )
            )
            step_tr = await conn.scalar(
                text(
                    "SELECT COUNT(*) FROM exercise_step_translations est "
                    "JOIN exercise_steps es ON es.id = est.exercise_step_id "
                    "JOIN exercises e ON e.id = es.exercise_id "
                    "WHERE e.kind = 'cc' AND est.locale = 'pl-PL'"
                )
            )
            days = await conn.scalar(text("SELECT COUNT(*) FROM program_days"))
    finally:
        await engine.dispose()

    assert cc == 6
    assert steps == 60
    assert step_tr == 60
    assert days == 3


def test_seed_root_points_at_backend_seed() -> None:
    assert SEED_ROOT.name == "seed"
    assert (SEED_ROOT / "cc" / "entities.json").is_file()
    json.loads((SEED_ROOT / "cc" / "pl-PL" / "catalog.json").read_text(encoding="utf-8"))
