"""Database query functions for API endpoints.

These functions provide paginated and filtered access to database entities
for the API layer. They return raw models rather than formatted responses.
"""

from datetime import datetime, timezone
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


# =============================================================================
# User Queries
# =============================================================================


async def list_users_with_stats(
    engine: "Engine",
    server_id: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[dict], int]:
    """List users with insight counts and message counts.

    Returns users sorted by insight count (descending).
    Excludes anonymous users.

    Args:
        engine: SQLAlchemy database engine.
        server_id: Optional server filter.
        offset: Pagination offset.
        limit: Maximum results.

    Returns:
        Tuple of (list of user dicts, total count).
    """
    from zos.database import insights as insights_table, messages as messages_table, user_profiles

    with engine.connect() as conn:
        # Get latest profile for each user
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
                user_profiles.c.is_bot,
            )
            .join(
                profile_subq,
                (user_profiles.c.user_id == profile_subq.c.user_id)
                & (user_profiles.c.captured_at == profile_subq.c.max_captured),
            )
            .where(user_profiles.c.is_bot == False)  # Exclude bots
            .subquery()
        )

        # Count insights per user (from topic keys containing user ID)
        # Topic keys like server:X:user:USER_ID or user:USER_ID
        insight_counts = (
            select(
                latest_profiles.c.user_id,
                func.count(insights_table.c.id).label("insight_count"),
            )
            .select_from(
                latest_profiles.outerjoin(
                    insights_table,
                    insights_table.c.topic_key.like(
                        func.concat("%:user:", latest_profiles.c.user_id, "%")
                    )
                    | insights_table.c.topic_key.like(
                        func.concat("user:", latest_profiles.c.user_id)
                    ),
                )
            )
            .where(
                (insights_table.c.quarantined == False) | (insights_table.c.id.is_(None))
            )
            .group_by(latest_profiles.c.user_id)
            .subquery()
        )

        # Count messages per user
        message_counts = (
            select(
                messages_table.c.author_id.label("user_id"),
                func.count().label("message_count"),
            )
            .where(
                messages_table.c.deleted_at.is_(None),
                ~messages_table.c.author_id.like("<chat%"),
            )
            .group_by(messages_table.c.author_id)
            .subquery()
        )

        # Build server filter for insights if needed
        server_filter = []
        if server_id:
            server_filter.append(
                insights_table.c.topic_key.like(f"server:{server_id}:%")
            )

        # Main query joining profiles with counts
        base_query = (
            select(
                latest_profiles.c.user_id,
                latest_profiles.c.display_name,
                latest_profiles.c.username,
                func.coalesce(insight_counts.c.insight_count, 0).label("insight_count"),
                func.coalesce(message_counts.c.message_count, 0).label("message_count"),
            )
            .select_from(
                latest_profiles
                .outerjoin(insight_counts, latest_profiles.c.user_id == insight_counts.c.user_id)
                .outerjoin(message_counts, latest_profiles.c.user_id == message_counts.c.user_id)
            )
        )

        # Count total
        count_stmt = select(func.count()).select_from(latest_profiles)
        total = conn.execute(count_stmt).scalar() or 0

        # Data query with pagination, sorted by insight count
        data_stmt = (
            base_query
            .order_by(func.coalesce(insight_counts.c.insight_count, 0).desc())
            .offset(offset)
            .limit(limit)
        )

        results = []
        for row in conn.execute(data_stmt).fetchall():
            name = row.display_name or row.username or f"[{row.user_id}]"
            results.append({
                "user_id": row.user_id,
                "display_name": row.display_name,
                "username": row.username,
                "name": name,
                "insight_count": row.insight_count,
                "message_count": row.message_count,
            })

        return results, total


