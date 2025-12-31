"""Discord client for Zos message ingestion."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import discord
from discord import Intents

from zos.config import DiscordConfig, get_config
from zos.discord.backfill import backfill_channel
from zos.discord.repository import MessageRepository
from zos.exceptions import DiscordError
from zos.logging import get_logger
from zos.salience.earner import SalienceEarner
from zos.topics.extractor import MessageContext

logger = get_logger("discord.client")


class ZosDiscordClient(discord.Client):
    """Discord client that ingests messages and reactions."""

    def __init__(
        self,
        config: DiscordConfig | None = None,
        repository: MessageRepository | None = None,
        salience_earner: SalienceEarner | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the Discord client.

        Args:
            config: Discord configuration. Uses global config if None.
            repository: Message repository for DB operations.
            salience_earner: Salience earner for tracking attention.
            **kwargs: Additional arguments passed to discord.Client.
        """
        if config is None:
            config = get_config().discord
        self.config = config

        # Get DB only if needed for creating components
        if repository is None:
            from zos.db import get_db

            db = get_db()
            repository = MessageRepository(db)
        self.repository = repository

        if salience_earner is None:
            from zos.config import get_config as get_full_config
            from zos.db import get_db

            db = get_db()
            salience_earner = SalienceEarner(
                db,
                get_full_config().salience.earning_weights,
            )
        self.salience_earner = salience_earner

        # Configure intents
        intents = Intents.default()
        intents.message_content = True  # Required for content access
        intents.guild_messages = True
        intents.dm_messages = True
        intents.reactions = True
        intents.guilds = True
        intents.members = True  # For role snapshot

        super().__init__(intents=intents, **kwargs)

    def _should_process_guild(self, guild: discord.Guild | None) -> bool:
        """Check if we should process events from this guild (by ID)."""
        if guild is None:
            return True  # DMs always processed
        if not self.config.guilds:
            return True  # No filter = process all guilds
        return guild.id in self.config.guilds

    def _should_process_channel(self, channel: discord.abc.Messageable) -> bool:
        """Check if channel should be processed (opt-out by ID)."""
        if not self.config.excluded_channels:
            return True  # No exclusions = process all
        channel_id = getattr(channel, "id", None)
        if channel_id is None:
            return True  # Should not happen, but be safe
        return channel_id not in self.config.excluded_channels

    def _should_process_message(self, message: discord.Message) -> bool:
        """Determine if a message should be processed."""
        # Ignore bot messages
        if message.author.bot:
            return False

        if not self._should_process_guild(message.guild):
            return False

        return self._should_process_channel(message.channel)

    def _is_user_tracked(self, message: discord.Message) -> bool:
        """Check if user has opted in for tracking.

        Returns True if:
        - Message is a DM (initiation implies consent)
        - No tracking role is configured (everyone tracked)
        - User has the tracking opt-in role
        """
        # DMs always tracked
        if message.guild is None:
            return True

        # No role configured = everyone tracked
        if not self.config.tracking_opt_in_role:
            return True

        # Check if user has the role
        if isinstance(message.author, discord.Member):
            return any(
                role.name == self.config.tracking_opt_in_role
                for role in message.author.roles
            )

        return False  # Can't verify role = not tracked

    def _is_member_tracked(self, user: discord.User | discord.Member) -> bool:
        """Check if a user/member has opted in for tracking.

        Used for reaction handlers where we have a User or Member, not a Message.

        Returns True if:
        - No tracking role is configured (everyone tracked)
        - User is a Member with the tracking opt-in role
        """
        # No role configured = everyone tracked
        if not self.config.tracking_opt_in_role:
            return True

        # Check if user has the role
        if isinstance(user, discord.Member):
            return any(
                role.name == self.config.tracking_opt_in_role for role in user.roles
            )

        return False  # Can't verify role for plain User = not tracked

    async def on_ready(self) -> None:
        """Called when the client is ready."""
        if self.user:
            logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guilds")

        # Trigger backfill for configured channels
        await self._run_backfill()

    async def _run_backfill(self) -> None:
        """Run backfill for all accessible channels (opt-out filtering)."""
        channels_to_backfill: list[discord.TextChannel] = []

        for guild in self.guilds:
            # Skip guilds not in config (if config specifies guilds)
            if not self._should_process_guild(guild):
                logger.debug(f"Skipping guild {guild.name} (not in config)")
                continue

            for channel in guild.text_channels:
                # Skip excluded channels
                if not self._should_process_channel(channel):
                    logger.debug(f"Skipping channel {channel.name} (excluded)")
                    continue
                channels_to_backfill.append(channel)

        if not channels_to_backfill:
            logger.info("No channels to backfill")
            return

        logger.info(f"Starting backfill for {len(channels_to_backfill)} channels")
        for channel in channels_to_backfill:
            try:
                await backfill_channel(
                    channel, self.repository, self.config.tracking_opt_in_role
                )
            except Exception as e:
                logger.error(f"Backfill failed for channel {channel.name}: {e}")

    async def on_message(self, message: discord.Message) -> None:
        """Handle new messages."""
        if not self._should_process_message(message):
            return

        is_tracked = self._is_user_tracked(message)

        # Determine thread/channel relationship
        is_thread = isinstance(message.channel, discord.Thread)
        if is_thread:
            # For threads: channel_id = thread_id, parent_channel_id = parent
            channel_id = message.channel.id
            thread_id = message.channel.id
            parent_channel_id = message.channel.parent_id
        else:
            # For regular channels: no thread info
            channel_id = message.channel.id
            thread_id = None
            parent_channel_id = None

        # Anonymize non-opted users (privacy protection)
        if is_tracked:
            author_id = message.author.id
            author_name = message.author.display_name
            author_roles_snapshot = self._get_roles_snapshot(message)
        else:
            author_id = 0  # Anonymous marker
            author_name = "chat"
            author_roles_snapshot = "[]"

        try:
            self.repository.upsert_message(
                message_id=message.id,
                guild_id=message.guild.id if message.guild else None,
                guild_name=message.guild.name if message.guild else None,
                channel_id=channel_id,
                channel_name=getattr(message.channel, "name", "DM"),
                thread_id=thread_id,
                parent_channel_id=parent_channel_id,
                author_id=author_id,
                author_name=author_name,
                author_roles_snapshot=author_roles_snapshot,
                content=message.content,
                created_at=message.created_at,
                visibility_scope="dm" if message.guild is None else "public",
                is_tracked=is_tracked,
            )
            # Earn salience for this message (only for tracked users)
            # Note: author_id is already 0 for non-tracked users
            reply_author_id = None
            if message.reference and message.reference.resolved:
                ref = message.reference.resolved
                if isinstance(ref, discord.Message):
                    reply_author_id = ref.author.id

            ctx = MessageContext(
                author_id=author_id,  # Use anonymized ID
                channel_id=message.channel.id,
                content=message.content,
                reply_to_author_id=reply_author_id,
                is_tracked=is_tracked,
            )
            self.salience_earner.earn_for_message(
                ctx, message.id, message.created_at
            )

            logger.debug(
                f"Stored message {message.id} from {author_name} "
                f"(tracked={is_tracked})"
            )
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
        if not self._should_process_guild(message.guild):
            return
        if not self._should_process_channel(message.channel):
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
        if not self._should_process_guild(message.guild):
            return
        if not self._should_process_channel(message.channel):
            return

        is_reactor_tracked = self._is_member_tracked(user)

        # Anonymize non-opted reactors (privacy protection)
        if is_reactor_tracked:
            reactor_id = user.id
            reactor_name = user.display_name
        else:
            reactor_id = 0  # Anonymous marker
            reactor_name = "chat"

        emoji_str = str(reaction.emoji)
        try:
            now = datetime.now(UTC)
            self.repository.add_reaction(
                message_id=message.id,
                emoji=emoji_str,
                user_id=reactor_id,
                user_name=reactor_name,
                created_at=now,
            )

            # Earn salience for reaction given (reactor)
            self.salience_earner.earn_for_reaction_given(
                reactor_id=reactor_id,  # Use anonymized ID
                channel_id=message.channel.id,
                message_id=message.id,
                timestamp=now,
                is_tracked=is_reactor_tracked,
            )

            # Earn salience for reaction received (message author)
            # Note: We use the real author_id here for salience tracking
            # (the message author is already tracked or anonymous in their message)
            if message.author.id != user.id:  # Don't double-count self-reactions
                is_author_tracked = self._is_user_tracked(message)
                self.salience_earner.earn_for_reaction_received(
                    author_id=message.author.id if is_author_tracked else 0,
                    reactor_id=reactor_id,
                    channel_id=message.channel.id,
                    message_id=message.id,
                    timestamp=now,
                    is_author_tracked=is_author_tracked,
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
        if not self._should_process_guild(message.guild):
            return
        if not self._should_process_channel(message.channel):
            return

        is_reactor_tracked = self._is_member_tracked(user)

        # Use anonymized ID for non-tracked users (matches how we stored the reaction)
        reactor_id = user.id if is_reactor_tracked else 0

        emoji_str = str(reaction.emoji)
        try:
            self.repository.remove_reaction(
                message_id=message.id,
                emoji=emoji_str,
                user_id=reactor_id,
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
