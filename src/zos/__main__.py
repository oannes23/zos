"""Main entry point for Zos."""

import asyncio
import sys
from pathlib import Path

from zos.config import init_config
from zos.db import close_db, init_db
from zos.discord.client import run_client
from zos.exceptions import ZosError
from zos.logging import setup_logging


async def async_main(config_path: Path | None = None) -> int:
    """Async main entry point for Zos.

    Args:
        config_path: Optional path to config file.

    Returns:
        Exit code (0 for success, non-zero for failure).
    """
    # Initialize configuration
    try:
        config = init_config(config_path)
    except Exception as e:
        print(f"Failed to load configuration: {e}", file=sys.stderr)
        return 1

    # Set up logging
    logger = setup_logging(config.logging)
    logger.info("Configuration loaded")

    # Initialize database
    try:
        init_db(config.database)
        logger.info("Database initialized")
    except ZosError as e:
        logger.error(f"Database initialization failed: {e}")
        return 1

    # Run Discord client
    try:
        logger.info("Starting Discord client")
        await run_client(config.discord)
    except ZosError as e:
        logger.error(f"Discord client error: {e}")
        return 1
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    finally:
        # Clean up
        close_db()
        logger.info("Shutdown complete")

    return 0


def main(config_path: Path | None = None) -> int:
    """Main entry point for Zos.

    Args:
        config_path: Optional path to config file.

    Returns:
        Exit code (0 for success, non-zero for failure).
    """
    try:
        return asyncio.run(async_main(config_path))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    # Parse command line args for config path
    config_path = None
    if len(sys.argv) > 1:
        config_path = Path(sys.argv[1])

    sys.exit(main(config_path))