async def get_user_details(
    engine: "Engine",
    user_id: str,
) -> dict | None:
    """Get detailed information about a user.

    Args:
        engine: SQLAlchemy database engine.
        user_id: The user ID.

    Returns:
        Dict with user details or None if not found.
    """
    from zos.database import messages as messages_table, user_profiles

    with engine.connect() as conn:
        # Get latest profile
        stmt = (
            select(
                user_profiles.c.user_id,
                user_profiles.c.display_name,
                user_profiles.c.username,
                user_profiles.c.discriminator,
                user_profiles.c.avatar_url,
                user_profiles.c.is_bot,
                user_profiles.c.joined_at,
                user_profiles.c.account_created_at,
                user_profiles.c.bio,
                user_profiles.c.pronouns,
                user_profiles.c.captured_at,
            )
            .where(user_profiles.c.user_id == user_id)
            .order_by(user_profiles.c.captured_at.desc())
            .limit(1)
        )
        row = conn.execute(stmt).fetchone()

        if not row:
            return None

        # Count messages
        msg_count_stmt = (
            select(func.count())
            .select_from(messages_table)
            .where(
                messages_table.c.author_id == user_id,
                messages_table.c.deleted_at.is_(None),
            )
        )
        message_count = conn.execute(msg_count_stmt).scalar() or 0

        name = row.display_name or row.username or f"[{user_id}]"

        return {
            "user_id": row.user_id,
            "display_name": row.display_name,
            "username": row.username,
            "discriminator": row.discriminator,
            "name": name,
            "avatar_url": row.avatar_url,
            "is_bot": row.is_bot,
            "joined_at": row.joined_at,
            "account_created_at": row.account_created_at,
            "bio": row.bio,
            "pronouns": row.pronouns,
            "captured_at": row.captured_at,
            "message_count": message_count,
        }


async def get_user_insights(
    engine: "Engine",
    user_id: str,
    limit: int = 20,
) -> list:
    """Get insights about a specific user.

    Finds insights where topic_key contains the user ID.

    Args:
        engine: SQLAlchemy database engine.
        user_id: The user ID.
        limit: Maximum results.

    Returns:
        List of Insight models.
    """
    from zos.database import insights as insights_table
    from zos.insights import _row_to_insight_static

    with engine.connect() as conn:
        stmt = (
            select(insights_table)
            .where(
                insights_table.c.quarantined == False,
                (
                    insights_table.c.topic_key.like(f"%:user:{user_id}")
                    | insights_table.c.topic_key.like(f"%:user:{user_id}:%")
                    | insights_table.c.topic_key.like(f"user:{user_id}")
                ),
            )
            .order_by(insights_table.c.created_at.desc())
            .limit(limit)
        )
        rows = conn.execute(stmt).fetchall()
        return [_row_to_insight_static(r) for r in rows]


async def get_user_dyads(
    engine: "Engine",
    user_id: str,
    limit: int = 10,
) -> list:
    """Get dyad insights involving a specific user.

    Args:
        engine: SQLAlchemy database engine.
        user_id: The user ID.
        limit: Maximum results.

    Returns:
        List of Insight models for dyad topics.
    """
    from zos.database import insights as insights_table
    from zos.insights import _row_to_insight_static

    with engine.connect() as conn:
        stmt = (
            select(insights_table)
            .where(
                insights_table.c.quarantined == False,
                insights_table.c.topic_key.like(f"%:dyad:%"),
                insights_table.c.topic_key.like(f"%{user_id}%"),
            )
            .order_by(insights_table.c.created_at.desc())
            .limit(limit)
        )
        rows = conn.execute(stmt).fetchall()
        return [_row_to_insight_static(r) for r in rows]


# =============================================================================
# Channel Queries
# =============================================================================


async def list_channels_with_stats(
    engine: "Engine",
    server_id: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[dict], int]:
    """List channels with message and insight counts.

    Returns channels sorted by message count (descending).

    Args:
        engine: SQLAlchemy database engine.
        server_id: Optional server filter.
        offset: Pagination offset.
        limit: Maximum results.

    Returns:
        Tuple of (list of channel dicts, total count).
    """
    from zos.database import channels as channels_table, messages as messages_table, servers

    with engine.connect() as conn:
        base_conditions = []
        if server_id:
            base_conditions.append(channels_table.c.server_id == server_id)

        # Count messages per channel
        message_counts = (
            select(
                messages_table.c.channel_id,
                func.count().label("message_count"),
            )
            .where(messages_table.c.deleted_at.is_(None))
            .group_by(messages_table.c.channel_id)
            .subquery()
        )

        # Main query
        base_query = (
            select(
                channels_table.c.id,
                channels_table.c.name,
                channels_table.c.server_id,
                channels_table.c.type,
                servers.c.name.label("server_name"),
                func.coalesce(message_counts.c.message_count, 0).label("message_count"),
            )
            .select_from(
                channels_table
                .outerjoin(servers, channels_table.c.server_id == servers.c.id)
                .outerjoin(message_counts, channels_table.c.id == message_counts.c.channel_id)
            )
        )

        if base_conditions:
            base_query = base_query.where(and_(*base_conditions))

        # Count total
        count_subq = select(channels_table.c.id)
        if base_conditions:
            count_subq = count_subq.where(and_(*base_conditions))
        count_stmt = select(func.count()).select_from(count_subq.subquery())
        total = conn.execute(count_stmt).scalar() or 0

        # Data query with pagination
        data_stmt = (
            base_query
            .order_by(func.coalesce(message_counts.c.message_count, 0).desc())
            .offset(offset)
            .limit(limit)
        )

        results = []
        for row in conn.execute(data_stmt).fetchall():
            results.append({
                "channel_id": row.id,
                "name": row.name or f"[{row.id}]",
                "server_id": row.server_id,
                "server_name": row.server_name,
                "type": row.type,
                "message_count": row.message_count,
            })

        return results, total


