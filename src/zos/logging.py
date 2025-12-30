"""Logging configuration for Zos."""

import logging
import sys
from pathlib import Path

from zos.config import LoggingConfig


def setup_logging(config: LoggingConfig | None = None) -> logging.Logger:
    """Set up logging based on configuration.

    Args:
        config: Logging configuration. If None, uses defaults.

    Returns:
        The root zos logger.
    """
    if config is None:
        config = LoggingConfig()

    # Get the root zos logger
    logger = logging.getLogger("zos")
    logger.setLevel(getattr(logging, config.level.upper()))

    # Clear any existing handlers
    logger.handlers.clear()

    # Create formatter
    formatter = logging.Formatter(config.format)

    # Console handler (always)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler (optional)
    if config.file:
        file_path = Path(config.file)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(file_path)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # Don't propagate to root logger
    logger.propagate = False

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name under the zos namespace.

    Args:
        name: Logger name (will be prefixed with 'zos.')

    Returns:
        Logger instance.
    """
    if name.startswith("zos."):
        return logging.getLogger(name)
    return logging.getLogger(f"zos.{name}")
