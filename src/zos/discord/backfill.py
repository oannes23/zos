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
        lookback_days: How many days of history to fetch if no messages exist.

    Returns:
        Number of messages backfilled.
    """
    channel_id = channel.id
    guild_id = channel.guild.id if channel.guild else None

    logger.info(f"Starting backfill for channel {channel.name} ({channel_id})")

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

        # Get role snapshot
        roles_json = _get_roles_snapshot(message)

        # Determine if in thread
        thread_id = channel_id if isinstance(channel, discord.Thread) else None

        repository.upsert_message(
            message_id=message.id,
            guild_id=guild_id,
            channel_id=channel_id,
            thread_id=thread_id,
            author_id=message.author.id,
            author_roles_snapshot=roles_json,
            content=message.content,
            created_at=message.created_at,
            visibility_scope="dm" if guild_id is None else "public",
        )
        count += 1

        if count % 100 == 0:
            logger.info(f"Backfilled {count} messages from {channel.name}")

    logger.info(f"Backfill complete for {channel.name}: {count} messages")
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
