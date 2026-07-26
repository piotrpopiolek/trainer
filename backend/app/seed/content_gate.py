"""Content completeness gate for CC catalog (FR-020a / FR-084)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.seed.loader import SEED_ROOT

ENTITIES = SEED_ROOT / "cc" / "entities.json"
PL_CATALOG = SEED_ROOT / "cc" / "pl-PL" / "catalog.json"


def soft_structure_ok(seed_root: Path | None = None) -> tuple[bool, str]:
    root = seed_root or SEED_ROOT
    entities_path = root / "cc" / "entities.json"
    pl_path = root / "cc" / "pl-PL" / "catalog.json"
    if not entities_path.is_file() or not pl_path.is_file():
        return False, "missing backend/seed/cc entities or pl-PL catalog JSON"

    entities = json.loads(entities_path.read_text(encoding="utf-8"))
    pl = json.loads(pl_path.read_text(encoding="utf-8"))

    exercises = entities.get("exercises") or []
    steps_n = int(entities.get("steps_per_exercise") or 0)
    if len(exercises) != 6 or steps_n != 10:
        return False, f"expected 6 exercises × 10 steps, got {len(exercises)}×{steps_n}"

    if len(pl.get("exercises") or []) != 6:
        return False, "pl-PL catalog must translate 6 exercises"
    if len(pl.get("days") or []) != 3:
        return False, "pl-PL catalog must translate 3 days"
    if len(pl.get("steps") or []) != 60:
        return False, (
            "pl-PL catalog must have 60 step translations, "
            f"got {len(pl.get('steps') or [])}"
        )

    return True, "structure ok (draft allowed until F1.prod)"


def strict_ready_ok(seed_root: Path | None = None) -> tuple[bool, str]:
    root = seed_root or SEED_ROOT
    pl_path = root / "cc" / "pl-PL" / "catalog.json"
    pl = json.loads(pl_path.read_text(encoding="utf-8"))
    drafts: list[str] = []
    for step in pl.get("steps") or []:
        status = step.get("content_status")
        name = step.get("name") or ""
        description = step.get("description") or ""
        label = f"{step.get('exercise_slug')}#{step.get('step_number')}"
        if status != "ready":
            drafts.append(f"{label}:status")
        if not name.strip() or "[DRAFT]" in name:
            drafts.append(f"{label}:name")
        if not description.strip() or "[DRAFT]" in description:
            drafts.append(f"{label}:description")
    prog = pl.get("program") or {}
    if "[DRAFT]" in (prog.get("name") or "") or "[DRAFT]" in (prog.get("description") or ""):
        drafts.append("program")
    if drafts:
        return False, f"strict gate failed ({len(drafts)} issues); e.g. {drafts[0]}"
    return True, "strict ready ok"


def run_content_gate(*, strict: bool | None = None) -> tuple[int, str]:
    if strict is None:
        strict = os.environ.get("TRAINER_CONTENT_GATE_STRICT", "0") == "1"

    seed_present = SEED_ROOT.exists() and any(SEED_ROOT.rglob("*.json"))
    if not seed_present:
        msg = "content gate: no seed JSON yet (expected after seed-catalog)"
        if strict:
            return 1, msg
        return 0, f"{msg} - soft pass"

    ok, detail = soft_structure_ok()
    if not ok:
        return 1, f"content gate: {detail}"

    if strict:
        ok, detail = strict_ready_ok()
        if not ok:
            return 1, f"content gate: {detail}"
        return 0, f"content gate: {detail}"

    return 0, f"content gate: soft mode — {detail}"
