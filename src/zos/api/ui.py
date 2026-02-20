"""UI routes for Zos introspection interface.

Provides htmx + Jinja2 web interface for browsing insights,
salience, and layer runs.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from zos.api.deps import get_config, get_db, get_impulse_engine, get_ledger
from zos.api.runs import (
    get_layer_run,
    get_layer_run_stats,
    list_layer_runs,
)
from zos.layers import LayerLoader
from zos.salience import BudgetGroup, get_budget_group

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from zos.chattiness import ImpulseEngine
    from zos.config import Config
    from zos.salience import SalienceLedger

router = APIRouter(prefix="/ui", tags=["ui"])

# Template directory relative to this file
_templates_dir = Path(__file__).parent.parent / "ui" / "templates"
templates = Jinja2Templates(directory=_templates_dir)


# =============================================================================
# Template Filters
# =============================================================================


def format_number(value) -> str:
    """Format large numbers with commas.

    Args:
        value: The number to format.

    Returns:
        Formatted string with commas, or em-dash for None.
    """
    if value is None:
        return "—"
    return f"{value:,}"


def format_cost(value) -> str:
    """Format cost in USD.

    Args:
        value: The cost value.

    Returns:
        Formatted USD string, or em-dash for None.
    """
    if value is None:
        return "—"
    return f"${value:.4f}"


def format_duration(seconds) -> str:
    """Format duration in human-readable form.

    Args:
        seconds: Duration in seconds.

    Returns:
        Human-readable duration string, or em-dash for None.
    """
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.0f}s"


def relative_time(dt: datetime | None) -> str:
    """Convert datetime to human-relative string.

    Args:
        dt: The datetime to convert. If None, returns em-dash.

    Returns:
        Human-readable relative time string like "3 days ago".
    """
    if dt is None:
        return "—"

    # Ensure we're comparing timezone-aware datetimes
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        # Assume naive datetime is UTC
        dt = dt.replace(tzinfo=timezone.utc)

    delta = now - dt

    # Handle future times
    if delta.total_seconds() < 0:
        return "in the future"

    if delta < timedelta(minutes=1):
        return "just now"
    elif delta < timedelta(hours=1):
        minutes = int(delta.total_seconds() / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif delta < timedelta(days=1):
        hours = int(delta.total_seconds() / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif delta < timedelta(days=7):
        days = delta.days
        return f"{days} day{'s' if days != 1 else ''} ago"
    elif delta < timedelta(days=30):
        weeks = delta.days // 7
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    elif delta < timedelta(days=365):
        months = delta.days // 30
        return f"{months} month{'s' if months != 1 else ''} ago"
    else:
        years = delta.days // 365
        return f"{years} year{'s' if years != 1 else ''} ago"


# Register custom filters
templates.env.filters["format_number"] = format_number
templates.env.filters["format_cost"] = format_cost
templates.env.filters["format_duration"] = format_duration
templates.env.filters["relative_time"] = relative_time


def _entity_link_for_topic(topic_key: str) -> str | None:
    """Parse a topic key and return the best URL for navigation.

    Registered as a Jinja2 global so templates can generate entity links.
    All topic types now link to the unified /ui/topics/ page.

    Args:
        topic_key: The raw topic key (e.g. server:X:user:Y).

    Returns:
        URL string or None if no linkable entity.
    """
    if not topic_key:
        return None

    parts = topic_key.split(":")

    # self topics have no useful detail page
    if parts[0] == "self":
        return None

    # emoji/thread topics are low-value for navigation
    if parts[0] == "server" and len(parts) >= 4:
        if parts[2] in ("emoji", "thread"):
            return None

    return f"/ui/topics/{topic_key}"


# Register globals after function definitions
templates.env.globals["entity_link"] = _entity_link_for_topic


def _get_all_layers() -> list[dict]:
    """Load all layer configs and return as dicts.

    Returns:
        List of dicts with name, category, description, schedule, trigger,
        target_category, target_filter, max_targets, nodes, hash.
    """
    try:
        layers_dir = Path("layers")
        if not layers_dir.exists():
            return []
        loader = LayerLoader(layers_dir)
        all_layers = loader.load_all()
        result = []
        for name in sorted(all_layers):
            layer = all_layers[name]
            result.append({
                "name": layer.name,
                "category": layer.category.value if hasattr(layer.category, 'value') else str(layer.category),
                "description": layer.description,
                "schedule": layer.schedule,
                "trigger": layer.trigger,
                "target_category": layer.target_category,
                "target_filter": layer.target_filter,
                "max_targets": layer.max_targets,
                "nodes": [
                    {
                        "name": node.name,
                        "type": node.type.value if hasattr(node.type, 'value') else str(node.type),
                        "params": node.params,
                    }
                    for node in layer.nodes
                ],
                "hash": loader.get_hash(name),
            })
        return result
    except Exception:
        return []


def _get_dev_mode(request: Request) -> bool:
    """Check if dev mode is enabled from app config.

    Args:
        request: FastAPI request with app state.

    Returns:
        True if dev mode is enabled, False otherwise.
    """
    try:
        return request.app.state.config.development.dev_mode
    except Exception:
        return False


def _format_topic_display(resolved_key: str) -> str:
    """Format a resolved topic key for human-friendly display.

    Transforms structured topic keys into readable format:
    - server:ServerName:user:Username → ServerName - Username
    - server:ServerName:dyad:User1:User2 → ServerName - User1 & User2
    - server:ServerName:channel:ChannelName → ServerName - #ChannelName
    - user:Username → Username
    - dyad:User1:User2 → User1 & User2
    - self:zos → Zos

    Args:
        resolved_key: The resolved topic key with human-readable names.

    Returns:
        Formatted display string.
    """
    parts = resolved_key.split(":")

    if not parts:
        return resolved_key

    # Handle server-scoped topics
    if parts[0] == "server" and len(parts) >= 2:
        server_name = parts[1]

        if len(parts) >= 4:
            entity_type = parts[2]

            if entity_type == "user":
                user_name = parts[3]
                return f"{server_name} - {user_name}"

            elif entity_type == "dyad" and len(parts) >= 5:
                user1 = parts[3]
                user2 = parts[4]
                return f"{server_name} - {user1} & {user2}"

            elif entity_type == "channel":
                channel_name = parts[3]
                # Remove # prefix if already there
                if channel_name.startswith("#"):
                    return f"{server_name} - {channel_name}"
                return f"{server_name} - #{channel_name}"

            elif entity_type == "thread":
                thread_name = parts[3]
                return f"{server_name} - {thread_name}"

            elif entity_type == "emoji":
                emoji = ":".join(parts[3:])
                if not emoji or emoji == "::":
                    return f"{server_name} - emoji"
                return f"{server_name} - {emoji}"

            elif entity_type == "subject":
                subject_name = parts[3].replace("_", " ").title()
                return f"{server_name} - {subject_name}"

        # Just server
        return server_name

    # Handle global topics
    elif parts[0] == "user" and len(parts) >= 2:
        return parts[1]

    elif parts[0] == "dyad" and len(parts) >= 3:
        return f"{parts[1]} & {parts[2]}"

    elif parts[0] == "self":
        return "Zos"

    # Fallback
    return resolved_key


async def _resolve_topic_keys_for_ui(
    db: "Engine", topic_keys: list[str]
) -> dict[str, str]:
    """Resolve multiple topic keys to human-readable display names.

    Uses batch resolution for efficiency, then formats for display.

    Args:
        db: Database engine.
        topic_keys: List of topic keys to resolve.

    Returns:
        Dict mapping original topic key to formatted display name.
    """
    from zos.api.readable import NameResolver

    if not topic_keys:
        return {}

    resolver = NameResolver(db)
    resolved = await resolver.resolve_batch(topic_keys)

    # Build map: original -> formatted display name
    return {original: _format_topic_display(readable) for readable, original in resolved}


async def _resolve_topic_key_for_ui(db: "Engine", topic_key: str) -> str:
    """Resolve a single topic key to human-readable display name.

    Args:
        db: Database engine.
        topic_key: Topic key to resolve.

    Returns:
        Human-readable formatted display name.
    """
    resolved_map = await _resolve_topic_keys_for_ui(db, [topic_key])
    return resolved_map.get(topic_key, topic_key)


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """UI home page / dashboard.

    Displays overview cards for insights, salience, and layer runs.
    Cards load their content via htmx for a responsive experience.
    """
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"active": "home", "dev_mode": _get_dev_mode(request)},
    )


@router.get("/status", response_class=HTMLResponse)
async def status_badge(
    request: Request,
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Status indicator for nav bar (htmx partial).

    Returns a small badge indicating system health.
    Called periodically by htmx to keep status current.
    """
    try:
        with db.connect() as conn:
            conn.execute(text("SELECT 1"))
        return HTMLResponse('<span class="badge badge-success">Healthy</span>')
    except Exception:
        return HTMLResponse('<span class="badge badge-error">Error</span>')


@router.get("/insights", response_class=HTMLResponse)
async def insights_page(request: Request) -> HTMLResponse:
    """Insights browser page.

    Main page for browsing and searching insights with filtering
    by category and full-text search with debounce.
    """
    return templates.TemplateResponse(
        request=request,
        name="insights/list.html",
        context={"active": "insights", "dev_mode": _get_dev_mode(request)},
    )


