"""Database query functions for API endpoints.

These functions provide paginated and filtered access to database entities
for the API layer. They return raw models rather than formatted responses.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import and_, delete, func, select, update

from zos.database import insights as insights_table
from zos.insights import _row_to_insight_static
from zos.models import Insight

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


async def list_insights(
    engine: "Engine",
    category: str | None = None,
    since: datetime | None = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[Insight], int]:
    """List insights with pagination.

    Returns insights ordered by creation time (newest first).
    Quarantined insights are excluded.

    Args:
        engine: SQLAlchemy database engine.
        category: Optional category filter.
        since: Optional datetime filter for insights after this time.
        offset: Number of results to skip.
        limit: Maximum results to return.

    Returns:
        Tuple of (list of Insight models, total count).
    """
    with engine.connect() as conn:
        # Build base conditions
        base_conditions = [insights_table.c.quarantined == False]

        if category:
            base_conditions.append(insights_table.c.category == category)
        if since:
            base_conditions.append(insights_table.c.created_at >= since)

        # Count query
        count_stmt = (
            select(func.count())
            .select_from(insights_table)
            .where(and_(*base_conditions))
        )
        total = conn.execute(count_stmt).scalar() or 0

        # Data query
        data_stmt = (
            select(insights_table)
            .where(and_(*base_conditions))
            .order_by(insights_table.c.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        rows = conn.execute(data_stmt).fetchall()
        insights = [_row_to_insight_static(r) for r in rows]

        return insights, total


async def search_insights(
    engine: "Engine",
    query: str,
    category: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[Insight], int]:
    """Search insights by content.

    Performs case-insensitive LIKE search on insight content.
    Quarantined insights are excluded.

    Args:
        engine: SQLAlchemy database engine.
        query: Search string to match in content.
        category: Optional category filter.
        offset: Number of results to skip.
        limit: Maximum results to return.

    Returns:
        Tuple of (list of Insight models, total count).
    """
    # SQLite LIKE is case-insensitive by default for ASCII
    search_pattern = f"%{query}%"

    with engine.connect() as conn:
        # Build base conditions
        base_conditions = [
            insights_table.c.quarantined == False,
            insights_table.c.content.like(search_pattern),
        ]

        if category:
            base_conditions.append(insights_table.c.category == category)

        # Count query
        count_stmt = (
            select(func.count())
            .select_from(insights_table)
            .where(and_(*base_conditions))
        )
        total = conn.execute(count_stmt).scalar() or 0

        # Data query
        data_stmt = (
            select(insights_table)
            .where(and_(*base_conditions))
            .order_by(insights_table.c.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        rows = conn.execute(data_stmt).fetchall()
        insights = [_row_to_insight_static(r) for r in rows]

        return insights, total


# =============================================================================
# Dev Mode Operations (Mutations)
# =============================================================================


async def update_insight(
    engine: "Engine",
    insight_id: str,
    updates: dict,
) -> None:
    """Update insight fields by ID.

    Performs a partial update, only modifying the fields provided in updates.

    Args:
        engine: SQLAlchemy database engine.
        insight_id: The insight ID to update.
        updates: Dictionary of field names to new values.
    """
    if not updates:
        return

    with engine.connect() as conn:
        stmt = (
            update(insights_table)
            .where(insights_table.c.id == insight_id)
            .values(**updates)
        )
        conn.execute(stmt)
        conn.commit()


async def delete_insight(
    engine: "Engine",
    insight_id: str,
) -> None:
    """Delete an insight by ID (hard delete).

    Permanently removes the insight from the database. Use sparingly -
    memory is sacred.

    Args:
        engine: SQLAlchemy database engine.
        insight_id: The insight ID to delete.
    """
    with engine.connect() as conn:
        stmt = delete(insights_table).where(insights_table.c.id == insight_id)
        conn.execute(stmt)
        conn.commit()


async def bulk_delete_insights(
    engine: "Engine",
    topic_key: str | None = None,
    category: str | None = None,
    before: datetime | None = None,
) -> int:
    """Bulk delete insights matching criteria.

    At least one filter should be provided to avoid accidental full deletion.
    Returns the number of deleted rows.

    Args:
        engine: SQLAlchemy database engine.
        topic_key: Optional topic key filter.
        category: Optional category filter.
        before: Optional datetime filter (delete insights created before this).

    Returns:
        Number of insights deleted.
    """
    conditions = []

    if topic_key:
        conditions.append(insights_table.c.topic_key == topic_key)
    if category:
        conditions.append(insights_table.c.category == category)
    if before:
        conditions.append(insights_table.c.created_at < before)

    if not conditions:
        # Safety: refuse to delete everything
        return 0

    with engine.connect() as conn:
        stmt = delete(insights_table).where(and_(*conditions))
        result = conn.execute(stmt)
        conn.commit()
        return result.rowcount


# =============================================================================
# Message Queries
# =============================================================================


def _row_to_message(row) -> "Message":
    """Convert SQLAlchemy row to Message model.

    Args:
        row: SQLAlchemy row result.

    Returns:
        Message model instance.
    """
    from zos.models import Message, VisibilityScope

    return Message(
        id=row.id,
        channel_id=row.channel_id,
        server_id=row.server_id,
        author_id=row.author_id,
        content=row.content,
        created_at=row.created_at,
        visibility_scope=VisibilityScope(row.visibility_scope),
        reactions_aggregate=row.reactions_aggregate,
        reply_to_id=row.reply_to_id,
        thread_id=row.thread_id,
        has_media=row.has_media,
        has_links=row.has_links,
        ingested_at=row.ingested_at,
        deleted_at=row.deleted_at,
    )


async def list_messages(
    engine: "Engine",
    channel_id: str | None = None,
    author_id: str | None = None,
    server_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list["Message"], int]:
    """List messages with pagination and optional filters.

    Returns messages ordered by creation time (newest first).
    Deleted messages (deleted_at not null) are excluded.
    Anonymous users (author_id starting with <chat) are excluded.

    Args:
        engine: SQLAlchemy database engine.
        channel_id: Optional channel filter.
        author_id: Optional author filter.
        server_id: Optional server filter.
        since: Optional datetime filter for messages after this time.
        until: Optional datetime filter for messages before this time.
        offset: Number of results to skip.
        limit: Maximum results to return.

    Returns:
        Tuple of (list of Message models, total count).
    """
    from zos.database import messages as messages_table
    from zos.models import Message

    with engine.connect() as conn:
        # Build base conditions - exclude deleted messages and anonymous users
        base_conditions = [
            messages_table.c.deleted_at.is_(None),
            ~messages_table.c.author_id.like("<chat%"),  # Exclude anonymous users
        ]

        if channel_id:
            base_conditions.append(messages_table.c.channel_id == channel_id)
        if author_id:
            base_conditions.append(messages_table.c.author_id == author_id)
        if server_id:
            base_conditions.append(messages_table.c.server_id == server_id)
        if since:
            base_conditions.append(messages_table.c.created_at >= since)
        if until:
            base_conditions.append(messages_table.c.created_at <= until)

        # Count query
        count_stmt = (
            select(func.count())
            .select_from(messages_table)
            .where(and_(*base_conditions))
        )
        total = conn.execute(count_stmt).scalar() or 0

        # Data query
        data_stmt = (
            select(messages_table)
            .where(and_(*base_conditions))
            .order_by(messages_table.c.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        rows = conn.execute(data_stmt).fetchall()
        messages = [_row_to_message(r) for r in rows]

        return messages, total


async def search_messages(
    engine: "Engine",
    query: str,
    channel_id: str | None = None,
    author_id: str | None = None,
    server_id: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list["Message"], int]:
    """Search messages by content.

    Performs case-insensitive LIKE search on message content.
    Deleted messages and anonymous users are excluded.

    Args:
        engine: SQLAlchemy database engine.
        query: Search string to match in content.
        channel_id: Optional channel filter.
        author_id: Optional author filter.
        server_id: Optional server filter.
        offset: Number of results to skip.
        limit: Maximum results to return.

    Returns:
        Tuple of (list of Message models, total count).
    """
    from zos.database import messages as messages_table
    from zos.models import Message

    search_pattern = f"%{query}%"

    with engine.connect() as conn:
        base_conditions = [
            messages_table.c.deleted_at.is_(None),
            messages_table.c.content.like(search_pattern),
            ~messages_table.c.author_id.like("<chat%"),  # Exclude anonymous users
        ]

        if channel_id:
            base_conditions.append(messages_table.c.channel_id == channel_id)
        if author_id:
            base_conditions.append(messages_table.c.author_id == author_id)
        if server_id:
            base_conditions.append(messages_table.c.server_id == server_id)

        # Count query
        count_stmt = (
            select(func.count())
            .select_from(messages_table)
            .where(and_(*base_conditions))
        )
        total = conn.execute(count_stmt).scalar() or 0

        # Data query
        data_stmt = (
            select(messages_table)
            .where(and_(*base_conditions))
            .order_by(messages_table.c.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        rows = conn.execute(data_stmt).fetchall()
        messages = [_row_to_message(r) for r in rows]

        return messages, total


async def get_message(
    engine: "Engine",
    message_id: str,
) -> "Message | None":
    """Get a single message by ID.

    Args:
        engine: SQLAlchemy database engine.
        message_id: The message ID.

    Returns:
        Message model or None if not found.
    """
    from zos.database import messages as messages_table
    from zos.models import Message

    with engine.connect() as conn:
        stmt = select(messages_table).where(messages_table.c.id == message_id)
        row = conn.execute(stmt).fetchone()

        if row is None:
            return None

        return _row_to_message(row)


async def get_message_stats(
    engine: "Engine",
    server_id: str | None = None,
) -> dict:
    """Get message statistics.

    Returns counts by channel and author.

    Args:
        engine: SQLAlchemy database engine.
        server_id: Optional server filter.

    Returns:
        Dictionary with stats including total count, by_channel, by_author.
    """
    from zos.database import messages as messages_table

    with engine.connect() as conn:
        base_conditions = [messages_table.c.deleted_at.is_(None)]
        if server_id:
            base_conditions.append(messages_table.c.server_id == server_id)

        # Total count
        total_stmt = (
            select(func.count())
            .select_from(messages_table)
            .where(and_(*base_conditions))
        )
        total = conn.execute(total_stmt).scalar() or 0

        # Count by channel (top 20)
        channel_stmt = (
            select(
                messages_table.c.channel_id,
                func.count().label("count"),
            )
            .where(and_(*base_conditions))
            .group_by(messages_table.c.channel_id)
            .order_by(func.count().desc())
            .limit(20)
        )
        by_channel = [
            {"channel_id": row.channel_id, "count": row.count}
            for row in conn.execute(channel_stmt).fetchall()
        ]

        # Count by author (top 20)
        author_stmt = (
            select(
                messages_table.c.author_id,
                func.count().label("count"),
            )
            .where(and_(*base_conditions))
            .group_by(messages_table.c.author_id)
            .order_by(func.count().desc())
            .limit(20)
        )
        by_author = [
            {"author_id": row.author_id, "count": row.count}
            for row in conn.execute(author_stmt).fetchall()
        ]

        return {
            "total": total,
            "by_channel": by_channel,
            "by_author": by_author,
        }


async def get_channels_for_filter(
    engine: "Engine",
    server_id: str | None = None,
) -> list[dict]:
    """Get channels with message counts for filter dropdown.

    Args:
        engine: SQLAlchemy database engine.
        server_id: Optional server filter.

    Returns:
        List of dicts with channel_id, name, and message_count.
    """
    from zos.database import channels as channels_table, messages as messages_table

    with engine.connect() as conn:
        base_conditions = [messages_table.c.deleted_at.is_(None)]
        if server_id:
            base_conditions.append(messages_table.c.server_id == server_id)

        # Get channels that have messages, ordered by message count
        stmt = (
            select(
                messages_table.c.channel_id,
                channels_table.c.name,
                func.count().label("count"),
            )
            .select_from(
                messages_table.outerjoin(
                    channels_table,
                    messages_table.c.channel_id == channels_table.c.id,
                )
            )
            .where(and_(*base_conditions))
            .group_by(messages_table.c.channel_id, channels_table.c.name)
            .order_by(func.count().desc())
            .limit(50)
        )

        return [
            {
                "channel_id": row.channel_id,
                "name": row.name or f"[{row.channel_id}]",
                "count": row.count,
            }
            for row in conn.execute(stmt).fetchall()
        ]


async def get_authors_for_filter(
    engine: "Engine",
    server_id: str | None = None,
) -> list[dict]:
    """Get authors with message counts for filter dropdown.

    Excludes anonymous users (author_id starting with <chat).

    Args:
        engine: SQLAlchemy database engine.
        server_id: Optional server filter.

    Returns:
        List of dicts with author_id, name, and message_count.
    """
    from zos.database import messages as messages_table, user_profiles

    with engine.connect() as conn:
        base_conditions = [
            messages_table.c.deleted_at.is_(None),
            ~messages_table.c.author_id.like("<chat%"),  # Exclude anonymous users
        ]
        if server_id:
            base_conditions.append(messages_table.c.server_id == server_id)

        # Subquery to get latest profile per user
        profile_subq = (
            select(
                user_profiles.c.user_id,
                func.max(user_profiles.c.captured_at).label("max_captured"),
            )
            .group_by(user_profiles.c.user_id)
            .subquery()
        )

        latest_profiles = (
            select(
                user_profiles.c.user_id,
                user_profiles.c.display_name,
                user_profiles.c.username,
            )
            .join(
                profile_subq,
                (user_profiles.c.user_id == profile_subq.c.user_id)
                & (user_profiles.c.captured_at == profile_subq.c.max_captured),
            )
            .subquery()
        )

        # Get authors that have messages, ordered by message count
        stmt = (
            select(
                messages_table.c.author_id,
                latest_profiles.c.display_name,
                latest_profiles.c.username,
                func.count().label("count"),
            )
            .select_from(
                messages_table.outerjoin(
                    latest_profiles,
                    messages_table.c.author_id == latest_profiles.c.user_id,
                )
            )
            .where(and_(*base_conditions))
            .group_by(
                messages_table.c.author_id,
                latest_profiles.c.display_name,
                latest_profiles.c.username,
            )
            .order_by(func.count().desc())
            .limit(50)
        )

        results = []
        for row in conn.execute(stmt).fetchall():
            name = row.display_name or row.username or f"[{row.author_id}]"
            results.append({
                "author_id": row.author_id,
                "name": name,
                "count": row.count,
            })

        return results