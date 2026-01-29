"""Messages API endpoints for Zos.

Provides endpoints for querying stored Discord messages with pagination,
filtering, and human-readable name resolution.
"""

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from zos.api.deps import get_db

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

log = structlog.get_logger()

router = APIRouter(prefix="/messages", tags=["messages"])


# =============================================================================
# Response Models
# =============================================================================


class MessageResponse(BaseModel):
    """Single message response model."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_id: str
    channel_name: Optional[str] = None  # Present when readable=true
    server_id: Optional[str] = None
    server_name: Optional[str] = None  # Present when readable=true
    author_id: str
    author_name: Optional[str] = None  # Present when readable=true
    content: str
    created_at: datetime
    visibility_scope: str
    reactions_aggregate: Optional[dict[str, int]] = None
    reply_to_id: Optional[str] = None
    thread_id: Optional[str] = None
    has_media: bool
    has_links: bool
    temporal_marker: str  # "3 days ago" style relative time


class MessageListResponse(BaseModel):
    """Paginated list of messages response."""

    readable: bool = False
    messages: list[MessageResponse]
    total: int
    offset: int
    limit: int


class ChannelStats(BaseModel):
    """Message count for a channel."""

    channel_id: str
    channel_name: Optional[str] = None
    count: int


class AuthorStats(BaseModel):
    """Message count for an author."""

    author_id: str
    author_name: Optional[str] = None
    count: int


class MessageStatsResponse(BaseModel):
    """Message statistics response."""

    total: int
    by_channel: list[ChannelStats]
    by_author: list[AuthorStats]


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


async def _format_message_response(
    message,
    channel_name: str | None = None,
    server_name: str | None = None,
    author_name: str | None = None,
) -> MessageResponse:
    """Format message for API response.

    Args:
        message: Message model instance.
        channel_name: Optional resolved channel name.
        server_name: Optional resolved server name.
        author_name: Optional resolved author name.

    Returns:
        MessageResponse for API output.
    """
    return MessageResponse(
        id=message.id,
        channel_id=message.channel_id,
        channel_name=channel_name,
        server_id=message.server_id,
        server_name=server_name,
        author_id=message.author_id,
        author_name=author_name,
        content=message.content,
        created_at=message.created_at,
        visibility_scope=message.visibility_scope.value,
        reactions_aggregate=message.reactions_aggregate,
        reply_to_id=message.reply_to_id,
        thread_id=message.thread_id,
        has_media=message.has_media,
        has_links=message.has_links,
        temporal_marker=_relative_time(message.created_at),
    )


class MessageNameResolver:
    """Resolve Discord IDs to human-readable names for messages."""

    def __init__(self, db: "Engine"):
        self.db = db
        self._user_cache: dict[str, str | None] = {}
        self._channel_cache: dict[str, str | None] = {}
        self._server_cache: dict[str, str | None] = {}

    async def resolve_messages(
        self, messages: list
    ) -> list[tuple[str | None, str | None, str | None]]:
        """Resolve names for a batch of messages.

        Args:
            messages: List of Message models.

        Returns:
            List of (channel_name, server_name, author_name) tuples.
        """
        await self._prime_cache(messages)

        results = []
        for msg in messages:
            channel_name = self._channel_cache.get(msg.channel_id)
            server_name = self._server_cache.get(msg.server_id) if msg.server_id else None
            author_name = self._user_cache.get(msg.author_id)
            results.append((channel_name, server_name, author_name))

        return results

    async def _prime_cache(self, messages: list) -> None:
        """Preload caches with entities from messages."""
        from sqlalchemy import func, select

        from zos.database import channels, servers, user_profiles

        user_ids = {m.author_id for m in messages}
        channel_ids = {m.channel_id for m in messages}
        server_ids = {m.server_id for m in messages if m.server_id}

        with self.db.connect() as conn:
            # Fetch channels
            if channel_ids:
                stmt = select(channels.c.id, channels.c.name).where(
                    channels.c.id.in_(list(channel_ids))
                )
                for row in conn.execute(stmt):
                    self._channel_cache[row.id] = row.name

            # Fetch servers
            if server_ids:
                stmt = select(servers.c.id, servers.c.name).where(
                    servers.c.id.in_(list(server_ids))
                )
                for row in conn.execute(stmt):
                    self._server_cache[row.id] = row.name

            # Fetch users (most recent profile for each)
            if user_ids:
                subq = (
                    select(
                        user_profiles.c.user_id,
                        func.max(user_profiles.c.captured_at).label("max_captured"),
                    )
                    .where(user_profiles.c.user_id.in_(list(user_ids)))
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

                for row in conn.execute(stmt):
                    if row.display_name:
                        name = row.display_name
                    elif row.discriminator and row.discriminator != "0":
                        name = f"{row.username}#{row.discriminator}"
                    else:
                        name = row.username
                    self._user_cache[row.user_id] = name


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/search", response_model=MessageListResponse)
async def search_messages(
    q: str = Query(..., min_length=2, description="Search query"),
    channel_id: Optional[str] = Query(None, description="Filter by channel"),
    author_id: Optional[str] = Query(None, description="Filter by author"),
    server_id: Optional[str] = Query(None, description="Filter by server"),
    readable: bool = Query(False, description="Replace IDs with human-readable names"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results to return"),
    db: "Engine" = Depends(get_db),
) -> MessageListResponse:
    """Search messages by content.

    Performs a case-insensitive search on message content using LIKE matching.
    Deleted messages are excluded.

    Args:
        q: Search query string (minimum 2 characters).
        channel_id: Optional channel filter.
        author_id: Optional author filter.
        server_id: Optional server filter.
        readable: If true, resolve IDs to human-readable names.
        offset: Pagination offset.
        limit: Maximum results per page.

    Returns:
        MessageListResponse with matching messages and pagination info.
    """
    from zos.api.db_queries import search_messages as db_search

    log.info(
        "messages_search",
        query=q,
        channel_id=channel_id,
        author_id=author_id,
        readable=readable,
        offset=offset,
        limit=limit,
    )

    messages, total = await db_search(
        db,
        query=q,
        channel_id=channel_id,
        author_id=author_id,
        server_id=server_id,
        offset=offset,
        limit=limit,
    )

    if readable and messages:
        resolver = MessageNameResolver(db)
        resolved = await resolver.resolve_messages(messages)

        formatted = [
            await _format_message_response(msg, chan, srv, auth)
            for msg, (chan, srv, auth) in zip(messages, resolved)
        ]
    else:
        formatted = [await _format_message_response(msg) for msg in messages]

    return MessageListResponse(
        readable=readable,
        messages=formatted,
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/stats", response_model=MessageStatsResponse)
async def get_message_stats(
    server_id: Optional[str] = Query(None, description="Filter by server"),
    readable: bool = Query(False, description="Replace IDs with human-readable names"),
    db: "Engine" = Depends(get_db),
) -> MessageStatsResponse:
    """Get message statistics.

    Returns total message count and breakdowns by channel and author.

    Args:
        server_id: Optional server filter.
        readable: If true, resolve IDs to human-readable names.

    Returns:
        MessageStatsResponse with counts by channel and author.
    """
    from zos.api.db_queries import get_message_stats as db_stats

    log.info("messages_stats", server_id=server_id, readable=readable)

    stats = await db_stats(db, server_id=server_id)

    by_channel = [
        ChannelStats(
            channel_id=c["channel_id"],
            count=c["count"],
        )
        for c in stats["by_channel"]
    ]

    by_author = [
        AuthorStats(
            author_id=a["author_id"],
            count=a["count"],
        )
        for a in stats["by_author"]
    ]

    # Resolve names if readable mode is enabled
    if readable:
        from sqlalchemy import func, select

        from zos.database import channels, servers, user_profiles

        with db.connect() as conn:
            # Resolve channel names
            channel_ids = [c.channel_id for c in by_channel]
            if channel_ids:
                stmt = select(channels.c.id, channels.c.name).where(
                    channels.c.id.in_(channel_ids)
                )
                channel_names = {row.id: row.name for row in conn.execute(stmt)}
                for c in by_channel:
                    c.channel_name = channel_names.get(c.channel_id)

            # Resolve author names
            author_ids = [a.author_id for a in by_author]
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
                    )
                    .join(
                        subq,
                        (user_profiles.c.user_id == subq.c.user_id)
                        & (user_profiles.c.captured_at == subq.c.max_captured),
                    )
                )

                author_names = {}
                for row in conn.execute(stmt):
                    author_names[row.user_id] = row.display_name or row.username

                for a in by_author:
                    a.author_name = author_names.get(a.author_id)

    return MessageStatsResponse(
        total=stats["total"],
        by_channel=by_channel,
        by_author=by_author,
    )


@router.get("/{message_id}", response_model=MessageResponse)
async def get_message(
    message_id: str,
    readable: bool = Query(False, description="Replace IDs with human-readable names"),
    db: "Engine" = Depends(get_db),
) -> MessageResponse:
    """Get a single message by ID.

    Args:
        message_id: The Discord message ID.
        readable: If true, resolve IDs to human-readable names.

    Returns:
        MessageResponse with full message details.

    Raises:
        HTTPException: 404 if message not found.
    """
    from zos.api.db_queries import get_message as db_get

    log.info("messages_get", message_id=message_id, readable=readable)

    message = await db_get(db, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    if readable:
        resolver = MessageNameResolver(db)
        resolved = await resolver.resolve_messages([message])
        channel_name, server_name, author_name = resolved[0]
        return await _format_message_response(
            message, channel_name, server_name, author_name
        )
    else:
        return await _format_message_response(message)


@router.get("", response_model=MessageListResponse)
async def list_messages(
    channel_id: Optional[str] = Query(None, description="Filter by channel"),
    author_id: Optional[str] = Query(None, description="Filter by author"),
    server_id: Optional[str] = Query(None, description="Filter by server"),
    since: Optional[datetime] = Query(None, description="Only include messages after this time"),
    until: Optional[datetime] = Query(None, description="Only include messages before this time"),
    readable: bool = Query(False, description="Replace IDs with human-readable names"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results to return"),
    db: "Engine" = Depends(get_db),
) -> MessageListResponse:
    """List messages with optional filters.

    Returns messages ordered by creation time (newest first).
    Deleted messages are excluded.

    Args:
        channel_id: Optional channel filter.
        author_id: Optional author filter.
        server_id: Optional server filter.
        since: Optional datetime filter for messages after this time.
        until: Optional datetime filter for messages before this time.
        readable: If true, resolve IDs to human-readable names.
        offset: Pagination offset.
        limit: Maximum results per page.

    Returns:
        MessageListResponse with messages and pagination info.
    """
    from zos.api.db_queries import list_messages as db_list

    log.info(
        "messages_list",
        channel_id=channel_id,
        author_id=author_id,
        server_id=server_id,
        since=since,
        until=until,
        readable=readable,
        offset=offset,
        limit=limit,
    )

    messages, total = await db_list(
        db,
        channel_id=channel_id,
        author_id=author_id,
        server_id=server_id,
        since=since,
        until=until,
        offset=offset,
        limit=limit,
    )

    if readable and messages:
        resolver = MessageNameResolver(db)
        resolved = await resolver.resolve_messages(messages)

        formatted = [
            await _format_message_response(msg, chan, srv, auth)
            for msg, (chan, srv, auth) in zip(messages, resolved)
        ]
    else:
        formatted = [await _format_message_response(msg) for msg in messages]

    return MessageListResponse(
        readable=readable,
        messages=formatted,
        total=total,
        offset=offset,
        limit=limit,
    )
