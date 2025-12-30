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
        channel_id: int,
        thread_id: int | None,
        author_id: int,
        author_roles_snapshot: str,
        content: str,
        created_at: datetime,
        visibility_scope: str,
    ) -> None:
        """Insert or update a message.

        Uses INSERT ... ON CONFLICT for idempotent upserts (important for backfill).
        """
        self.db.execute(
            """
            INSERT INTO messages (
                message_id, guild_id, channel_id, thread_id, author_id,
                author_roles_snapshot, content, created_at, visibility_scope
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                content = excluded.content,
                edited_at = CASE
                    WHEN messages.content != excluded.content
                    THEN datetime('now')
                    ELSE messages.edited_at
                END
            """,
            (
                message_id,
                guild_id,
                channel_id,
                thread_id,
                author_id,
                author_roles_snapshot,
                content,
                created_at.isoformat(),
                visibility_scope,
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
        created_at: datetime,
    ) -> None:
        """Add a reaction (idempotent).

        If the reaction already exists, it will be un-removed and timestamp updated.
        """
        self.db.execute(
            """
            INSERT INTO reactions (message_id, emoji, user_id, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(message_id, emoji, user_id) DO UPDATE SET
                is_removed = 0,
                created_at = excluded.created_at
            """,
            (message_id, emoji, user_id, created_at.isoformat()),
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
