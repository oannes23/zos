"""UI routes for Zos introspection interface.

Provides htmx + Jinja2 web interface for browsing insights,
salience, and layer runs.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from zos.api.deps import get_config, get_db, get_ledger
from zos.api.runs import (
    get_layer_run,
    get_layer_run_stats,
    list_layer_runs,
)
from zos.layers import LayerLoader
from zos.salience import BudgetGroup, get_budget_group

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

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
                emoji = parts[3]
                return f"{server_name} - {emoji}"

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
    by channel and author.
    """
    from zos.api.db_queries import get_authors_for_filter, get_channels_for_filter

    channels = await get_channels_for_filter(db)
    authors = await get_authors_for_filter(db)

    return templates.TemplateResponse(
        request=request,
        name="messages/list.html",
        context={
            "active": "messages",
            "dev_mode": _get_dev_mode(request),
            "channels": channels,
            "authors": authors,
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

    formatted = [_format_message_for_ui(m, db) for m in messages]

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

    formatted = [_format_message_for_ui(m, db) for m in messages]

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

    formatted = [_format_message_for_ui(m, db) for m in messages]

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
    formatted = [_format_message_for_ui(m, db) for m in messages]

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
# Salience Dashboard (Story 5.7)
# =============================================================================


@router.get("/salience", response_class=HTMLResponse)
async def salience_page(request: Request) -> HTMLResponse:
    """Salience dashboard page.

    Main page for visualizing salience balances, budget allocation,
    and attention flow across topics.
    """
    return templates.TemplateResponse(
        request=request,
        name="salience/dashboard.html",
        context={"active": "salience", "dev_mode": _get_dev_mode(request)},
    )


@router.get("/salience/groups", response_class=HTMLResponse)
async def salience_groups_partial(
    request: Request,
    ledger: "SalienceLedger" = Depends(get_ledger),
    config: "Config" = Depends(get_config),
    db: "Engine" = Depends(get_db),
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

    # Add readable names to top_topics
    for group_data in groups_data:
        for topic in group_data["top_topics"]:
            topic["readable_topic_key"] = resolved_names.get(topic["topic_key"])

    return templates.TemplateResponse(
        request=request,
        name="salience/_groups.html",
        context={"groups": groups_data},
    )


@router.get("/salience/top", response_class=HTMLResponse)
async def salience_top_partial(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    ledger: "SalienceLedger" = Depends(get_ledger),
    db: "Engine" = Depends(get_db),
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

    formatted = [
        {
            "topic_key": t.key,
            "readable_topic_key": resolved_names.get(t.key),
            "balance": t.balance,
            "cap": ledger.get_cap(t.key),
            "budget_group": get_budget_group(t.key).value,
            "last_activity": t.last_activity_at,
        }
        for t in topics_with_balance
    ]

    return templates.TemplateResponse(
        request=request,
        name="salience/_top.html",
        context={"topics": formatted},
    )


@router.get("/salience/topic/{topic_key:path}", response_class=HTMLResponse)
async def salience_topic_detail(
    request: Request,
    topic_key: str,
    ledger: "SalienceLedger" = Depends(get_ledger),
    db: "Engine" = Depends(get_db),
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

    topic_data = {
        "topic_key": topic_key,
        "readable_topic_key": readable_topic_key,
        "balance": balance,
        "cap": cap,
        "utilization": balance / cap if cap > 0 else 0,
        "last_activity": topic.last_activity_at if topic else None,
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

    return {
        "id": message.id,
        "channel_id": message.channel_id,
        "channel_name": channel_name,
        "server_id": message.server_id,
        "server_name": server_name,
        "author_id": message.author_id,
        "author_name": author_name,
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
