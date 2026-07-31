"""Build backend/seed/cc/step_standards.json from the approved plan matrix."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend" / "seed" / "cc" / "step_standards.json"


def r(sets: int, reps: int, both: bool = False) -> dict:
    d: dict = {"sets": sets, "min_reps": reps, "require_both_sides": both}
    return d


def d(sec: int) -> dict:
    return {"sets": 1, "min_duration_sec": sec, "require_both_sides": False}


def row(slug: str, n: int, beg: dict, mid: dict, prog: dict) -> dict:
    return {
        "exercise_slug": slug,
        "step_number": n,
        "beginner": beg,
        "intermediate": mid,
        "progression": prog,
    }


STEPS: list[dict] = []

# push_ups
PU = [
    (1, r(1, 10), r(2, 25), r(3, 50)),
    (2, r(1, 10), r(2, 20), r(3, 40)),
    (3, r(1, 10), r(2, 15), r(3, 30)),
    (4, r(1, 8), r(2, 12), r(2, 25)),
    (5, r(1, 5), r(2, 10), r(2, 20)),
    (6, r(1, 5), r(2, 10), r(2, 20)),
    (7, r(1, 5, True), r(2, 10, True), r(2, 20, True)),
    (8, r(1, 5, True), r(2, 10, True), r(2, 20, True)),
    (9, r(1, 5, True), r(2, 10, True), r(2, 20, True)),
    (10, r(1, 5, True), r(2, 10, True), r(1, 100, True)),
]
for n, b, i, p in PU:
    STEPS.append(row("push_ups", n, b, i, p))

SQ = [
    (1, r(1, 10), r(2, 25), r(3, 50)),
    (2, r(1, 10), r(2, 20), r(3, 40)),
    (3, r(1, 10), r(2, 15), r(3, 30)),
    (4, r(1, 8), r(2, 35), r(2, 50)),
    (5, r(1, 5), r(2, 10), r(2, 30)),
    (6, r(1, 5), r(2, 10), r(2, 20)),
    (7, r(1, 5, True), r(2, 10, True), r(2, 20, True)),
    (8, r(1, 5, True), r(2, 10, True), r(2, 20, True)),
    (9, r(1, 5, True), r(2, 10, True), r(2, 20, True)),
    (10, r(1, 5, True), r(2, 10, True), r(2, 50, True)),
]
for n, b, i, p in SQ:
    STEPS.append(row("squats", n, b, i, p))

PL = [
    (1, r(1, 10), r(2, 20), r(3, 40)),
    (2, r(1, 10), r(2, 20), r(3, 30)),
    (3, r(1, 10), r(2, 15), r(3, 20)),
    (4, r(1, 8), r(2, 11), r(2, 15)),
    (5, r(1, 5), r(2, 8), r(2, 10)),
    (6, r(1, 5), r(2, 8), r(2, 10)),
    (7, r(1, 4, True), r(2, 6, True), r(2, 8, True)),
    (8, r(1, 3, True), r(2, 5, True), r(2, 8, True)),
    (9, r(1, 3, True), r(2, 5, True), r(2, 7, True)),
    (10, r(1, 1, True), r(2, 3, True), r(2, 6, True)),
]
for n, b, i, p in PL:
    STEPS.append(row("pull_ups", n, b, i, p))

LR = [
    (1, r(1, 10), r(2, 25), r(3, 40)),
    (2, r(1, 10), r(2, 20), r(3, 35)),
    (3, r(1, 10), r(2, 15), r(3, 30)),
    (4, r(1, 8), r(2, 15), r(3, 25)),
    (5, r(1, 5), r(2, 10), r(2, 20)),
    (6, r(1, 5), r(2, 10), r(2, 15)),
    (7, r(1, 5), r(2, 10), r(2, 15)),
    (8, r(1, 5), r(2, 10), r(2, 15)),
    (9, r(1, 5), r(2, 10), r(2, 15)),
    (10, r(1, 5), r(2, 10), r(2, 30)),
]
for n, b, i, p in LR:
    STEPS.append(row("leg_raises", n, b, i, p))

BR = [
    (1, r(1, 10), r(2, 25), r(3, 50)),
    (2, r(1, 10), r(2, 20), r(3, 40)),
    (3, r(1, 8), r(2, 15), r(3, 30)),
    (4, r(1, 8), r(2, 15), r(2, 25)),
    (5, r(1, 8), r(2, 15), r(2, 20)),
    (6, r(1, 6), r(2, 10), r(2, 15)),
    (7, r(1, 3), r(2, 6), r(2, 10)),
    (8, r(1, 2), r(2, 4), r(2, 8)),
    (9, r(1, 1), r(2, 3), r(2, 6)),
    (10, r(1, 1), r(2, 3), r(2, 10)),
]
for n, b, i, p in BR:
    STEPS.append(row("bridges", n, b, i, p))

HS = [
    (1, d(30), d(60), d(120)),
    (2, d(10), d(30), d(60)),
    (3, d(30), d(60), d(120)),
    (4, r(1, 5), r(2, 10), r(2, 20)),
    (5, r(1, 5), r(2, 10), r(2, 15)),
    (6, r(1, 5), r(2, 9), r(2, 12)),
    (7, r(1, 5, True), r(2, 8, True), r(2, 10, True)),
    (8, r(1, 4, True), r(2, 6, True), r(2, 8, True)),
    (9, r(1, 3, True), r(2, 4, True), r(2, 6, True)),
    (10, r(1, 1, True), r(2, 2, True), r(1, 5, True)),
]
for n, b, i, p in HS:
    STEPS.append(row("handstand_push_ups", n, b, i, p))


def main() -> None:
    assert len(STEPS) == 60, len(STEPS)
    payload = {"schema_version": 1, "steps": STEPS}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} steps={len(STEPS)}")


if __name__ == "__main__":
    main()
