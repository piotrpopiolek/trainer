"""Load seed JSON from backend/seed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SEED_ROOT = Path(__file__).resolve().parents[2] / "seed"


def load_json(*relative: str) -> dict[str, Any]:
    path = SEED_ROOT.joinpath(*relative)
    with path.open(encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    return data
