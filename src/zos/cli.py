"""Command-line interface for Zos."""

import asyncio
from pathlib import Path

import click

from zos import __version__
from zos.config import Config
from zos.logging import get_logger, setup_logging

log = get_logger("cli")


@click.group()
@click.option(
    "-c",
    "--config-file",
    type=click.Path(exists=False, path_type=Path),
    default=None,
    help="Path to configuration file.",
)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    default=None,
    help="Set logging level (overrides config).",
)
@click.option(
    "--log-json/--no-log-json",
    default=None,
    help="Output logs as JSON or human-readable format (overrides config).",
)
@click.pass_context
def cli(
    ctx: click.Context,
    config_file: Path | None,
    log_level: str | None,
    log_json: bool | None,
) -> None:
    """Zos - Discord agent with temporal depth.

    A system that observes, reflects, and accumulates understanding.
    """
    ctx.ensure_object(dict)

    # Load configuration
    config = Config.load_or_default(config_file)
    ctx.obj["config"] = config
    ctx.obj["config_file"] = config_file

    # Determine logging settings (CLI overrides config)
    effective_log_level = log_level or config.log_level
    effective_log_json = log_json if log_json is not None else config.log_json

    # Set up logging with the effective options
    setup_logging(json_output=effective_log_json, level=effective_log_level)


@cli.command()
def version() -> None:
    """Print version information."""
    click.echo(f"zos {__version__}")


@cli.command()
@click.pass_context
def observe(ctx: click.Context) -> None:
    """Start the Discord observation bot.

    Connects to Discord and begins observing community conversations.
    This is the "eyes and ears" of Zos - attentive presence in communities.

    Requires DISCORD_TOKEN environment variable to be set.
    Use Ctrl+C or send SIGTERM for graceful shutdown.
    """
    from zos.observation import run_bot

    config = ctx.obj["config"]

    if not config.discord_token:
        click.echo("Error: DISCORD_TOKEN environment variable not set", err=True)
        click.echo("Set DISCORD_TOKEN to your bot token to connect to Discord.", err=True)
        raise SystemExit(1)

    log.info("observe_command_invoked")

    try:
        asyncio.run(run_bot(config))
    except KeyboardInterrupt:
        # This shouldn't normally be reached since we handle SIGINT,
        # but it's a safety net for cases where signal handling fails
        log.info("shutdown_requested_keyboard")
    except Exception as e:
        log.error("observe_failed", error=str(e))
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@cli.group()
def db() -> None:
    """Database management commands."""
    pass


@db.command(name="status")
@click.pass_context
def db_status(ctx: click.Context) -> None:
    """Show database migration status."""
    from zos.database import get_engine
    from zos.migrations import get_current_version, get_migrations

    config = ctx.obj["config"]
    engine = get_engine(config)

    current = get_current_version(engine)
    migrations = get_migrations()

    click.echo(f"Database: {config.database_path}")
    click.echo(f"Current version: {current}")
    click.echo(f"Available migrations: {len(migrations)}")

    pending = [(v, m) for v, m in migrations if v > current]
    if pending:
        click.echo(f"Pending migrations: {len(pending)}")
        for version, module in pending:
            desc = getattr(module, "DESCRIPTION", "No description")
            click.echo(f"  {version}: {desc}")
    else:
        click.echo("No pending migrations")


@db.command(name="migrate")
@click.option(
    "--target",
    type=int,
    default=None,
    help="Target version (default: latest).",
)
@click.pass_context
def db_migrate(ctx: click.Context, target: int | None) -> None:
    """Apply pending database migrations."""
    from zos.database import get_engine
    from zos.migrations import get_current_version, migrate

    config = ctx.obj["config"]
    engine = get_engine(config)

    before = get_current_version(engine)
    after = migrate(engine, target_version=target)

    if before == after:
        click.echo(f"Database already at version {after}")
    else:
        click.echo(f"Migrated from version {before} to {after}")


@cli.group()
def config() -> None:
    """Configuration management commands."""
    pass


@config.command(name="check")
@click.option(
    "-c",
    "--config-file",
    type=click.Path(exists=True, path_type=Path),
    default="config.yaml",
    help="Path to configuration file.",
)
def config_check(config_file: Path) -> None:
    """Validate configuration file."""
    try:
        cfg = Config.load(config_file)
        click.echo(f"Configuration valid: {config_file}")
        click.echo(f"  Data directory: {cfg.data_dir}")
        click.echo(f"  Database path: {cfg.database_path}")
        click.echo(f"  Log level: {cfg.log_level}")

        if cfg.models:
            profile_count = len(cfg.models.profiles)
            click.echo(f"  Model profiles: {profile_count}")

            # List the semantic aliases
            aliases = [k for k, v in cfg.models.profiles.items() if isinstance(v, str)]
            if aliases:
                click.echo(f"  Model aliases: {', '.join(aliases)}")
        else:
            click.echo("  Model profiles: not configured")

        if cfg.servers:
            click.echo(f"  Server overrides: {len(cfg.servers)}")

    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    except Exception as e:
        click.echo(f"Configuration error: {e}", err=True)
        raise SystemExit(1)


@cli.group()
def salience() -> None:
    """Salience management commands."""
    pass


@salience.command(name="decay")
@click.pass_context
def salience_decay(ctx: click.Context) -> None:
    """Manually trigger salience decay.

    Applies decay to all inactive topics. Topics are considered inactive
    if they haven't had activity in the last N days (configurable via
    salience.decay_threshold_days).

    This command is useful for testing or manual maintenance. In production,
    decay runs automatically via the scheduler.
    """
    from zos.database import create_tables, get_engine
    from zos.salience import SalienceLedger

    cfg = ctx.obj["config"]
    engine = get_engine(cfg)
    create_tables(engine)

    ledger = SalienceLedger(engine, cfg)

    async def run() -> tuple[int, float]:
        return await ledger.apply_decay()

    count, total = asyncio.run(run())

    click.echo(f"Decayed {count} topics, total {total:.2f} salience")
    click.echo(f"  Threshold: {cfg.salience.decay_threshold_days} days")
    click.echo(f"  Decay rate: {cfg.salience.decay_rate_per_day * 100:.1f}% per day")


if __name__ == "__main__":
    cli()