@router.get("/insights/list", response_class=HTMLResponse)
async def insights_list_partial(
    request: Request,
    category: Optional[str] = Query(None, description="Filter by insight category"),
    q: Optional[str] = Query(None, description="Search query"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Partial for insights list (htmx).

    Returns HTML partial with paginated list of insights,
    optionally filtered by category. Used by htmx for dynamic updates.
    """
    from zos.api.db_queries import list_insights as db_list, search_insights as db_search

    if q:
        insights, total = await db_search(
            db,
            query=q,
            category=category,
            offset=offset,
            limit=limit,
        )
    else:
        insights, total = await db_list(
            db,
            category=category,
            since=None,
            offset=offset,
            limit=limit,
        )

    # Resolve topic keys to human-readable names
    topic_keys = [i.topic_key for i in insights]
    resolved_names = await _resolve_topic_keys_for_ui(db, topic_keys)

    formatted = [
        _format_insight_for_ui(i, resolved_names.get(i.topic_key))
        for i in insights
    ]

    return templates.TemplateResponse(
        request=request,
        name="insights/_list.html",
        context={
            "insights": formatted,
            "total": total,
            "offset": offset,
            "limit": limit,
            "category": category,
            "q": q,
        },
    )


@router.get("/insights/search", response_class=HTMLResponse)
async def insights_search_partial(
    request: Request,
    q: str = Query(..., min_length=2, description="Search query"),
    category: Optional[str] = Query(None, description="Filter by category"),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Search partial for insights (htmx).

    Performs content search and returns the list partial.
    Triggered by debounced keyup in search input.
    """
    from zos.api.db_queries import search_insights as db_search

    insights, total = await db_search(
        db,
        query=q,
        category=category,
        offset=offset,
        limit=limit,
    )

    # Resolve topic keys to human-readable names
    topic_keys = [i.topic_key for i in insights]
    resolved_names = await _resolve_topic_keys_for_ui(db, topic_keys)

    formatted = [
        _format_insight_for_ui(i, resolved_names.get(i.topic_key))
        for i in insights
    ]

    return templates.TemplateResponse(
        request=request,
        name="insights/_list.html",
        context={
            "insights": formatted,
            "total": total,
            "offset": offset,
            "limit": limit,
            "category": category,
            "q": q,
        },
    )


# NOTE: /insights/recent MUST be defined before /insights/{insight_id} to avoid
# route matching "recent" as an insight_id
@router.get("/insights/recent", response_class=HTMLResponse)
async def insights_recent(
    request: Request,
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Recent insights partial for dashboard card.

    Returns a short list of the most recent insights for the dashboard.
    """
    from zos.api.db_queries import list_insights as db_list

    insights, total = await db_list(db, category=None, since=None, offset=0, limit=5)

    if not insights:
        return HTMLResponse('<p class="text-muted">No insights yet</p>')

    # Resolve topic keys to human-readable names
    topic_keys = [i.topic_key for i in insights]
    resolved_names = await _resolve_topic_keys_for_ui(db, topic_keys)

    formatted = [
        _format_insight_for_ui(i, resolved_names.get(i.topic_key))
        for i in insights
    ]

    # Simple list for dashboard
    html_parts = []
    for i in formatted:
        display_name = i["readable_topic_key"] or i["topic_key"]
        html_parts.append(
            f'<div class="list-item list-item-truncate">'
            f'<a href="/ui/insights/{i["id"]}" class="truncate-text" title="{i["topic_key"]}">{display_name}</a>'
            f'<span class="text-muted ml-1">{i["temporal_marker"]}</span>'
            f'</div>'
        )

    return HTMLResponse("".join(html_parts))


@router.get("/insights/topic/{topic_key:path}", response_class=HTMLResponse)
async def insights_by_topic_partial(
    request: Request,
    topic_key: str,
    exclude: Optional[str] = Query(None, description="Insight ID to exclude"),
    limit: int = Query(5, ge=1, le=20),
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Related insights partial for detail page (htmx).

    Returns other insights on the same topic, excluding the current one.
    Used to show related insights on the detail page.
    """
    from sqlalchemy import and_, select

    from zos.database import insights as insights_table
    from zos.insights import _row_to_insight_static

    with db.connect() as conn:
        conditions = [
            insights_table.c.topic_key == topic_key,
            insights_table.c.quarantined == False,
        ]
        if exclude:
            conditions.append(insights_table.c.id != exclude)

        stmt = (
            select(insights_table)
            .where(and_(*conditions))
            .order_by(insights_table.c.created_at.desc())
            .limit(limit)
        )

        rows = conn.execute(stmt).fetchall()
        insights = [_row_to_insight_static(r) for r in rows]

    # Resolve topic keys to human-readable names
    topic_keys = [i.topic_key for i in insights]
    resolved_names = await _resolve_topic_keys_for_ui(db, topic_keys)

    formatted = [
        _format_insight_for_ui(i, resolved_names.get(i.topic_key))
        for i in insights
    ]

    # Reuse the list partial for related insights
    return templates.TemplateResponse(
        request=request,
        name="insights/_list.html",
        context={
            "insights": formatted,
            "total": len(formatted),
            "offset": 0,
            "limit": limit,
            "category": None,
            "q": None,
        },
    )


@router.get("/insights/{insight_id}", response_class=HTMLResponse)
async def insight_detail(
    request: Request,
    insight_id: str,
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Insight detail page.

    Shows full insight content, metrics, valence visualization,
    and related insights on the same topic.
    """
    from zos.insights import get_insight

    insight = await get_insight(db, insight_id)
    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found")

    # Resolve topic key to human-readable name
    readable_topic = await _resolve_topic_key_for_ui(db, insight.topic_key)
    formatted = _format_insight_for_ui(insight, readable_topic)

    return templates.TemplateResponse(
        request=request,
        name="insights/detail.html",
        context={"insight": formatted, "active": "insights", "dev_mode": _get_dev_mode(request)},
    )


# =============================================================================
# Messages Browser (Story 5.12)
# =============================================================================


@router.get("/messages", response_class=HTMLResponse)
async def messages_page(
    request: Request,
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Messages browser page.

    Main page for browsing and searching messages with filtering
    by channel and author. Preloads first page of messages server-side
    to avoid the blank "Loading..." state.
    """
    from zos.api.db_queries import (
        get_authors_for_filter,
        get_channels_for_filter,
        list_messages as db_list,
    )

    channels = await get_channels_for_filter(db)
    authors = await get_authors_for_filter(db)

    # Preload first page of messages server-side
    limit = 20
    messages, total = await db_list(db, offset=0, limit=limit)
    formatted = _format_messages_batch_for_ui(messages, db)

    return templates.TemplateResponse(
        request=request,
        name="messages/list.html",
        context={
            "active": "messages",
            "dev_mode": _get_dev_mode(request),
            "channels": channels,
            "authors": authors,
            "messages": formatted,
            "total": total,
            "offset": 0,
            "limit": limit,
        },
    )


@router.get("/messages/list", response_class=HTMLResponse)
async def messages_list_partial(
    request: Request,
    channel_id: Optional[str] = Query(None, description="Filter by channel"),
    author_id: Optional[str] = Query(None, description="Filter by author"),
    q: Optional[str] = Query(None, description="Search query"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Partial for messages list (htmx).

    Returns HTML partial with paginated list of messages,
    optionally filtered by channel or author.
    """
    from zos.api.db_queries import list_messages as db_list, search_messages as db_search

    # Empty string from form should be treated as None
    filter_channel = channel_id if channel_id else None
    filter_author = author_id if author_id else None

    if q:
        messages, total = await db_search(
            db,
            query=q,
            channel_id=filter_channel,
            author_id=filter_author,
            offset=offset,
            limit=limit,
        )
    else:
        messages, total = await db_list(
            db,
            channel_id=filter_channel,
            author_id=filter_author,
            offset=offset,
            limit=limit,
        )

    formatted = _format_messages_batch_for_ui(messages, db)

    return templates.TemplateResponse(
        request=request,
        name="messages/_list.html",
        context={
            "messages": formatted,
            "total": total,
            "offset": offset,
            "limit": limit,
            "channel_id": filter_channel,
            "author_id": filter_author,
            "q": q,
        },
    )


@router.get("/messages/search", response_class=HTMLResponse)
async def messages_search_partial(
    request: Request,
    q: str = Query(..., min_length=2, description="Search query"),
    channel_id: Optional[str] = Query(None, description="Filter by channel"),
    author_id: Optional[str] = Query(None, description="Filter by author"),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Search partial for messages (htmx).

    Performs content search and returns the list partial.
    Triggered by debounced keyup in search input.
    """
    from zos.api.db_queries import search_messages as db_search

    # Empty string from form should be treated as None
    filter_channel = channel_id if channel_id else None
    filter_author = author_id if author_id else None

    messages, total = await db_search(
        db,
        query=q,
        channel_id=filter_channel,
        author_id=filter_author,
        offset=offset,
        limit=limit,
    )

    formatted = _format_messages_batch_for_ui(messages, db)

    return templates.TemplateResponse(
        request=request,
        name="messages/_list.html",
        context={
            "messages": formatted,
            "total": total,
            "offset": offset,
            "limit": limit,
            "channel_id": filter_channel,
            "author_id": filter_author,
            "q": q,
        },
    )


@router.get("/messages/recent", response_class=HTMLResponse)
async def messages_recent(
    request: Request,
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Recent messages partial for dashboard card.

    Returns a short list of the most recent messages for the dashboard.
    """
    from zos.api.db_queries import list_messages as db_list

    messages, total = await db_list(db, offset=0, limit=5)

    if not messages:
        return HTMLResponse('<p class="text-muted">No messages yet</p>')

    formatted = _format_messages_batch_for_ui(messages, db)

    # Simple list for dashboard
    html_parts = []
    for m in formatted:
        author = m["author_name"] or m["author_id"][:8] + "..."
        content_preview = m["content"][:50] + "..." if len(m["content"]) > 50 else m["content"]
        html_parts.append(
            f'<div class="list-item">'
            f'<a href="/ui/messages/{m["id"]}">{author}</a>'
            f'<span class="text-muted ml-1">{content_preview}</span>'
            f'</div>'
        )

    return HTMLResponse("".join(html_parts))


@router.get("/messages/channel/{channel_id}", response_class=HTMLResponse)
async def messages_by_channel_partial(
    request: Request,
    channel_id: str,
    exclude: Optional[str] = Query(None, description="Message ID to exclude"),
    limit: int = Query(5, ge=1, le=20),
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Related messages partial for detail page (htmx).

    Returns other messages in the same channel, excluding the current one.
    """
    from sqlalchemy import and_, select

    from zos.database import messages as messages_table

    with db.connect() as conn:
        conditions = [
            messages_table.c.channel_id == channel_id,
            messages_table.c.deleted_at.is_(None),
        ]
        if exclude:
            conditions.append(messages_table.c.id != exclude)

        stmt = (
            select(messages_table)
            .where(and_(*conditions))
            .order_by(messages_table.c.created_at.desc())
            .limit(limit)
        )

        rows = conn.execute(stmt).fetchall()

    from zos.api.db_queries import _row_to_message

    messages = [_row_to_message(r) for r in rows]
    formatted = _format_messages_batch_for_ui(messages, db)

    return templates.TemplateResponse(
        request=request,
        name="messages/_list.html",
        context={
            "messages": formatted,
            "total": len(formatted),
            "offset": 0,
            "limit": limit,
            "channel_id": None,
            "author_id": None,
            "q": None,
        },
    )


@router.get("/messages/{message_id}/modal", response_class=HTMLResponse)
async def message_detail_modal(
    request: Request,
    message_id: str,
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Message detail modal partial (htmx).

    Returns modal content for a message, including full content,
    reactions breakdown, media attachments, and links.
    """
    from zos.api.db_queries import get_links_for_message, get_media_for_message, get_message

    message = await get_message(db, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    formatted = _format_message_for_ui(message, db)

    # Fetch media and links if flagged
    media = await get_media_for_message(db, message_id) if message.has_media else []
    links = await get_links_for_message(db, message_id) if message.has_links else []

    return templates.TemplateResponse(
        request=request,
        name="messages/_detail.html",
        context={
            "message": formatted,
            "media": media,
            "links": links,
        },
    )


# NOTE: /messages/{message_id} must be defined after other /messages/* routes
@router.get("/messages/{message_id}", response_class=HTMLResponse)
async def message_detail(
    request: Request,
    message_id: str,
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Message detail page.

    Shows full message content, metadata, reactions,
    and related messages in the same channel.
    """
    from zos.api.db_queries import get_message

    message = await get_message(db, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    formatted = _format_message_for_ui(message, db)

    return templates.TemplateResponse(
        request=request,
        name="messages/detail.html",
        context={"message": formatted, "active": "messages", "dev_mode": _get_dev_mode(request)},
    )


# =============================================================================
# Users Browser
# =============================================================================


@router.get("/users")
async def users_page() -> RedirectResponse:
    """Redirect old users page to unified topics view."""
    return RedirectResponse("/ui/topics?category=user", status_code=302)


@router.get("/users/list", response_class=HTMLResponse)
async def users_list_partial(
    request: Request,
    q: Optional[str] = Query(None, description="Search query"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Partial for users list (htmx).

    Returns HTML partial with paginated list of users,
    optionally filtered by search query.
    """
    from zos.api.db_queries import list_users_with_stats

    users, total = await list_users_with_stats(
        db,
        offset=offset,
        limit=limit,
    )

    # Filter by search query if provided
    if q:
        q_lower = q.lower()
        users = [
            u for u in users
            if q_lower in (u.get("name") or "").lower()
            or q_lower in (u.get("username") or "").lower()
        ]
        total = len(users)

    return templates.TemplateResponse(
        request=request,
        name="users/_list.html",
        context={
            "users": users,
            "total": total,
            "offset": offset,
            "limit": limit,
            "q": q,
        },
    )


# NOTE: Partial routes must be defined before the {user_id} route
@router.get("/users/{user_id}/insights", response_class=HTMLResponse)
async def user_insights_partial(
    request: Request,
    user_id: str,
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Partial for user insights (htmx)."""
    from zos.api.db_queries import get_user_insights

    insights = await get_user_insights(db, user_id)

    if not insights:
        return HTMLResponse('<p class="text-muted">No insights yet</p>')

    # Resolve topic keys
    topic_keys = [i.topic_key for i in insights]
    resolved_names = await _resolve_topic_keys_for_ui(db, topic_keys)

    formatted = [
        _format_insight_for_ui(i, resolved_names.get(i.topic_key))
        for i in insights
    ]

    html_parts = []
    for i in formatted:
        display_name = i["readable_topic_key"] or i["topic_key"]
        html_parts.append(
            f'<div class="list-item list-item-truncate">'
            f'<a href="/ui/insights/{i["id"]}" class="truncate-text" title="{i["topic_key"]}">{display_name}</a>'
            f'<span class="text-muted ml-1">{i["temporal_marker"]}</span>'
            f'</div>'
        )

    return HTMLResponse("".join(html_parts))


@router.get("/users/{user_id}/dyads", response_class=HTMLResponse)
async def user_dyads_partial(
    request: Request,
    user_id: str,
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Partial for user dyad relationships (htmx)."""
    from zos.api.db_queries import get_user_dyads

    insights = await get_user_dyads(db, user_id)

    if not insights:
        return HTMLResponse('<p class="text-muted">No relationship insights yet</p>')

    # Resolve topic keys
    topic_keys = [i.topic_key for i in insights]
    resolved_names = await _resolve_topic_keys_for_ui(db, topic_keys)

    formatted = [
        _format_insight_for_ui(i, resolved_names.get(i.topic_key))
        for i in insights
    ]

    html_parts = []
    for i in formatted:
        display_name = i["readable_topic_key"] or i["topic_key"]
        html_parts.append(
            f'<div class="list-item list-item-truncate">'
            f'<a href="/ui/insights/{i["id"]}" class="truncate-text" title="{i["topic_key"]}">{display_name}</a>'
            f'<span class="text-muted ml-1">{i["temporal_marker"]}</span>'
            f'</div>'
        )

    return HTMLResponse("".join(html_parts))


@router.get("/users/{user_id}/messages", response_class=HTMLResponse)
async def user_messages_partial(
    request: Request,
    user_id: str,
    limit: int = Query(5, ge=1, le=20),
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Partial for user's recent messages (htmx)."""
    from zos.api.db_queries import list_messages

    messages, total = await list_messages(
        db,
        author_id=user_id,
        limit=limit,
    )

    if not messages:
        return HTMLResponse('<p class="text-muted">No messages</p>')

    formatted = _format_messages_batch_for_ui(messages, db)

    html_parts = []
    for m in formatted:
        channel = m["channel_name"] or m["channel_id"][:8] + "..."
        content_preview = m["content"][:80] + "..." if len(m["content"]) > 80 else m["content"]
        html_parts.append(
            f'<div class="list-item">'
            f'<a href="/ui/messages/{m["id"]}" class="truncate-text">{content_preview}</a>'
            f'<span class="text-muted ml-1">#{channel}</span>'
            f'</div>'
        )

    return HTMLResponse("".join(html_parts))


@router.get("/users/{user_id}", response_class=HTMLResponse)
async def user_detail(
    request: Request,
    user_id: str,
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """User detail page.

    Shows full user info, insights, dyads, and recent messages.
    """
    from zos.api.db_queries import get_user_details

    user = await get_user_details(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return templates.TemplateResponse(
        request=request,
        name="users/detail.html",
        context={"user": user, "active": "users", "dev_mode": _get_dev_mode(request)},
    )


# =============================================================================
# Channels Browser
# =============================================================================


@router.get("/channels")
async def channels_page() -> RedirectResponse:
    """Redirect old channels page to unified topics view."""
    return RedirectResponse("/ui/topics?category=channel", status_code=302)


@router.get("/channels/list", response_class=HTMLResponse)
async def channels_list_partial(
    request: Request,
    q: Optional[str] = Query(None, description="Search query"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Partial for channels list (htmx).

    Returns HTML partial with paginated list of channels,
    optionally filtered by search query.
    """
    from zos.api.db_queries import list_channels_with_stats

    channels, total = await list_channels_with_stats(
        db,
        offset=offset,
        limit=limit,
    )

    # Filter by search query if provided
    if q:
        q_lower = q.lower()
        channels = [
            c for c in channels
            if q_lower in (c.get("name") or "").lower()
            or q_lower in (c.get("server_name") or "").lower()
        ]
        total = len(channels)

    return templates.TemplateResponse(
        request=request,
        name="channels/_list.html",
        context={
            "channels": channels,
            "total": total,
            "offset": offset,
            "limit": limit,
            "q": q,
        },
    )


# NOTE: Partial routes must be defined before the {channel_id} route
@router.get("/channels/{channel_id}/insights", response_class=HTMLResponse)
async def channel_insights_partial(
    request: Request,
    channel_id: str,
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Partial for channel insights (htmx)."""
    from zos.api.db_queries import get_channel_insights

    insights = await get_channel_insights(db, channel_id)

    if not insights:
        return HTMLResponse('<p class="text-muted">No related insights yet</p>')

    # Resolve topic keys
    topic_keys = [i.topic_key for i in insights]
    resolved_names = await _resolve_topic_keys_for_ui(db, topic_keys)

    formatted = [
        _format_insight_for_ui(i, resolved_names.get(i.topic_key))
        for i in insights
    ]

    html_parts = []
    for i in formatted:
        display_name = i["readable_topic_key"] or i["topic_key"]
        html_parts.append(
            f'<div class="list-item list-item-truncate">'
            f'<a href="/ui/insights/{i["id"]}" class="truncate-text" title="{i["topic_key"]}">{display_name}</a>'
            f'<span class="text-muted ml-1">{i["temporal_marker"]}</span>'
            f'</div>'
        )

    return HTMLResponse("".join(html_parts))


@router.get("/channels/{channel_id}/messages", response_class=HTMLResponse)
async def channel_messages_partial(
    request: Request,
    channel_id: str,
    limit: int = Query(5, ge=1, le=20),
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Partial for channel's recent messages (htmx)."""
    from zos.api.db_queries import list_messages

    messages, total = await list_messages(
        db,
        channel_id=channel_id,
        limit=limit,
    )

    if not messages:
        return HTMLResponse('<p class="text-muted">No messages</p>')

    formatted = _format_messages_batch_for_ui(messages, db)

    html_parts = []
    for m in formatted:
        author = m["author_name"] or m["author_id"][:8] + "..."
        content_preview = m["content"][:80] + "..." if len(m["content"]) > 80 else m["content"]
        html_parts.append(
            f'<div class="list-item">'
            f'<a href="/ui/messages/{m["id"]}" class="truncate-text">{content_preview}</a>'
            f'<span class="text-muted ml-1">{author}</span>'
            f'</div>'
        )

    return HTMLResponse("".join(html_parts))


@router.get("/channels/{channel_id}/top-users", response_class=HTMLResponse)
async def channel_top_users_partial(
    request: Request,
    channel_id: str,
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Partial for channel's top users (htmx)."""
    from zos.api.db_queries import get_channel_top_users

    users = await get_channel_top_users(db, channel_id)

    if not users:
        return HTMLResponse('<p class="text-muted">No users found</p>')

    html_parts = []
    for u in users:
        name = u.get("name") or u.get("user_id", "Unknown")[:8] + "..."
        html_parts.append(
            f'<div class="list-item">'
            f'<a href="/ui/users/{u["user_id"]}">{name}</a>'
            f'<span class="text-muted ml-1">{u["message_count"]:,} messages</span>'
            f'</div>'
        )

    return HTMLResponse("".join(html_parts))


@router.get("/channels/{channel_id}", response_class=HTMLResponse)
async def channel_detail(
    request: Request,
    channel_id: str,
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Channel detail page.

    Shows full channel info, insights, messages, and top users.
    """
    from zos.api.db_queries import get_channel_details

    channel = await get_channel_details(db, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    return templates.TemplateResponse(
        request=request,
        name="channels/detail.html",
        context={"channel": channel, "active": "channels", "dev_mode": _get_dev_mode(request)},
    )


# =============================================================================
# Subjects Browser
# =============================================================================


@router.get("/subjects")
async def subjects_page() -> RedirectResponse:
    """Redirect old subjects page to unified topics view."""
    return RedirectResponse("/ui/topics?category=subject", status_code=302)


@router.get("/subjects/list", response_class=HTMLResponse)
async def subjects_list_partial(
    request: Request,
    q: Optional[str] = Query(None, description="Search query"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    db: "Engine" = Depends(get_db),
    ledger: "SalienceLedger" = Depends(get_ledger),
    impulse_engine: "ImpulseEngine | None" = Depends(get_impulse_engine),
) -> HTMLResponse:
    """Partial for subjects list (htmx).

    Returns HTML partial with paginated list of subjects,
    optionally filtered by search query.
    """
    from zos.api.db_queries import list_subjects_with_stats

    subjects, total = await list_subjects_with_stats(
        db,
        offset=offset,
        limit=limit,
    )

    # Get salience balances for all subjects
    topic_keys = [s["topic_key"] for s in subjects]
    balances = await ledger.get_balances(topic_keys) if topic_keys else {}

    # Get impulse balances if available
    impulse_balances = impulse_engine.get_balances(topic_keys) if impulse_engine else {}

    for s in subjects:
        s["salience_balance"] = balances.get(s["topic_key"], 0.0)
        s["impulse_balance"] = impulse_balances.get(s["topic_key"], 0.0)

    # Sort by salience balance descending
    subjects.sort(key=lambda s: s["salience_balance"], reverse=True)

    # Filter by search query if provided
    if q:
        q_lower = q.lower()
        subjects = [
            s for s in subjects
            if q_lower in (s.get("subject_name") or "").lower()
            or q_lower in (s.get("server_name") or "").lower()
        ]
        total = len(subjects)

    return templates.TemplateResponse(
        request=request,
        name="subjects/_list.html",
        context={
            "subjects": subjects,
            "total": total,
            "offset": offset,
            "limit": limit,
            "q": q,
            "impulse_enabled": impulse_engine is not None,
        },
    )


@router.get("/subjects/{topic_key:path}", response_class=HTMLResponse)
async def subject_detail_partial(
    request: Request,
    topic_key: str,
    ledger: "SalienceLedger" = Depends(get_ledger),
    db: "Engine" = Depends(get_db),
    impulse_engine: "ImpulseEngine | None" = Depends(get_impulse_engine),
) -> HTMLResponse:
    """Subject detail partial (htmx modal).

    Returns HTML partial for the subject detail modal showing salience,
    related insights, and recent transactions.
    """
    from zos.api.db_queries import get_subject_insights

    balance = await ledger.get_balance(topic_key)
    cap = ledger.get_cap(topic_key)
    topic = await ledger.get_topic(topic_key)
    transactions = await ledger.get_history(topic_key, limit=20)
    insights = await get_subject_insights(db, topic_key, limit=10)

    # Resolve topic key to human-readable name
    readable_topic_key = await _resolve_topic_key_for_ui(db, topic_key)

    # Impulse data
    impulse_balance = impulse_engine.get_balance(topic_key) if impulse_engine else 0.0
    impulse_enabled = impulse_engine is not None
    impulse_threshold = request.app.state.config.chattiness.threshold if impulse_enabled else None

    # Format insights for display
    resolved_names = await _resolve_topic_keys_for_ui(
        db, [i.topic_key for i in insights]
    )
    formatted_insights = [
        _format_insight_for_ui(i, resolved_names.get(i.topic_key))
        for i in insights
    ]

    subject_data = {
        "topic_key": topic_key,
        "readable_topic_key": readable_topic_key,
        "balance": balance,
        "cap": cap,
        "utilization": balance / cap if cap > 0 else 0,
        "created_at": topic.created_at if topic else None,
        "last_activity": topic.last_activity_at if topic else None,
        "impulse_balance": impulse_balance,
        "impulse_threshold": impulse_threshold,
        "impulse_enabled": impulse_enabled,
        "insights": formatted_insights,
        "insight_count": len(insights),
        "recent_transactions": [
            {
                "created_at": t.created_at,
                "transaction_type": t.transaction_type.value,
                "amount": t.amount,
                "reason": t.reason,
            }
            for t in transactions
        ],
    }

    return templates.TemplateResponse(
        request=request,
        name="subjects/_detail.html",
        context={"subject": subject_data},
    )


# =============================================================================
# Topics Browser (Unified)
# =============================================================================


@router.get("/topics", response_class=HTMLResponse)
async def topics_page(request: Request) -> HTMLResponse:
    """Unified topics browser page.

    Main page for browsing all topic types with category filtering
    and sorting by salience or impulse.
    """
    from zos.models import TopicCategory

    categories = [c.value for c in TopicCategory]

    return templates.TemplateResponse(
        request=request,
        name="topics/list.html",
        context={
            "active": "topics",
            "dev_mode": _get_dev_mode(request),
            "categories": categories,
            "selected_category": None,
        },
    )


@router.get("/topics/list", response_class=HTMLResponse)
async def topics_list_partial(
    request: Request,
    category: Optional[str] = Query(None, description="Filter by topic category"),
    sort: str = Query("salience", description="Sort by salience or impulse"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(30, ge=1, le=100, description="Page size"),
    db: "Engine" = Depends(get_db),
    ledger: "SalienceLedger" = Depends(get_ledger),
    impulse_engine: "ImpulseEngine | None" = Depends(get_impulse_engine),
) -> HTMLResponse:
    """Partial for topics list (htmx).

    Returns HTML partial with paginated, filterable list of all topics
    with salience, impulse, and insight stats.
    """
    from zos.api.db_queries import list_all_topics_with_stats

    # Empty string from form should be treated as None
    filter_category = category if category else None

    topics_list, total = await list_all_topics_with_stats(
        db,
        category=filter_category,
        offset=offset,
        limit=limit,
        sort_by=sort,
    )

    # Resolve topic keys to human-readable names
    topic_keys = [t["topic_key"] for t in topics_list]
    resolved_names = await _resolve_topic_keys_for_ui(db, topic_keys)

    # Get caps and impulse balances
    impulse_balances = impulse_engine.get_balances(topic_keys) if impulse_engine else {}

    for t in topics_list:
        t["readable_topic_key"] = resolved_names.get(t["topic_key"])
        t["cap"] = ledger.get_cap(t["topic_key"])
        t["impulse_balance"] = impulse_balances.get(t["topic_key"], 0.0)
        t["last_activity"] = t["last_activity_at"]

    # Sort by impulse globally then paginate (DB returned all rows unsorted)
    if sort == "impulse":
        topics_list.sort(key=lambda t: t["impulse_balance"], reverse=True)
        topics_list = topics_list[offset:offset + limit]

    impulse_enabled = impulse_engine is not None
    impulse_threshold = request.app.state.config.chattiness.threshold if impulse_enabled else None

    return templates.TemplateResponse(
        request=request,
        name="topics/_list.html",
        context={
            "topics": topics_list,
            "total": total,
            "offset": offset,
            "limit": limit,
            "category": filter_category,
            "sort": sort,
            "impulse_enabled": impulse_enabled,
            "impulse_threshold": impulse_threshold,
        },
    )


def _extract_entity_id(topic_key: str) -> str | None:
    """Extract the entity ID (user_id or channel_id) from a topic key.

    Returns the Discord snowflake ID for user/channel topics, None otherwise.
    """
    parts = topic_key.split(":")
    # server:X:user:USER_ID or server:X:channel:CHANNEL_ID
    if parts[0] == "server" and len(parts) >= 4 and parts[2] in ("user", "channel"):
        return parts[3]
    # user:USER_ID
    if parts[0] == "user" and len(parts) >= 2:
        return parts[1]
    return None


def _extract_category_from_key(topic_key: str) -> str | None:
    """Extract the topic category from a topic key string."""
    parts = topic_key.split(":")
    if parts[0] == "server" and len(parts) >= 4:
        return parts[2]  # user, channel, dyad, subject, thread, emoji
    if parts[0] in ("user", "self", "dyad"):
        return parts[0]
    return None


# NOTE: /topics/list MUST be defined before /topics/{topic_key:path}
@router.get("/topics/{topic_key:path}/insights", response_class=HTMLResponse)
async def topic_insights_partial(
    request: Request,
    topic_key: str,
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Partial for topic insights (htmx)."""
    from sqlalchemy import and_, select

    from zos.database import insights as insights_table
    from zos.insights import _row_to_insight_static

    with db.connect() as conn:
        stmt = (
            select(insights_table)
            .where(
                and_(
                    insights_table.c.topic_key == topic_key,
                    insights_table.c.quarantined == False,
                )
            )
            .order_by(insights_table.c.created_at.desc())
            .limit(10)
        )
        rows = conn.execute(stmt).fetchall()
        insights = [_row_to_insight_static(r) for r in rows]

    if not insights:
        return HTMLResponse('<p class="text-muted">No insights yet</p>')

    topic_keys = [i.topic_key for i in insights]
    resolved_names = await _resolve_topic_keys_for_ui(db, topic_keys)

    formatted = [
        _format_insight_for_ui(i, resolved_names.get(i.topic_key))
        for i in insights
    ]

    html_parts = []
    for i in formatted:
        display_name = i["readable_topic_key"] or i["topic_key"]
        html_parts.append(
            f'<div class="list-item list-item-truncate">'
            f'<a href="/ui/insights/{i["id"]}" class="truncate-text" title="{i["topic_key"]}">{display_name}</a>'
            f'<span class="text-muted ml-1">{i["temporal_marker"]}</span>'
            f'</div>'
        )

    return HTMLResponse("".join(html_parts))


@router.get("/topics/{topic_key:path}/salience-history", response_class=HTMLResponse)
async def topic_salience_history_partial(
    request: Request,
    topic_key: str,
    ledger: "SalienceLedger" = Depends(get_ledger),
) -> HTMLResponse:
    """Partial for salience transaction history (htmx)."""
    transactions = await ledger.get_history(topic_key, limit=20)

    formatted = [
        {
            "created_at": t.created_at,
            "transaction_type": t.transaction_type.value,
            "amount": t.amount,
            "reason": t.reason,
        }
        for t in transactions
    ]

    return templates.TemplateResponse(
        request=request,
        name="topics/_salience_history.html",
        context={"transactions": formatted},
    )


@router.get("/topics/{topic_key:path}/impulse-history", response_class=HTMLResponse)
async def topic_impulse_history_partial(
    request: Request,
    topic_key: str,
    impulse_engine: "ImpulseEngine | None" = Depends(get_impulse_engine),
) -> HTMLResponse:
    """Partial for impulse transaction history (htmx)."""
    if not impulse_engine:
        return HTMLResponse('<p class="text-muted">Impulse not enabled</p>')

    transactions = impulse_engine.get_history(topic_key, limit=20)

    return templates.TemplateResponse(
        request=request,
        name="topics/_impulse_history.html",
        context={"transactions": transactions},
    )


@router.get("/topics/{topic_key:path}/user-info", response_class=HTMLResponse)
async def topic_user_info_partial(
    request: Request,
    topic_key: str,
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Partial for user profile info (htmx)."""
    from zos.api.db_queries import get_user_details

    entity_id = _extract_entity_id(topic_key)
    if not entity_id:
        return HTMLResponse('<p class="text-muted">No user data available</p>')

    user = await get_user_details(db, entity_id)
    if not user:
        return HTMLResponse('<p class="text-muted">User not found</p>')

    html = '<div class="card-body stats-grid">'
    html += f'<div class="stat"><span class="stat-value">{format_number(user.get("message_count", 0))}</span><span class="stat-label">Messages</span></div>'
    if user.get("bio"):
        html += f'<div class="stat wide"><span class="stat-label">Bio</span><span class="stat-value small">{user["bio"]}</span></div>'
    if user.get("pronouns"):
        html += f'<div class="stat"><span class="stat-label">Pronouns</span><span class="stat-value small">{user["pronouns"]}</span></div>'
    if user.get("joined_at"):
        html += f'<div class="stat"><span class="stat-label">Joined</span><span class="stat-value small">{relative_time(user["joined_at"])}</span></div>'
    html += '</div>'

    return HTMLResponse(html)


@router.get("/topics/{topic_key:path}/channel-info", response_class=HTMLResponse)
async def topic_channel_info_partial(
    request: Request,
    topic_key: str,
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Partial for channel info (htmx)."""
    from zos.api.db_queries import get_channel_details

    entity_id = _extract_entity_id(topic_key)
    if not entity_id:
        return HTMLResponse('<p class="text-muted">No channel data available</p>')

    channel = await get_channel_details(db, entity_id)
    if not channel:
        return HTMLResponse('<p class="text-muted">Channel not found</p>')

    html = '<div class="card-body stats-grid">'
    html += f'<div class="stat"><span class="stat-value">{format_number(channel.get("message_count", 0))}</span><span class="stat-label">Messages</span></div>'
    html += f'<div class="stat"><span class="stat-value">{format_number(channel.get("author_count", 0))}</span><span class="stat-label">Active Users</span></div>'
    if channel.get("type"):
        html += f'<div class="stat"><span class="stat-label">Type</span><span class="stat-value small">{channel["type"]}</span></div>'
    html += '</div>'

    return HTMLResponse(html)


@router.get("/topics/{topic_key:path}/messages", response_class=HTMLResponse)
async def topic_messages_partial(
    request: Request,
    topic_key: str,
    limit: int = Query(5, ge=1, le=20),
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Partial for recent messages related to a topic (htmx)."""
    from zos.api.db_queries import list_messages

    entity_id = _extract_entity_id(topic_key)
    category = _extract_category_from_key(topic_key)

    if not entity_id or category not in ("user", "channel"):
        return HTMLResponse('<p class="text-muted">No messages available</p>')

    if category == "user":
        messages, total = await list_messages(db, author_id=entity_id, limit=limit)
    else:
        messages, total = await list_messages(db, channel_id=entity_id, limit=limit)

    if not messages:
        return HTMLResponse('<p class="text-muted">No messages</p>')

    formatted = _format_messages_batch_for_ui(messages, db)

    html_parts = []
    for m in formatted:
        if category == "user":
            channel = m["channel_name"] or m["channel_id"][:8] + "..."
            content_preview = m["content"][:80] + "..." if len(m["content"]) > 80 else m["content"]
            html_parts.append(
                f'<div class="list-item">'
                f'<a href="/ui/messages/{m["id"]}" class="truncate-text">{content_preview}</a>'
                f'<span class="text-muted ml-1">#{channel}</span>'
                f'</div>'
            )
        else:
            author = m["author_name"] or m["author_id"][:8] + "..."
            content_preview = m["content"][:80] + "..." if len(m["content"]) > 80 else m["content"]
            html_parts.append(
                f'<div class="list-item">'
                f'<a href="/ui/messages/{m["id"]}" class="truncate-text">{content_preview}</a>'
                f'<span class="text-muted ml-1">{author}</span>'
                f'</div>'
            )

    return HTMLResponse("".join(html_parts))


@router.get("/topics/{topic_key:path}/dyads", response_class=HTMLResponse)
async def topic_dyads_partial(
    request: Request,
    topic_key: str,
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Partial for user dyad relationships (htmx)."""
    from zos.api.db_queries import get_user_dyads

    entity_id = _extract_entity_id(topic_key)
    if not entity_id:
        return HTMLResponse('<p class="text-muted">No relationship data available</p>')

    insights = await get_user_dyads(db, entity_id)

    if not insights:
        return HTMLResponse('<p class="text-muted">No relationship insights yet</p>')

    topic_keys = [i.topic_key for i in insights]
    resolved_names = await _resolve_topic_keys_for_ui(db, topic_keys)

    formatted = [
        _format_insight_for_ui(i, resolved_names.get(i.topic_key))
        for i in insights
    ]

    html_parts = []
    for i in formatted:
        display_name = i["readable_topic_key"] or i["topic_key"]
        html_parts.append(
            f'<div class="list-item list-item-truncate">'
            f'<a href="/ui/insights/{i["id"]}" class="truncate-text" title="{i["topic_key"]}">{display_name}</a>'
            f'<span class="text-muted ml-1">{i["temporal_marker"]}</span>'
            f'</div>'
        )

    return HTMLResponse("".join(html_parts))


@router.get("/topics/{topic_key:path}", response_class=HTMLResponse)
async def topic_detail(
    request: Request,
    topic_key: str,
    ledger: "SalienceLedger" = Depends(get_ledger),
    db: "Engine" = Depends(get_db),
    impulse_engine: "ImpulseEngine | None" = Depends(get_impulse_engine),
) -> HTMLResponse:
    """Topic detail page.

    Shows salience, impulse, insights, and category-specific info for any topic.
    """
    balance = await ledger.get_balance(topic_key)
    cap = ledger.get_cap(topic_key)

    # Resolve topic key to human-readable name
    readable_topic_key = await _resolve_topic_key_for_ui(db, topic_key)

    # Impulse data
    impulse_balance = impulse_engine.get_balance(topic_key) if impulse_engine else 0.0
    impulse_enabled = impulse_engine is not None
    impulse_threshold = request.app.state.config.chattiness.threshold if impulse_enabled else None

    # Extract category and entity_id from topic key
    category = _extract_category_from_key(topic_key) or "unknown"
    entity_id = _extract_entity_id(topic_key)

    topic_data = {
        "topic_key": topic_key,
        "readable_topic_key": readable_topic_key,
        "category": category,
        "entity_id": entity_id,
        "balance": balance,
        "cap": cap,
        "utilization": balance / cap if cap > 0 else 0,
        "budget_group": get_budget_group(topic_key).value,
        "impulse_balance": impulse_balance,
        "impulse_threshold": impulse_threshold,
        "impulse_enabled": impulse_enabled,
    }

    return templates.TemplateResponse(
        request=request,
        name="topics/detail.html",
        context={"topic": topic_data, "active": "topics", "dev_mode": _get_dev_mode(request)},
    )


# =============================================================================
# Salience Dashboard (Story 5.7)
# =============================================================================


@router.get("/salience")
async def salience_page() -> RedirectResponse:
    """Redirect old salience dashboard to unified topics view."""
    return RedirectResponse("/ui/topics", status_code=302)


@router.get("/salience/groups", response_class=HTMLResponse)
async def salience_groups_partial(
    request: Request,
    ledger: "SalienceLedger" = Depends(get_ledger),
    config: "Config" = Depends(get_config),
    db: "Engine" = Depends(get_db),
    impulse_engine: "ImpulseEngine | None" = Depends(get_impulse_engine),
) -> HTMLResponse:
    """Budget groups partial (htmx).

    Returns HTML partial showing all budget groups with their allocations,
    topic counts, and top topics.
    """
    groups_data = []
    all_topic_keys = []  # Collect all topic keys for batch resolution

    for group in BudgetGroup:
        # Get allocation from config
        if group == BudgetGroup.SELF:
            allocation = config.salience.self_budget
        else:
            allocation = getattr(config.salience.budget, group.value, 0)
            # Handle the global_group alias
            if group == BudgetGroup.GLOBAL:
                allocation = config.salience.budget.global_group

        # Get topics in this group
        topics_list = await ledger.get_topics_by_group(group)

        if not topics_list:
            groups_data.append({
                "group": group.value,
                "allocation": allocation,
                "total_salience": 0.0,
                "topic_count": 0,
                "top_topics": [],
            })
            continue

        # Get balances for all topics
        topic_keys = [t.key for t in topics_list]
        balances = await ledger.get_balances(topic_keys)

        total = sum(balances.values())

        # Sort by balance and get top 5
        sorted_topics = sorted(
            topics_list, key=lambda t: balances.get(t.key, 0), reverse=True
        )[:5]

        top_topics = [
            {
                "topic_key": t.key,
                "balance": balances.get(t.key, 0),
                "cap": ledger.get_cap(t.key),
                "last_activity": t.last_activity_at,
            }
            for t in sorted_topics
        ]

        # Collect topic keys for resolution
        all_topic_keys.extend([t.key for t in sorted_topics])

        groups_data.append({
            "group": group.value,
            "allocation": allocation,
            "total_salience": total,
            "topic_count": len(topics_list),
            "top_topics": top_topics,
        })

    # Resolve all topic keys to human-readable names
    resolved_names = await _resolve_topic_keys_for_ui(db, all_topic_keys)

    # Get impulse balances for all top topics
    impulse_balances = impulse_engine.get_balances(all_topic_keys) if impulse_engine else {}

    # Add readable names and impulse to top_topics
    for group_data in groups_data:
        for topic in group_data["top_topics"]:
            topic["readable_topic_key"] = resolved_names.get(topic["topic_key"])
            topic["impulse_balance"] = impulse_balances.get(topic["topic_key"], 0.0)

    return templates.TemplateResponse(
        request=request,
        name="salience/_groups.html",
        context={
            "groups": groups_data,
            "impulse_enabled": impulse_engine is not None,
        },
    )


@router.get("/salience/top", response_class=HTMLResponse)
async def salience_top_partial(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    ledger: "SalienceLedger" = Depends(get_ledger),
    db: "Engine" = Depends(get_db),
    impulse_engine: "ImpulseEngine | None" = Depends(get_impulse_engine),
) -> HTMLResponse:
    """Top topics partial (htmx).

    Returns HTML partial showing the highest salience topics across all groups.
    Used both by the dashboard card and the full salience page.
    """
    topics_with_balance = await ledger.get_top_topics(limit=limit)

    if not topics_with_balance:
        return HTMLResponse('<p class="text-muted">No topics yet</p>')

    # Resolve topic keys to human-readable names
    topic_keys = [t.key for t in topics_with_balance]
    resolved_names = await _resolve_topic_keys_for_ui(db, topic_keys)

    # Get impulse balances if available
    impulse_balances = impulse_engine.get_balances(topic_keys) if impulse_engine else {}

    formatted = [
        {
            "topic_key": t.key,
            "readable_topic_key": resolved_names.get(t.key),
            "balance": t.balance,
            "cap": ledger.get_cap(t.key),
            "budget_group": get_budget_group(t.key).value,
            "last_activity": t.last_activity_at,
            "impulse_balance": impulse_balances.get(t.key, 0.0),
        }
        for t in topics_with_balance
    ]

    impulse_enabled = impulse_engine is not None
    impulse_threshold = request.app.state.config.chattiness.threshold if impulse_enabled else None

    return templates.TemplateResponse(
        request=request,
        name="salience/_top.html",
        context={
            "topics": formatted,
            "impulse_enabled": impulse_enabled,
            "impulse_threshold": impulse_threshold,
        },
    )


@router.get("/salience/topic/{topic_key:path}", response_class=HTMLResponse)
async def salience_topic_detail(
    request: Request,
    topic_key: str,
    ledger: "SalienceLedger" = Depends(get_ledger),
    db: "Engine" = Depends(get_db),
    impulse_engine: "ImpulseEngine | None" = Depends(get_impulse_engine),
) -> HTMLResponse:
    """Topic detail partial (htmx modal).

    Returns HTML partial for the topic detail modal showing balance,
    utilization, and recent transactions.
    """
    balance = await ledger.get_balance(topic_key)
    cap = ledger.get_cap(topic_key)
    topic = await ledger.get_topic(topic_key)
    transactions = await ledger.get_history(topic_key, limit=20)

    # Resolve topic key to human-readable name
    readable_topic_key = await _resolve_topic_key_for_ui(db, topic_key)

    # Impulse data
    impulse_balance = impulse_engine.get_balance(topic_key) if impulse_engine else 0.0
    impulse_enabled = impulse_engine is not None
    impulse_threshold = request.app.state.config.chattiness.threshold if impulse_enabled else None

    topic_data = {
        "topic_key": topic_key,
        "readable_topic_key": readable_topic_key,
        "balance": balance,
        "cap": cap,
        "utilization": balance / cap if cap > 0 else 0,
        "last_activity": topic.last_activity_at if topic else None,
        "impulse_balance": impulse_balance,
        "impulse_threshold": impulse_threshold,
        "impulse_enabled": impulse_enabled,
        "recent_transactions": [
            {
                "created_at": t.created_at,
                "transaction_type": t.transaction_type.value,
                "amount": t.amount,
                "reason": t.reason,
            }
            for t in transactions
        ],
    }

    return templates.TemplateResponse(
        request=request,
        name="salience/_topic_detail.html",
        context={"topic": topic_data},
    )


# =============================================================================
# Layer Runs (Story 5.8)
# =============================================================================


@router.get("/runs", response_class=HTMLResponse)
async def runs_page(
    request: Request,
) -> HTMLResponse:
    """Layer runs page.

    Main page for browsing layer run history with filters.
    Content loads via htmx for responsive experience.
    """
    layers = _get_layer_names()

    return templates.TemplateResponse(
        request=request,
        name="runs/list.html",
        context={"active": "runs", "layers": layers, "dev_mode": _get_dev_mode(request)},
    )


@router.get("/runs/stats", response_class=HTMLResponse)
async def runs_stats_partial(
    request: Request,
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Stats partial (htmx).

    Returns statistics cards for the last 7 days of layer runs.
    Displays total runs, success/failure counts, insights created, and cost.
    """
    since = datetime.now(timezone.utc) - timedelta(days=7)
    stats = get_layer_run_stats(db, since=since)

    return templates.TemplateResponse(
        request=request,
        name="runs/_stats.html",
        context={"stats": stats},
    )


@router.get("/runs/list", response_class=HTMLResponse)
async def runs_list_partial(
    request: Request,
    layer_name: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Runs list partial (htmx).

    Returns a table of layer runs with pagination.
    Supports filtering by layer name and status.
    """
    # Empty string from form should be treated as None
    filter_layer = layer_name if layer_name else None
    filter_status = status if status else None

    runs, total = list_layer_runs(
        db,
        layer_name=filter_layer,
        status=filter_status,
        offset=offset,
        limit=limit,
    )

    formatted = [_format_run_for_ui(r) for r in runs]

    return templates.TemplateResponse(
        request=request,
        name="runs/_list.html",
        context={
            "runs": formatted,
            "total": total,
            "offset": offset,
            "limit": limit,
        },
    )


@router.get("/runs/recent", response_class=HTMLResponse)
async def runs_recent(
    request: Request,
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Recent runs partial for dashboard card.

    Shows the 5 most recent layer runs in a compact format.
    """
    runs, total = list_layer_runs(db, limit=5)

    if not runs:
        return HTMLResponse('<p class="text-muted">No runs yet</p>')

    formatted = [_format_run_for_ui(r) for r in runs]

    # Simple list for dashboard
    html_parts = ['<div class="runs-list-compact">']
    for run in formatted:
        status_class = f"badge-{run['status']}"
        time_str = relative_time(run['started_at'])
        html_parts.append(f'''
            <div class="list-item">
                <span class="badge {status_class}">{run['status']}</span>
                <span class="ml-1">{run['layer_name']}</span>
                <span class="text-muted ml-1">{time_str}</span>
            </div>
        ''')
    html_parts.append('</div>')

    return HTMLResponse(''.join(html_parts))


@router.get("/runs/{run_id}/calls", response_class=HTMLResponse)
async def run_calls_partial(
    request: Request,
    run_id: str,
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """LLM calls for a specific layer run (htmx partial).

    Returns a compact table of LLM calls made during this run.
    """
    from zos.api.db_queries import list_llm_calls

    calls, total = await list_llm_calls(db, layer_run_id=run_id, limit=50)

    return templates.TemplateResponse(
        request=request,
        name="runs/_calls.html",
        context={"calls": calls},
    )


@router.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail_partial(
    request: Request,
    run_id: str,
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Run detail partial (htmx modal).

    Returns detailed information about a specific layer run.
    Includes errors if any occurred during execution.
    """
    run = get_layer_run(db, run_id)
    if not run:
        return HTMLResponse("<p>Run not found</p>", status_code=404)

    return templates.TemplateResponse(
        request=request,
        name="runs/_detail.html",
        context={"run": _format_run_for_ui(run)},
    )


# =============================================================================
# Budget Dashboard
# =============================================================================


@router.get("/budget", response_class=HTMLResponse)
async def budget_page(
    request: Request,
    days: int = Query(30, ge=1, le=365),
) -> HTMLResponse:
    """Budget dashboard page.

    Main page for viewing cost tracking, token usage,
    and budget visualizations over time.
    """
    return templates.TemplateResponse(
        request=request,
        name="budget/dashboard.html",
        context={"active": "budget", "dev_mode": _get_dev_mode(request), "days": days},
    )


@router.get("/budget/summary", response_class=HTMLResponse)
async def budget_summary_partial(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Budget summary partial (htmx).

    Returns summary cards showing total cost, tokens, runs, and insights.
    """
    from zos.api.db_queries import get_budget_summary

    summary = await get_budget_summary(db, days=days)

    return templates.TemplateResponse(
        request=request,
        name="budget/_summary.html",
        context={"summary": summary},
    )


@router.get("/budget/daily", response_class=HTMLResponse)
async def budget_daily_partial(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Daily cost breakdown partial (htmx).

    Returns a chart/table showing costs over time.
    """
    from zos.api.db_queries import get_daily_costs

    daily = await get_daily_costs(db, days=days)

    return templates.TemplateResponse(
        request=request,
        name="budget/_daily.html",
        context={"daily": daily, "days": days},
    )


@router.get("/budget/by-layer", response_class=HTMLResponse)
async def budget_by_layer_partial(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Cost by layer partial (htmx).

    Returns a breakdown of costs grouped by layer name.
    """
    from zos.api.db_queries import get_cost_by_layer

    by_layer = await get_cost_by_layer(db, days=days)

    return templates.TemplateResponse(
        request=request,
        name="budget/_by_layer.html",
        context={"by_layer": by_layer, "days": days},
    )


@router.get("/budget/by-model", response_class=HTMLResponse)
async def budget_by_model_partial(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Cost by model partial (htmx).

    Returns a breakdown of costs grouped by model.
    """
    from zos.api.db_queries import get_cost_by_model

    by_model = await get_cost_by_model(db, days=days)

    return templates.TemplateResponse(
        request=request,
        name="budget/_by_model.html",
        context={"by_model": by_model, "days": days},
    )


@router.get("/budget/by-call-type", response_class=HTMLResponse)
async def budget_by_call_type_partial(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Cost by call type partial (htmx).

    Returns a breakdown of costs grouped by call type.
    """
    from zos.api.db_queries import get_cost_by_call_type

    by_call_type = await get_cost_by_call_type(db, days=days)

    return templates.TemplateResponse(
        request=request,
        name="budget/_by_call_type.html",
        context={"by_call_type": by_call_type, "days": days},
    )


@router.get("/budget/calls", response_class=HTMLResponse)
async def budget_calls_partial(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    call_type: Optional[str] = Query(None),
    model_profile: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """LLM calls list partial (htmx).

    Returns paginated list of individual LLM calls with filtering.
    """
    from zos.api.db_queries import list_llm_calls

    calls, total = await list_llm_calls(
        db,
        days=days,
        call_type=call_type,
        model_profile=model_profile,
        offset=offset,
        limit=limit,
    )

    return templates.TemplateResponse(
        request=request,
        name="budget/_calls.html",
        context={
            "calls": calls,
            "total": total,
            "offset": offset,
            "limit": limit,
            "days": days,
            "call_type": call_type,
            "model_profile": model_profile,
        },
    )


@router.get("/budget/calls/{call_id}", response_class=HTMLResponse)
async def budget_call_detail(
    request: Request,
    call_id: str,
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """LLM call detail view (htmx modal).

    Returns full details of a single LLM call including prompt and response.
    """
    from zos.api.db_queries import get_llm_call

    call = await get_llm_call(db, call_id)

    if call is None:
        return templates.TemplateResponse(
            request=request,
            name="budget/_call_detail.html",
            context={"call": None, "error": "Call not found"},
        )

    return templates.TemplateResponse(
        request=request,
        name="budget/_call_detail.html",
        context={"call": call},
    )


# =============================================================================
# Media Dashboard
# =============================================================================


@router.get("/media", response_class=HTMLResponse)
async def media_page(request: Request) -> HTMLResponse:
    """Media dashboard page.

    Main page for browsing link and image analyses.
    Content loads via htmx for responsive experience.
    """
    return templates.TemplateResponse(
        request=request,
        name="media/dashboard.html",
        context={"active": "media", "dev_mode": _get_dev_mode(request)},
    )


@router.get("/media/stats", response_class=HTMLResponse)
async def media_stats_partial(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Media stats partial (htmx).

    Returns summary cards for link and image analysis activity.
    """
    from zos.api.db_queries import get_media_stats

    stats = await get_media_stats(db, days=days)

    return templates.TemplateResponse(
        request=request,
        name="media/_stats.html",
        context={"stats": stats},
    )


@router.get("/media/images", response_class=HTMLResponse)
async def media_images_partial(
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Image analyses list partial (htmx).

    Returns paginated card grid of image analyses.
    """
    from zos.api.db_queries import list_media_analysis

    images, total = await list_media_analysis(db, offset=offset, limit=limit)

    return templates.TemplateResponse(
        request=request,
        name="media/_images.html",
        context={
            "images": images,
            "total": total,
            "offset": offset,
            "limit": limit,
        },
    )


@router.get("/media/images/{image_id}", response_class=HTMLResponse)
async def media_image_detail(
    request: Request,
    image_id: str,
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Image detail partial (htmx modal).

    Returns full image view with description and metadata.
    """
    from zos.api.db_queries import get_media_analysis_by_id

    image = await get_media_analysis_by_id(db, image_id)
    if image is None:
        return HTMLResponse("<p>Image not found</p>", status_code=404)

    return templates.TemplateResponse(
        request=request,
        name="media/_image_detail.html",
        context={"image": image},
    )


@router.get("/media/links", response_class=HTMLResponse)
async def media_links_partial(
    request: Request,
    domain: Optional[str] = Query(None),
    is_youtube: Optional[bool] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Link analyses list partial (htmx).

    Returns paginated table of link analyses with filters.
    """
    from zos.api.db_queries import list_link_analysis

    # Empty string from form should be treated as None
    filter_domain = domain if domain else None

    links, total = await list_link_analysis(
        db,
        domain=filter_domain,
        is_youtube=is_youtube,
        offset=offset,
        limit=limit,
    )

    # Fetch top domains for filter chips (lightweight query)
    from sqlalchemy import func, select as sa_select

    from zos.database import link_analysis

    top_domains: list[dict] = []
    with db.connect() as conn:
        stmt = (
            sa_select(
                link_analysis.c.domain,
                func.count().label("count"),
            )
            .group_by(link_analysis.c.domain)
            .order_by(func.count().desc())
            .limit(10)
        )
        top_domains = [
            {"domain": row.domain, "count": row.count}
            for row in conn.execute(stmt).fetchall()
        ]

    return templates.TemplateResponse(
        request=request,
        name="media/_links.html",
        context={
            "links": links,
            "total": total,
            "offset": offset,
            "limit": limit,
            "domain": filter_domain,
            "is_youtube": is_youtube,
            "top_domains": top_domains,
        },
    )


# =============================================================================
# Layers Browser
# =============================================================================


@router.get("/layers", response_class=HTMLResponse)
async def layers_page(request: Request) -> HTMLResponse:
    """Layers browser page.

    Main page for browsing configured reflection layers.
    """
    all_layers = _get_all_layers()
    categories = sorted({l["category"] for l in all_layers})
    return templates.TemplateResponse(
        request=request,
        name="layers/list.html",
        context={
            "active": "layers",
            "dev_mode": _get_dev_mode(request),
            "categories": categories,
        },
    )


# NOTE: /layers/list MUST be defined before /layers/{layer_name}
@router.get("/layers/list", response_class=HTMLResponse)
async def layers_list_partial(
    request: Request,
    category: Optional[str] = Query(None, description="Filter by category"),
) -> HTMLResponse:
    """Partial for layers card grid (htmx).

    Returns HTML partial with all configured layers as cards,
    optionally filtered by category.
    """
    layers = _get_all_layers()
    if category:
        layers = [l for l in layers if l["category"] == category]

    return templates.TemplateResponse(
        request=request,
        name="layers/_list.html",
        context={"layers": layers},
    )


@router.get("/layers/{layer_name}/runs", response_class=HTMLResponse)
async def layer_runs_partial(
    request: Request,
    layer_name: str,
    limit: int = Query(10, ge=1, le=50),
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Recent runs for a specific layer (htmx partial).

    Returns a table of recent runs filtered by layer name.
    """
    runs, total = list_layer_runs(db, layer_name=layer_name, limit=limit)
    formatted = [_format_run_for_ui(r) for r in runs]

    return templates.TemplateResponse(
        request=request,
        name="layers/_runs.html",
        context={"runs": formatted, "total": total, "layer_name": layer_name},
    )


@router.get("/layers/{layer_name}/insights", response_class=HTMLResponse)
async def layer_insights_partial(
    request: Request,
    layer_name: str,
    limit: int = Query(10, ge=1, le=50),
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Recent insights for a specific layer (htmx partial).

    Returns insight cards produced by this layer.
    """
    from zos.api.db_queries import get_insights_by_layer_name

    insights = await get_insights_by_layer_name(db, layer_name, limit=limit)

    if not insights:
        return HTMLResponse('<p class="text-muted">No insights from this layer yet</p>')

    # Resolve topic keys
    topic_keys = [i.topic_key for i in insights]
    resolved_names = await _resolve_topic_keys_for_ui(db, topic_keys)

    formatted = [
        _format_insight_for_ui(i, resolved_names.get(i.topic_key))
        for i in insights
    ]

    return templates.TemplateResponse(
        request=request,
        name="layers/_insights.html",
        context={"insights": formatted},
    )


@router.get("/layers/{layer_name}", response_class=HTMLResponse)
async def layer_detail(
    request: Request,
    layer_name: str,
) -> HTMLResponse:
    """Layer detail page.

    Shows full layer configuration, pipeline visualization,
    recent runs, and recent insights.
    """
    all_layers = _get_all_layers()
    layer = next((l for l in all_layers if l["name"] == layer_name), None)
    if not layer:
        raise HTTPException(status_code=404, detail="Layer not found")

    return templates.TemplateResponse(
        request=request,
        name="layers/detail.html",
        context={"layer": layer, "active": "layers", "dev_mode": _get_dev_mode(request)},
    )


# =============================================================================
# Enhanced Run Detail
# =============================================================================


@router.get("/runs/{run_id}/insights", response_class=HTMLResponse)
async def run_insights_partial(
    request: Request,
    run_id: str,
    db: "Engine" = Depends(get_db),
) -> HTMLResponse:
    """Insights created by a specific run (htmx partial).

    Returns insight cards produced during a specific layer run.
    Lazy-loaded inside the run detail modal.
    """
    from zos.api.db_queries import get_insights_by_run

    insights = await get_insights_by_run(db, run_id)

    if not insights:
        return HTMLResponse('<p class="text-muted">No insights created in this run</p>')

    # Resolve topic keys
    topic_keys = [i.topic_key for i in insights]
    resolved_names = await _resolve_topic_keys_for_ui(db, topic_keys)

    formatted = [
        _format_insight_for_ui(i, resolved_names.get(i.topic_key))
        for i in insights
    ]

    return templates.TemplateResponse(
        request=request,
        name="runs/_insights.html",
        context={"insights": formatted},
    )


# =============================================================================
# Helper Functions
# =============================================================================


def _format_run_for_ui(run) -> dict:
    """Convert LayerRun to dict for template rendering.

    Args:
        run: LayerRun model instance.

    Returns:
        Dict with all fields needed for UI templates.
    """
    duration = None
    if run.completed_at and run.started_at:
        duration = (run.completed_at - run.started_at).total_seconds()

    return {
        "id": run.id,
        "layer_name": run.layer_name,
        "layer_hash": run.layer_hash,
        "layer_link": f"/ui/layers/{run.layer_name}",
        "status": run.status.value,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "duration_seconds": duration,
        "targets_matched": run.targets_matched,
        "targets_processed": run.targets_processed,
        "targets_skipped": run.targets_skipped,
        "insights_created": run.insights_created,
        "model_profile": run.model_profile,
        "model_provider": run.model_provider,
        "model_name": run.model_name,
        "tokens_input": run.tokens_input,
        "tokens_output": run.tokens_output,
        "tokens_total": run.tokens_total,
        "estimated_cost_usd": run.estimated_cost_usd,
        "errors": run.errors,
    }


def _get_layer_names(config_path: Path | None = None) -> list[str]:
    """Get list of available layer names.

    Args:
        config_path: Optional path to layers directory.

    Returns:
        Sorted list of layer names.
    """
    try:
        layers_dir = config_path or Path("layers")
        if not layers_dir.exists():
            return []
        loader = LayerLoader(layers_dir)
        loader.load_all()
        return loader.list_layers()
    except Exception:
        # If we can't load layers, return empty list
        return []


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


def _format_insight_for_ui(insight, readable_topic_key: str | None = None) -> dict:
    """Format insight for UI templates.

    Converts an Insight model to a dictionary suitable for Jinja2 templates,
    including computed temporal markers and structured valence data.

    Args:
        insight: Insight model instance.
        readable_topic_key: Optional human-readable topic key.

    Returns:
        Dictionary with all fields needed for UI rendering.
    """
    age = _relative_time(insight.created_at)
    strength_label = _strength_label(insight.strength)

    return {
        "id": insight.id,
        "topic_key": insight.topic_key,
        "readable_topic_key": readable_topic_key,
        "category": insight.category,
        "content": insight.content,
        "created_at": insight.created_at,
        "temporal_marker": f"{strength_label} from {age}",
        "strength": insight.strength,
        "confidence": insight.confidence,
        "importance": insight.importance,
        "novelty": insight.novelty,
        "valence": {
            "joy": insight.valence_joy,
            "concern": insight.valence_concern,
            "curiosity": insight.valence_curiosity,
            "warmth": insight.valence_warmth,
            "tension": insight.valence_tension,
        },
        "supersedes": insight.supersedes,
        "layer_run_id": insight.layer_run_id,
        "entity_link": _entity_link_for_topic(insight.topic_key),
    }


def _format_message_for_ui(message, db: "Engine") -> dict:
    """Format message for UI templates.

    Converts a Message model to a dictionary suitable for Jinja2 templates,
    including resolved names for author, channel, and server.

    Args:
        message: Message model instance.
        db: Database engine for name resolution.

    Returns:
        Dictionary with all fields needed for UI rendering.
    """
    from sqlalchemy import func, select

    from zos.database import channels, servers, user_profiles

    # Resolve names
    channel_name = None
    server_name = None
    author_name = None

    with db.connect() as conn:
        # Get channel name
        stmt = select(channels.c.name).where(channels.c.id == message.channel_id)
        row = conn.execute(stmt).fetchone()
        if row:
            channel_name = row.name

        # Get server name
        if message.server_id:
            stmt = select(servers.c.name).where(servers.c.id == message.server_id)
            row = conn.execute(stmt).fetchone()
            if row:
                server_name = row.name

        # Get author name (most recent profile)
        subq = (
            select(
                user_profiles.c.user_id,
                func.max(user_profiles.c.captured_at).label("max_captured"),
            )
            .where(user_profiles.c.user_id == message.author_id)
            .group_by(user_profiles.c.user_id)
            .subquery()
        )

        stmt = (
            select(
                user_profiles.c.display_name,
                user_profiles.c.username,
                user_profiles.c.discriminator,
            )
            .join(
                subq,
                (user_profiles.c.user_id == subq.c.user_id)
                & (user_profiles.c.captured_at == subq.c.max_captured),
            )
        )
        row = conn.execute(stmt).fetchone()
        if row:
            if row.display_name:
                author_name = row.display_name
            elif row.discriminator and row.discriminator != "0":
                author_name = f"{row.username}#{row.discriminator}"
            else:
                author_name = row.username

    # Build topic keys for entity links
    author_topic_key = None
    channel_topic_key = None
    if message.server_id:
        author_topic_key = f"server:{message.server_id}:user:{message.author_id}"
        channel_topic_key = f"server:{message.server_id}:channel:{message.channel_id}"

    return {
        "id": message.id,
        "channel_id": message.channel_id,
        "channel_name": channel_name,
        "server_id": message.server_id,
        "server_name": server_name,
        "author_id": message.author_id,
        "author_name": author_name,
        "author_topic_key": author_topic_key,
        "channel_topic_key": channel_topic_key,
        "content": message.content,
        "created_at": message.created_at,
        "temporal_marker": relative_time(message.created_at),
        "visibility_scope": message.visibility_scope.value,
        "reactions_aggregate": message.reactions_aggregate,
        "reply_to_id": message.reply_to_id,
        "thread_id": message.thread_id,
        "has_media": message.has_media,
        "has_links": message.has_links,
    }


def _format_messages_batch_for_ui(messages, db: "Engine") -> list[dict]:
    """Format multiple messages for UI templates with batched name resolution.

    Instead of 3 queries per message (channel, server, author), this collects
    all unique IDs and runs 3 bulk queries total, then maps results back.

    Args:
        messages: List of Message model instances.
        db: Database engine for name resolution.

    Returns:
        List of dictionaries with all fields needed for UI rendering.
    """
    if not messages:
        return []

    from sqlalchemy import func, select

    from zos.database import channels, servers, user_profiles

    # Collect unique IDs
    channel_ids = {m.channel_id for m in messages}
    server_ids = {m.server_id for m in messages if m.server_id}
    author_ids = {m.author_id for m in messages}

    channel_names: dict[str, str] = {}
    server_names: dict[str, str] = {}
    author_names: dict[str, str] = {}

    with db.connect() as conn:
        # Batch: channel names
        if channel_ids:
            stmt = select(channels.c.id, channels.c.name).where(
                channels.c.id.in_(channel_ids)
            )
            for row in conn.execute(stmt).fetchall():
                if row.name:
                    channel_names[row.id] = row.name

        # Batch: server names
        if server_ids:
            stmt = select(servers.c.id, servers.c.name).where(
                servers.c.id.in_(server_ids)
            )
            for row in conn.execute(stmt).fetchall():
                if row.name:
                    server_names[row.id] = row.name

        # Batch: author names (most recent profile per user)
        if author_ids:
            subq = (
                select(
                    user_profiles.c.user_id,
                    func.max(user_profiles.c.captured_at).label("max_captured"),
                )
                .where(user_profiles.c.user_id.in_(author_ids))
                .group_by(user_profiles.c.user_id)
                .subquery()
            )

            stmt = (
                select(
                    user_profiles.c.user_id,
                    user_profiles.c.display_name,
                    user_profiles.c.username,
                    user_profiles.c.discriminator,
                )
                .join(
                    subq,
                    (user_profiles.c.user_id == subq.c.user_id)
                    & (user_profiles.c.captured_at == subq.c.max_captured),
                )
            )
            for row in conn.execute(stmt).fetchall():
                if row.display_name:
                    author_names[row.user_id] = row.display_name
                elif row.discriminator and row.discriminator != "0":
                    author_names[row.user_id] = f"{row.username}#{row.discriminator}"
                elif row.username:
                    author_names[row.user_id] = row.username

    # Build formatted dicts using resolved names
    results = []
    for message in messages:
        # Build topic keys for entity links
        author_topic_key = None
        channel_topic_key = None
        if message.server_id:
            author_topic_key = f"server:{message.server_id}:user:{message.author_id}"
            channel_topic_key = f"server:{message.server_id}:channel:{message.channel_id}"

        results.append({
            "id": message.id,
            "channel_id": message.channel_id,
            "channel_name": channel_names.get(message.channel_id),
            "server_id": message.server_id,
            "server_name": server_names.get(message.server_id) if message.server_id else None,
            "author_id": message.author_id,
            "author_name": author_names.get(message.author_id),
            "author_topic_key": author_topic_key,
            "channel_topic_key": channel_topic_key,
            "content": message.content,
            "created_at": message.created_at,
            "temporal_marker": relative_time(message.created_at),
            "visibility_scope": message.visibility_scope.value,
            "reactions_aggregate": message.reactions_aggregate,
            "reply_to_id": message.reply_to_id,
            "thread_id": message.thread_id,
            "has_media": message.has_media,
            "has_links": message.has_links,
        })

    return results
