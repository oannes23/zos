"""Insights API endpoints for Zos.

Provides endpoints for querying insights by topic, searching, and listing
recent insights with pagination.
"""

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from zos.api.deps import get_config, get_db
from zos.insights import InsightRetriever, PROFILES

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from zos.config import Config

log = structlog.get_logger()

router = APIRouter(prefix="/insights", tags=["insights"])


# =============================================================================
# Response Models
# =============================================================================


class InsightResponse(BaseModel):
    """Single insight response model.

    Includes all insight fields plus computed temporal marker
    that describes how "fresh" the memory feels.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    topic_key: str
    topic_key_original: Optional[str] = None  # Present when readable=true
    category: str
    content: str
    created_at: datetime
    temporal_marker: str
    strength: float
    confidence: float
    importance: float
    novelty: float
    valence: dict[str, Optional[float]]
    open_questions: Optional[list[str]] = None  # Forward-looking curiosity


class InsightListResponse(BaseModel):
    """Paginated list of insights response.

    Includes pagination metadata for navigating through results.
    """

    readable: bool = False  # True when human-readable names are enabled
    insights: list[InsightResponse]
    total: int
    offset: int
    limit: int


# =============================================================================
# Helper Functions
# =============================================================================


def _relative_time(dt: datetime) -> str:
    """Human-relative time description.

    Args:
        dt: Datetime to describe.

    Returns:
        Human-readable relative time string.
    """
    # Ensure timezone-aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    delta = now - dt

    if delta < timedelta(hours=1):
        return "just now"
    elif delta < timedelta(days=1):
        hours = int(delta.total_seconds() / 3600)
        return f"{hours} hours ago"
    elif delta < timedelta(days=7):
        return f"{delta.days} days ago"
    elif delta < timedelta(days=30):
        weeks = delta.days // 7
        return f"{weeks} weeks ago"
    else:
        months = delta.days // 30
        return f"{months} months ago"


def _strength_label(strength: float) -> str:
    """Human-readable strength description.

    Maps numeric strength values to phenomenological descriptions
    that convey how "strongly held" a memory is.

    Args:
        strength: The strength value.

    Returns:
        Human-readable description.
    """
    if strength >= 8:
        return "strong memory"
    elif strength >= 5:
        return "clear memory"
    elif strength >= 2:
        return "fading memory"
    else:
        return "distant memory"


def _format_insight_response(
    insight,
    temporal_marker: str | None = None,
    readable_topic_key: str | None = None,
    original_topic_key: str | None = None,
) -> InsightResponse:
    """Format insight for API response.

    Handles both Insight and FormattedInsight objects by checking
    for the presence of temporal_marker attribute.

    Args:
        insight: Either an Insight model or FormattedInsight.
        temporal_marker: Optional pre-computed temporal marker.
        readable_topic_key: Optional human-readable topic key (when readable=true).
        original_topic_key: Optional original topic key (when readable=true).

    Returns:
        InsightResponse for API output.
    """
    # Calculate temporal marker if not already present
    if temporal_marker is not None:
        marker = temporal_marker
    elif hasattr(insight, "temporal_marker"):
        marker = insight.temporal_marker
    else:
        age = _relative_time(insight.created_at)
        strength_label = _strength_label(insight.strength)
        marker = f"{strength_label} from {age}"

    # Use readable topic key if provided, otherwise use original
    topic_key = readable_topic_key if readable_topic_key else insight.topic_key

    return InsightResponse(
        id=insight.id,
        topic_key=topic_key,
        topic_key_original=original_topic_key,
        category=insight.category,
        content=insight.content,
        created_at=insight.created_at,
        temporal_marker=marker,
        strength=insight.strength,
        confidence=insight.confidence,
        importance=insight.importance,
        novelty=insight.novelty,
        valence={
            "joy": insight.valence_joy,
            "concern": insight.valence_concern,
            "curiosity": insight.valence_curiosity,
            "warmth": insight.valence_warmth,
            "tension": insight.valence_tension,
            # Expanded valence dimensions
            "awe": insight.valence_awe,
            "grief": insight.valence_grief,
            "longing": insight.valence_longing,
            "peace": insight.valence_peace,
            "gratitude": insight.valence_gratitude,
        },
        open_questions=insight.open_questions,
    )


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/search", response_model=InsightListResponse)
async def search_insights(
    q: str = Query(..., min_length=2, description="Search query"),
    category: Optional[str] = Query(None, description="Filter by insight category"),
    readable: bool = Query(False, description="Replace IDs with human-readable names"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results to return"),
    db: "Engine" = Depends(get_db),
) -> InsightListResponse:
    """Search insights by content.

    Performs a case-insensitive search on insight content using LIKE matching.
    Quarantined insights are excluded by default.

    Args:
        q: Search query string (minimum 2 characters).
        category: Optional category filter.
        readable: If true, resolve IDs to human-readable names.
        offset: Pagination offset.
        limit: Maximum results per page.

    Returns:
        InsightListResponse with matching insights and pagination info.
    """
    from zos.api.db_queries import search_insights as db_search
    from zos.api.readable import NameResolver

    log.info(
        "insights_search",
        query=q,
        category=category,
        readable=readable,
        offset=offset,
        limit=limit,
    )

    insights, total = await db_search(
        db,
        query=q,
        category=category,
        offset=offset,
        limit=limit,
    )

    # Resolve names if readable mode is enabled
    if readable and insights:
        resolver = NameResolver(db)
        topic_keys = [i.topic_key for i in insights]
        resolved = await resolver.resolve_batch(topic_keys)
        resolved_map = {orig: readable_key for readable_key, orig in resolved}

        formatted = [
            _format_insight_response(
                i,
                readable_topic_key=resolved_map.get(i.topic_key, i.topic_key),
                original_topic_key=i.topic_key,
            )
            for i in insights
        ]
    else:
        formatted = [_format_insight_response(i) for i in insights]

    return InsightListResponse(
        readable=readable,
        insights=formatted,
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("", response_model=InsightListResponse)
async def list_insights(
    category: Optional[str] = Query(None, description="Filter by insight category"),
    since: Optional[datetime] = Query(None, description="Only include insights after this time"),
    readable: bool = Query(False, description="Replace IDs with human-readable names"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results to return"),
    db: "Engine" = Depends(get_db),
) -> InsightListResponse:
    """List recent insights with optional filters.

    Returns insights ordered by creation time (newest first).
    Quarantined insights are excluded by default.

    Args:
        category: Optional category filter.
        since: Optional datetime filter for insights after this time.
        readable: If true, resolve IDs to human-readable names.
        offset: Pagination offset.
        limit: Maximum results per page.

    Returns:
        InsightListResponse with insights and pagination info.
    """
    from zos.api.db_queries import list_insights as db_list
    from zos.api.readable import NameResolver

    log.info(
        "insights_list",
        category=category,
        since=since,
        readable=readable,
        offset=offset,
        limit=limit,
    )

    insights, total = await db_list(
        db,
        category=category,
        since=since,
        offset=offset,
        limit=limit,
    )

    # Resolve names if readable mode is enabled
    if readable and insights:
        resolver = NameResolver(db)
        topic_keys = [i.topic_key for i in insights]
        resolved = await resolver.resolve_batch(topic_keys)
        resolved_map = {orig: readable_key for readable_key, orig in resolved}

        formatted = [
            _format_insight_response(
                i,
                readable_topic_key=resolved_map.get(i.topic_key, i.topic_key),
                original_topic_key=i.topic_key,
            )
            for i in insights
        ]
    else:
        formatted = [_format_insight_response(i) for i in insights]

    return InsightListResponse(
        readable=readable,
        insights=formatted,
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{topic_key:path}", response_model=list[InsightResponse])
async def get_insights_for_topic(
    topic_key: str,
    profile: str = Query("balanced", description="Retrieval profile: recent, balanced, deep, comprehensive"),
    readable: bool = Query(False, description="Replace IDs with human-readable names"),
    limit: int = Query(10, ge=1, le=100, description="Maximum insights to return"),
    include_quarantined: bool = Query(False, description="Include quarantined insights"),
    db: "Engine" = Depends(get_db),
    config: "Config" = Depends(get_config),
) -> list[InsightResponse]:
    """Get insights for a specific topic.

    Uses retrieval profiles to balance between recent and strong insights.
    Topic keys may contain colons (e.g., server:123:user:456) which are
    handled by FastAPI's path converter.

    Args:
        topic_key: The topic key to query (e.g., "server:123:user:456").
        profile: Retrieval profile name (recent, balanced, deep, comprehensive).
        readable: If true, resolve IDs to human-readable names.
        limit: Maximum number of insights.
        include_quarantined: Whether to include quarantined insights.

    Returns:
        List of InsightResponse objects for the topic.
    """
    from zos.api.readable import NameResolver
    from zos.insights import get_insight

    log.info(
        "insights_for_topic",
        topic_key=topic_key,
        profile=profile,
        readable=readable,
        limit=limit,
        include_quarantined=include_quarantined,
    )

    # Validate profile name
    if profile not in PROFILES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid profile '{profile}'. Valid profiles: {', '.join(PROFILES.keys())}",
        )

    retriever = InsightRetriever(db, config)

    # Handle include_quarantined by modifying profile if needed
    if include_quarantined:
        from zos.insights import RetrievalProfile

        base_profile = PROFILES[profile]
        modified_profile = RetrievalProfile(
            recency_weight=base_profile.recency_weight,
            strength_weight=base_profile.strength_weight,
            max_age_days=base_profile.max_age_days,
            include_conflicting=True,  # This controls quarantine inclusion
        )
        formatted_insights = await retriever.retrieve(
            topic_key=topic_key,
            profile=modified_profile,
            limit=limit,
        )
    else:
        formatted_insights = await retriever.retrieve(
            topic_key=topic_key,
            profile=profile,
            limit=limit,
        )

    # Fetch full insight data for each formatted insight
    # (FormattedInsight only has a subset of fields, but we need all for API response)
    insights_with_markers = []
    for fi in formatted_insights:
        insight = await get_insight(db, fi.id)
        if insight:
            insights_with_markers.append((insight, fi.temporal_marker))

    # Resolve names if readable mode is enabled
    if readable and insights_with_markers:
        resolver = NameResolver(db)
        topic_keys = [i.topic_key for i, _ in insights_with_markers]
        resolved = await resolver.resolve_batch(topic_keys)
        resolved_map = {orig: readable_key for readable_key, orig in resolved}

        results = [
            _format_insight_response(
                insight,
                temporal_marker=marker,
                readable_topic_key=resolved_map.get(insight.topic_key, insight.topic_key),
                original_topic_key=insight.topic_key,
            )
            for insight, marker in insights_with_markers
        ]
    else:
        results = [
            _format_insight_response(insight, temporal_marker=marker)
            for insight, marker in insights_with_markers
        ]

    return results
