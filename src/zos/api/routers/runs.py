"""Runs endpoints."""

from fastapi import APIRouter, HTTPException, Query

from zos.api.dependencies import RunRepoDep
from zos.api.models import PaginatedRuns, RunDetail, RunSummary, TraceEntryResponse
from zos.scheduler.models import RunStatus

router = APIRouter()


@router.get("", response_model=PaginatedRuns)
async def list_runs(
    repo: RunRepoDep,
    layer: str | None = None,
    status: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> PaginatedRuns:
    """List runs with pagination and filters.

    Args:
        layer: Filter by layer name.
        status: Filter by status (pending, running, completed, failed, cancelled).
        offset: Number of runs to skip.
        limit: Maximum number of runs to return.
    """
    status_enum = None
    if status:
        try:
            status_enum = RunStatus(status)
        except ValueError:
            valid = [s.value for s in RunStatus]
            raise HTTPException(
                400, f"Invalid status: {status}. Valid: {', '.join(valid)}"
            ) from None

    runs = repo.get_runs(
        layer_name=layer,
        status=status_enum,
        limit=limit,
        offset=offset,
    )

    # Approximate total (actual count would require additional query)
    total = len(runs) + offset

    return PaginatedRuns(
        runs=[
            RunSummary(
                run_id=r.run_id,
                layer_name=r.layer_name,
                status=r.status.value,
                triggered_by=r.triggered_by.value,
                started_at=r.started_at,
                completed_at=r.completed_at,
                targets_processed=r.targets_processed,
                targets_total=r.targets_total,
                tokens_used=r.tokens_used,
            )
            for r in runs
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(
    run_id: str,
    repo: RunRepoDep,
    include_trace: bool = Query(False),
) -> RunDetail:
    """Get detailed run information.

    Args:
        run_id: The run UUID.
        include_trace: Whether to include execution trace entries.
    """
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"Run not found: {run_id}")

    trace = None
    if include_trace:
        trace_entries = repo.get_trace(run_id)
        trace = [
            TraceEntryResponse(
                node_name=e.node_name,
                topic_key=e.topic_key,
                success=e.success,
                skipped=e.skipped,
                skip_reason=e.skip_reason,
                error=e.error,
                tokens_used=e.tokens_used,
                executed_at=e.executed_at,
            )
            for e in trace_entries
        ]

    return RunDetail(
        run_id=run.run_id,
        layer_name=run.layer_name,
        status=run.status.value,
        triggered_by=run.triggered_by.value,
        started_at=run.started_at,
        completed_at=run.completed_at,
        schedule_expression=run.schedule_expression,
        window_start=run.window_start,
        window_end=run.window_end,
        error_message=run.error_message,
        targets_total=run.targets_total,
        targets_processed=run.targets_processed,
        targets_skipped=run.targets_skipped,
        tokens_used=run.tokens_used,
        estimated_cost_usd=run.estimated_cost_usd,
        salience_spent=run.salience_spent,
        trace=trace,
    )
