"""Time window calculation for layer execution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from zos.logging import get_logger

if TYPE_CHECKING:
    from zos.scheduler.repository import RunRepository

logger = get_logger("scheduler.window")


def calculate_run_window(
    layer_name: str,
    max_lookback_hours: int,
    run_repo: RunRepository,
) -> tuple[datetime, datetime]:
    """Calculate the time window for a layer execution.

    The window starts from either:
    1. The completion time of the last successful run (if one exists)
    2. max_lookback_hours before now (if no successful runs or too old)

    The window always ends at the current time.

    Args:
        layer_name: Name of the layer to calculate window for.
        max_lookback_hours: Maximum hours to look back for messages.
        run_repo: Run repository for querying previous runs.

    Returns:
        Tuple of (window_start, window_end) datetimes in UTC.
    """
    window_end = datetime.now(UTC)
    max_start = window_end - timedelta(hours=max_lookback_hours)

    # Try to find last successful run
    last_run = run_repo.get_last_successful_run(layer_name)

    if last_run and last_run.completed_at:
        # Use last run's completion time, but cap at max_lookback_hours
        window_start = max(last_run.completed_at, max_start)
        logger.debug(
            f"Window for {layer_name}: since last run at {last_run.completed_at} "
            f"(capped at {max_start})"
        )
    else:
        # No previous run, use max lookback
        window_start = max_start
        logger.debug(
            f"Window for {layer_name}: no previous run, using max lookback "
            f"({max_lookback_hours}h from {window_start})"
        )

    return window_start, window_end
