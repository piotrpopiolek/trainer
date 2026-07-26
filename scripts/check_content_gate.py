"""Content completeness gate for CC catalog (FR-020a / FR-084).

Soft by default until F1.prod. Set TRAINER_CONTENT_GATE_STRICT=1 to fail
when seed translations are incomplete (program, 3 days, 6 exercises, 60 steps ready).

Thin CLI wrapper — logic lives in app.seed.content_gate (usable in Compose tests).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `python scripts/check_content_gate.py` without installed package.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.seed.content_gate import run_content_gate  # noqa: E402


def main() -> int:
    code, message = run_content_gate()
    stream = sys.stderr if code else sys.stdout
    print(message, file=stream)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