async def get_channel_details(
    engine: "Engine",
    channel_id: str,
) -> dict | None:
    """Get detailed information about a channel.

    Args:
        engine: SQLAlchemy database engine.
        channel_id: The channel ID.

    Returns:
        Dict with channel details or None if not found.
    """
    from zos.database import channels as channels_table, messages as messages_table, servers

    with engine.connect() as conn:
        # Get channel info
        stmt = (
            select(
                channels_table.c.id,
                channels_table.c.name,
                channels_table.c.server_id,
                channels_table.c.type,
                channels_table.c.parent_id,
                channels_table.c.created_at,
                servers.c.name.label("server_name"),
            )
            .select_from(
                channels_table.outerjoin(servers, channels_table.c.server_id == servers.c.id)
            )
            .where(channels_table.c.id == channel_id)
        )
        row = conn.execute(stmt).fetchone()

        if not row:
            return None

        # Count messages
        msg_count_stmt = (
            select(func.count())
            .select_from(messages_table)
            .where(
                messages_table.c.channel_id == channel_id,
                messages_table.c.deleted_at.is_(None),
            )
        )
        message_count = conn.execute(msg_count_stmt).scalar() or 0

        # Count unique authors
        author_count_stmt = (
            select(func.count(func.distinct(messages_table.c.author_id)))
            .select_from(messages_table)
            .where(
                messages_table.c.channel_id == channel_id,
                messages_table.c.deleted_at.is_(None),
                ~messages_table.c.author_id.like("<chat%"),
            )
        )
        author_count = conn.execute(author_count_stmt).scalar() or 0

        return {
            "channel_id": row.id,
            "name": row.name or f"[{channel_id}]",
            "server_id": row.server_id,
            "server_name": row.server_name,
            "type": row.type,
            "parent_id": row.parent_id,
            "created_at": row.created_at,
            "message_count": message_count,
            "author_count": author_count,
        }


async def get_channel_insights(
    engine: "Engine",
    channel_id: str,
    limit: int = 20,
) -> list:
    """Get insights about a specific channel.

    Args:
        engine: SQLAlchemy database engine.
        channel_id: The channel ID.
        limit: Maximum results.

    Returns:
        List of Insight models.
    """
    from zos.database import insights as insights_table
    from zos.insights import _row_to_insight_static

    with engine.connect() as conn:
        stmt = (
            select(insights_table)
            .where(
                insights_table.c.quarantined == False,
                (
                    insights_table.c.topic_key.like(f"%:channel:{channel_id}")
                    | insights_table.c.context_channel == channel_id
                ),
            )
            .order_by(insights_table.c.created_at.desc())
            .limit(limit)
        )
        rows = conn.execute(stmt).fetchall()
        return [_row_to_insight_static(r) for r in rows]


async def get_channel_top_users(
    engine: "Engine",
    channel_id: str,
    limit: int = 10,
) -> list[dict]:
    """Get top users in a channel by message count.

    Args:
        engine: SQLAlchemy database engine.
        channel_id: The channel ID.
        limit: Maximum results.

    Returns:
        List of dicts with user info and message count.
    """
    from zos.database import messages as messages_table, user_profiles

    with engine.connect() as conn:
        # Get latest profile for each user
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

        stmt = (
            select(
                messages_table.c.author_id,
                latest_profiles.c.display_name,
                latest_profiles.c.username,
                func.count().label("message_count"),
            )
            .select_from(
                messages_table.outerjoin(
                    latest_profiles,
                    messages_table.c.author_id == latest_profiles.c.user_id,
                )
            )
            .where(
                messages_table.c.channel_id == channel_id,
                messages_table.c.deleted_at.is_(None),
                ~messages_table.c.author_id.like("<chat%"),
            )
            .group_by(
                messages_table.c.author_id,
                latest_profiles.c.display_name,
                latest_profiles.c.username,
            )
            .order_by(func.count().desc())
            .limit(limit)
        )

        results = []
        for row in conn.execute(stmt).fetchall():
            name = row.display_name or row.username or f"[{row.author_id}]"
            results.append({
                "user_id": row.author_id,
                "name": name,
                "message_count": row.message_count,
            })

        return results


