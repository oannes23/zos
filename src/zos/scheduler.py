"""Reflection Scheduler for Zos.

Integrates APScheduler to trigger layer execution on cron schedules.
Handles job persistence, missed job coalescing, and manual triggers.

Key concepts:
- Layers with schedule fields are registered on startup
- Jobs are rebuilt from layer files on each restart (fresh on restart)
- Missed jobs coalesce (run once even if multiple intervals were missed)
- Manual triggers bypass the schedule
- Self-reflection can trigger on insight thresholds

Design decision: We use MemoryJobStore instead of SQLAlchemyJobStore because:
1. Jobs are rebuilt from layer YAML files on every startup
2. Async methods can't be pickled for persistent storage
3. This matches the "fresh on restart" design from the spec
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from zos.layers import Layer, LayerCategory, LayerLoader
from zos.logging import get_logger
from zos.models import LayerRun, utcnow
from zos.salience import BudgetGroup, ReflectionSelector

if TYPE_CHECKING:
    from zos.config import Config
    from zos.executor import LayerExecutor
    from zos.salience import SalienceLedger

log = get_logger("scheduler")


class ReflectionScheduler:
    """Schedules and triggers layer execution.

    The scheduler manages cron-based layer execution for the reflection system.
    It:
    - Registers all scheduled layers on startup
    - Triggers layer execution at configured times
    - Handles missed jobs with coalescing
    - Provides manual trigger capability
    - Supports self-reflection threshold triggers

    Attributes:
        executor: LayerExecutor for running layers.
        loader: LayerLoader for accessing layer definitions.
        selector: ReflectionSelector for topic selection.
        ledger: SalienceLedger for insight counting.
        config: Application configuration.
        scheduler: APScheduler instance.
    """

    def __init__(
        self,
        db_path: str,
        executor: "LayerExecutor",
        loader: LayerLoader,
        selector: ReflectionSelector,
        ledger: "SalienceLedger",
        config: "Config",
    ) -> None:
        """Initialize the reflection scheduler.

        Args:
            db_path: Path to SQLite database (kept for API compatibility,
                     but we use memory store since jobs rebuild on startup).
            executor: LayerExecutor for running layers.
            loader: LayerLoader for accessing layer definitions.
            selector: ReflectionSelector for topic selection.
            ledger: SalienceLedger for insight counting and queries.
            config: Application configuration.
        """
        self.executor = executor
        self.loader = loader
        self.selector = selector
        self.ledger = ledger
        self.config = config
        self._db_path = db_path  # Stored for reference but not used

        # Create scheduler with in-memory job store
        # Jobs are rebuilt from layer YAML files on every startup,
        # so persistence is not needed (and async methods can't be pickled)
        self.scheduler = AsyncIOScheduler(
            job_defaults={
                "coalesce": True,  # Combine missed executions
                "max_instances": 1,  # No concurrent runs of same job
                "misfire_grace_time": 3600,  # 1 hour grace for missed jobs
            },
            timezone=timezone.utc,  # All schedules in UTC
        )

    def start(self) -> None:
        """Start the scheduler.

        Registers all scheduled layers and starts the scheduler.
        Existing jobs are replaced with fresh definitions from layer files
        to ensure consistency with the current layer configuration.
        """
        self._register_layers()
        self.scheduler.start()
        log.info(
            "scheduler_started",
            jobs=len(self.scheduler.get_jobs()),
            timezone="UTC",
        )

    def stop(self) -> None:
        """Stop the scheduler gracefully."""
        self.scheduler.shutdown(wait=True)
        log.info("scheduler_stopped")

    def _register_layers(self) -> None:
        """Register all scheduled layers.

        Loads all layers and registers those with cron schedules.
        Per design decision: always rebuild schedule from current layer
        definitions on startup (fresh on restart).
        """
        try:
            layers = self.loader.load_all()
        except Exception as e:
            log.error("failed_to_load_layers", error=str(e))
            return

        for name, layer in layers.items():
            if layer.schedule:
                self._register_layer(layer)

    def _register_layer(self, layer: Layer) -> None:
        """Register a single layer's schedule.

        Args:
            layer: The layer to register.
        """
        job_id = f"layer:{layer.name}"

        # Remove existing job if any (ensures fresh definition)
        existing = self.scheduler.get_job(job_id)
        if existing:
            self.scheduler.remove_job(job_id)

        # Parse cron schedule with explicit UTC timezone
        try:
            trigger = CronTrigger.from_crontab(layer.schedule, timezone=timezone.utc)
        except ValueError as e:
            log.error(
                "invalid_cron_schedule",
                layer=layer.name,
                schedule=layer.schedule,
                error=str(e),
            )
            return

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
            job_id=job_id,
        )

    async def _execute_layer(self, layer_name: str) -> LayerRun | None:
        """Execute a layer (called by scheduler).

        Args:
            layer_name: Name of the layer to execute.

        Returns:
            LayerRun if successful, None if layer not found or no topics.
        """
        log.info("layer_triggered", layer=layer_name, trigger="schedule")

        try:
            layer = self.loader.get_layer(layer_name)
            if not layer:
                # Layer may have been removed - reload and try again
                self.loader.reload()
                layer = self.loader.get_layer(layer_name)

            if not layer:
                log.error("layer_not_found", layer=layer_name)
                return None

            # Select topics for this layer
            topics = await self._select_topics(layer)

            if not topics:
                log.info("no_topics_selected", layer=layer_name)
                return None

            # Execute
            run = await self.executor.execute_layer(layer, topics)

            log.info(
                "layer_completed",
                layer=layer_name,
                status=run.status.value,
                insights=run.insights_created,
                targets_processed=run.targets_processed,
            )

            return run

        except Exception as e:
            log.error(
                "layer_execution_failed",
                layer=layer_name,
                error=str(e),
            )
            return None

    async def _select_topics(self, layer: Layer) -> list[str]:
        """Select topics for a layer based on its configuration.

        Args:
            layer: The layer to select topics for.

        Returns:
            List of topic keys to process.
        """
        # Self-reflection targets self topics
        if layer.category == LayerCategory.SELF:
            return await self._get_self_topics()

        # Use budget-based selection
        total_budget = self._get_total_budget(layer.category)

        selected = await self.selector.select_for_reflection(
            total_budget=total_budget,
        )

        # Get topics for this layer's budget group
        group = self._category_to_group(layer.category)
        topics = selected.get(group, [])

        # Apply layer's max_targets
        return topics[: layer.max_targets]

    async def _get_self_topics(self) -> list[str]:
        """Get self topics for self-reflection.

        Returns:
            List of self topic keys.
        """
        # Global self topic
        self_topics = ["self:zos"]

        # Could add server-scoped self topics here if needed
        # For MVP, just the global self topic

        return self_topics

    def _get_total_budget(self, category: LayerCategory) -> float:
        """Get total reflection budget for a category.

        Args:
            category: The layer category.

        Returns:
            Total budget for reflection.
        """
        # Use a reasonable default budget
        # This could be made configurable
        base_budget = 100.0

        # Self gets its own budget from config
        if category == LayerCategory.SELF:
            return self.config.salience.self_budget

        return base_budget

    def _category_to_group(self, category: LayerCategory) -> BudgetGroup:
        """Map layer category to budget group.

        Args:
            category: The layer category.

        Returns:
            The corresponding budget group.
        """
        mapping = {
            LayerCategory.USER: BudgetGroup.SOCIAL,
            LayerCategory.DYAD: BudgetGroup.SOCIAL,
            LayerCategory.CHANNEL: BudgetGroup.SPACES,
            LayerCategory.SUBJECT: BudgetGroup.SEMANTIC,
            LayerCategory.SELF: BudgetGroup.SELF,
            LayerCategory.SYNTHESIS: BudgetGroup.GLOBAL,
        }
        return mapping.get(category, BudgetGroup.SOCIAL)

    async def check_self_reflection_trigger(self) -> LayerRun | None:
        """Check if self-reflection should trigger based on insight count.

        Examines layers with trigger_threshold and triggers execution
        if the count of self-insights since last run exceeds the threshold.

        Returns:
            LayerRun if triggered, None otherwise.
        """
        try:
            layers = self.loader.load_all()
        except Exception as e:
            log.error("failed_to_load_layers_for_trigger_check", error=str(e))
            return None

        for layer in layers.values():
            if layer.trigger_threshold and layer.category == LayerCategory.SELF:
                # Count self-insights since last run
                count = await self._count_self_insights_since_last_run(layer.name)

                if count >= layer.trigger_threshold:
                    log.info(
                        "self_reflection_threshold_reached",
                        layer=layer.name,
                        count=count,
                        threshold=layer.trigger_threshold,
                    )
                    return await self._execute_layer(layer.name)

        return None

    async def _count_self_insights_since_last_run(self, layer_name: str) -> int:
        """Count self-insights created since the last run of a layer.

        Args:
            layer_name: Name of the layer.

        Returns:
            Count of self-insights since last run.
        """
        from sqlalchemy import and_, func, select

        from zos.database import insights as insights_table, layer_runs as layer_runs_table

        # Get the last run time for this layer
        with self.ledger.engine.connect() as conn:
            last_run_result = conn.execute(
                select(layer_runs_table.c.completed_at)
                .where(layer_runs_table.c.layer_name == layer_name)
                .order_by(layer_runs_table.c.completed_at.desc())
                .limit(1)
            ).fetchone()

            if last_run_result and last_run_result.completed_at:
                since = last_run_result.completed_at
            else:
                # No previous run - count all self-insights
                since = datetime(1970, 1, 1, tzinfo=timezone.utc)

            # Count self-insights since last run
            result = conn.execute(
                select(func.count())
                .select_from(insights_table)
                .where(
                    and_(
                        insights_table.c.topic_key.like("self:%"),
                        insights_table.c.created_at > since,
                    )
                )
            ).scalar()

            return result or 0

    async def trigger_now(self, layer_name: str) -> LayerRun | None:
        """Manually trigger a layer execution.

        Bypasses the schedule and executes the layer immediately.

        Args:
            layer_name: Name of the layer to trigger.

        Returns:
            LayerRun if successful, None if layer not found, no topics, or error.
        """
        layer = self.loader.get_layer(layer_name)
        if not layer:
            # Try reloading in case layer was added
            self.loader.reload()
            layer = self.loader.get_layer(layer_name)

        if not layer:
            log.warning("manual_trigger_layer_not_found", layer=layer_name)
            return None

        log.info("layer_triggered", layer=layer_name, trigger="manual")

        topics = await self._select_topics(layer)
        if not topics:
            log.info("manual_trigger_no_topics", layer=layer_name)
            return None

        try:
            return await self.executor.execute_layer(layer, topics)
        except Exception as e:
            log.error(
                "manual_trigger_execution_failed",
                layer=layer_name,
                error=str(e),
            )
            return None

    def get_jobs(self) -> list[dict]:
        """Get information about all scheduled jobs.

        Returns:
            List of job info dictionaries with name, next_run_time, etc.
        """
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": job.next_run_time,
                "trigger": str(job.trigger),
            })
        return jobs

    def get_job(self, job_id: str) -> dict | None:
        """Get information about a specific job.

        Args:
            job_id: The job ID (e.g., "layer:nightly-user-reflection").

        Returns:
            Job info dict or None if not found.
        """
        job = self.scheduler.get_job(job_id)
        if not job:
            return None

        return {
            "id": job.id,
            "name": job.name,
            "next_run_time": job.next_run_time,
            "trigger": str(job.trigger),
        }

    def pause_layer(self, layer_name: str) -> bool:
        """Pause a scheduled layer.

        Args:
            layer_name: Name of the layer to pause.

        Returns:
            True if paused successfully, False if not found.
        """
        job_id = f"layer:{layer_name}"
        job = self.scheduler.get_job(job_id)
        if not job:
            return False

        self.scheduler.pause_job(job_id)
        log.info("layer_paused", layer=layer_name)
        return True

    def resume_layer(self, layer_name: str) -> bool:
        """Resume a paused layer.

        Args:
            layer_name: Name of the layer to resume.

        Returns:
            True if resumed successfully, False if not found.
        """
        job_id = f"layer:{layer_name}"
        job = self.scheduler.get_job(job_id)
        if not job:
            return False

        self.scheduler.resume_job(job_id)
        log.info("layer_resumed", layer=layer_name)
        return True
