"""Audit endpoint for LLM calls and execution traces."""

from datetime import datetime

from fastapi import APIRouter, Query

from zos.api.dependencies import DatabaseDep
from zos.api.models import LLMCallRecord, PaginatedAudit

router = APIRouter()


@router.get("", response_model=PaginatedAudit)
async def get_audit_log(
    db: DatabaseDep,
    run_id: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> PaginatedAudit:
    """Get LLM call audit log.

    Returns records of all LLM API calls made during reflection runs.

    Args:
        run_id: Filter by run ID.
        offset: Number of records to skip.
        limit: Maximum number of records to return.
    """
    conditions = []
    params: list[str | int] = []

    if run_id:
        conditions.append("run_id = ?")
        params.append(run_id)

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    params.extend([limit, offset])

    rows = db.execute(
        f"""
        SELECT * FROM llm_calls
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params),
    ).fetchall()

    records = [
        LLMCallRecord(
            id=row["id"],
            run_id=row["run_id"],
            topic_key=row["topic_key"],
            layer=row["layer"],
            node=row["node"],
            model=row["model"],
            prompt_tokens=row["prompt_tokens"],
            completion_tokens=row["completion_tokens"],
            total_tokens=row["total_tokens"],
            estimated_cost_usd=row["estimated_cost_usd"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
        for row in rows
    ]

    return PaginatedAudit(
        records=records,
        total=len(records) + offset,
        offset=offset,
        limit=limit,
    )
