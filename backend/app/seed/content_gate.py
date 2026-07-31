"""Content completeness gate for CC catalog (FR-020a / FR-084)."""

from __future__ import annotations

import json
import os
import re
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


def _has_draft_marker(value: str) -> bool:
    return "[DRAFT]" in value


def _nonempty_clean(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(text) and not _has_draft_marker(text)


def _sentence_count(text: str) -> int:
    """Count sentence-like units ending with . ! or ? (FR-020a: 2–6)."""
    parts = [p.strip() for p in re.split(r"[.!?]+", text) if p.strip()]
    return len(parts)


def strict_ready_ok(seed_root: Path | None = None) -> tuple[bool, str]:
    """F1.prod: program + 3 days + 6 exercises + 60 steps ready, no [DRAFT]."""
    root = seed_root or SEED_ROOT
    entities_path = root / "cc" / "entities.json"
    pl_path = root / "cc" / "pl-PL" / "catalog.json"
    entities = json.loads(entities_path.read_text(encoding="utf-8"))
    pl = json.loads(pl_path.read_text(encoding="utf-8"))
    issues: list[str] = []

    prog = pl.get("program") or {}
    if not _nonempty_clean(prog.get("name")):
        issues.append("program:name")
    if not _nonempty_clean(prog.get("description")):
        issues.append("program:description")

    days = pl.get("days") or []
    if len(days) != 3:
        issues.append("days:count")
    for day in days:
        idx = day.get("day_index")
        if not _nonempty_clean(day.get("name")):
            issues.append(f"day#{idx}:name")

    exercises = pl.get("exercises") or []
    if len(exercises) != 6:
        issues.append("exercises:count")
    for ex in exercises:
        slug = ex.get("slug") or "?"
        if not _nonempty_clean(ex.get("name")):
            issues.append(f"exercise:{slug}:name")
        if not _nonempty_clean(ex.get("description")):
            issues.append(f"exercise:{slug}:description")

    expected_slugs = [e["slug"] for e in (entities.get("exercises") or [])]
    steps_n = int(entities.get("steps_per_exercise") or 10)
    expected_keys = {(slug, n) for slug in expected_slugs for n in range(1, steps_n + 1)}

    steps = pl.get("steps") or []
    if len(steps) != 60:
        issues.append(f"steps:count={len(steps)}")
    seen: set[tuple[str, int]] = set()
    for step in steps:
        status = step.get("content_status")
        slug = str(step.get("exercise_slug") or "")
        try:
            num = int(step.get("step_number"))
        except (TypeError, ValueError):
            issues.append(f"{slug}#:bad_step_number")
            continue
        label = f"{slug}#{num}"
        key = (slug, num)
        if key in seen:
            issues.append(f"{label}:duplicate")
        seen.add(key)
        if status != "ready":
            issues.append(f"{label}:status")
        if not _nonempty_clean(step.get("name")):
            issues.append(f"{label}:name")
        desc = step.get("description") or ""
        if not _nonempty_clean(desc):
            issues.append(f"{label}:description")
        else:
            sc = _sentence_count(desc)
            if sc < 1 or sc > 6:
                issues.append(f"{label}:description_sentence_count={sc}")
        for field in ("execution", "rationale", "technique"):
            if not _nonempty_clean(step.get(field)):
                issues.append(f"{label}:{field}")

    missing = expected_keys - seen
    extra = seen - expected_keys
    for slug, num in sorted(missing)[:5]:
        issues.append(f"{slug}#{num}:missing")
    for slug, num in sorted(extra)[:5]:
        issues.append(f"{slug}#{num}:unexpected")

    if issues:
        return False, f"strict gate failed ({len(issues)} issues); e.g. {issues[0]}"
    return True, "strict ready ok (60× pl-PL ready)"


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