# =============================================================================
# Budget / Cost Queries
# =============================================================================


async def get_budget_summary(
    engine: "Engine",
    days: int = 30,
) -> dict:
    """Get overall budget summary.

    Returns total cost, tokens, runs, and insights for the specified period.

    Args:
        engine: SQLAlchemy database engine.
        days: Number of days to look back (default 30).

    Returns:
        Dict with total_cost_usd, total_tokens, total_runs, total_insights,
        and avg_cost_per_run.
    """
    from datetime import timedelta

    from zos.database import layer_runs, llm_calls

    since = datetime.now(timezone.utc) - timedelta(days=days)

    with engine.connect() as conn:
        # Get layer runs stats
        runs_stmt = (
            select(
                func.count().label("total_runs"),
                func.coalesce(func.sum(layer_runs.c.tokens_total), 0).label("total_tokens"),
                func.coalesce(func.sum(layer_runs.c.estimated_cost_usd), 0.0).label("total_cost"),
                func.coalesce(func.sum(layer_runs.c.insights_created), 0).label("total_insights"),
            )
            .where(layer_runs.c.started_at >= since)
        )
        runs_row = conn.execute(runs_stmt).fetchone()

        total_runs = runs_row.total_runs or 0
        total_tokens = runs_row.total_tokens or 0
        total_cost = runs_row.total_cost or 0.0
        total_insights = runs_row.total_insights or 0

        avg_cost_per_run = total_cost / total_runs if total_runs > 0 else 0.0

        # Get LLM calls count
        calls_stmt = (
            select(func.count())
            .select_from(llm_calls)
            .where(llm_calls.c.created_at >= since)
        )
        total_calls = conn.execute(calls_stmt).scalar() or 0

        return {
            "total_cost_usd": total_cost,
            "total_tokens": total_tokens,
            "total_runs": total_runs,
            "total_insights": total_insights,
            "total_calls": total_calls,
            "avg_cost_per_run": avg_cost_per_run,
            "days": days,
        }


async def get_daily_costs(
    engine: "Engine",
    days: int = 30,
) -> list[dict]:
    """Get daily cost breakdown for visualization.

    Returns cost and token data grouped by day.

    Args:
        engine: SQLAlchemy database engine.
        days: Number of days to look back (default 30).

    Returns:
        List of dicts with date, cost_usd, tokens, runs, insights.
    """
    from datetime import timedelta

    from zos.database import layer_runs

    since = datetime.now(timezone.utc) - timedelta(days=days)

    with engine.connect() as conn:
        # Group by date - SQLite specific date function
        stmt = (
            select(
                func.date(layer_runs.c.started_at).label("date"),
                func.coalesce(func.sum(layer_runs.c.estimated_cost_usd), 0.0).label("cost_usd"),
                func.coalesce(func.sum(layer_runs.c.tokens_total), 0).label("tokens"),
                func.count().label("runs"),
                func.coalesce(func.sum(layer_runs.c.insights_created), 0).label("insights"),
            )
            .where(layer_runs.c.started_at >= since)
            .group_by(func.date(layer_runs.c.started_at))
            .order_by(func.date(layer_runs.c.started_at))
        )

        results = []
        for row in conn.execute(stmt).fetchall():
            results.append({
                "date": row.date,
                "cost_usd": float(row.cost_usd),
                "tokens": int(row.tokens),
                "runs": int(row.runs),
                "insights": int(row.insights),
            })

        return results


