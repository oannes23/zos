"""Standalone API server entry point.

Run with: uv run python -m zos.api [config_path]
"""

import sys
from pathlib import Path

import uvicorn

from zos.config import init_config
from zos.db import init_db
from zos.logging import setup_logging


def main() -> int:
    """Run standalone API server.

    Returns:
        Exit code (0 for success, non-zero for failure).
    """
    config_path = None
    if len(sys.argv) > 1:
        config_path = Path(sys.argv[1])

    # Initialize
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
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        return 1

    # Create and run app
    from zos.api import create_app

    app = create_app(config.api)

    logger.info(f"Starting API server on {config.api.host}:{config.api.port}")
    uvicorn.run(
        app,
        host=config.api.host,
        port=config.api.port,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
