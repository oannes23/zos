"""FastAPI application for Zos introspection API.

Provides endpoints for querying insights, salience, and operational state.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from zos.api.dev import router as dev_router
from zos.api.health import router as health_router
from zos.api.insights import router as insights_router
from zos.api.messages import router as messages_router
from zos.api.runs import router as runs_router
from zos.api.salience import router as salience_router
from zos.api.ui import router as ui_router

if TYPE_CHECKING:
    from zos.config import Config

log = structlog.get_logger()

# Static files directory
_static_dir = Path(__file__).parent.parent / "ui" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle.

    Handles startup and shutdown events for resource management.
    """
    log.info("api_starting")
    yield
    log.info("api_stopping")


def create_app(config: "Config") -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config: Application configuration.

    Returns:
        Configured FastAPI application instance.
    """
    app = FastAPI(
        title="Zos Introspection API",
        description="""
## About

Zos is a Discord agent that observes, reflects, and accumulates understanding.

This API provides introspection into Zos's internal state:
- **Messages**: Stored Discord messages for browsing and search
- **Insights**: Accumulated understanding about users, relationships, and topics
- **Salience**: The attention-budget system governing what Zos thinks about
- **Layer Runs**: Audit trail of reflection executions

## Authentication

Currently no authentication (local development only).
        """,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS for local development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:8000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request logging middleware
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        log.info(
            "request_start",
            method=request.method,
            path=request.url.path,
        )
        response = await call_next(request)
        log.info(
            "request_complete",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
        )
        return response

    # Mount static files for UI
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

    # Register routes
    app.include_router(health_router)
    app.include_router(insights_router)
    app.include_router(messages_router)
    app.include_router(runs_router)
    app.include_router(salience_router)
    app.include_router(ui_router)
    app.include_router(dev_router)

    return app
