"""Run manager for layer execution lifecycle.

The RunManager orchestrates the full lifecycle of layer executions:
- Pre-run checks (overlap detection)
- Time window calculation
- Budget allocation
- Layer execution
- Post-run bookkeeping (traces, completion)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from zos.budget.allocator import BudgetAllocator
from zos.layer.executor import PipelineExecutor
from zos.logging import get_logger
from zos.scheduler.models import Run, RunStatus, TriggerType
from zos.scheduler.repository import RunRepository
from zos.scheduler.window import calculate_run_window

if TYPE_CHECKING:
    from zos.config import ZosConfig
    from zos.db import Database
    from zos.layer.loader import LayerLoader
    from zos.llm.client import LLMClient

logger = get_logger("scheduler.run_manager")


class RunManager:
    """Manages layer execution lifecycle.

    Handles:
    - Pre-execution checks (is layer already running?)
    - Time window calculation (since last successful run)
    - Budget allocation
    - Run record creation and updates
    - Trace persistence
    - Crash recovery (marking stale runs as failed)
    """

    def __init__(
        self,
        db: Database,
        llm_client: LLMClient,
        config: ZosConfig,
        layer_loader: LayerLoader,
    ) -> None:
        """Initialize the run manager.

        Args:
            db: Database instance.
            llm_client: LLM client for layer execution.
            config: Zos configuration.
            layer_loader: Layer definition loader.
        """
        self.db = db
        self.llm_client = llm_client
        self.config = config
        self.layer_loader = layer_loader
        self._run_repo = RunRepository(db)
        self._executor = PipelineExecutor(db=db, llm_client=llm_client, config=config)
        self._allocator = BudgetAllocator(db=db, config=config.budget)

    async def execute_layer(
        self,
        layer_name: str,
        triggered_by: TriggerType,
        schedule_expression: str | None = None,
        dry_run: bool = False,
    ) -> Run | None:
        """Execute a layer with full lifecycle management.

        This method handles the complete run lifecycle:
        1. Check if layer is already running (skip if so)
        2. Load layer definition
        3. Calculate time window
        4. Create budget allocation plan
        5. Create run record
        6. Execute the layer pipeline
        7. Save traces and finalize run record

        Args:
            layer_name: Name of the layer to execute.
            triggered_by: How the run was triggered.
            schedule_expression: Cron expression if scheduled.
            dry_run: If True, validate without executing.

        Returns:
            The completed Run record, or None if skipped due to overlap.
        """
        # Check for overlapping run
        if self._run_repo.is_layer_running(layer_name):
            logger.info(f"Skipping {layer_name}: layer is already running")
            return None

        # Load layer definition
        layer = self.layer_loader.load(layer_name)

        # Get max lookback hours from layer config
        max_lookback_hours = layer.max_lookback_hours

        # Calculate time window
        window_start, window_end = calculate_run_window(
            layer_name=layer_name,
            max_lookback_hours=max_lookback_hours,
            run_repo=self._run_repo,
        )

        logger.info(
            f"Starting run for {layer_name} "
            f"(window: {window_start.isoformat()} to {window_end.isoformat()})"
        )

        # Create allocation plan
        allocation_plan = self._allocator.create_allocation_plan(since=window_start)

        # Create run record
        run = Run(
            run_id=allocation_plan.run_id,
            layer_name=layer_name,
            triggered_by=triggered_by,
            status=RunStatus.PENDING,
            started_at=datetime.now(UTC),
            window_start=window_start,
            window_end=window_end,
            schedule_expression=schedule_expression,
        )
        self._run_repo.create_run(run)

        # Update status to running
        self._run_repo.update_status(run.run_id, RunStatus.RUNNING)

        try:
            # Execute the layer pipeline
            result = await self._executor.execute(
                layer=layer,
                allocation_plan=allocation_plan,
                dry_run=dry_run,
                window_start=window_start,
                window_end=window_end,
            )

            # Save trace entries
            self._run_repo.save_trace(run.run_id, result.trace)

            # Calculate estimated cost (tokens * cost per token)
            # Using a rough estimate for now
            estimated_cost = result.total_tokens * 0.00001  # Placeholder rate

            # Calculate salience spent
            salience_spent = (
                layer.salience_rules.spend_per_target * result.targets_processed
            )

            # Complete the run
            self._run_repo.complete_run(
                run_id=run.run_id,
                result=result,
                estimated_cost_usd=estimated_cost,
                salience_spent=salience_spent,
            )

            # Fetch updated run record
            completed_run = self._run_repo.get_run(run.run_id)

            logger.info(
                f"Completed run {run.run_id} for {layer_name}: "
                f"processed={result.targets_processed}, "
                f"skipped={result.targets_skipped}, "
                f"tokens={result.total_tokens}"
            )

            return completed_run

        except Exception as e:
            # Mark run as failed
            error_msg = str(e)
            self._run_repo.update_status(
                run.run_id,
                RunStatus.FAILED,
                error_message=error_msg,
            )
            logger.error(f"Run {run.run_id} failed: {error_msg}")
            raise

    def recover_stale_runs(self) -> int:
        """Mark any stale runs as failed.

        Should be called on startup to handle runs that were
        interrupted by a crash or restart.

        Returns:
            Number of runs marked as failed.
        """
        count = self._run_repo.mark_stale_runs_failed()
        if count > 0:
            logger.info(f"Recovered {count} stale runs")
        return count

    def get_run(self, run_id: str) -> Run | None:
        """Get a run by ID.

        Args:
            run_id: The run ID.

        Returns:
            The run, or None if not found.
        """
        return self._run_repo.get_run(run_id)

    def get_runs(
        self,
        layer_name: str | None = None,
        status: RunStatus | None = None,
        limit: int = 50,
    ) -> list[Run]:
        """Query runs with optional filters.

        Args:
            layer_name: Filter by layer name.
            status: Filter by status.
            limit: Maximum runs to return.

        Returns:
            List of matching runs.
        """
        return self._run_repo.get_runs(
            layer_name=layer_name,
            status=status,
            limit=limit,
        )

    def is_layer_running(self, layer_name: str) -> bool:
        """Check if a layer is currently running.

        Args:
            layer_name: Name of the layer.

        Returns:
            True if layer has an active run.
        """
        return self._run_repo.is_layer_running(layer_name)
