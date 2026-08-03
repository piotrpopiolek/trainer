"""Compose one-shot: finalize overdue satellite daily outcomes (FR-053).

Usage:
  docker compose --profile ops run --rm satellite-finalize
  # or:
  docker compose run --rm api python -m app.jobs.satellite_finalize
"""

from __future__ import annotations

import asyncio
import logging
import os

from app.db.session import dispose_engine, get_session_factory
from app.services.satellite_finalize import run_satellite_finalize_batch

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "info").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("satellite_finalize")


async def _main() -> int:
    heartbeat = os.environ.get("SATELLITE_FINALIZE_HEARTBEAT_PATH", "").strip() or None
    limit_raw = os.environ.get("SATELLITE_FINALIZE_LIMIT", "").strip()
    limit = int(limit_raw) if limit_raw else 500
    factory = get_session_factory()
    try:
        async with factory() as db:
            result = await run_satellite_finalize_batch(
                db, heartbeat_path=heartbeat, limit=limit
            )
        if result["fail"] > 0:
            logger.error("satellite_finalize.fail batch=%s", result)
            return 1
        logger.info("satellite_finalize.ok batch=%s", result)
        return 0
    except Exception:
        logger.exception("satellite_finalize.crash")
        return 1
    finally:
        await dispose_engine()


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
