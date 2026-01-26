"""Layer runs API endpoints for Zos.

Provides endpoints for querying layer run history and operational status.
Layer runs are the audit trail of reflection execution - essential for
understanding what Zos has been doing and debugging issues.
"""

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func, select

from zos.api.deps import get_db
from zos.database import layer_runs
from zos.models import LayerRun, LayerRunStatus, row_to_model

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

log = structlog.get_logger()

router = APIRouter(prefix="/runs", tags=["layer-runs"])


# =============================================================================
# Response Models
# =============================================================================


class LayerRunSummary(BaseModel):
    """Summary view of a layer run for list responses."""

    id: str
    layer_name: str
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    duration_seconds: Optional[float]
    targets_processed: int
    insights_created: int
    tokens_total: Optional[int]
    estimated_cost_usd: Optional[float]


class LayerRunDetail(BaseModel):
    """Detailed view of a layer run including errors."""

    id: str
    layer_name: str
    layer_hash: str
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    duration_seconds: Optional[float]
    targets_matched: int
    targets_processed: int
    targets_skipped: int
    insights_created: int
    model_profile: Optional[str]
    model_provider: Optional[str]
    model_name: Optional[str]
    tokens_input: Optional[int]
    tokens_output: Optional[int]
    tokens_total: Optional[int]
    estimated_cost_usd: Optional[float]
    errors: Optional[list[dict]]


class LayerRunListResponse(BaseModel):
    """Paginated list of layer runs."""

    runs: list[LayerRunSummary]
    total: int
    offset: int
    limit: int


class LayerStats(BaseModel):
    """Statistics for a single layer."""

    runs: int
    insights: int


class LayerRunStatsResponse(BaseModel):
    """Aggregate statistics for layer runs."""

    period_days: int
    total_runs: int
    successful_runs: int
    failed_runs: int
    dry_runs: int
    total_insights: int
    total_tokens: int
    total_cost_usd: float
    by_layer: dict[str, LayerStats]


# =============================================================================
# Helper Functions
# =============================================================================


def _format_run_summary(run: LayerRun) -> LayerRunSummary:
    """Format run for list response.

    Args:
        run: The LayerRun model instance.

    Returns:
        LayerRunSummary with calculated duration.
    """
    duration = None
    if run.completed_at and run.started_at:
        duration = (run.completed_at - run.started_at).total_seconds()

    return LayerRunSummary(
        id=run.id,
        layer_name=run.layer_name,
        status=run.status.value,
        started_at=run.started_at,
        completed_at=run.completed_at,
        duration_seconds=duration,
        targets_processed=run.targets_processed,
        insights_created=run.insights_created,
        tokens_total=run.tokens_total,
        estimated_cost_usd=run.estimated_cost_usd,
    )


def _format_run_detail(run: LayerRun) -> LayerRunDetail:
    """Format run for detail response.

    Args:
        run: The LayerRun model instance.

    Returns:
        LayerRunDetail with all fields including errors.
    """
    duration = None
    if run.completed_at and run.started_at:
        duration = (run.completed_at - run.started_at).total_seconds()

    return LayerRunDetail(
        id=run.id,
        layer_name=run.layer_name,
        layer_hash=run.layer_hash,
        status=run.status.value,
        started_at=run.started_at,
        completed_at=run.completed_at,
        duration_seconds=duration,
        targets_matched=run.targets_matched,
        targets_processed=run.targets_processed,
        targets_skipped=run.targets_skipped,
        insights_created=run.insights_created,
        model_profile=run.model_profile,
        model_provider=run.model_provider,
        model_name=run.model_name,
        tokens_input=run.tokens_input,
        tokens_output=run.tokens_output,
        tokens_total=run.tokens_total,
        estimated_cost_usd=run.estimated_cost_usd,
        errors=run.errors,
    )


# =============================================================================
# Database Operations
# =============================================================================


def list_layer_runs(
    db: "Engine",
    layer_name: str | None = None,
    status: str | None = None,
    since: datetime | None = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[LayerRun], int]:
    """List layer runs with filters.

    Args:
        db: Database engine.
        layer_name: Optional filter by layer name.
        status: Optional filter by status.
        since: Optional filter for runs after this time.
        offset: Pagination offset.
        limit: Maximum number of results.

    Returns:
        Tuple of (list of LayerRun models, total count).
    """
    with db.connect() as conn:
        # Build base conditions
        conditions = []
        if layer_name:
            conditions.append(layer_runs.c.layer_name == layer_name)
        if status:
            conditions.append(layer_runs.c.status == status)
        if since:
            conditions.append(layer_runs.c.started_at >= since)

        # Count query
        count_stmt = select(func.count()).select_from(layer_runs)
        if conditions:
            count_stmt = count_stmt.where(*conditions)

        total = conn.execute(count_stmt).scalar() or 0

        # Data query - apply conditions before ordering
        stmt = select(layer_runs)
        if conditions:
            stmt = stmt.where(*conditions)
        stmt = stmt.order_by(layer_runs.c.started_at.desc()).offset(offset).limit(limit)

        rows = conn.execute(stmt).fetchall()

        runs = [
            LayerRun(
                id=row.id,
                layer_name=row.layer_name,
                layer_hash=row.layer_hash,
                started_at=row.started_at,
                completed_at=row.completed_at,
                status=LayerRunStatus(row.status),
                targets_matched=row.targets_matched,
                targets_processed=row.targets_processed,
                targets_skipped=row.targets_skipped,
                insights_created=row.insights_created,
                model_profile=row.model_profile,
                model_provider=row.model_provider,
                model_name=row.model_name,
                tokens_input=row.tokens_input,
                tokens_output=row.tokens_output,
                tokens_total=row.tokens_total,
                estimated_cost_usd=row.estimated_cost_usd,
                errors=row.errors,
            )
            for row in rows
        ]

        return runs, total


