# Story 4.6: Scheduler Integration

**Epic**: Reflection
**Status**: 🔴 Not Started
**Estimated complexity**: Medium

## Goal

Integrate APScheduler to trigger layer execution on cron schedules.

## Acceptance Criteria

- [ ] Layers register their schedules on startup
- [ ] Cron expressions trigger layer execution
- [ ] Jobs persist across restarts
- [ ] Missed jobs handled appropriately
- [ ] Manual trigger via CLI
- [ ] Job status visible in API

## Technical Notes

### Scheduler Setup

```python
# src/zos/scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
import structlog

log = structlog.get_logger()

class ReflectionScheduler:
    """Schedules and triggers layer execution."""

    def __init__(
        self,
        db_path: str,
        executor: LayerExecutor,
        loader: LayerLoader,
        selector: ReflectionSelector,
        config: Config,
    ):
        self.executor = executor
        self.loader = loader
        self.selector = selector
        self.config = config

        # Create scheduler with persistent job store
        jobstores = {
            'default': SQLAlchemyJobStore(url=f'sqlite:///{db_path}')
        }

        self.scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            job_defaults={
                'coalesce': True,  # Combine missed executions
                'max_instances': 1,  # No concurrent runs of same job
                'misfire_grace_time': 3600,  # 1 hour grace for missed jobs
            }
        )

    def start(self):
        """Start the scheduler."""
        self._register_layers()
        self.scheduler.start()
        log.info("scheduler_started", jobs=len(self.scheduler.get_jobs()))

    def stop(self):
        """Stop the scheduler."""
        self.scheduler.shutdown()
        log.info("scheduler_stopped")

    def _register_layers(self):
        """Register all scheduled layers."""
        layers = self.loader.load_all()

        for name, layer in layers.items():
            if layer.schedule:
                self._register_layer(layer)

    def _register_layer(self, layer: Layer):
        """Register a single layer's schedule."""
        job_id = f"layer:{layer.name}"

        # Remove existing job if any
        existing = self.scheduler.get_job(job_id)
        if existing:
            self.scheduler.remove_job(job_id)

        # Parse cron schedule
        trigger = CronTrigger.from_crontab(layer.schedule)

        # Add job
        self.scheduler.add_job(
            self._execute_layer,
            trigger=trigger,
            args=[layer.name],
            id=job_id,
            name=f"Reflection: {layer.name}",
            replace_existing=True,
        )

        log.info(
            "layer_scheduled",
            layer=layer.name,
            schedule=layer.schedule,
        )
```

### Layer Execution Job

```python
    async def _execute_layer(self, layer_name: str):
        """Execute a layer (called by scheduler)."""
        log.info("layer_triggered", layer=layer_name, trigger="schedule")

        try:
            layer = self.loader.get_layer(layer_name)
            if not layer:
                log.error("layer_not_found", layer=layer_name)
                return

            # Select topics for this layer
            topics = await self._select_topics(layer)

            if not topics:
                log.info("no_topics_selected", layer=layer_name)
                return

            # Execute
            run = await self.executor.execute_layer(layer, topics)

            log.info(
                "layer_completed",
                layer=layer_name,
                status=run.status.value,
                insights=run.insights_created,
            )

        except Exception as e:
            log.error(
                "layer_execution_failed",
                layer=layer_name,
                error=str(e),
            )

    async def _select_topics(self, layer: Layer) -> list[str]:
        """Select topics for a layer based on its configuration."""
        if layer.target_category == 'self':
            # Self-reflection targets self topics
            return await self._get_self_topics()

        # Use budget-based selection
        budget = self.config.salience.budget
        total_budget = self._get_total_budget(layer.category)

        selected = await self.selector.select_for_reflection(
            total_budget=total_budget,
        )

        # Get topics for this layer's budget group
        group = self._category_to_group(layer.category)
        topics = selected.get(group, [])

        # Apply layer's max_targets
        return topics[:layer.max_targets]
```

