"""Content completeness gate for CC catalog (FR-020a / FR-084).

Soft by default until F1.prod. Set TRAINER_CONTENT_GATE_STRICT=1 to fail
when seed translations are incomplete (program, 3 days, 6 exercises, 60 steps ready).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "backend" / "seed"


def main() -> int:
    strict = os.environ.get("TRAINER_CONTENT_GATE_STRICT", "0") == "1"
    seed_present = SEED.exists() and any(SEED.rglob("*.json"))

    if not seed_present:
        msg = "content gate: no seed JSON yet (expected after seed-catalog)"
        if strict:
            print(msg, file=sys.stderr)
            return 1
        print(f"{msg} - soft pass")
        return 0

    # Strict checks land with seed-catalog / F1.prod (ready status, no [DRAFT], 60 steps).
    if strict:
        print(
            "content gate strict mode: full ready-status validation not implemented yet",
            file=sys.stderr,
        )
        return 1

    print("content gate: soft mode (strict in F1.prod) - seed JSON present, skip hard checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
