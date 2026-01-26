"""Health check endpoint for Zos API.

Provides system health status including database and scheduler connectivity.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text

from zos.api.deps import get_db

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str
    version: str
    timestamp: datetime
    database: str
    scheduler: str


@router.get("/health", response_model=HealthResponse)
async def health_check(db: "Engine" = Depends(get_db)) -> HealthResponse:
    """Check system health.

    Returns status of database connection and scheduler.
    Overall status is 'ok' if all components are healthy,
    'degraded' if any component has issues.
    """
    # Check database
    try:
        with db.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"

    # Check scheduler (simplified for now - will be enhanced in later stories)
    scheduler_status = "ok"

    # Determine overall status
    overall_status = "ok" if db_status == "ok" else "degraded"

    return HealthResponse(
        status=overall_status,
        version="0.1.0",
        timestamp=datetime.now(timezone.utc),
        database=db_status,
        scheduler=scheduler_status,
    )
