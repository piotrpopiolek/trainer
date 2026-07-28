"""Compose one-shot: hard-purge soft-deleted accounts (FR-006c).

Usage:
  docker compose --profile ops run --rm purge
  # or:
  docker compose run --rm api python -m app.jobs.purge
"""

from __future__ import annotations

import asyncio
import logging
import os

from app.db.session import dispose_engine, get_session_factory
from app.services.purge import run_purge_batch

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "info").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("purge")


async def _main() -> int:
    heartbeat = os.environ.get("PURGE_HEARTBEAT_PATH", "").strip() or None
    factory = get_session_factory()
    async with factory() as db:
        result = await run_purge_batch(db, heartbeat_path=heartbeat)
    await dispose_engine()
    if result["fail"] > 0:
        logger.error("purge.fail batch_failures=%s", result["fail"])
        return 1
    logger.info("purge.ok batch=%s", result)
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
