"""Scheduler for layer execution using APScheduler.

Wraps APScheduler to provide cron-based scheduling for layer execution.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from zos.logging import get_logger
from zos.scheduler.models import Run, TriggerType

if TYPE_CHECKING:
    from zos.layer.schema import LayerDefinition
    from zos.scheduler.run_manager import RunManager

logger = get_logger("scheduler")


class LayerScheduler:
    """APScheduler wrapper for layer execution.

    Manages scheduled execution of layers based on their cron expressions.
    Integrates with RunManager for actual execution and lifecycle handling.
    """

    def __init__(self, run_manager: RunManager) -> None:
        """Initialize the scheduler.

        Args:
            run_manager: RunManager for executing layers.
        """
        self.run_manager = run_manager
        self._scheduler = AsyncIOScheduler()
        self._registered_layers: dict[str, str] = {}  # layer_name -> schedule

    def register_layer(self, layer: LayerDefinition) -> bool:
        """Register a layer for scheduled execution.

        Args:
            layer: Layer definition with schedule.

        Returns:
            True if layer was registered, False if no schedule defined.
        """
        if not layer.schedule:
            logger.debug(f"Layer {layer.name} has no schedule, skipping registration")
            return False

        # Parse cron expression
        try:
            trigger = CronTrigger.from_crontab(layer.schedule)
        except ValueError as e:
            logger.error(f"Invalid cron expression for {layer.name}: {e}")
            return False

        # Add job
        self._scheduler.add_job(
            self._execute_scheduled,
            trigger=trigger,
            args=[layer.name, layer.schedule],
            id=f"layer:{layer.name}",
            name=f"Layer: {layer.name}",
            replace_existing=True,
        )

        self._registered_layers[layer.name] = layer.schedule
        logger.info(f"Registered layer {layer.name} with schedule: {layer.schedule}")
        return True

    def register_layers(self, layers: list[LayerDefinition]) -> int:
        """Register multiple layers.

        Args:
            layers: List of layer definitions.

        Returns:
            Number of layers successfully registered.
        """
        count = 0
        for layer in layers:
            if self.register_layer(layer):
                count += 1
        return count

    def unregister_layer(self, layer_name: str) -> bool:
        """Unregister a layer from scheduled execution.

        Args:
            layer_name: Name of the layer to unregister.

        Returns:
            True if layer was unregistered, False if not found.
        """
        job_id = f"layer:{layer_name}"
        try:
            self._scheduler.remove_job(job_id)
            self._registered_layers.pop(layer_name, None)
            logger.info(f"Unregistered layer {layer_name}")
            return True
        except Exception:
            return False

    async def _execute_scheduled(
        self,
        layer_name: str,
        schedule_expression: str,
    ) -> None:
        """Execute a scheduled layer.

        Called by APScheduler when a cron trigger fires.

        Args:
            layer_name: Name of the layer to execute.
            schedule_expression: The cron expression that triggered this run.
        """
        logger.info(f"Scheduled execution triggered for layer: {layer_name}")
        try:
            await self.run_manager.execute_layer(
                layer_name=layer_name,
                triggered_by=TriggerType.SCHEDULE,
                schedule_expression=schedule_expression,
            )
        except Exception as e:
            logger.error(f"Scheduled execution failed for {layer_name}: {e}")

    async def trigger_layer(
        self,
        layer_name: str,
        triggered_by: TriggerType = TriggerType.MANUAL,
    ) -> Run | None:
        """Manually trigger a layer execution.

        Args:
            layer_name: Name of the layer to execute.
            triggered_by: Trigger source (default: MANUAL).

        Returns:
            The completed Run record, or None if skipped.
        """
        logger.info(f"Manual trigger for layer: {layer_name}")
        return await self.run_manager.execute_layer(
            layer_name=layer_name,
            triggered_by=triggered_by,
        )

    def start(self) -> None:
        """Start the scheduler.

        Also recovers any stale runs from previous executions.
        """
        # Recover stale runs before starting
        self.run_manager.recover_stale_runs()

        self._scheduler.start()
        logger.info(
            f"Scheduler started with {len(self._registered_layers)} registered layers"
        )

    def stop(self, wait: bool = True) -> None:
        """Stop the scheduler.

        Args:
            wait: Whether to wait for running jobs to complete.
        """
        self._scheduler.shutdown(wait=wait)
        logger.info("Scheduler stopped")

    def get_next_run_time(self, layer_name: str) -> datetime | None:
        """Get the next scheduled run time for a layer.

        Args:
            layer_name: Name of the layer.

        Returns:
            Next run datetime, or None if layer not scheduled.
        """
        job_id = f"layer:{layer_name}"
        job = self._scheduler.get_job(job_id)
        if job and job.next_run_time is not None:
            next_time: datetime = job.next_run_time
            return next_time
        return None

    def get_scheduled_layers(self) -> dict[str, str]:
        """Get all registered layers and their schedules.

        Returns:
            Mapping of layer name to cron expression.
        """
        return dict(self._registered_layers)

    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        running: bool = self._scheduler.running
        return running

    def get_jobs_info(self) -> list[dict[str, Any]]:
        """Get information about all scheduled jobs.

        Returns:
            List of job info dictionaries.
        """
        jobs = []
        for job in self._scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
            })
        return jobs
