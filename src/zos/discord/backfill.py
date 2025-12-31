"""Backfill logic for fetching historical Discord messages."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import discord

from zos.logging import get_logger

if TYPE_CHECKING:
    from zos.discord.repository import MessageRepository

logger = get_logger("discord.backfill")

# Default lookback period (14 days of history)
DEFAULT_LOOKBACK_DAYS = 14


async def backfill_channel(
    channel: discord.TextChannel | discord.Thread,
    repository: MessageRepository,
    tracking_opt_in_role: str | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> int:
    """Backfill messages from a channel.

    Strategy:
    1. Get the latest message ID we have for this channel
    2. If we have messages, fetch only newer messages (after=latest_id)
    3. If no messages, fetch up to lookback_days of history
    4. Use channel.history() which handles rate limits automatically

    Args:
        channel: The Discord channel to backfill.
        repository: Message repository for persistence.
        tracking_opt_in_role: Role name required for user tracking (None = all tracked).
        lookback_days: How many days of history to fetch if no messages exist.

    Returns:
        Number of messages backfilled.
    """
    channel_id = channel.id
    guild = channel.guild
    guild_id = guild.id if guild else None
    guild_name = guild.name if guild else None
    channel_name = channel.name

    logger.info(f"Starting backfill for channel {channel_name} ({channel_id})")

    # Determine starting point
    latest_id = repository.get_latest_message_id(channel_id)

    if latest_id:
        logger.info(f"Resuming backfill after message {latest_id}")
        after = discord.Object(id=latest_id)
        cutoff = None
    else:
        # No existing messages - use time-based lookback
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        after = None
        logger.info(f"Fresh backfill, looking back {lookback_days} days to {cutoff}")

    count = 0
    async for message in channel.history(limit=None, after=after, oldest_first=True):
        # Stop if we've gone past our lookback window (for fresh backfill)
        if cutoff and message.created_at < cutoff:
            continue

        # Skip bot messages
        if message.author.bot:
            continue

        # Determine thread/channel relationship
        is_thread = isinstance(channel, discord.Thread)
        if is_thread:
            thread_id = channel_id
            parent_channel_id = channel.parent_id
        else:
            thread_id = None
            parent_channel_id = None

        # Determine tracking status
        is_tracked = _is_user_tracked(message, tracking_opt_in_role)

        # Anonymize non-opted users (privacy protection)
        if is_tracked:
            author_id = message.author.id
            author_name = message.author.display_name
            roles_json = _get_roles_snapshot(message)
        else:
            author_id = 0  # Anonymous marker
            author_name = "chat"
            roles_json = "[]"

        repository.upsert_message(
            message_id=message.id,
            guild_id=guild_id,
            guild_name=guild_name,
            channel_id=channel_id,
            channel_name=channel_name,
            thread_id=thread_id,
            parent_channel_id=parent_channel_id,
            author_id=author_id,
            author_name=author_name,
            author_roles_snapshot=roles_json,
            content=message.content,
            created_at=message.created_at,
            visibility_scope="dm" if guild_id is None else "public",
            is_tracked=is_tracked,
        )
        count += 1

        if count % 100 == 0:
            logger.info(f"Backfilled {count} messages from {channel_name}")

    logger.info(f"Backfill complete for {channel_name}: {count} messages")
    return count


def _get_roles_snapshot(message: discord.Message) -> str:
    """Get JSON array of author's role IDs.

    Args:
        message: The Discord message.

    Returns:
        JSON string of role IDs (excluding @everyone).
    """
    if isinstance(message.author, discord.Member):
        role_ids = [role.id for role in message.author.roles if role.name != "@everyone"]
        return json.dumps(role_ids)
    return "[]"


def _is_user_tracked(message: discord.Message, tracking_opt_in_role: str | None) -> bool:
    """Check if user has opted in for tracking.

    Args:
        message: The Discord message.
        tracking_opt_in_role: Role name required for tracking (None = all tracked).

    Returns:
        True if user should be tracked, False otherwise.
    """
    # DMs always tracked (initiation implies consent)
    if message.guild is None:
        return True

    # No role configured = everyone tracked
    if not tracking_opt_in_role:
        return True

    # Check if user has the role
    if isinstance(message.author, discord.Member):
        return any(
            role.name == tracking_opt_in_role for role in message.author.roles
        )

    return False  # Can't verify role = not tracked
