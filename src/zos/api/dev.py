"""Development mode API endpoints for Zos.

Provides CRUD operations for insights that are only available when
dev_mode is enabled. These endpoints are for development and testing
purposes only - they should never be enabled in production.

All mutations are audit-logged for transparency.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from pathlib import Path

from zos.api.deps import get_config, get_db
from zos.database import generate_id, insights as insights_table
from zos.models import Insight, VisibilityScope

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from zos.config import Config

log = structlog.get_logger()

router = APIRouter(prefix="/dev", tags=["development"])

# Template directory relative to this file
_templates_dir = Path(__file__).parent.parent / "ui" / "templates"
templates = Jinja2Templates(directory=_templates_dir)


# =============================================================================
# Dependency
# =============================================================================


def require_dev_mode(config: "Config" = Depends(get_config)) -> bool:
    """Dependency that ensures dev mode is enabled.

    Raises HTTPException 403 if dev_mode is not enabled in config.

    Args:
        config: Application configuration.

    Returns:
        True if dev mode is enabled.

    Raises:
        HTTPException: If dev mode is not enabled.
    """
    if not config.development.dev_mode:
        raise HTTPException(
            status_code=403,
            detail="Dev mode is not enabled. Set development.dev_mode: true in config.",
        )
    return True


# =============================================================================
# Request/Response Models
# =============================================================================


class InsightCreate(BaseModel):
    """Request model for creating a new insight."""

    topic_key: str = Field(..., description="Topic key (e.g., server:123:user:456)")
    category: str = Field(..., description="Insight category (e.g., user_reflection)")
    content: str = Field(..., description="The insight content")
    confidence: float = Field(0.5, ge=0.0, le=1.0, description="Confidence (0.0-1.0)")
    importance: float = Field(0.5, ge=0.0, le=1.0, description="Importance (0.0-1.0)")
    novelty: float = Field(0.5, ge=0.0, le=1.0, description="Novelty (0.0-1.0)")
    strength_adjustment: float = Field(1.0, ge=0.1, le=10.0, description="Strength adjustment factor")
    valence_joy: Optional[float] = Field(None, ge=0.0, le=1.0)
    valence_concern: Optional[float] = Field(None, ge=0.0, le=1.0)
    valence_curiosity: Optional[float] = Field(0.5, ge=0.0, le=1.0, description="Defaults to 0.5 to satisfy constraint")
    valence_warmth: Optional[float] = Field(None, ge=0.0, le=1.0)
    valence_tension: Optional[float] = Field(None, ge=0.0, le=1.0)


class InsightUpdate(BaseModel):
    """Request model for updating an insight (partial update)."""

    content: Optional[str] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    importance: Optional[float] = Field(None, ge=0.0, le=1.0)
    novelty: Optional[float] = Field(None, ge=0.0, le=1.0)
    quarantined: Optional[bool] = None


class BulkDeleteFilters(BaseModel):
    """Filters for bulk delete operation."""

    topic_key: Optional[str] = Field(None, description="Delete insights for this topic")
    category: Optional[str] = Field(None, description="Delete insights of this category")
    before: Optional[datetime] = Field(None, description="Delete insights created before this time")


class InsightCreateResponse(BaseModel):
    """Response for insight creation."""

    id: str
    message: str


class InsightUpdateResponse(BaseModel):
    """Response for insight update."""

    message: str


class InsightDeleteResponse(BaseModel):
    """Response for insight deletion."""

    message: str


class BulkDeleteResponse(BaseModel):
    """Response for bulk delete operation."""

    deleted: int


# =============================================================================
# API Endpoints
# =============================================================================


def _ensure_dev_layer_run(engine: "Engine") -> str:
    """Ensure the dev_manual layer run exists.

    Creates a placeholder layer_run record for dev mode insights.
    This is needed because insights have a foreign key to layer_runs.

    Args:
        engine: Database engine.

    Returns:
        The layer run ID ("dev_manual").
    """
    from zos.database import layer_runs
    from sqlalchemy import select

    layer_run_id = "dev_manual"

    with engine.connect() as conn:
        # Check if it already exists
        stmt = select(layer_runs).where(layer_runs.c.id == layer_run_id)
        result = conn.execute(stmt).fetchone()

        if not result:
            # Create the dev_manual layer run
            now = datetime.now(timezone.utc)
            stmt = layer_runs.insert().values(
                id=layer_run_id,
                layer_name="dev_manual",
                layer_hash="dev",
                started_at=now,
                completed_at=now,
                status="success",
                targets_matched=0,
                targets_processed=0,
                targets_skipped=0,
                insights_created=0,
            )
            conn.execute(stmt)
            conn.commit()

            log.info("dev_layer_run_created", layer_run_id=layer_run_id)

    return layer_run_id


def _ensure_topic(engine: "Engine", topic_key: str) -> None:
    """Ensure a topic exists in the database.

    Creates a provisional topic if it doesn't exist. This is needed
    because insights have a foreign key to topics.key.

    Args:
        engine: Database engine.
        topic_key: The topic key to ensure exists.
    """
    from zos.database import topics
    from sqlalchemy import select

    with engine.connect() as conn:
        # Check if it already exists
        stmt = select(topics).where(topics.c.key == topic_key)
        result = conn.execute(stmt).fetchone()

        if not result:
            # Determine category from topic key
            parts = topic_key.split(":")
            if topic_key.startswith("self:"):
                category = "self"
                is_global = True
            elif topic_key.startswith("user:") and "server:" not in topic_key:
                category = "user"
                is_global = True
            elif topic_key.startswith("server:"):
                if ":user:" in topic_key:
                    category = "user"
                elif ":channel:" in topic_key:
                    category = "channel"
                else:
                    category = "server"
                is_global = False
            else:
                category = "other"
                is_global = False

            # Create provisional topic
            now = datetime.now(timezone.utc)
            stmt = topics.insert().values(
                key=topic_key,
                category=category,
                is_global=is_global,
                provisional=True,
                created_at=now,
                last_activity_at=now,
            )
            conn.execute(stmt)
            conn.commit()

            log.info("dev_topic_created", topic_key=topic_key, category=category)


@router.post("/insights", response_model=InsightCreateResponse, dependencies=[Depends(require_dev_mode)])
async def create_insight(
    data: InsightCreate,
    db: "Engine" = Depends(get_db),
) -> InsightCreateResponse:
    """Create a new insight (dev mode only).

    Creates an insight with manually specified fields. The insight is marked
    as coming from a dev_manual layer run.

    Args:
        data: Insight creation data.
        db: Database engine.

    Returns:
        InsightCreateResponse with the new insight ID.
    """
    from zos.insights import insert_insight

    # Ensure the dev_manual layer run exists (for foreign key constraint)
    layer_run_id = _ensure_dev_layer_run(db)

    # Ensure the topic exists (for foreign key constraint)
    _ensure_topic(db, data.topic_key)

    insight_id = generate_id()
    now = datetime.now(timezone.utc)

    insight = Insight(
        id=insight_id,
        topic_key=data.topic_key,
        category=data.category,
        content=data.content,
        sources_scope_max=VisibilityScope.PUBLIC,
        created_at=now,
        layer_run_id=layer_run_id,
        salience_spent=0.0,
        strength_adjustment=data.strength_adjustment,
        strength=data.strength_adjustment,  # No salience spent, so strength = adjustment
        original_topic_salience=0.0,  # Dev insights don't track original salience
        confidence=data.confidence,
        importance=data.importance,
        novelty=data.novelty,
        valence_joy=data.valence_joy,
        valence_concern=data.valence_concern,
        valence_curiosity=data.valence_curiosity,
        valence_warmth=data.valence_warmth,
        valence_tension=data.valence_tension,
    )

    await insert_insight(db, insight)

    log.info(
        "dev_insight_created",
        insight_id=insight_id,
        topic=data.topic_key,
        category=data.category,
    )

    return InsightCreateResponse(id=insight_id, message="Insight created")


@router.patch("/insights/{insight_id}", response_model=InsightUpdateResponse, dependencies=[Depends(require_dev_mode)])
async def update_insight(
    insight_id: str,
    data: InsightUpdate,
    db: "Engine" = Depends(get_db),
) -> InsightUpdateResponse:
    """Update an existing insight (dev mode only).

    Only updates fields that are provided in the request body.

    Args:
        insight_id: The insight ID to update.
        data: Fields to update.
        db: Database engine.

    Returns:
        InsightUpdateResponse confirming the update.

    Raises:
        HTTPException: If insight not found.
    """
    from zos.insights import get_insight
    from zos.api.db_queries import update_insight as db_update

    insight = await get_insight(db, insight_id)
    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found")

    updates = data.model_dump(exclude_none=True)
    if updates:
        await db_update(db, insight_id, updates)

        log.info(
            "dev_insight_updated",
            insight_id=insight_id,
            updates=list(updates.keys()),
        )

    return InsightUpdateResponse(message="Insight updated")


@router.delete("/insights/{insight_id}", response_model=InsightDeleteResponse, dependencies=[Depends(require_dev_mode)])
async def delete_insight(
    insight_id: str,
    db: "Engine" = Depends(get_db),
) -> InsightDeleteResponse:
    """Delete an insight (dev mode only).

    Performs a hard delete - the insight is permanently removed from the database.
    Memory is sacred - use sparingly. This is for development cleanup only.

    Args:
        insight_id: The insight ID to delete.
        db: Database engine.

    Returns:
        InsightDeleteResponse confirming the deletion.

    Raises:
        HTTPException: If insight not found.
    """
    from zos.insights import get_insight
    from zos.api.db_queries import delete_insight as db_delete

    insight = await get_insight(db, insight_id)
    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found")

    await db_delete(db, insight_id)

    log.warning(
        "dev_insight_deleted",
        insight_id=insight_id,
        topic=insight.topic_key,
        content_preview=insight.content[:50] if len(insight.content) > 50 else insight.content,
    )

    return InsightDeleteResponse(message="Insight deleted")


@router.post("/insights/bulk-delete", response_model=BulkDeleteResponse, dependencies=[Depends(require_dev_mode)])
async def bulk_delete_insights(
    filters: BulkDeleteFilters,
    db: "Engine" = Depends(get_db),
) -> BulkDeleteResponse:
    """Bulk delete insights matching criteria (dev mode only).

    At least one filter must be specified to prevent accidental deletion
    of all insights.

    Args:
        filters: Delete criteria.
        db: Database engine.

    Returns:
        BulkDeleteResponse with count of deleted insights.

    Raises:
        HTTPException: If no filters specified.
    """
    from zos.api.db_queries import bulk_delete_insights as db_bulk_delete

    if not any([filters.topic_key, filters.category, filters.before]):
        raise HTTPException(
            status_code=400,
            detail="Must specify at least one filter (topic_key, category, or before)",
        )

    count = await db_bulk_delete(
        db,
        topic_key=filters.topic_key,
        category=filters.category,
        before=filters.before,
    )

    log.warning(
        "dev_bulk_delete",
        count=count,
        topic_key=filters.topic_key,
        category=filters.category,
        before=filters.before.isoformat() if filters.before else None,
    )

    return BulkDeleteResponse(deleted=count)


# =============================================================================
# UI Endpoints
# =============================================================================


@router.get("/create-insight", response_class=HTMLResponse)
async def create_insight_page(
    request: Request,
    _: bool = Depends(require_dev_mode),
) -> HTMLResponse:
    """Manual insight creation page (dev mode only).

    Renders a form for creating insights manually during development.

    Args:
        request: FastAPI request object.

    Returns:
        HTML response with the creation form.
    """
    return templates.TemplateResponse(
        request=request,
        name="dev/create_insight.html",
        context={"active": "dev", "dev_mode": True},  # Always true since require_dev_mode passed
    )