def get_layer_run(db: "Engine", run_id: str) -> LayerRun | None:
    """Get a single layer run by ID.

    Args:
        db: Database engine.
        run_id: The run ID (ULID).

    Returns:
        LayerRun model or None if not found.
    """
    with db.connect() as conn:
        stmt = select(layer_runs).where(layer_runs.c.id == run_id)
        row = conn.execute(stmt).fetchone()

        if not row:
            return None

        return LayerRun(
            id=row.id,
            layer_name=row.layer_name,
            layer_hash=row.layer_hash,
            started_at=row.started_at,
            completed_at=row.completed_at,
            status=LayerRunStatus(row.status),
            targets_matched=row.targets_matched,
            targets_processed=row.targets_processed,
            targets_skipped=row.targets_skipped,
            insights_created=row.insights_created,
            model_profile=row.model_profile,
            model_provider=row.model_provider,
            model_name=row.model_name,
            tokens_input=row.tokens_input,
            tokens_output=row.tokens_output,
            tokens_total=row.tokens_total,
            estimated_cost_usd=row.estimated_cost_usd,
            errors=row.errors,
        )


def get_layer_run_stats(db: "Engine", since: datetime) -> dict:
    """Get aggregate statistics for layer runs.

    Args:
        db: Database engine.
        since: Only include runs after this time.

    Returns:
        Dictionary with aggregate statistics.
    """
    with db.connect() as conn:
        # Aggregate query
        stmt = select(
            func.count().label("total"),
            func.sum(
                case((layer_runs.c.status == "success", 1), else_=0)
            ).label("successful"),
            func.sum(
                case((layer_runs.c.status == "failed", 1), else_=0)
            ).label("failed"),
            func.sum(
                case((layer_runs.c.status == "dry", 1), else_=0)
            ).label("dry"),
            func.sum(layer_runs.c.insights_created).label("insights"),
            func.sum(layer_runs.c.tokens_total).label("tokens"),
            func.sum(layer_runs.c.estimated_cost_usd).label("cost"),
        ).where(layer_runs.c.started_at >= since)

        row = conn.execute(stmt).fetchone()

        # Per-layer breakdown
        by_layer_stmt = (
            select(
                layer_runs.c.layer_name,
                func.count().label("runs"),
                func.sum(layer_runs.c.insights_created).label("insights"),
            )
            .where(layer_runs.c.started_at >= since)
            .group_by(layer_runs.c.layer_name)
        )

        by_layer_rows = conn.execute(by_layer_stmt).fetchall()

        return {
            "total_runs": row.total or 0,
            "successful": row.successful or 0,
            "failed": row.failed or 0,
            "dry": row.dry or 0,
            "total_insights": row.insights or 0,
            "total_tokens": row.tokens or 0,
            "total_cost": row.cost or 0.0,
            "by_layer": {
                r.layer_name: {"runs": r.runs, "insights": r.insights or 0}
                for r in by_layer_rows
            },
        }


# =============================================================================
# Endpoints
# =============================================================================


@router.get("", response_model=LayerRunListResponse)
async def list_runs(
    layer_name: Optional[str] = Query(None, description="Filter by layer name"),
    status: Optional[str] = Query(None, description="Filter by status"),
    since: Optional[datetime] = Query(None, description="Only runs after this time"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
    db: "Engine" = Depends(get_db),
) -> LayerRunListResponse:
    """List recent layer runs.

    Returns paginated list of layer runs with optional filters.
    Ordered by start time descending (most recent first).
    """
    runs, total = list_layer_runs(
        db,
        layer_name=layer_name,
        status=status,
        since=since,
        offset=offset,
        limit=limit,
    )

    log.info(
        "list_runs",
        total=total,
        returned=len(runs),
        layer_name=layer_name,
        status=status,
    )

    return LayerRunListResponse(
        runs=[_format_run_summary(r) for r in runs],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/stats/summary", response_model=LayerRunStatsResponse)
async def get_run_stats(
    days: int = Query(7, ge=1, le=30, description="Number of days to include"),
    db: "Engine" = Depends(get_db),
) -> LayerRunStatsResponse:
    """Get aggregate statistics for recent runs.

    Returns summary statistics including counts by status,
    total tokens, costs, and per-layer breakdowns.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    stats = get_layer_run_stats(db, since=since)

    log.info(
        "get_run_stats",
        days=days,
        total_runs=stats["total_runs"],
    )

    return LayerRunStatsResponse(
        period_days=days,
        total_runs=stats["total_runs"],
        successful_runs=stats["successful"],
        failed_runs=stats["failed"],
        dry_runs=stats["dry"],
        total_insights=stats["total_insights"],
        total_tokens=stats["total_tokens"],
        total_cost_usd=stats["total_cost"],
        by_layer={
            name: LayerStats(runs=data["runs"], insights=data["insights"])
            for name, data in stats["by_layer"].items()
        },
    )


@router.get("/{run_id}", response_model=LayerRunDetail)
async def get_run(
    run_id: str,
    db: "Engine" = Depends(get_db),
) -> LayerRunDetail:
    """Get details of a specific layer run.

    Returns full run details including any errors encountered.
    Errors are framed as "felt experience" - friction in operation
    that becomes material for understanding system behavior.
    """
    run = get_layer_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    log.info("get_run", run_id=run_id, status=run.status.value)

    return _format_run_detail(run)
