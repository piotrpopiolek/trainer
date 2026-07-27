"""Catalog and legal seed package.

Keep this module free of heavy imports (SQLAlchemy) so CI can run
`scripts/check_content_gate.py` with a bare Python interpreter.
"""

from __future__ import annotations

from typing import Any

__all__ = ["run_seed", "seed_all"]


def __getattr__(name: str) -> Any:
    if name in {"run_seed", "seed_all"}:
        from app.seed.runner import run_seed, seed_all

        return run_seed if name == "run_seed" else seed_all
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
