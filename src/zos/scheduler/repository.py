"""Repository for run management database operations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from zos.logging import get_logger
from zos.scheduler.models import Run, RunStatus, TraceEntry, TriggerType

if TYPE_CHECKING:
    from zos.db import Database
    from zos.layer.executor import ExecutionResult

logger = get_logger("scheduler.repository")


class RunRepository:
    """Database operations for run management.

    Handles CRUD operations for runs and run traces in the SQLite database.
    """

    def __init__(self, db: Database) -> None:
        """Initialize the repository.

        Args:
            db: Database instance.
        """
        self.db = db

    def create_run(self, run: Run) -> None:
        """Create a new run record.

        Args:
            run: The run to create.
        """
        self.db.execute(
            """
            INSERT INTO runs (
                run_id, layer_name, triggered_by, schedule_expression,
                started_at, status, window_start, window_end,
                targets_total, targets_processed, targets_skipped,
                tokens_used, estimated_cost_usd, salience_spent
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.run_id,
                run.layer_name,
                run.triggered_by.value,
                run.schedule_expression,
                run.started_at.isoformat(),
                run.status.value,
                run.window_start.isoformat(),
                run.window_end.isoformat(),
                run.targets_total,
                run.targets_processed,
                run.targets_skipped,
                run.tokens_used,
                run.estimated_cost_usd,
                run.salience_spent,
            ),
        )
        logger.debug(f"Created run record: {run.run_id}")

    def update_status(
        self,
        run_id: str,
        status: RunStatus,
        error_message: str | None = None,
    ) -> None:
        """Update run status.

        Args:
            run_id: ID of the run to update.
            status: New status.
            error_message: Optional error message (for failed runs).
        """
        if status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
            # Also set completed_at
            self.db.execute(
                """
                UPDATE runs SET status = ?, error_message = ?, completed_at = ?
                WHERE run_id = ?
                """,
                (status.value, error_message, datetime.now(UTC).isoformat(), run_id),
            )
        else:
            self.db.execute(
                """
                UPDATE runs SET status = ?, error_message = ?
                WHERE run_id = ?
                """,
                (status.value, error_message, run_id),
            )
        logger.debug(f"Updated run {run_id} status to {status.value}")

    def complete_run(
        self,
        run_id: str,
        result: ExecutionResult,
        estimated_cost_usd: float = 0.0,
        salience_spent: float = 0.0,
    ) -> None:
        """Finalize a run with execution results.

        Args:
            run_id: ID of the run to complete.
            result: Execution result from the pipeline executor.
            estimated_cost_usd: Estimated cost in USD.
            salience_spent: Total salience spent.
        """
        status = RunStatus.COMPLETED if result.success else RunStatus.FAILED
        error_message = "; ".join(result.errors) if result.errors else None

        self.db.execute(
            """
            UPDATE runs SET
                status = ?,
                completed_at = ?,
                error_message = ?,
                targets_total = ?,
                targets_processed = ?,
                targets_skipped = ?,
                tokens_used = ?,
                estimated_cost_usd = ?,
                salience_spent = ?
            WHERE run_id = ?
            """,
            (
                status.value,
                result.completed_at.isoformat() if result.completed_at else None,
                error_message,
                result.targets_processed + result.targets_skipped,
                result.targets_processed,
                result.targets_skipped,
                result.total_tokens,
                estimated_cost_usd,
                salience_spent,
                run_id,
            ),
        )
        logger.debug(f"Completed run {run_id} with status {status.value}")

    def get_run(self, run_id: str) -> Run | None:
        """Get a single run by ID.

        Args:
            run_id: ID of the run to fetch.

        Returns:
            The run record, or None if not found.
        """
        row = self.db.execute(
            "SELECT * FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()

        if row is None:
            return None

        return self._row_to_run(row)

    def get_runs(
        self,
        layer_name: str | None = None,
        status: RunStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Run]:
        """Query runs with optional filters.

        Args:
            layer_name: Filter by layer name.
            status: Filter by status.
            limit: Maximum number of runs to return.
            offset: Number of runs to skip.

        Returns:
            List of matching runs, ordered by started_at descending.
        """
        conditions = []
        params: list[Any] = []

        if layer_name is not None:
            conditions.append("layer_name = ?")
            params.append(layer_name)

        if status is not None:
            conditions.append("status = ?")
            params.append(status.value)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.extend([limit, offset])

        rows = self.db.execute(
            f"""
            SELECT * FROM runs
            WHERE {where_clause}
            ORDER BY started_at DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params),
        ).fetchall()

        return [self._row_to_run(row) for row in rows]

    def get_last_successful_run(self, layer_name: str) -> Run | None:
        """Get the most recent successful run for a layer.

        Args:
            layer_name: Name of the layer.

        Returns:
            The most recent completed run, or None if no successful runs.
        """
        row = self.db.execute(
            """
            SELECT * FROM runs
            WHERE layer_name = ? AND status = 'completed'
            ORDER BY completed_at DESC
            LIMIT 1
            """,
            (layer_name,),
        ).fetchone()

        if row is None:
            return None

        return self._row_to_run(row)

    def is_layer_running(self, layer_name: str) -> bool:
        """Check if a layer has an active (pending or running) run.

        Args:
            layer_name: Name of the layer.

        Returns:
            True if layer has an active run.
        """
        row = self.db.execute(
            """
            SELECT COUNT(*) as count FROM runs
            WHERE layer_name = ? AND status IN ('pending', 'running')
            """,
            (layer_name,),
        ).fetchone()

        return row["count"] > 0 if row else False

    def mark_stale_runs_failed(self) -> int:
        """Mark any 'running' runs as failed (for crash recovery).

        Returns:
            Number of runs marked as failed.
        """
        cursor = self.db.execute(
            """
            UPDATE runs SET
                status = 'failed',
                error_message = 'Run interrupted (process restart)',
                completed_at = ?
            WHERE status IN ('pending', 'running')
            """,
            (datetime.now(UTC).isoformat(),),
        )
        count = cursor.rowcount
        if count > 0:
            logger.warning(f"Marked {count} stale runs as failed")
        return count

    def save_trace(self, run_id: str, trace: list[dict[str, Any]]) -> None:
        """Save execution trace entries to database.

        Args:
            run_id: ID of the run.
            trace: List of trace entry dicts from ExecutionResult.
        """
        entries = []
        for entry in trace:
            entries.append((
                run_id,
                entry.get("node", "unknown"),
                entry.get("topic"),
                1 if entry.get("success", False) else 0,
                1 if entry.get("skipped", False) else 0,
                entry.get("skip_reason"),
                entry.get("error"),
                entry.get("tokens_used", 0),
                entry.get("timestamp", datetime.now(UTC).isoformat()),
            ))

        self.db.executemany(
            """
            INSERT INTO run_traces (
                run_id, node_name, topic_key, success, skipped,
                skip_reason, error, tokens_used, executed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            entries,
        )
        logger.debug(f"Saved {len(entries)} trace entries for run {run_id}")

    def get_trace(self, run_id: str) -> list[TraceEntry]:
        """Get trace entries for a run.

        Args:
            run_id: ID of the run.

        Returns:
            List of trace entries.
        """
        rows = self.db.execute(
            """
            SELECT * FROM run_traces
            WHERE run_id = ?
            ORDER BY id ASC
            """,
            (run_id,),
        ).fetchall()

        return [self._row_to_trace_entry(row) for row in rows]

    def _row_to_run(self, row: Any) -> Run:
        """Convert a database row to a Run object."""
        return Run(
            run_id=row["run_id"],
            layer_name=row["layer_name"],
            triggered_by=TriggerType(row["triggered_by"]),
            status=RunStatus(row["status"]),
            started_at=datetime.fromisoformat(row["started_at"]),
            window_start=datetime.fromisoformat(row["window_start"]),
            window_end=datetime.fromisoformat(row["window_end"]),
            schedule_expression=row["schedule_expression"],
            completed_at=(
                datetime.fromisoformat(row["completed_at"])
                if row["completed_at"]
                else None
            ),
            error_message=row["error_message"],
            targets_total=row["targets_total"],
            targets_processed=row["targets_processed"],
            targets_skipped=row["targets_skipped"],
            tokens_used=row["tokens_used"],
            estimated_cost_usd=row["estimated_cost_usd"] or 0.0,
            salience_spent=row["salience_spent"] or 0.0,
        )

    def _row_to_trace_entry(self, row: Any) -> TraceEntry:
        """Convert a database row to a TraceEntry object."""
        return TraceEntry(
            run_id=row["run_id"],
            node_name=row["node_name"],
            topic_key=row["topic_key"],
            success=bool(row["success"]),
            skipped=bool(row["skipped"]),
            skip_reason=row["skip_reason"],
            error=row["error"],
            tokens_used=row["tokens_used"],
            executed_at=datetime.fromisoformat(row["executed_at"]),
        )
