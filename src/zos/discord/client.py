"""Discord client for Zos message ingestion."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import discord
from discord import Intents

from zos.config import DiscordConfig, get_config
from zos.discord.backfill import backfill_channel
from zos.discord.repository import MessageRepository
from zos.exceptions import DiscordError
from zos.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger("discord.client")


class ZosDiscordClient(discord.Client):
    """Discord client that ingests messages and reactions."""

    def __init__(
        self,
        config: DiscordConfig | None = None,
        repository: MessageRepository | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the Discord client.

        Args:
            config: Discord configuration. Uses global config if None.
            repository: Message repository for DB operations.
            **kwargs: Additional arguments passed to discord.Client.
        """
        if config is None:
            config = get_config().discord
        self.config = config

        if repository is None:
            from zos.db import get_db

            repository = MessageRepository(get_db())
        self.repository = repository

        # Configure intents
        intents = Intents.default()
        intents.message_content = True  # Required for content access
        intents.guild_messages = True
        intents.dm_messages = True
        intents.reactions = True
        intents.guilds = True
        intents.members = True  # For role snapshot

        super().__init__(intents=intents, **kwargs)

    def _should_process_guild(self, guild_id: int | None) -> bool:
        """Check if we should process events from this guild."""
        if not self.config.guild_ids:
            return True  # No filter = process all
        if guild_id is None:
            return True  # DMs always processed
        return guild_id in self.config.guild_ids

    def _should_process_channel(self, channel_id: int) -> bool:
        """Check if we should process events from this channel."""
        if not self.config.watched_channel_ids:
            return True  # No filter = process all
        return channel_id in self.config.watched_channel_ids

    def _should_process_message(self, message: discord.Message) -> bool:
        """Determine if a message should be processed."""
        # Ignore bot messages
        if message.author.bot:
            return False

        guild_id = message.guild.id if message.guild else None
        if not self._should_process_guild(guild_id):
            return False

        return self._should_process_channel(message.channel.id)

    async def on_ready(self) -> None:
        """Called when the client is ready."""
        if self.user:
            logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guilds")

        # Trigger backfill for configured channels
        await self._run_backfill()

    async def _run_backfill(self) -> None:
        """Run backfill for all configured channels."""
        channels_to_backfill = self.config.watched_channel_ids
        if not channels_to_backfill:
            logger.info("No channels configured for backfill")
            return

        logger.info(f"Starting backfill for {len(channels_to_backfill)} channels")
        for channel_id in channels_to_backfill:
            channel = self.get_channel(channel_id)
            if channel is None:
                logger.warning(f"Could not find channel {channel_id} for backfill")
                continue

            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                logger.warning(f"Channel {channel_id} is not a text channel, skipping")
                continue

            try:
                await backfill_channel(channel, self.repository)
            except Exception as e:
                logger.error(f"Backfill failed for channel {channel_id}: {e}")

    async def on_message(self, message: discord.Message) -> None:
        """Handle new messages."""
        if not self._should_process_message(message):
            return

        try:
            self.repository.upsert_message(
                message_id=message.id,
                guild_id=message.guild.id if message.guild else None,
                channel_id=message.channel.id,
                thread_id=(
                    message.channel.id
                    if isinstance(message.channel, discord.Thread)
                    else None
                ),
                author_id=message.author.id,
                author_roles_snapshot=self._get_roles_snapshot(message),
                content=message.content,
                created_at=message.created_at,
                visibility_scope="dm" if message.guild is None else "public",
            )
            logger.debug(f"Stored message {message.id} from {message.author}")
        except Exception as e:
            logger.error(f"Failed to store message {message.id}: {e}")

    async def on_message_edit(
        self, _before: discord.Message, after: discord.Message
    ) -> None:
        """Handle message edits - overwrite content."""
        if not self._should_process_message(after):
            return

        try:
            self.repository.update_message_content(
                message_id=after.id,
                content=after.content,
                edited_at=after.edited_at or datetime.now(UTC),
            )
            logger.debug(f"Updated message {after.id}")
        except Exception as e:
            logger.error(f"Failed to update message {after.id}: {e}")

    async def on_message_delete(self, message: discord.Message) -> None:
        """Handle message deletion - soft delete."""
        # Check guild/channel filters
        guild_id = message.guild.id if message.guild else None
        if not self._should_process_guild(guild_id):
            return
        if not self._should_process_channel(message.channel.id):
            return

        try:
            self.repository.soft_delete_message(message.id)
            logger.debug(f"Soft deleted message {message.id}")
        except Exception as e:
            logger.error(f"Failed to soft delete message {message.id}: {e}")

    async def on_reaction_add(
        self, reaction: discord.Reaction, user: discord.User | discord.Member
    ) -> None:
        """Handle reaction additions."""
        if user.bot:
            return

        message = reaction.message
        guild_id = message.guild.id if message.guild else None
        if not self._should_process_guild(guild_id):
            return
        if not self._should_process_channel(message.channel.id):
            return

        emoji_str = str(reaction.emoji)
        try:
            self.repository.add_reaction(
                message_id=message.id,
                emoji=emoji_str,
                user_id=user.id,
                created_at=datetime.now(UTC),
            )
            logger.debug(f"Added reaction {emoji_str} to message {message.id}")
        except Exception as e:
            logger.error(f"Failed to add reaction: {e}")

    async def on_reaction_remove(
        self, reaction: discord.Reaction, user: discord.User | discord.Member
    ) -> None:
        """Handle reaction removals."""
        if user.bot:
            return

        message = reaction.message
        guild_id = message.guild.id if message.guild else None
        if not self._should_process_guild(guild_id):
            return
        if not self._should_process_channel(message.channel.id):
            return

        emoji_str = str(reaction.emoji)
        try:
            self.repository.remove_reaction(
                message_id=message.id,
                emoji=emoji_str,
                user_id=user.id,
            )
            logger.debug(f"Removed reaction {emoji_str} from message {message.id}")
        except Exception as e:
            logger.error(f"Failed to remove reaction: {e}")

    def _get_roles_snapshot(self, message: discord.Message) -> str:
        """Get JSON array of author's role IDs."""
        if isinstance(message.author, discord.Member):
            role_ids = [
                role.id for role in message.author.roles if role.name != "@everyone"
            ]
            return json.dumps(role_ids)
        return "[]"


# Global client instance
_client: ZosDiscordClient | None = None


async def run_client(config: DiscordConfig | None = None) -> None:
    """Run the Discord client.

    Args:
        config: Discord configuration. Uses global config if None.

    Raises:
        DiscordError: If token is not configured.
    """
    global _client
    if config is None:
        config = get_config().discord

    if not config.token:
        raise DiscordError("Discord token not configured")

    _client = ZosDiscordClient(config=config)
    try:
        await _client.start(config.token)
    finally:
        if _client and not _client.is_closed():
            await _client.close()
        _client = None


def get_client() -> ZosDiscordClient:
    """Get the global Discord client instance."""
    if _client is None:
        raise DiscordError("Discord client not initialized")
    return _client
