# Story 5.1: FastAPI Scaffold

**Epic**: Introspection
**Status**: 🔴 Not Started
**Estimated complexity**: Small

## Goal

Establish the FastAPI application structure with health check, CORS, and auto-generated documentation.

## Acceptance Criteria

- [ ] FastAPI app initializes
- [ ] `/health` endpoint returns status
- [ ] `/docs` shows OpenAPI documentation
- [ ] CORS configured for local development
- [ ] App integrates with main `serve` command
- [ ] Structured logging for requests

## Technical Notes

### Application Structure

```python
# src/zos/api.py
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import structlog

log = structlog.get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    log.info("api_starting")
    # Startup: connect to database, etc.
    yield
    # Shutdown: cleanup
    log.info("api_stopping")

def create_app(config: Config) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Zos Introspection API",
        description="Query Zos's understanding, salience, and operational state",
        version="0.1.0",
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

    # Register routes
    app.include_router(health_router)
    # More routers added in subsequent stories

    return app
```

### Health Endpoint

```python
# src/zos/api/health.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from datetime import datetime

router = APIRouter(tags=["health"])

class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: datetime
    database: str
    scheduler: str

@router.get("/health", response_model=HealthResponse)
async def health_check(db: Database = Depends(get_db)):
    """Check system health."""
    # Check database
    try:
        await db.execute("SELECT 1")
        db_status = "ok"
    except Exception:
        db_status = "error"

    # Check scheduler (if available)
    scheduler_status = "ok"  # Simplified for now

    return HealthResponse(
        status="ok" if db_status == "ok" else "degraded",
        version="0.1.0",
        timestamp=datetime.utcnow(),
        database=db_status,
        scheduler=scheduler_status,
    )
```

### Dependency Injection

```python
# src/zos/api/deps.py
from fastapi import Depends, Request

def get_config(request: Request) -> Config:
    """Get config from app state."""
    return request.app.state.config

def get_db(request: Request) -> Database:
    """Get database from app state."""
    return request.app.state.db

def get_ledger(request: Request) -> SalienceLedger:
    """Get salience ledger from app state."""
    return request.app.state.ledger
```

### CLI Integration

```python
# src/zos/cli.py
import uvicorn

@cli.command()
@click.option("--host", default="127.0.0.1", help="Host to bind")
@click.option("--port", default=8000, help="Port to bind")
@click.pass_context
def api(ctx, host: str, port: int):
    """Start only the API server (no observation/reflection)."""
    config = ctx.obj["config"]

    async def run():
        db = Database(config)
        await db.connect()

        app = create_app(config)
        app.state.config = config
        app.state.db = db
        app.state.ledger = SalienceLedger(db, config)

        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        await server.serve()

    asyncio.run(run())
```

### API Router Organization

```
src/zos/api/
├── __init__.py
├── health.py      # Health endpoint
├── insights.py    # Insights endpoints (Story 5.2)
├── salience.py    # Salience endpoints (Story 5.3)
├── runs.py        # Layer runs endpoints (Story 5.4)
├── deps.py        # Dependency injection
└── ui.py          # UI routes (Story 5.5+)
```

### OpenAPI Customization

```python
def create_app(config: Config) -> FastAPI:
    app = FastAPI(
        title="Zos Introspection API",
        description="""
## About

Zos is a Discord agent that observes, reflects, and accumulates understanding.

This API provides introspection into Zos's internal state:
- **Insights**: Accumulated understanding about users, relationships, and topics
- **Salience**: The attention-budget system governing what Zos thinks about
- **Layer Runs**: Audit trail of reflection executions

## Authentication

Currently no authentication (local development only).
        """,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/api/__init__.py` | Package init, create_app |
| `src/zos/api/health.py` | Health endpoint |
| `src/zos/api/deps.py` | Dependency injection |
| `src/zos/cli.py` | Add `api` command |
| `tests/test_api_health.py` | Health endpoint tests |

## Test Cases

1. App starts without error
2. `/health` returns 200
3. `/docs` renders OpenAPI UI
4. CORS headers present
5. Request logging works

## Definition of Done

- [ ] `zos api` starts server
- [ ] `/health` works
- [ ] `/docs` shows documentation
- [ ] Ready for additional routes

---

**Requires**: Epic 1 complete
**Blocks**: Stories 5.2-5.9
