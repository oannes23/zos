"""Main entry point for Zos."""

import asyncio
import contextlib
import sys
from pathlib import Path

from zos.config import init_config
from zos.db import close_db, init_db
from zos.discord.client import run_client
from zos.exceptions import ZosError
from zos.logging import setup_logging


async def run_api_server(host: str, port: int) -> None:
    """Run the FastAPI server.

    Args:
        host: Host address to bind to.
        port: Port to listen on.
    """
    import uvicorn

    from zos.api import create_app
    from zos.config import get_config

    app = create_app(get_config().api)
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


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

    try:
        # Create tasks
        tasks: list[asyncio.Task[None]] = []

        # Discord client task
        logger.info("Starting Discord client")
        discord_task: asyncio.Task[None] = asyncio.create_task(
            run_client(config.discord),
            name="discord",
        )
        tasks.append(discord_task)

        # API server task (if enabled)
        if config.api.enabled:
            logger.info(f"Starting API server on {config.api.host}:{config.api.port}")
            api_task: asyncio.Task[None] = asyncio.create_task(
                run_api_server(config.api.host, config.api.port),
                name="api",
            )
            tasks.append(api_task)

        # Wait for any task to complete (or fail)
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel remaining tasks
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        # Check for errors
        for task in done:
            exc = task.exception()
            if exc:
                raise exc

    except ZosError as e:
        logger.error(f"Error: {e}")
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
