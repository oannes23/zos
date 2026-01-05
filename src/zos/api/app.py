"""FastAPI application factory."""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from zos.api.routers import audit, config, health, insights, layers, runs, salience
from zos.config import ApiConfig
from zos.exceptions import ZosError


def create_app(api_config: ApiConfig | None = None) -> FastAPI:
    """Create FastAPI application.

    Args:
        api_config: API configuration. If None, uses defaults.

    Returns:
        Configured FastAPI application.
    """
    app = FastAPI(
        title="Zos Introspection API",
        description="Read-only API for Zos system state and audit data",
        version="0.1.0",
    )

    # Add CORS if configured
    if api_config and api_config.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=api_config.cors_origins,
            allow_credentials=True,
            allow_methods=["GET"],
            allow_headers=["*"],
        )

    # Add error handling
    @app.exception_handler(ZosError)
    async def zos_error_handler(_request: Request, exc: ZosError) -> JSONResponse:
        """Handle ZosError exceptions."""
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "type": type(exc).__name__},
        )

    @app.exception_handler(Exception)
    async def general_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        """Handle unexpected exceptions."""
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "type": type(exc).__name__},
        )

    # Register routers
    app.include_router(health.router, tags=["health"])
    app.include_router(config.router, prefix="/config", tags=["config"])
    app.include_router(layers.router, prefix="/layers", tags=["layers"])
    app.include_router(runs.router, prefix="/runs", tags=["runs"])
    app.include_router(insights.router, prefix="/insights", tags=["insights"])
    app.include_router(salience.router, prefix="/salience", tags=["salience"])
    app.include_router(audit.router, prefix="/audit", tags=["audit"])

    return app
