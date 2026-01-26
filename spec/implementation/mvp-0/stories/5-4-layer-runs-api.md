# Story 5.4: Layer Runs API

**Epic**: Introspection
**Status**: 🟢 Complete
**Estimated complexity**: Small

## Goal

Implement API endpoints for querying layer run history and operational status.

## Acceptance Criteria

- [x] GET `/runs` lists recent layer runs
- [x] GET `/runs/{run_id}` returns run details with errors
- [x] Filter by layer name, status
- [x] Includes token usage and cost estimates
- [x] Dry runs distinguishable

## Technical Notes

### Endpoints

```python
# src/zos/api/runs.py
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

router = APIRouter(prefix="/runs", tags=["layer-runs"])

class LayerRunSummary(BaseModel):
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
    runs: list[LayerRunSummary]
    total: int
    offset: int
    limit: int

@router.get("", response_model=LayerRunListResponse)
async def list_runs(
    layer_name: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    since: Optional[datetime] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Database = Depends(get_db),
):
    """List recent layer runs."""
    runs, total = await db.list_layer_runs(
        layer_name=layer_name,
        status=status,
        since=since,
        offset=offset,
        limit=limit,
    )

    return LayerRunListResponse(
        runs=[_format_run_summary(r) for r in runs],
        total=total,
        offset=offset,
        limit=limit,
    )

@router.get("/{run_id}", response_model=LayerRunDetail)
async def get_run(
    run_id: str,
    db: Database = Depends(get_db),
):
    """Get details of a specific layer run."""
    run = await db.get_layer_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return _format_run_detail(run)

@router.get("/stats/summary")
async def get_run_stats(
    days: int = Query(7, ge=1, le=30),
    db: Database = Depends(get_db),
):
    """Get aggregate statistics for recent runs."""
    since = datetime.utcnow() - timedelta(days=days)
    stats = await db.get_layer_run_stats(since=since)

    return {
        "period_days": days,
        "total_runs": stats['total_runs'],
        "successful_runs": stats['successful'],
        "failed_runs": stats['failed'],
        "dry_runs": stats['dry'],
        "total_insights": stats['total_insights'],
        "total_tokens": stats['total_tokens'],
        "total_cost_usd": stats['total_cost'],
        "by_layer": stats['by_layer'],
    }
```

### Response Formatting

```python
def _format_run_summary(run: LayerRun) -> LayerRunSummary:
    """Format run for list response."""
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
    """Format run for detail response."""
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
```

### Database Queries

```python
# src/zos/database.py

async def list_layer_runs(
    self,
    layer_name: str | None = None,
    status: str | None = None,
    since: datetime | None = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[LayerRun], int]:
    """List layer runs with filters."""
    # Count
    count_stmt = select(func.count()).select_from(layer_runs)
    if layer_name:
        count_stmt = count_stmt.where(layer_runs.c.layer_name == layer_name)
    if status:
        count_stmt = count_stmt.where(layer_runs.c.status == status)
    if since:
        count_stmt = count_stmt.where(layer_runs.c.started_at >= since)

    total = await self.fetch_scalar(count_stmt)

    # Data
    stmt = select(layer_runs).order_by(
        layer_runs.c.started_at.desc()
    ).offset(offset).limit(limit)

    if layer_name:
        stmt = stmt.where(layer_runs.c.layer_name == layer_name)
    if status:
        stmt = stmt.where(layer_runs.c.status == status)
    if since:
        stmt = stmt.where(layer_runs.c.started_at >= since)

    rows = await self.fetch_all(stmt)
    return [row_to_model(r, LayerRun) for r in rows], total

async def get_layer_run_stats(self, since: datetime) -> dict:
    """Get aggregate statistics for layer runs."""
    stmt = select(
        func.count().label('total'),
        func.sum(case((layer_runs.c.status == 'success', 1), else_=0)).label('successful'),
        func.sum(case((layer_runs.c.status == 'failed', 1), else_=0)).label('failed'),
        func.sum(case((layer_runs.c.status == 'dry', 1), else_=0)).label('dry'),
        func.sum(layer_runs.c.insights_created).label('insights'),
        func.sum(layer_runs.c.tokens_total).label('tokens'),
        func.sum(layer_runs.c.estimated_cost_usd).label('cost'),
    ).where(layer_runs.c.started_at >= since)

    row = await self.fetch_one(stmt)

    # Per-layer breakdown
    by_layer_stmt = select(
        layer_runs.c.layer_name,
        func.count().label('runs'),
        func.sum(layer_runs.c.insights_created).label('insights'),
    ).where(
        layer_runs.c.started_at >= since
    ).group_by(layer_runs.c.layer_name)

    by_layer_rows = await self.fetch_all(by_layer_stmt)

    return {
        'total_runs': row['total'] or 0,
        'successful': row['successful'] or 0,
        'failed': row['failed'] or 0,
        'dry': row['dry'] or 0,
        'total_insights': row['insights'] or 0,
        'total_tokens': row['tokens'] or 0,
        'total_cost': row['cost'] or 0,
        'by_layer': {r['layer_name']: {'runs': r['runs'], 'insights': r['insights']} for r in by_layer_rows},
    }
```

### Example Responses

**GET /runs?limit=5**
```json
{
  "runs": [
    {
      "id": "01HQXYZ...",
      "layer_name": "nightly-user-reflection",
      "status": "success",
      "started_at": "2026-01-23T03:00:00Z",
      "completed_at": "2026-01-23T03:02:30Z",
      "duration_seconds": 150.5,
      "targets_processed": 10,
      "insights_created": 8,
      "tokens_total": 15000,
      "estimated_cost_usd": 0.045
    }
  ],
  "total": 142,
  "offset": 0,
  "limit": 5
}
```

**GET /runs/stats/summary?days=7**
```json
{
  "period_days": 7,
  "total_runs": 42,
  "successful_runs": 38,
  "failed_runs": 1,
  "dry_runs": 3,
  "total_insights": 156,
  "total_tokens": 450000,
  "total_cost_usd": 1.35,
  "by_layer": {
    "nightly-user-reflection": {"runs": 7, "insights": 52},
    "weekly-self-reflection": {"runs": 1, "insights": 1}
  }
}
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/api/runs.py` | Layer runs endpoints |
| `src/zos/api/__init__.py` | Register router |
| `src/zos/database.py` | Query methods |
| `tests/test_api_runs.py` | API tests |

## Test Cases

1. List returns recent runs
2. Filter by layer name works
3. Filter by status works
4. Detail includes errors
5. Stats aggregation correct
6. Duration calculated properly

## Definition of Done

- [x] All endpoints work
- [x] Filters functional
- [x] Stats accurate
- [x] Ready for monitoring UI

---

**Requires**: Story 5.1, Story 4.3 (layer runs exist)
**Blocks**: Story 5.8 (UI monitor)
