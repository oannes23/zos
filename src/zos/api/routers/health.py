"""Health check endpoint."""

from fastapi import APIRouter

from zos.api.models import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Check system health.

    Returns basic health information about the Zos system.
    """
    return HealthResponse(
        status="ok",
        version="0.1.0",
        database=True,  # If we got here, DB is initialized
    )
