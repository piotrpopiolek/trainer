"""Compose one-shot: cleanup auth_sessions / oauth_states / rate_limit_buckets.

Usage:
  docker compose --profile ops run --rm cleanup
  # or:
  docker compose run --rm api python -m app.jobs.cleanup
"""

from __future__ import annotations

import asyncio
import logging
import os

from app.db.session import dispose_engine, get_session_factory
from app.services.cleanup import run_cleanup_batch

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "info").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("cleanup")


async def _main() -> int:
    factory = get_session_factory()
    try:
        async with factory() as db:
            result = await run_cleanup_batch(db)
        logger.info("cleanup.ok %s", result)
        return 0
    except Exception:
        logger.exception("cleanup.fail")
        return 1
    finally:
        await dispose_engine()


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