async def get_cost_by_layer(
    engine: "Engine",
    days: int = 30,
) -> list[dict]:
    """Get cost breakdown by layer name.

    Args:
        engine: SQLAlchemy database engine.
        days: Number of days to look back (default 30).

    Returns:
        List of dicts with layer_name, cost_usd, tokens, runs, insights,
        sorted by cost descending.
    """
    from datetime import timedelta

    from zos.database import layer_runs

    since = datetime.now(timezone.utc) - timedelta(days=days)

    with engine.connect() as conn:
        stmt = (
            select(
                layer_runs.c.layer_name,
                func.coalesce(func.sum(layer_runs.c.estimated_cost_usd), 0.0).label("cost_usd"),
                func.coalesce(func.sum(layer_runs.c.tokens_total), 0).label("tokens"),
                func.coalesce(func.sum(layer_runs.c.tokens_input), 0).label("tokens_input"),
                func.coalesce(func.sum(layer_runs.c.tokens_output), 0).label("tokens_output"),
                func.count().label("runs"),
                func.coalesce(func.sum(layer_runs.c.insights_created), 0).label("insights"),
            )
            .where(layer_runs.c.started_at >= since)
            .group_by(layer_runs.c.layer_name)
            .order_by(func.sum(layer_runs.c.estimated_cost_usd).desc())
        )

        results = []
        for row in conn.execute(stmt).fetchall():
            results.append({
                "layer_name": row.layer_name,
                "cost_usd": float(row.cost_usd),
                "tokens": int(row.tokens),
                "tokens_input": int(row.tokens_input),
                "tokens_output": int(row.tokens_output),
                "runs": int(row.runs),
                "insights": int(row.insights),
            })

        return results


async def get_cost_by_model(
    engine: "Engine",
    days: int = 30,
) -> list[dict]:
    """Get cost breakdown by model.

    Args:
        engine: SQLAlchemy database engine.
        days: Number of days to look back (default 30).

    Returns:
        List of dicts with model_provider, model_name, model_profile,
        cost_usd, tokens, calls, sorted by cost descending.
    """
    from datetime import timedelta

    from zos.database import llm_calls

    since = datetime.now(timezone.utc) - timedelta(days=days)

    with engine.connect() as conn:
        stmt = (
            select(
                llm_calls.c.model_provider,
                llm_calls.c.model_name,
                llm_calls.c.model_profile,
                func.coalesce(func.sum(llm_calls.c.estimated_cost_usd), 0.0).label("cost_usd"),
                func.coalesce(func.sum(llm_calls.c.tokens_total), 0).label("tokens"),
                func.coalesce(func.sum(llm_calls.c.tokens_input), 0).label("tokens_input"),
                func.coalesce(func.sum(llm_calls.c.tokens_output), 0).label("tokens_output"),
                func.count().label("calls"),
            )
            .where(llm_calls.c.created_at >= since)
            .group_by(
                llm_calls.c.model_provider,
                llm_calls.c.model_name,
                llm_calls.c.model_profile,
            )
            .order_by(func.sum(llm_calls.c.estimated_cost_usd).desc())
        )

        results = []
        for row in conn.execute(stmt).fetchall():
            results.append({
                "model_provider": row.model_provider,
                "model_name": row.model_name,
                "model_profile": row.model_profile,
                "cost_usd": float(row.cost_usd),
                "tokens": int(row.tokens),
                "tokens_input": int(row.tokens_input),
                "tokens_output": int(row.tokens_output),
                "calls": int(row.calls),
            })

        return results


async def get_cost_by_call_type(
    engine: "Engine",
    days: int = 30,
) -> list[dict]:
    """Get cost breakdown by call type (reflection, vision, conversation, etc).

    Args:
        engine: SQLAlchemy database engine.
        days: Number of days to look back (default 30).

    Returns:
        List of dicts with call_type, cost_usd, tokens, calls,
        sorted by cost descending.
    """
    from datetime import timedelta

    from zos.database import llm_calls

    since = datetime.now(timezone.utc) - timedelta(days=days)

    with engine.connect() as conn:
        stmt = (
            select(
                llm_calls.c.call_type,
                func.coalesce(func.sum(llm_calls.c.estimated_cost_usd), 0.0).label("cost_usd"),
                func.coalesce(func.sum(llm_calls.c.tokens_total), 0).label("tokens"),
                func.count().label("calls"),
            )
            .where(llm_calls.c.created_at >= since)
            .group_by(llm_calls.c.call_type)
            .order_by(func.sum(llm_calls.c.estimated_cost_usd).desc())
        )

        results = []
        for row in conn.execute(stmt).fetchall():
            results.append({
                "call_type": row.call_type,
                "cost_usd": float(row.cost_usd),
                "tokens": int(row.tokens),
                "calls": int(row.calls),
            })

        return results