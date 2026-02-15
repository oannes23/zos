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
@click.option("--host", default="127.0.0.1", help="API host to bind.")
@click.option("--port", default=8000, type=int, help="API port to bind.")
@click.option(
    "--layers-dir",
    type=click.Path(exists=True, path_type=Path),
    default="layers",
    help="Layers directory.",
)
@click.option(
    "--prompts-dir",
    type=click.Path(exists=True, path_type=Path),
    default="prompts",
    help="Prompts directory.",
)
@click.pass_context
def serve(
    ctx: click.Context,
    host: str,
    port: int,
    layers_dir: Path,
    prompts_dir: Path,
) -> None:
    """Start the full Zos service (observation + reflection + API).

    This is the unified command that runs all components together:
    - Discord observation bot (polls messages, tracks reactions)
    - Reflection scheduler (runs layers on cron schedules)
    - Introspection API (queries insights, salience, layer runs)

    All components share the same database and configuration.
    Use Ctrl+C or send SIGTERM for graceful shutdown.

    Requires DISCORD_TOKEN environment variable to be set.
    """
    import uvicorn
    from uvicorn import Config as UvicornConfig
    from uvicorn import Server

    from zos.api import create_app
    from zos.chattiness import ImpulseEngine
    from zos.database import create_tables, get_engine
    from zos.executor import LayerExecutor
    from zos.layers import LayerLoader
    from zos.llm import ModelClient
    from zos.migrations import migrate
    from zos.observation import run_bot
    from zos.salience import ReflectionSelector, SalienceLedger
    from zos.scheduler import ReflectionScheduler
    from zos.templates import TemplateEngine

    config = ctx.obj["config"]

    if not config.discord_token:
        click.echo("Error: DISCORD_TOKEN environment variable not set", err=True)
        click.echo("Set DISCORD_TOKEN to your bot token to connect to Discord.", err=True)
        raise SystemExit(1)

    # Initialize database
    engine = get_engine(config)
    migrate(engine)
    create_tables(engine)

    log.info(
        "serve_command_invoked",
        api_host=host,
        api_port=port,
        layers_dir=str(layers_dir),
        prompts_dir=str(prompts_dir),
    )

    async def run():
        """Run all components concurrently."""
        llm = None
        scheduler = None
        try:
            # Set up reflection components
            loader = LayerLoader(layers_dir)
            ledger = SalienceLedger(engine, config)

            # Ensure core topics exist on startup
            await ledger.ensure_topic("self:zos")
            log.info("core_topics_initialized")

            selector = ReflectionSelector(ledger, config)
            templates = TemplateEngine(
                templates_dir=prompts_dir,
                data_dir=config.data_dir,
                self_concept_max_chars=config.self_concept_max_chars,
            )
            llm = ModelClient(config, engine=engine)

            # Create impulse engine for conversation
            impulse_engine = ImpulseEngine(engine, config)

            # Create send callback for Discord message delivery
            # This closure is passed to the executor, keeping it decoupled from discord.py
            send_bot_ref: list = []  # Mutable ref to bot (set after bot starts)

            async def send_to_discord(
                content: str, context: dict
            ) -> str | None:
                """Send a message to Discord via the bot."""
                bot = send_bot_ref[0] if send_bot_ref else None
                if bot is None:
                    log.warning("send_callback_no_bot")
                    return None

                try:
                    if context.get("operator_dm"):
                        msg = None
                        for op_id in config.discord.operators.user_ids:
                            user = await bot.fetch_user(int(op_id))
                            msg = await user.send(content)
                        return str(msg.id) if msg else None
                    elif context.get("dm_user_id"):
                        user = await bot.fetch_user(int(context["dm_user_id"]))
                        msg = await user.send(content)
                        return str(msg.id)
                    elif context.get("channel_id"):
                        channel = bot.get_channel(int(context["channel_id"]))
                        if channel:
                            msg = await channel.send(content)
                            return str(msg.id)
                except Exception as e:
                    log.error("send_to_discord_failed", error=str(e))
                return None

            executor = LayerExecutor(
                engine=engine,
                ledger=ledger,
                templates=templates,
                llm=llm,
                config=config,
                loader=loader,
                send_callback=send_to_discord,
            )

            # Create and start scheduler
            scheduler = ReflectionScheduler(
                db_path=str(config.data_dir / "scheduler.db"),
                executor=executor,
                loader=loader,
                selector=selector,
                ledger=ledger,
                config=config,
            )
            scheduler.impulse_engine = impulse_engine
            scheduler.start()
            log.info("scheduler_started")

            # Create API app and configure state
            app = create_app(config)
            app.state.config = config
            app.state.db = engine
            app.state.ledger = ledger
            app.state.impulse_engine = impulse_engine if config.chattiness.enabled else None

            # Create uvicorn server
            uvicorn_config = UvicornConfig(
                app,
                host=host,
                port=port,
                log_level="info",
            )
            server = Server(uvicorn_config)

            # Run bot and API concurrently
            # The bot task will run until cancelled or shutdown
            # The API task runs the uvicorn server
            api_task = asyncio.create_task(server.serve())
            bot_task = asyncio.create_task(
                run_bot(
                    config,
                    engine,
                    scheduler,
                    impulse_engine=impulse_engine,
                    executor=executor,
                    layer_loader=loader,
                    bot_ref=send_bot_ref,
                )
            )

            # Wait for both tasks
            # If either completes or fails, cancel the other
            done, pending = await asyncio.wait(
                [bot_task, api_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Cancel pending tasks
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            # Check for exceptions in completed tasks
            for task in done:
                if not task.cancelled() and task.exception():
                    raise task.exception()  # type: ignore[misc]

        finally:
            # Clean up scheduler
            if scheduler is not None:
                scheduler.stop()
                log.info("scheduler_stopped")

            # Close LLM client to release aiohttp resources
            if llm is not None:
                await llm.close()
                log.debug("llm_client_closed")

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("serve_shutdown_requested")
    except Exception as e:
        log.error("serve_failed", error=str(e))
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    finally:
        engine.dispose()


@cli.command()
@click.pass_context
def observe(ctx: click.Context) -> None:
    """Start the Discord observation bot.

    Connects to Discord and begins observing community conversations.
    This is the "eyes and ears" of Zos - attentive presence in communities.

    Requires DISCORD_TOKEN environment variable to be set.
    Use Ctrl+C or send SIGTERM for graceful shutdown.
    """
    from zos.database import create_tables, get_engine
    from zos.migrations import migrate
    from zos.observation import run_bot

    config = ctx.obj["config"]

    if not config.discord_token:
        click.echo("Error: DISCORD_TOKEN environment variable not set", err=True)
        click.echo("Set DISCORD_TOKEN to your bot token to connect to Discord.", err=True)
        raise SystemExit(1)

    # Initialize database
    engine = get_engine(config)
    migrate(engine)
    create_tables(engine)

    log.info("observe_command_invoked")

    try:
        asyncio.run(run_bot(config, engine))
    except KeyboardInterrupt:
        # This shouldn't normally be reached since we handle SIGINT,
        # but it's a safety net for cases where signal handling fails
        log.info("shutdown_requested_keyboard")
    except Exception as e:
        log.error("observe_failed", error=str(e))
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    finally:
        engine.dispose()


@cli.command()
@click.option("--host", default="127.0.0.1", help="Host to bind.")
@click.option("--port", default=8000, type=int, help="Port to bind.")
@click.pass_context
def api(ctx: click.Context, host: str, port: int) -> None:
    """Start only the API server (no observation/reflection).

    Provides introspection endpoints for querying insights, salience,
    and operational state. Access the API documentation at /docs.

    This is useful for development and debugging, or when running
    the API separately from the observation/reflection processes.
    """
    import uvicorn

    from zos.api import create_app
    from zos.database import create_tables, get_engine
    from zos.migrations import migrate
    from zos.salience import SalienceLedger

    cfg = ctx.obj["config"]

    async def run():
        # Set up database
        engine = get_engine(cfg)
        migrate(engine)
        create_tables(engine)

        # Create app and configure state
        app = create_app(cfg)
        app.state.config = cfg
        app.state.db = engine
        app.state.ledger = SalienceLedger(engine, cfg)

        # Impulse engine (only when chattiness enabled)
        if cfg.chattiness.enabled:
            from zos.chattiness import ImpulseEngine
            app.state.impulse_engine = ImpulseEngine(engine, cfg)
        else:
            app.state.impulse_engine = None

        # Run the server
        server_config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="info",
        )
        server = uvicorn.Server(server_config)
        await server.serve()

    log.info("api_command_invoked", host=host, port=port)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("api_shutdown_requested")
    except Exception as e:
        log.error("api_failed", error=str(e))
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


# =============================================================================
# Layer Commands
# =============================================================================


@cli.group()
def layer() -> None:
    """Layer management commands."""
    pass


@layer.command(name="list")
@click.option(
    "-d",
    "--dir",
    "layers_dir",
    type=click.Path(exists=True, path_type=Path),
    default="layers",
    help="Layers directory.",
)
def layer_list(layers_dir: Path) -> None:
    """List all available layers.

    Loads and validates all layer YAML files from the layers directory
    and displays their names, categories, and schedules.
    """
    from pydantic import ValidationError

    from zos.layers import LayerLoader, format_validation_error

    loader = LayerLoader(layers_dir)

    try:
        layers = loader.load_all()
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    except ValueError as e:
        # Validation error - already formatted
        click.echo(str(e), err=True)
        raise SystemExit(1)

    if not layers:
        click.echo("No layers found")
        return

    click.echo(f"Found {len(layers)} layer(s):\n")

    for name in sorted(layers.keys()):
        layer_obj = layers[name]
        schedule = layer_obj.schedule or layer_obj.trigger or "manual"
        click.echo(f"  {name}: {layer_obj.category.value} ({schedule})")


@layer.command(name="validate")
@click.argument("name")
@click.option(
    "-d",
    "--dir",
    "layers_dir",
    type=click.Path(exists=True, path_type=Path),
    default="layers",
    help="Layers directory.",
)
def layer_validate(name: str, layers_dir: Path) -> None:
    """Validate a specific layer by name.

    Loads all layers from the directory and validates the specified layer,
    displaying its configuration details if valid.
    """
    from pydantic import ValidationError

    from zos.layers import LayerLoader, format_validation_error

    loader = LayerLoader(layers_dir)

    try:
        layers = loader.load_all()
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    except ValueError as e:
        # Validation error - already formatted
        click.echo(str(e), err=True)
        raise SystemExit(1)

    if name not in layers:
        click.echo(f"Error: Layer '{name}' not found", err=True)
        click.echo(f"Available layers: {', '.join(sorted(layers.keys()))}", err=True)
        raise SystemExit(1)

    layer_obj = layers[name]
    layer_hash = loader.get_hash(name)

    click.echo(f"Layer '{name}' is valid")
    click.echo(f"  Category: {layer_obj.category.value}")
    click.echo(f"  Nodes: {len(layer_obj.nodes)}")
    click.echo(f"  Hash: {layer_hash}")

    if layer_obj.schedule:
        click.echo(f"  Schedule: {layer_obj.schedule}")
    if layer_obj.trigger:
        click.echo(f"  Trigger: {layer_obj.trigger}")
    if layer_obj.target_category:
        click.echo(f"  Target category: {layer_obj.target_category}")
    if layer_obj.target_filter:
        click.echo(f"  Target filter: {layer_obj.target_filter}")
    click.echo(f"  Max targets: {layer_obj.max_targets}")

    if layer_obj.description:
        click.echo(f"\n  Description:\n    {layer_obj.description.strip()}")


# =============================================================================
# Reflect Commands
# =============================================================================


@cli.group()
def reflect() -> None:
    """Reflection management commands."""
    pass


@reflect.command(name="trigger")
@click.argument("layer_name")
@click.option(
    "-d",
    "--dir",
    "layers_dir",
    type=click.Path(exists=True, path_type=Path),
    default="layers",
    help="Layers directory.",
)
@click.pass_context
def reflect_trigger(ctx: click.Context, layer_name: str, layers_dir: Path) -> None:
    """Manually trigger a layer execution.

    Bypasses the schedule and executes the specified layer immediately.
    Uses salience-based topic selection to choose which topics to process.

    Example: zos reflect trigger nightly-user-reflection
    """
    from zos.database import create_tables, get_engine
    from zos.executor import LayerExecutor
    from zos.layers import LayerLoader
    from zos.llm import ModelClient
    from zos.salience import ReflectionSelector, SalienceLedger
    from zos.scheduler import ReflectionScheduler
    from zos.templates import TemplateEngine

    cfg = ctx.obj["config"]
    engine = get_engine(cfg)
    create_tables(engine)

    async def run():
        # Set up components
        loader = LayerLoader(layers_dir)
        ledger = SalienceLedger(engine, cfg)
        selector = ReflectionSelector(ledger, cfg)

        # Load layers to verify the layer exists
        try:
            layers = loader.load_all()
        except ValueError as e:
            click.echo(str(e), err=True)
            return None

        if layer_name not in layers:
            click.echo(f"Error: Layer '{layer_name}' not found", err=True)
            click.echo(f"Available layers: {', '.join(sorted(layers.keys()))}", err=True)
            return None

        # Set up templates
        templates = TemplateEngine(
            templates_dir=Path("prompts"),
            data_dir=cfg.data_dir,
            self_concept_max_chars=cfg.self_concept_max_chars,
        )

        # Set up LLM client
        llm = ModelClient(cfg, engine=engine)

        try:
            # Set up executor
            executor = LayerExecutor(
                engine=engine,
                ledger=ledger,
                templates=templates,
                llm=llm,
                config=cfg,
                loader=loader,
            )

            # Create scheduler for the trigger
            scheduler = ReflectionScheduler(
                db_path=str(cfg.data_dir / "scheduler.db"),
                executor=executor,
                loader=loader,
                selector=selector,
                ledger=ledger,
                config=cfg,
            )

            # Trigger the layer
            return await scheduler.trigger_now(layer_name)
        finally:
            # Close LLM client to release aiohttp resources
            await llm.close()

    run_result = asyncio.run(run())

    if run_result:
        click.echo(f"Layer executed: {run_result.status.value}")
        click.echo(f"  Targets matched: {run_result.targets_matched}")
        click.echo(f"  Targets processed: {run_result.targets_processed}")
        click.echo(f"  Insights created: {run_result.insights_created}")
        if run_result.tokens_total:
            click.echo(f"  Tokens used: {run_result.tokens_total}")
        if run_result.estimated_cost_usd:
            click.echo(f"  Estimated cost: ${run_result.estimated_cost_usd:.4f}")
    else:
        click.echo("Layer not found or no topics selected")


@reflect.command(name="jobs")
@click.option(
    "-d",
    "--dir",
    "layers_dir",
    type=click.Path(exists=True, path_type=Path),
    default="layers",
    help="Layers directory.",
)
@click.pass_context
def reflect_jobs(ctx: click.Context, layers_dir: Path) -> None:
    """List layers with cron schedules.

    Shows all layers that have scheduled execution times.
    Layers without schedules can be triggered manually with 'zos reflect trigger'.
    """
    from zos.layers import LayerLoader

    # Load layers
    loader = LayerLoader(layers_dir)

    try:
        layers = loader.load_all()
    except ValueError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)

    scheduled = [(name, layer) for name, layer in layers.items() if layer.schedule]
    manual = [(name, layer) for name, layer in layers.items() if not layer.schedule]

    if not scheduled:
        click.echo("No scheduled reflection layers")
    else:
        click.echo(f"Scheduled reflection layers ({len(scheduled)}):\n")

        for name, layer_obj in sorted(scheduled):
            click.echo(f"  {name}")
            click.echo(f"    Category: {layer_obj.category.value}")
            click.echo(f"    Schedule: {layer_obj.schedule} (cron, UTC)")
            if layer_obj.trigger_threshold:
                click.echo(f"    Threshold trigger: {layer_obj.trigger_threshold} insights")
            click.echo(f"    Max targets: {layer_obj.max_targets}")
            click.echo()

    if manual:
        click.echo(f"\nManual layers ({len(manual)}):")
        for name, layer_obj in sorted(manual):
            click.echo(f"  {name}: {layer_obj.category.value}")


if __name__ == "__main__":
    cli()
