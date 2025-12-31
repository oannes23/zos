"""Database repository for Discord messages and reactions."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from zos.logging import get_logger

if TYPE_CHECKING:
    from zos.db import Database

logger = get_logger("discord.repository")


class MessageRepository:
    """Repository for Discord message and reaction persistence."""

    def __init__(self, db: Database) -> None:
        """Initialize the repository.

        Args:
            db: Database instance for persistence.
        """
        self.db = db

    def upsert_message(
        self,
        message_id: int,
        guild_id: int | None,
        guild_name: str | None,
        channel_id: int,
        channel_name: str,
        thread_id: int | None,
        parent_channel_id: int | None,
        author_id: int,
        author_name: str,
        author_roles_snapshot: str,
        content: str,
        created_at: datetime,
        visibility_scope: str,
        is_tracked: bool = True,
    ) -> None:
        """Insert or update a message.

        Uses INSERT ... ON CONFLICT for idempotent upserts (important for backfill).

        Args:
            thread_id: Thread ID if message is in a thread (channel_id will be the thread).
            parent_channel_id: Parent channel ID for thread messages (NULL for regular channels).
            is_tracked: Whether the user has opted in for tracking.
                        False = zero salience, not reflected upon.
        """
        self.db.execute(
            """
            INSERT INTO messages (
                message_id, guild_id, guild_name, channel_id, channel_name,
                thread_id, parent_channel_id, author_id, author_name, author_roles_snapshot,
                content, created_at, visibility_scope, is_tracked
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                content = excluded.content,
                author_name = excluded.author_name,
                channel_name = excluded.channel_name,
                guild_name = excluded.guild_name,
                edited_at = CASE
                    WHEN messages.content != excluded.content
                    THEN datetime('now')
                    ELSE messages.edited_at
                END
            """,
            (
                message_id,
                guild_id,
                guild_name,
                channel_id,
                channel_name,
                thread_id,
                parent_channel_id,
                author_id,
                author_name,
                author_roles_snapshot,
                content,
                created_at.isoformat(),
                visibility_scope,
                1 if is_tracked else 0,
            ),
        )

    def update_message_content(
        self,
        message_id: int,
        content: str,
        edited_at: datetime,
    ) -> None:
        """Update message content (for edits)."""
        self.db.execute(
            """
            UPDATE messages
            SET content = ?, edited_at = ?
            WHERE message_id = ?
            """,
            (content, edited_at.isoformat(), message_id),
        )

    def soft_delete_message(self, message_id: int) -> None:
        """Mark a message as deleted (soft delete)."""
        self.db.execute(
            """
            UPDATE messages
            SET is_deleted = 1, deleted_at = datetime('now')
            WHERE message_id = ?
            """,
            (message_id,),
        )

    def add_reaction(
        self,
        message_id: int,
        emoji: str,
        user_id: int,
        user_name: str,
        created_at: datetime,
    ) -> None:
        """Add a reaction (idempotent).

        If the reaction already exists, it will be un-removed and timestamp updated.
        """
        self.db.execute(
            """
            INSERT INTO reactions (message_id, emoji, user_id, user_name, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(message_id, emoji, user_id) DO UPDATE SET
                is_removed = 0,
                user_name = excluded.user_name,
                created_at = excluded.created_at
            """,
            (message_id, emoji, user_id, user_name, created_at.isoformat()),
        )

    def remove_reaction(
        self,
        message_id: int,
        emoji: str,
        user_id: int,
    ) -> None:
        """Mark a reaction as removed."""
        self.db.execute(
            """
            UPDATE reactions
            SET is_removed = 1
            WHERE message_id = ? AND emoji = ? AND user_id = ?
            """,
            (message_id, emoji, user_id),
        )

    def get_latest_message_id(self, channel_id: int) -> int | None:
        """Get the most recent message ID for a channel.

        Used by backfill to determine where to start.

        Args:
            channel_id: The channel to query.

        Returns:
            The latest message ID, or None if no messages exist.
        """
        result = self.db.execute(
            """
            SELECT message_id FROM messages
            WHERE channel_id = ?
            ORDER BY message_id DESC
            LIMIT 1
            """,
            (channel_id,),
        ).fetchone()
        return result[0] if result else None

    def message_exists(self, message_id: int) -> bool:
        """Check if a message exists in the database.

        Args:
            message_id: The message ID to check.

        Returns:
            True if the message exists, False otherwise.
        """
        result = self.db.execute(
            "SELECT 1 FROM messages WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        return result is not None

    def get_message_count(self, channel_id: int | None = None) -> int:
        """Get the count of messages, optionally filtered by channel.

        Args:
            channel_id: Optional channel ID to filter by.

        Returns:
            The count of messages.
        """
        if channel_id is not None:
            result = self.db.execute(
                "SELECT COUNT(*) FROM messages WHERE channel_id = ? AND is_deleted = 0",
                (channel_id,),
            ).fetchone()
        else:
            result = self.db.execute(
                "SELECT COUNT(*) FROM messages WHERE is_deleted = 0"
            ).fetchone()
        return result[0] if result else 0

    def get_messages_by_channel(
        self,
        channel_id: int,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Fetch messages for a channel within a time range.

        Args:
            channel_id: The channel to query.
            since: Optional start of time range (inclusive).
            until: Optional end of time range (inclusive).
            limit: Maximum number of messages to return.

        Returns:
            List of message dicts with all message fields.
        """
        query = """
            SELECT
                message_id, guild_id, guild_name, channel_id, channel_name,
                thread_id, parent_channel_id, author_id, author_name,
                author_roles_snapshot, content, created_at, edited_at,
                visibility_scope, is_tracked, is_deleted
            FROM messages
            WHERE channel_id = ? AND is_deleted = 0
        """
        params: list = [channel_id]

        if since:
            query += " AND created_at >= ?"
            params.append(since.isoformat())
        if until:
            query += " AND created_at <= ?"
            params.append(until.isoformat())

        query += " ORDER BY created_at ASC LIMIT ?"
        params.append(limit)

        rows = self.db.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def get_messages_by_user(
        self,
        user_id: int,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Fetch messages by a user within a time range.

        Args:
            user_id: The author ID to query.
            since: Optional start of time range (inclusive).
            until: Optional end of time range (inclusive).
            limit: Maximum number of messages to return.

        Returns:
            List of message dicts with all message fields.
        """
        query = """
            SELECT
                message_id, guild_id, guild_name, channel_id, channel_name,
                thread_id, parent_channel_id, author_id, author_name,
                author_roles_snapshot, content, created_at, edited_at,
                visibility_scope, is_tracked, is_deleted
            FROM messages
            WHERE author_id = ? AND is_deleted = 0
        """
        params: list = [user_id]

        if since:
            query += " AND created_at >= ?"
            params.append(since.isoformat())
        if until:
            query += " AND created_at <= ?"
            params.append(until.isoformat())

        query += " ORDER BY created_at ASC LIMIT ?"
        params.append(limit)

        rows = self.db.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def get_messages_by_user_in_channel(
        self,
        channel_id: int,
        user_id: int,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Fetch messages by a user in a specific channel.

        Args:
            channel_id: The channel to query.
            user_id: The author ID to query.
            since: Optional start of time range (inclusive).
            until: Optional end of time range (inclusive).
            limit: Maximum number of messages to return.

        Returns:
            List of message dicts with all message fields.
        """
        query = """
            SELECT
                message_id, guild_id, guild_name, channel_id, channel_name,
                thread_id, parent_channel_id, author_id, author_name,
                author_roles_snapshot, content, created_at, edited_at,
                visibility_scope, is_tracked, is_deleted
            FROM messages
            WHERE channel_id = ? AND author_id = ? AND is_deleted = 0
        """
        params: list = [channel_id, user_id]

        if since:
            query += " AND created_at >= ?"
            params.append(since.isoformat())
        if until:
            query += " AND created_at <= ?"
            params.append(until.isoformat())

        query += " ORDER BY created_at ASC LIMIT ?"
        params.append(limit)

        rows = self.db.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def get_messages_involving_users(
        self,
        user_id_1: int,
        user_id_2: int,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Fetch messages where either user participated (for dyad context).

        This is useful for understanding the interaction between two users.

        Args:
            user_id_1: First user ID.
            user_id_2: Second user ID.
            since: Optional start of time range (inclusive).
            until: Optional end of time range (inclusive).
            limit: Maximum number of messages to return.

        Returns:
            List of message dicts with all message fields.
        """
        query = """
            SELECT
                message_id, guild_id, guild_name, channel_id, channel_name,
                thread_id, parent_channel_id, author_id, author_name,
                author_roles_snapshot, content, created_at, edited_at,
                visibility_scope, is_tracked, is_deleted
            FROM messages
            WHERE (author_id = ? OR author_id = ?) AND is_deleted = 0
        """
        params: list = [user_id_1, user_id_2]

        if since:
            query += " AND created_at >= ?"
            params.append(since.isoformat())
        if until:
            query += " AND created_at <= ?"
            params.append(until.isoformat())

        query += " ORDER BY created_at ASC LIMIT ?"
        params.append(limit)

        rows = self.db.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def get_messages_for_context(
        self,
        since: datetime,
        channel_ids: list[int] | None = None,
        user_ids: list[int] | None = None,
        scope: str = "public",
        limit: int = 100,
    ) -> list[dict]:
        """Fetch messages for LLM context assembly with filtering.

        This method provides flexible filtering for building LLM context.

        Args:
            since: Only fetch messages after this timestamp.
            channel_ids: Optional list of channel IDs to include.
            user_ids: Optional list of user IDs to include.
            scope: Visibility scope filter ("public", "dm", or None for all).
            limit: Maximum number of messages to return.

        Returns:
            List of message dicts ordered by created_at ascending.
        """
        query = """
            SELECT
                message_id, guild_id, guild_name, channel_id, channel_name,
                thread_id, parent_channel_id, author_id, author_name,
                author_roles_snapshot, content, created_at, edited_at,
                visibility_scope, is_tracked, is_deleted
            FROM messages
            WHERE is_deleted = 0 AND created_at >= ?
        """
        params: list = [since.isoformat()]

        if scope:
            query += " AND visibility_scope = ?"
            params.append(scope)

        if channel_ids:
            placeholders = ",".join("?" for _ in channel_ids)
            query += f" AND channel_id IN ({placeholders})"
            params.extend(channel_ids)

        if user_ids:
            placeholders = ",".join("?" for _ in user_ids)
            query += f" AND author_id IN ({placeholders})"
            params.extend(user_ids)

        query += " ORDER BY created_at ASC LIMIT ?"
        params.append(limit)

        rows = self.db.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]