### Self-Reflection Trigger

```python
    async def check_self_reflection_trigger(self):
        """Check if self-reflection should trigger based on insight count."""
        layers = self.loader.load_all()

        for layer in layers.values():
            if layer.trigger_threshold:
                # Count self-insights since last run
                count = await self._count_self_insights_since_last_run(layer.name)

                if count >= layer.trigger_threshold:
                    log.info(
                        "self_reflection_threshold_reached",
                        layer=layer.name,
                        count=count,
                    )
                    await self._execute_layer(layer.name)
```

### Manual Trigger

```python
    async def trigger_now(self, layer_name: str) -> LayerRun | None:
        """Manually trigger a layer execution."""
        layer = self.loader.get_layer(layer_name)
        if not layer:
            return None

        log.info("layer_triggered", layer=layer_name, trigger="manual")

        topics = await self._select_topics(layer)
        if not topics:
            return None

        return await self.executor.execute_layer(layer, topics)
```

### CLI Commands

```python
# src/zos/cli.py

@cli.group()
def reflect():
    """Reflection management commands."""
    pass

@reflect.command()
@click.argument("layer_name")
@click.pass_context
def trigger(ctx, layer_name: str):
    """Manually trigger a layer execution."""
    config = ctx.obj["config"]
    # ... setup scheduler, executor, etc ...

    async def run():
        run = await scheduler.trigger_now(layer_name)
        if run:
            click.echo(f"Layer executed: {run.status.value}")
            click.echo(f"  Insights created: {run.insights_created}")
        else:
            click.echo("Layer not found or no topics selected")

    asyncio.run(run())

@reflect.command()
@click.pass_context
def jobs(ctx):
    """List scheduled reflection jobs."""
    # ... setup scheduler ...

    for job in scheduler.scheduler.get_jobs():
        next_run = job.next_run_time
        click.echo(f"  {job.name}")
        click.echo(f"    Next run: {next_run}")
```

### Integration with Main Process

```python
# src/zos/cli.py

@cli.command()
@click.pass_context
def serve(ctx):
    """Start the full Zos service (observation + reflection + API)."""
    config = ctx.obj["config"]

    async def run():
        # Setup components
        db = Database(config)
        await db.connect()

        llm = ModelClient(config)
        templates = TemplateEngine(Path("prompts"), config.data_dir / "self-concept.md")
        loader = LayerLoader(Path("layers"))
        ledger = SalienceLedger(db, config)
        selector = ReflectionSelector(ledger, config)
        executor = LayerExecutor(db, ledger, templates, llm, config)

        # Start scheduler
        scheduler = ReflectionScheduler(
            db_path=str(config.data_dir / "zos.db"),
            executor=executor,
            loader=loader,
            selector=selector,
            config=config,
        )
        scheduler.start()

        # Start Discord bot (with observation)
        bot = ZosBot(config, ledger)

        # Start API server
        # ... uvicorn setup ...

        try:
            await bot.start(config.discord_token)
        finally:
            scheduler.stop()
            await db.close()

    asyncio.run(run())
```

## Configuration

```yaml
# Scheduler settings
scheduler:
  misfire_grace_time: 3600  # 1 hour
  coalesce: true
  max_instances: 1
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/scheduler.py` | ReflectionScheduler class |
| `src/zos/cli.py` | Reflect commands, serve command |
| `tests/test_scheduler.py` | Scheduler tests |

## Test Cases

1. Layers register on startup
2. Cron triggers at correct time
3. Manual trigger works
4. Missed jobs coalesce
5. Job persists across restart
6. Self-reflection threshold works

## Definition of Done

- [ ] Scheduled execution works
- [ ] Manual trigger works
- [ ] Jobs persist
- [ ] Integrated with serve command

---

**Requires**: Stories 4.1-4.5 (layers, executor)
**Blocks**: Stories 4.7, 4.8 (need scheduler for real layers)
