"""python -m app.seed"""

from __future__ import annotations

import asyncio
import json

from app.seed.runner import run_seed


def main() -> None:
    counts = asyncio.run(run_seed())
    print(json.dumps({"ok": True, "counts": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
