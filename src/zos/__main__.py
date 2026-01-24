"""CLI entrypoint for running zos as a module."""

from zos.cli import cli
from zos.logging import setup_logging

if __name__ == "__main__":
    setup_logging()
    cli()
