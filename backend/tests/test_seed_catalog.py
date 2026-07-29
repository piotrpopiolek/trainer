"""Seed catalog structure + idempotent DB apply."""

import json
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.seed.content_gate import run_content_gate, soft_structure_ok, strict_ready_ok
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
    assert all(s.get("content_status") == "ready" for s in pl["steps"])
    assert pl["catalog_version"] >= 2
    assert "[DRAFT]" not in json.dumps(pl, ensure_ascii=False)
    legal = load_json("legal", "documents.json")
    legal_pl = load_json("legal", "pl-PL.json")
    assert {d["slug"] for d in legal["documents"]} >= {
        "health_disclaimer",
        "privacy_policy",
    }
    assert "[DRAFT]" not in json.dumps(legal_pl, ensure_ascii=False)
    assert "backup" in json.dumps(legal_pl, ensure_ascii=False).lower() or (
        "kopie zapasowe" in json.dumps(legal_pl, ensure_ascii=False).lower()
    )


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


def test_content_gate_strict_passes_ready_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRAINER_CONTENT_GATE_STRICT", "1")
    code, msg = run_content_gate()
    assert code == 0
    assert "strict ready ok" in msg


def test_content_gate_strict_fails_on_draft_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cc = tmp_path / "cc"
    (cc / "pl-PL").mkdir(parents=True)
    entities = json.loads((SEED_ROOT / "cc" / "entities.json").read_text(encoding="utf-8"))
    pl = json.loads(
        (SEED_ROOT / "cc" / "pl-PL" / "catalog.json").read_text(encoding="utf-8")
    )
    pl["steps"][0]["content_status"] = "draft"
    pl["steps"][0]["name"] = "[DRAFT] broken"
    (cc / "entities.json").write_text(
        json.dumps(entities, ensure_ascii=False), encoding="utf-8"
    )
    (cc / "pl-PL" / "catalog.json").write_text(
        json.dumps(pl, ensure_ascii=False), encoding="utf-8"
    )
    ok, _ = soft_structure_ok(tmp_path)
    assert ok
    ok, msg = strict_ready_ok(tmp_path)
    assert not ok
    assert "strict gate failed" in msg
    monkeypatch.setenv("TRAINER_CONTENT_GATE_STRICT", "1")


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
                    "WHERE e.kind = 'cc' AND est.locale = 'pl-PL' "
                    "AND est.content_status = 'ready'"
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
