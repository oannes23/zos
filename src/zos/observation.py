"""Discord observation bot for Zos.

This module implements the Discord gateway connection and message polling.
It is the "eyes and ears" of Zos - not passive recording but attentive presence,
choosing to attend to communities.

The bot uses batch polling rather than event-driven streaming, which mirrors
human Discord usage patterns and creates architectural space for future attention
allocation.

Messages are the moments of expression that Zos observes. Each message is
stored with full context - who said it, where, when, and what it references.
Anonymous users (those without the privacy gate role) receive stable daily
anonymous IDs, preserving conversation coherence without cross-session tracking.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import signal
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import discord
from discord.ext import commands, tasks
from sqlalchemy import and_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine

from zos.database import (
    channels,
    generate_id,
    media_analysis,
    messages,
    poll_state,
    reactions,
    servers,
    user_profiles,
    users,
)
from zos.llm import ModelClient, RateLimiter
from zos.logging import get_logger
from zos.models import (
    Channel,
    ChannelType,
    MediaAnalysis,
    MediaType,
    Message,
    PollState,
    Reaction,
    UserProfile,
    VisibilityScope,
    model_to_dict,
)

if TYPE_CHECKING:
    from zos.config import Config
    from zos.salience import EarningCoordinator
    from zos.scheduler import ReflectionScheduler

log = get_logger("observation")

# URL pattern for detecting links in messages
URL_PATTERN = re.compile(
    r"https?://[^\s<>\"']+|www\.[^\s<>\"']+"
)

# Supported image MIME types for vision analysis
SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}

# Vision prompt for phenomenological image description
# The prompt should elicit what it feels like to see the image, not just object detection
VISION_PROMPT = """Describe this image as if you were recounting it to someone who can't see it.

Focus on:
- What draws your attention first
- The overall mood or atmosphere
- Notable details that seem meaningful
- Any text or symbols visible
- What the image might mean in a social context (meme, photo, screenshot, etc.)

Write 2-3 sentences capturing both what you see and what it feels like to look at it."""


class ZosBot(commands.Bot):
    """Discord bot for observing community conversations.

    This bot connects to Discord, maintains gateway presence, and polls
    channels for messages. It observes but does not speak (in MVP 0 - The Watcher).

    Uses commands.Bot instead of discord.Client to support slash commands
    via cogs. The command tree provides operator controls for monitoring
    and managing Zos.

    The shutdown behavior completes the current topic being processed before
    exiting, ensuring insights are complete rather than abandoned mid-reflection.

    Attributes:
        config: Application configuration.
        engine: SQLAlchemy database engine.
        is_silenced: When True, observation is paused (no message ingestion).
        dev_mode: When True, CRUD operations on insights are enabled.
    """

    def __init__(
        self,
        config: Config,
        engine: Engine | None = None,
        scheduler: "ReflectionScheduler | None" = None,
    ) -> None:
        """Initialize the bot with required intents.

        Args:
            config: Application configuration.
            engine: SQLAlchemy database engine. If None, polling will be skipped.
            scheduler: ReflectionScheduler for triggering reflection. If None,
                      reflection commands will be unavailable.
        """
        # Minimal intents for observation
        intents = discord.Intents.default()
        intents.message_content = True  # Read message text
        intents.reactions = True  # Track reactions
        intents.members = True  # For user info

        # commands.Bot requires a command_prefix even though we use slash commands
        super().__init__(command_prefix="!", intents=intents)
        self.config = config
        self.engine = engine
        self.scheduler = scheduler
        self._shutdown_requested = False

        # Operator-controlled state
        self.is_silenced: bool = False
        self.dev_mode: bool = False

        # LLM client for vision analysis (lazy initialized)
        self._llm_client: ModelClient | None = None

        # Vision rate limiter (configured separately from provider rate limiting)
        self._vision_rate_limiter = RateLimiter(
            calls_per_minute=config.observation.vision_rate_limit_per_minute
        )

        # Reaction rate limiter
        self._reaction_user_limiter = RateLimiter(
            calls_per_minute=config.observation.reaction_user_rate_limit_per_minute
        )

        # Queue for pending media analysis tasks
        self._media_analysis_queue: asyncio.Queue[
            tuple[str, discord.Attachment]
        ] = asyncio.Queue(maxsize=config.observation.media_queue_max_size)
        self._media_analysis_task: asyncio.Task | None = None

        # Earning coordinator for salience (lazy initialized when engine is available)
        self._earning_coordinator: "EarningCoordinator | None" = None

    async def setup_hook(self) -> None:
        """Called when bot is ready to start tasks.

        This is the recommended place to start background tasks per discord.py docs.
        Also loads the operator commands cog and syncs slash commands.
        """
        # Load operator commands cog
        from zos.commands import OperatorCommands

        await self.add_cog(OperatorCommands(self))
        log.info("cog_loaded", cog="OperatorCommands")

        # Sync slash commands with Discord
        # This makes the commands available in Discord
        await self.tree.sync()
        log.info("commands_synced")

        # Start the polling task with configured interval
        interval = self.config.discord.polling_interval_seconds
        self.poll_messages.change_interval(seconds=interval)
        self.poll_messages.start()
        log.info(
            "background_task_started",
            task="poll_messages",
            interval_seconds=interval,
        )

        # Start media analysis background task if vision is enabled
        if self.config.observation.vision_enabled:
            self._media_analysis_task = asyncio.create_task(
                self._process_media_queue()
            )
            log.info("background_task_started", task="media_analysis")

    def _get_llm_client(self) -> ModelClient:
        """Get or create the LLM client for vision analysis.

        Returns:
            ModelClient instance.
        """
        if self._llm_client is None:
            self._llm_client = ModelClient(self.config)
        return self._llm_client

    def _get_earning_coordinator(self) -> "EarningCoordinator | None":
        """Get or create the earning coordinator for salience earning.

        Returns:
            EarningCoordinator instance, or None if no engine is available.
        """
        if self.engine is None:
            return None

        if self._earning_coordinator is None:
            from zos.salience import EarningCoordinator, SalienceLedger

            ledger = SalienceLedger(self.engine, self.config)
            self._earning_coordinator = EarningCoordinator(ledger, self.config)
        return self._earning_coordinator

    async def on_ready(self) -> None:
        """Called when connected to Discord.

        Logs connection status with server/channel counts for operational visibility.
        """
        guild_count = len(self.guilds)
        channel_count = sum(len(g.text_channels) for g in self.guilds)

        log.info(
            "discord_ready",
            user=str(self.user),
            guilds=guild_count,
            channels=channel_count,
        )

    async def on_disconnect(self) -> None:
        """Called when disconnected from Discord.

        discord.py handles reconnection automatically - this is just for logging.
        """
        log.warning("discord_disconnected")

    async def on_resumed(self) -> None:
        """Called when connection resumed after disconnect.

        Indicates successful reconnection handling.
        """
        log.info("discord_resumed")

    @tasks.loop(seconds=60)  # Default, overridden in setup_hook
    async def poll_messages(self) -> None:
        """Background task for message polling.

        Polls all accessible text channels for new messages since the last poll.
        Messages are stored with all fields from the data model.

        The task runs at the interval configured in discord.polling_interval_seconds.
        When silenced, polling is skipped.
        """
        if self._shutdown_requested:
            # Don't start new work if shutdown is in progress
            return

        if self.is_silenced:
            # Observation is paused by operator
            log.debug("poll_messages_tick_silenced")
            return

        if self.engine is None:
            log.debug("poll_messages_tick_no_engine")
            return

        log.debug("poll_messages_tick_start")
        total_messages = 0

        for guild in self.guilds:
            server_id = str(guild.id)

            # Ensure server exists in database
            await self._ensure_server(guild)

            for channel in guild.text_channels:
                # Check if we can read the channel
                if not channel.permissions_for(guild.me).read_message_history:
                    continue

                try:
                    count = await self._poll_channel(channel, server_id)
                    total_messages += count
                except discord.errors.Forbidden:
                    log.warning(
                        "channel_forbidden",
                        channel_id=str(channel.id),
                        channel_name=channel.name,
                    )
                except Exception as e:
                    log.error(
                        "poll_channel_error",
                        channel_id=str(channel.id),
                        error=str(e),
                    )

        # Also poll DM channels
        for dm in self.private_channels:
            if isinstance(dm, discord.DMChannel):
                try:
                    count = await self._poll_dm_channel(dm)
                    total_messages += count
                except Exception as e:
                    log.error(
                        "poll_dm_error",
                        channel_id=str(dm.id),
                        error=str(e),
                    )

        log.debug(
            "poll_messages_tick_complete",
            messages_stored=total_messages,
            media_queue_depth=self._media_analysis_queue.qsize(),
        )

    @poll_messages.before_loop
    async def before_poll(self) -> None:
        """Wait until bot is ready before polling.

        Ensures Discord client is fully connected before attempting to fetch messages.
        """
        await self.wait_until_ready()
        log.debug("poll_messages_ready")

    @poll_messages.after_loop
    async def after_poll(self) -> None:
        """Called when the polling loop ends."""
        log.debug("poll_messages_stopped")

    # =========================================================================
    # Database Operations
    # =========================================================================

    async def _ensure_server(self, guild: discord.Guild) -> None:
        """Ensure a server exists in the database.

        Args:
            guild: Discord guild to ensure exists.
        """
        if self.engine is None:
            return

        server_id = str(guild.id)
        now = datetime.now(timezone.utc)

        with self.engine.connect() as conn:
            # Use upsert to handle race conditions
            stmt = sqlite_insert(servers).values(
                id=server_id,
                name=guild.name,
                threads_as_topics=True,
                created_at=now,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["id"],
                set_={"name": guild.name},
            )
            conn.execute(stmt)
            conn.commit()

    async def _ensure_channel(
        self,
        channel: discord.TextChannel | discord.DMChannel,
        server_id: str | None,
    ) -> None:
        """Ensure a channel exists in the database.

        Args:
            channel: Discord channel to ensure exists.
            server_id: Parent server ID, or None for DMs.
        """
        if self.engine is None:
            return

        channel_id = str(channel.id)
        now = datetime.now(timezone.utc)

        # Determine channel type
        if isinstance(channel, discord.DMChannel):
            channel_type = ChannelType.DM.value
            channel_name = None
            # For DMs, we need to create a pseudo server entry
            # DMs don't have a real server, but channel FK requires one
            # Use a special "dm" server ID
            if server_id is None:
                server_id = "dm"
                # Ensure DM pseudo-server exists
                with self.engine.connect() as conn:
                    stmt = sqlite_insert(servers).values(
                        id=server_id,
                        name="Direct Messages",
                        threads_as_topics=False,
                        created_at=now,
                    )
                    stmt = stmt.on_conflict_do_nothing()
                    conn.execute(stmt)
                    conn.commit()
        elif isinstance(channel, discord.Thread):
            channel_type = ChannelType.THREAD.value
            channel_name = channel.name
        else:
            channel_type = ChannelType.TEXT.value
            channel_name = channel.name

        parent_id = None
        if hasattr(channel, "parent") and channel.parent:
            parent_id = str(channel.parent.id)

        with self.engine.connect() as conn:
            stmt = sqlite_insert(channels).values(
                id=channel_id,
                server_id=server_id,
                name=channel_name,
                type=channel_type,
                parent_id=parent_id,
                created_at=now,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["id"],
                set_={"name": channel_name},
            )
            conn.execute(stmt)
            conn.commit()

    async def _ensure_user(self, user_id: str) -> None:
        """Ensure a user exists in the database.

        Args:
            user_id: Discord user ID to ensure exists.
        """
        if self.engine is None:
            return

        with self.engine.connect() as conn:
            stmt = sqlite_insert(users).values(
                id=user_id,
                first_dm_acknowledged=False,
            )
            stmt = stmt.on_conflict_do_nothing()
            conn.execute(stmt)
            conn.commit()

    async def _fetch_extended_profile(
        self,
        user: discord.User | discord.Member,
    ) -> tuple[str | None, str | None]:
        """Fetch bio and pronouns from Discord profile API.

        This makes an additional API call to fetch extended profile data.
        Gracefully handles rate limits, forbidden access, and API errors.

        Args:
            user: Discord user or member object.

        Returns:
            (bio, pronouns) tuple, both may be None if unavailable or on error.
        """
        try:
            # fetch_profile() only exists on User, not Member
            # If we have a Member, fetch the User object first
            if isinstance(user, discord.Member):
                user = await self.fetch_user(user.id)
            profile = await user.fetch_profile()

            # Extract bio and pronouns if available
            bio = profile.bio if hasattr(profile, "bio") and profile.bio else None
            pronouns = profile.pronouns if hasattr(profile, "pronouns") and profile.pronouns else None

            return (bio, pronouns)

        except discord.Forbidden:
            # User has restricted profile or bot lacks permissions
            log.debug(
                "profile_fetch_forbidden",
                user_id=str(user.id),
            )
            return (None, None)

        except discord.HTTPException as e:
            # Rate limited or other API error
            log.warning(
                "profile_fetch_failed",
                user_id=str(user.id),
                error=str(e),
            )
            return (None, None)

        except Exception as e:
            # Unexpected error - log but don't crash
            log.warning(
                "profile_fetch_unexpected_error",
                user_id=str(user.id),
                error=str(e),
            )
            return (None, None)

    async def _upsert_user_profile(
        self,
        member: discord.Member | discord.User,
        server_id: str | None,
    ) -> None:
        """Capture or update user profile snapshot.

        Handles both server-specific (Member with roles, join date)
        and global (User from DM) profiles. Only captures profiles for
        users who pass the privacy gate (opted-in users).

        Caches profiles for 7 days to minimize database writes and API calls.

        Args:
            member: Discord user or member object.
            server_id: Server ID, or None for DM contexts (global profile).
        """
        if self.engine is None:
            return

        user_id = str(member.id)

        # Check if we have a recent profile (within 7 days)
        with self.engine.connect() as conn:
            query = select(user_profiles.c.captured_at, user_profiles.c.bio, user_profiles.c.pronouns).where(
                user_profiles.c.user_id == user_id
            )
            if server_id:
                query = query.where(user_profiles.c.server_id == server_id)
            else:
                query = query.where(user_profiles.c.server_id.is_(None))

            result = conn.execute(query.order_by(user_profiles.c.captured_at.desc()).limit(1)).fetchone()

            if result:
                captured_at = result.captured_at
                if captured_at.tzinfo is None:
                    captured_at = captured_at.replace(tzinfo=timezone.utc)
                age = datetime.now(timezone.utc) - captured_at
                if age < timedelta(days=7):
                    # Profile is recent, skip update
                    return

        # Determine if this is a server-scoped profile
        is_server_profile = server_id is not None and isinstance(member, discord.Member)

        # Fetch extended profile data (bio, pronouns)
        bio, pronouns = await self._fetch_extended_profile(member)

        # Build profile model
        profile = UserProfile(
            user_id=user_id,
            server_id=server_id,
            display_name=member.display_name,
            username=member.name,
            discriminator=member.discriminator if member.discriminator != "0" else None,
            avatar_url=str(member.avatar.url) if member.avatar else None,
            is_bot=member.bot,
            account_created_at=member.created_at,
            # Server-specific fields
            joined_at=member.joined_at if is_server_profile else None,
            roles=[str(r.id) for r in member.roles[1:]] if is_server_profile else None,  # Skip @everyone
            # Extended profile data
            bio=bio,
            pronouns=pronouns,
        )

        # Upsert profile
        profile_dict = model_to_dict(profile, exclude_none=False)

        with self.engine.connect() as conn:
            # Use upsert based on (user_id, server_id) uniqueness
            # Note: For upsert to work with nullable columns, we need special handling
            # SQLite upsert with nullable server_id requires explicit NULL handling
            stmt = sqlite_insert(user_profiles).values(**profile_dict)

            # For composite unique index with nullable column (server_id),
            # we need to handle NULL explicitly in the conflict target
            if server_id is None:
                # Global profile - match on user_id where server_id IS NULL
                # SQLite doesn't support partial indexes in on_conflict directly,
                # so we check for existing profile first and update/insert accordingly
                existing = conn.execute(
                    select(user_profiles.c.id).where(
                        (user_profiles.c.user_id == user_id) &
                        (user_profiles.c.server_id.is_(None))
                    )
                ).fetchone()

                if existing:
                    # Update existing global profile
                    conn.execute(
                        user_profiles.update()
                        .where(user_profiles.c.id == existing.id)
                        .values(**profile_dict)
                    )
                else:
                    # Insert new global profile
                    conn.execute(stmt)
            else:
                # Server-scoped profile - standard upsert works
                stmt = stmt.on_conflict_do_update(
                    index_elements=["user_id", "server_id"],
                    set_={
                        "id": profile_dict["id"],
                        "display_name": profile_dict["display_name"],
                        "username": profile_dict["username"],
                        "discriminator": profile_dict["discriminator"],
                        "avatar_url": profile_dict["avatar_url"],
                        "is_bot": profile_dict["is_bot"],
                        "joined_at": profile_dict["joined_at"],
                        "account_created_at": profile_dict["account_created_at"],
                        "roles": profile_dict["roles"],
                        "bio": profile_dict["bio"],
                        "pronouns": profile_dict["pronouns"],
                        "captured_at": profile_dict["captured_at"],
                    },
                )
                conn.execute(stmt)

            conn.commit()

        log.debug(
            "user_profile_captured",
            user_id=user_id,
            server_id=server_id,
            is_server_profile=is_server_profile,
        )

    def _get_last_polled(self, channel_id: str) -> datetime | None:
        """Get the last polled timestamp for a channel.

        Args:
            channel_id: Channel ID to look up.

        Returns:
            Last message timestamp, or None if never polled.
        """
        if self.engine is None:
            return None

        with self.engine.connect() as conn:
            result = conn.execute(
                select(poll_state.c.last_message_at).where(
                    poll_state.c.channel_id == channel_id
                )
            ).fetchone()

            if result and result.last_message_at:
                # Ensure timezone awareness
                ts = result.last_message_at
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                return ts
            return None

    def _set_last_polled(
        self,
        channel_id: str,
        last_message_at: datetime,
    ) -> None:
        """Update the last polled state for a channel.

        Args:
            channel_id: Channel ID to update.
            last_message_at: Timestamp of last message processed.
        """
        if self.engine is None:
            return

        now = datetime.now(timezone.utc)

        with self.engine.connect() as conn:
            stmt = sqlite_insert(poll_state).values(
                channel_id=channel_id,
                last_message_at=last_message_at,
                last_polled_at=now,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["channel_id"],
                set_={
                    "last_message_at": last_message_at,
                    "last_polled_at": now,
                },
            )
            conn.execute(stmt)
            conn.commit()

    def _upsert_message(self, msg: Message) -> None:
        """Insert or update a message in the database.

        Handles edits by upserting - if the message already exists,
        its content and metadata are updated.

        Args:
            msg: Message model to upsert.
        """
        if self.engine is None:
            return

        msg_dict = model_to_dict(msg)

        with self.engine.connect() as conn:
            stmt = sqlite_insert(messages).values(**msg_dict)
            # On conflict (edit), update content and flags
            stmt = stmt.on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "content": msg_dict["content"],
                    "has_media": msg_dict["has_media"],
                    "has_links": msg_dict["has_links"],
                    "ingested_at": msg_dict["ingested_at"],
                },
            )
            conn.execute(stmt)
            conn.commit()

    def _mark_message_deleted(self, message_id: str) -> None:
        """Mark a message as deleted with a soft delete tombstone.

        Args:
            message_id: ID of the message to mark deleted.
        """
        if self.engine is None:
            return

        now = datetime.now(timezone.utc)

        with self.engine.connect() as conn:
            conn.execute(
                messages.update()
                .where(messages.c.id == message_id)
                .values(deleted_at=now)
            )
            conn.commit()

    # =========================================================================
    # Polling Logic
    # =========================================================================

    async def _poll_channel(
        self,
        channel: discord.TextChannel,
        server_id: str,
    ) -> int:
        """Poll a single text channel for new messages.

        Args:
            channel: Discord text channel to poll.
            server_id: Parent server ID.

        Returns:
            Number of messages stored.
        """
        # Ensure channel exists in database
        await self._ensure_channel(channel, server_id)

        channel_id = str(channel.id)
        last_polled = self._get_last_polled(channel_id)

        # Initialize poll_state on first encounter with limited backfill
        if last_polled is None:
            backfill_hours = self.config.observation.backfill_hours
            last_polled = datetime.now(timezone.utc) - timedelta(hours=backfill_hours)
            log.debug(
                "channel_first_poll_backfill_limited",
                channel_id=channel_id,
                channel_name=channel.name,
                backfill_hours=backfill_hours,
            )

        messages_stored = 0
        last_message_at: datetime | None = None

        # Phase 1: Fetch new messages since last poll
        async for message in channel.history(
            after=last_polled,
            limit=100,  # Default batch size
            oldest_first=True,
        ):
            await self._store_message(message, server_id)
            messages_stored += 1
            last_message_at = message.created_at

            # Sync reactions for this message
            if message.reactions:
                await self._sync_reactions(message, server_id)

        # Update poll state if we processed any messages
        if messages_stored > 0 and last_message_at is not None:
            self._set_last_polled(channel_id, last_message_at)
            log.debug(
                "channel_polled",
                channel_id=channel_id,
                channel_name=channel.name,
                messages_stored=messages_stored,
            )

        # Phase 2: Re-sync reactions by checking stored messages from database
        # This catches reactions added to older messages after they were first polled
        resync_hours = self.config.observation.reaction_resync_hours
        resync_cutoff = datetime.now(timezone.utc) - timedelta(hours=resync_hours)

        # Query messages from database (last N hours, non-deleted, limit for performance)
        with self.engine.connect() as conn:
            stmt = (
                select(messages.c.id, messages.c.channel_id, messages.c.reactions_aggregate)
                .where(
                    and_(
                        messages.c.channel_id == channel_id,
                        messages.c.created_at >= resync_cutoff,
                        messages.c.deleted_at.is_(None),
                    )
                )
                .order_by(messages.c.created_at.desc())
                .limit(100)  # Only check 100 most recent messages for performance
            )
            stored_messages = conn.execute(stmt).fetchall()

        # Re-fetch each message from Discord to check for reaction changes
        reactions_resynced = 0
        messages_checked = 0
        for row in stored_messages:
            message_id = row.id
            messages_checked += 1

            # Skip if no reactions recorded in DB (optimization)
            if not row.reactions_aggregate:
                continue

            try:
                discord_message = await channel.fetch_message(int(message_id))
                if discord_message.reactions:
                    await self._sync_reactions(discord_message, server_id)
                    reactions_resynced += 1
            except discord.NotFound:
                # Message was deleted from Discord
                await self._mark_message_deleted(message_id)
            except discord.Forbidden:
                log.warning(
                    "message_fetch_forbidden",
                    message_id=message_id,
                    channel_id=channel_id,
                )
                continue
            except Exception as e:
                log.error(
                    "message_fetch_error",
                    message_id=message_id,
                    channel_id=channel_id,
                    error=str(e),
                )
                continue

        if reactions_resynced > 0:
            log.debug(
                "reaction_resync_completed",
                channel_id=channel_id,
                channel_name=channel.name,
                messages_checked=messages_checked,
                with_reactions=reactions_resynced,
            )

        return messages_stored

    async def _mark_message_deleted(self, message_id: str) -> None:
        """Mark a message as deleted (soft delete).

        Args:
            message_id: Discord message snowflake ID.
        """
        with self.engine.connect() as conn:
            conn.execute(
                messages.update()
                .where(messages.c.id == message_id)
                .values(deleted_at=datetime.now(timezone.utc))
            )
            conn.commit()
            log.debug("message_marked_deleted", message_id=message_id)

    async def _poll_dm_channel(self, channel: discord.DMChannel) -> int:
        """Poll a DM channel for new messages.

        Args:
            channel: Discord DM channel to poll.

        Returns:
            Number of messages stored.
        """
        # Ensure channel exists (will create pseudo-server for DMs)
        await self._ensure_channel(channel, None)

        # Ensure user exists
        if channel.recipient:
            await self._ensure_user(str(channel.recipient.id))

        channel_id = str(channel.id)
        last_polled = self._get_last_polled(channel_id)

        # Initialize poll_state on first encounter with limited backfill
        if last_polled is None:
            backfill_hours = self.config.observation.backfill_hours
            last_polled = datetime.now(timezone.utc) - timedelta(hours=backfill_hours)
            log.debug(
                "dm_channel_first_poll_backfill_limited",
                channel_id=channel_id,
                backfill_hours=backfill_hours,
            )

        messages_stored = 0
        last_message_at: datetime | None = None

        # Fetch messages since last poll
        async for message in channel.history(
            after=last_polled,
            limit=100,
            oldest_first=True,
        ):
            # DMs have no server_id
            await self._store_message(message, None)
            messages_stored += 1
            last_message_at = message.created_at

            # Sync reactions for this message (DMs can have reactions too)
            if message.reactions:
                await self._sync_reactions(message, None)

        # Update poll state
        if messages_stored > 0 and last_message_at is not None:
            self._set_last_polled(channel_id, last_message_at)
            log.debug(
                "dm_channel_polled",
                channel_id=channel_id,
                messages_stored=messages_stored,
            )

        return messages_stored

    async def _store_message(
        self,
        message: discord.Message,
        server_id: str | None,
    ) -> None:
        """Store a Discord message in the database.

        Args:
            message: Discord message to store.
            server_id: Server ID, or None for DMs.
        """
        # Determine visibility scope
        is_dm = isinstance(message.channel, discord.DMChannel)
        scope = VisibilityScope.DM if is_dm else VisibilityScope.PUBLIC

        # Resolve author ID (apply privacy gate)
        author_id = self._resolve_author_id(message.author, server_id)

        # Check for media/links
        has_media = bool(message.attachments) or bool(message.embeds)
        has_links = self._contains_links(message.content)

        # Get channel_id - for DMs, use the "dm" pseudo-server
        db_server_id = server_id
        if is_dm and server_id is None:
            db_server_id = None  # Message table allows null server_id for DMs

        # Build message record
        msg = Message(
            id=str(message.id),
            channel_id=str(message.channel.id),
            server_id=db_server_id,
            author_id=author_id,
            content=message.content,
            created_at=message.created_at,
            visibility_scope=scope,
            reply_to_id=(
                str(message.reference.message_id)
                if message.reference and message.reference.message_id
                else None
            ),
            thread_id=(
                str(message.thread.id)
                if hasattr(message, "thread") and message.thread
                else None
            ),
            has_media=has_media,
            has_links=has_links,
        )

        # Upsert (handles edits)
        self._upsert_message(msg)

        log.debug(
            "message_stored",
            message_id=msg.id,
            channel_id=msg.channel_id,
            author_anonymized=author_id.startswith("<chat"),
        )

        # Capture user profile (respects privacy gate - only for opted-in users)
        if not author_id.startswith("<chat"):
            await self._upsert_user_profile(message.author, server_id)

        # Earn salience for this message
        earning = self._get_earning_coordinator()
        if earning:
            try:
                topics = await earning.process_message(msg)
                if topics:
                    log.debug(
                        "salience_earned",
                        message_id=msg.id,
                        topics_earned=len(topics),
                    )
            except Exception as e:
                log.warning(
                    "earning_failed",
                    message_id=msg.id,
                    error=str(e),
                )
                # Don't fail message storage if earning fails

        # Queue media for analysis (doesn't block polling)
        # Privacy boundary: never analyze media from anonymous users
        if has_media and message.attachments:
            await self._queue_media_for_analysis(message, author_id)

    # =========================================================================
    # Privacy Gate
    # =========================================================================

    def _resolve_author_id(
        self,
        author: discord.User | discord.Member,
        server_id: str | None,
    ) -> str:
        """Resolve author ID, respecting privacy gate role.

        For users with the privacy gate role (or in servers without one),
        returns the real Discord ID. For users without the role, returns
        a stable anonymous ID that resets daily.

        Args:
            author: Discord user or member.
            server_id: Server ID, or None for DMs.

        Returns:
            User ID or anonymous ID string.
        """
        if server_id is None:
            # DMs always use real ID (implicit consent)
            return str(author.id)

        server_config = self.config.get_server_config(server_id)
        if not server_config.privacy_gate_role:
            # No privacy gate, all users tracked
            return str(author.id)

        # Check if user has privacy gate role
        # Use duck typing (check for roles attribute) rather than isinstance
        # This allows the code to work with both real Discord objects and mocks
        if hasattr(author, "roles") and author.roles is not None:
            role_ids = [str(r.id) for r in author.roles]
            if server_config.privacy_gate_role in role_ids:
                return str(author.id)

        # User doesn't have role - anonymize
        # Use consistent anonymous ID within context, reset daily
        return self._get_anonymous_id(str(author.id), server_id)

    def _get_anonymous_id(self, real_id: str, context_id: str) -> str:
        """Generate consistent anonymous ID for a user in a context.

        Anonymous IDs are stable within a day (date bucket) to preserve
        conversation coherence, but reset daily so anonymous users
        cannot be tracked across time.

        Args:
            real_id: Real Discord user ID.
            context_id: Context identifier (e.g., server_id).

        Returns:
            Anonymous ID string like "<chat_123>".
        """
        # Get date bucket (resets at midnight UTC)
        date_bucket = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Create stable hash from real_id + context + date
        hash_input = f"{real_id}:{context_id}:{date_bucket}"
        hash_bytes = hashlib.sha256(hash_input.encode()).digest()

        # Use first 4 bytes as number, mod 1000 for readable ID
        hash_num = int.from_bytes(hash_bytes[:4], "big") % 1000

        return f"<chat_{hash_num}>"

    def _contains_links(self, content: str) -> bool:
        """Check if message content contains URLs.

        Args:
            content: Message content to check.

        Returns:
            True if content contains URLs.
        """
        return bool(URL_PATTERN.search(content))

    # =========================================================================
    # Reaction Handling
    # =========================================================================

    def _serialize_emoji(self, emoji: discord.Emoji | discord.PartialEmoji | str) -> str:
        """Serialize emoji to storable string.

        Unicode emoji are stored as-is. Custom emoji are stored with just the name
        (global by name per design decision) as :name:.

        Args:
            emoji: Discord emoji object or unicode string.

        Returns:
            Serialized emoji string.
        """
        if isinstance(emoji, str):
            # Unicode emoji
            return emoji
        else:
            # Custom emoji - store just the name (global namespace)
            # Per design decision: treat same-named emoji as same concept across servers
            return f":{emoji.name}:"

    def _is_custom_emoji(self, emoji_str: str) -> bool:
        """Check if serialized emoji is custom.

        Args:
            emoji_str: Serialized emoji string.

        Returns:
            True if this is a custom emoji.
        """
        return emoji_str.startswith(":") and emoji_str.endswith(":") and len(emoji_str) > 2

    async def _sync_reactions(
        self,
        message: discord.Message,
        server_id: str | None,
    ) -> None:
        """Sync reactions for a message, marking removed ones with removed_at.

        Fetches current reactions from Discord, stores new ones, and marks
        any previously stored reactions that are no longer present.

        Args:
            message: Discord message to sync reactions for.
            server_id: Parent server ID, or None for DMs.
        """
        if self.engine is None:
            return

        message_id = str(message.id)

        # Build set of current reactions from Discord
        current_reactions: set[tuple[str, str]] = set()  # (user_id, emoji)

        for reaction in message.reactions:
            emoji_str = self._serialize_emoji(reaction.emoji)
            is_custom = self._is_custom_emoji(emoji_str)

            # Fetch users who reacted
            try:
                # Apply rate limiting before fetching reaction users
                await self._reaction_user_limiter.acquire()

                async for user in reaction.users():
                    # Apply privacy gate
                    user_id = self._resolve_author_id(user, server_id)

                    # Skip anonymous users for individual tracking
                    # Per spec: only opted-in users' reactions tracked individually
                    if user_id.startswith("<chat"):
                        continue

                    current_reactions.add((user_id, emoji_str))

                    # Store this reaction
                    is_new = await self._store_reaction(
                        message_id=message_id,
                        user_id=user_id,
                        emoji=emoji_str,
                        is_custom=is_custom,
                        server_id=server_id,
                    )

                    # Capture reactor's profile (same as message authors)
                    # This ensures we have profile data for users who react but don't post
                    await self._upsert_user_profile(user, server_id)

                    # Earn salience for new reactions
                    if is_new:
                        await self._earn_reaction_salience(
                            discord_message=message,
                            user_id=user_id,
                            emoji=emoji_str,
                            is_custom=is_custom,
                            server_id=server_id,
                        )
            except discord.errors.Forbidden:
                log.warning(
                    "reaction_users_forbidden",
                    message_id=message_id,
                    emoji=emoji_str,
                )
                continue

        # Get previously stored reactions for this message
        stored_reactions = self._get_reactions_for_message(message_id)

        # Find reactions that were removed (soft delete with removed_at)
        for stored in stored_reactions:
            # Skip already-removed reactions
            if stored.removed_at is not None:
                continue

            key = (stored.user_id, stored.emoji)
            if key not in current_reactions:
                # This reaction was removed - mark it
                self._mark_reaction_removed(stored.id)
                log.debug(
                    "reaction_removed",
                    message_id=message_id,
                    user_id=stored.user_id,
                    emoji=stored.emoji,
                )

        # Update aggregate counts on the message
        await self._update_message_reactions(message)

    async def _store_reaction(
        self,
        message_id: str,
        user_id: str,
        emoji: str,
        is_custom: bool,
        server_id: str | None,
    ) -> bool:
        """Store a single reaction.

        Uses upsert to handle re-fetching the same reaction.

        Args:
            message_id: ID of the message reacted to.
            user_id: ID of the user who reacted.
            emoji: Serialized emoji string.
            is_custom: Whether this is a custom emoji.
            server_id: Server ID for custom emoji topics.

        Returns:
            True if this was a new reaction, False if it already existed.
        """
        if self.engine is None:
            return False

        now = datetime.now(timezone.utc)
        is_new_reaction = False

        with self.engine.connect() as conn:
            # Check if reaction already exists
            existing = conn.execute(
                select(reactions.c.id).where(
                    (reactions.c.message_id == message_id)
                    & (reactions.c.user_id == user_id)
                    & (reactions.c.emoji == emoji)
                )
            ).fetchone()

            if existing:
                # Reaction exists - clear removed_at if it was set (reaction re-added)
                conn.execute(
                    reactions.update()
                    .where(reactions.c.id == existing.id)
                    .values(removed_at=None)
                )
            else:
                # New reaction - insert
                is_new_reaction = True
                reaction_model = Reaction(
                    id=generate_id(),
                    message_id=message_id,
                    user_id=user_id,
                    emoji=emoji,
                    is_custom=is_custom,
                    server_id=server_id,
                    created_at=now,
                )
                conn.execute(
                    reactions.insert().values(**model_to_dict(reaction_model))
                )

            conn.commit()

        return is_new_reaction

    async def _earn_reaction_salience(
        self,
        discord_message: discord.Message,
        user_id: str,
        emoji: str,
        is_custom: bool,
        server_id: str | None,
    ) -> None:
        """Earn salience for a reaction.

        This is called when a new reaction is stored to earn salience
        for the relevant topics.

        Args:
            discord_message: Discord message the reaction is on.
            user_id: ID of the user who reacted.
            emoji: Serialized emoji string.
            is_custom: Whether this is a custom emoji.
            server_id: Server ID for custom emoji topics.
        """
        earning = self._get_earning_coordinator()
        if not earning:
            return

        try:
            # Build Message model for earning
            message_id = str(discord_message.id)
            author_id = self._resolve_author_id(discord_message.author, server_id)
            is_dm = isinstance(discord_message.channel, discord.DMChannel)
            scope = VisibilityScope.DM if is_dm else VisibilityScope.PUBLIC

            msg_model = Message(
                id=message_id,
                channel_id=str(discord_message.channel.id),
                server_id=server_id,
                author_id=author_id,
                content=discord_message.content,
                created_at=discord_message.created_at,
                visibility_scope=scope,
                reply_to_id=None,
                thread_id=None,
                has_media=False,
                has_links=False,
            )

            reaction_model = Reaction(
                message_id=message_id,
                user_id=user_id,
                emoji=emoji,
                is_custom=is_custom,
                server_id=server_id,
            )

            topics = await earning.process_reaction(reaction_model, msg_model)
            if topics:
                log.debug(
                    "reaction_salience_earned",
                    message_id=message_id,
                    topics_earned=len(topics),
                )
        except Exception as e:
            log.warning(
                "reaction_earning_failed",
                message_id=str(discord_message.id),
                error=str(e),
            )
            # Don't fail reaction storage if earning fails

    def _get_reactions_for_message(self, message_id: str) -> list[Reaction]:
        """Get all reactions for a message.

        Args:
            message_id: Message ID to get reactions for.

        Returns:
            List of Reaction models.
        """
        if self.engine is None:
            return []

        with self.engine.connect() as conn:
            result = conn.execute(
                select(reactions).where(reactions.c.message_id == message_id)
            ).fetchall()

            return [
                Reaction(
                    id=row.id,
                    message_id=row.message_id,
                    user_id=row.user_id,
                    emoji=row.emoji,
                    is_custom=row.is_custom,
                    server_id=row.server_id,
                    created_at=row.created_at,
                    removed_at=row.removed_at,
                )
                for row in result
            ]

    def _mark_reaction_removed(self, reaction_id: str) -> None:
        """Mark a reaction as removed with soft delete timestamp.

        Args:
            reaction_id: ID of the reaction to mark removed.
        """
        if self.engine is None:
            return

        now = datetime.now(timezone.utc)

        with self.engine.connect() as conn:
            conn.execute(
                reactions.update()
                .where(reactions.c.id == reaction_id)
                .values(removed_at=now)
            )
            conn.commit()

    async def _update_message_reactions(self, message: discord.Message) -> None:
        """Update the aggregate reaction counts on a message.

        Args:
            message: Discord message with reactions.
        """
        if self.engine is None:
            return

        # Build aggregate: {emoji_str: count}
        aggregate: dict[str, int] = {}
        for reaction in message.reactions:
            emoji_str = self._serialize_emoji(reaction.emoji)
            aggregate[emoji_str] = reaction.count

        message_id = str(message.id)

        with self.engine.connect() as conn:
            conn.execute(
                messages.update()
                .where(messages.c.id == message_id)
                .values(reactions_aggregate=json.dumps(aggregate) if aggregate else None)
            )
            conn.commit()

        if aggregate:
            log.debug(
                "reactions_aggregate_updated",
                message_id=message_id,
                reaction_count=sum(aggregate.values()),
            )

    # =========================================================================
    # Media Analysis
    # =========================================================================

    def _is_image(self, attachment: discord.Attachment) -> bool:
        """Check if attachment is a supported image type.

        Args:
            attachment: Discord attachment to check.

        Returns:
            True if this is a supported image type for vision analysis.
        """
        return attachment.content_type in SUPPORTED_IMAGE_TYPES

    def _infer_media_type(self, attachment: discord.Attachment) -> str:
        """Infer media type from attachment, with fallback to filename extension.

        Discord attachments should have content_type set, but occasionally don't.
        When missing, infer from file extension to avoid sending wrong media type to vision API.

        Args:
            attachment: Discord attachment to infer type for.

        Returns:
            MIME type string (e.g., "image/png", "image/jpeg").
        """
        # Prefer the explicit content type if available
        if attachment.content_type:
            return attachment.content_type

        # Fall back to filename extension
        if attachment.filename:
            filename_lower = attachment.filename.lower()
            if filename_lower.endswith('.png'):
                return "image/png"
            elif filename_lower.endswith(('.jpg', '.jpeg')):
                return "image/jpeg"
            elif filename_lower.endswith('.gif'):
                return "image/gif"
            elif filename_lower.endswith('.webp'):
                return "image/webp"

        # Last resort default
        log.warning(
            "media_type_unknown",
            filename=attachment.filename,
            defaulting_to="image/jpeg"
        )
        return "image/jpeg"

    def _detect_media_type_from_bytes(self, data: bytes) -> str | None:
        """Detect image media type from magic bytes (file signature).

        This is more reliable than trusting metadata or file extensions,
        which can be incorrect when files are renamed or mislabeled.

        Args:
            data: Raw image bytes.

        Returns:
            MIME type string if recognized, None if unrecognized format.
        """
        if len(data) < 12:
            return None

        # PNG: 89 50 4E 47 0D 0A 1A 0A
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            return "image/png"

        # JPEG: FF D8 FF
        if data[:3] == b'\xff\xd8\xff':
            return "image/jpeg"

        # GIF: GIF87a or GIF89a
        if data[:6] in (b'GIF87a', b'GIF89a'):
            return "image/gif"

        # WebP: RIFF....WEBP (bytes 0-3 = "RIFF", bytes 8-11 = "WEBP")
        if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return "image/webp"

        return None

    async def _queue_media_for_analysis(
        self,
        message: discord.Message,
        author_id: str,
    ) -> None:
        """Queue any image attachments for vision analysis.

        Messages are stored immediately with has_media=true. Images are
        queued for separate analysis that doesn't block polling.

        Privacy boundary: Anonymous users (<chat>) have their media logged
        but NOT analyzed. This respects the privacy gate - we don't process
        visual content from users who haven't opted into identity tracking.

        Args:
            message: Discord message with potential media attachments.
            author_id: Resolved author ID (may be <chat_N> for anonymous users).
        """
        if not self.config.observation.vision_enabled:
            return

        # Privacy boundary: never analyze media from anonymous users
        if author_id.startswith("<chat"):
            if message.attachments:
                log.debug(
                    "media_skipped_anonymous",
                    message_id=str(message.id),
                    attachment_count=len(message.attachments),
                )
            return

        for attachment in message.attachments:
            if self._is_image(attachment):
                # Log warning if queue is getting full
                queue_size = self._media_analysis_queue.qsize()
                if queue_size > self.config.observation.media_queue_max_size * 0.8:
                    log.warning(
                        "media_queue_near_full",
                        queue_size=queue_size,
                        max_size=self.config.observation.media_queue_max_size,
                    )

                await self._media_analysis_queue.put(
                    (str(message.id), attachment)
                )
                log.debug(
                    "media_queued",
                    message_id=str(message.id),
                    filename=attachment.filename,
                    content_type=attachment.content_type,
                )

    async def _process_media_queue(self) -> None:
        """Background task to process queued media for analysis.

        Runs continuously, pulling items from the queue and analyzing them.
        Uses rate limiting to prevent API exhaustion. Failures are logged
        but don't block other analysis.
        """
        log.debug("media_analysis_task_started")

        while not self._shutdown_requested:
            try:
                # Wait for an item with a timeout to allow checking shutdown
                try:
                    message_id, attachment = await asyncio.wait_for(
                        self._media_analysis_queue.get(),
                        timeout=5.0,
                    )
                except asyncio.TimeoutError:
                    continue

                # Analyze the image
                await self._analyze_image(message_id, attachment)

            except asyncio.CancelledError:
                log.debug("media_analysis_task_cancelled")
                break
            except Exception as e:
                log.error("media_analysis_queue_error", error=str(e))
                # Continue processing despite errors

        log.debug("media_analysis_task_stopped")

    async def _analyze_image(
        self,
        message_id: str,
        attachment: discord.Attachment,
    ) -> None:
        """Analyze an image with vision model.

        Downloads the image, sends it to the vision model for phenomenological
        description, and stores the analysis. Failures are logged but don't
        block message storage or other analysis.

        Args:
            message_id: ID of the message containing the image.
            attachment: Discord attachment to analyze.
        """
        try:
            # Apply vision-specific rate limiting
            await self._vision_rate_limiter.acquire()

            # Download image
            image_data = await attachment.read()
            image_base64 = base64.b64encode(image_data).decode("utf-8")

            log.debug(
                "vision_analysis_start",
                message_id=message_id,
                filename=attachment.filename,
                size_bytes=len(image_data),
            )

            # Detect actual media type from bytes (most reliable)
            detected_type = self._detect_media_type_from_bytes(image_data)
            inferred_type = self._infer_media_type(attachment)

            if detected_type:
                if detected_type != inferred_type:
                    log.warning(
                        "media_type_mismatch",
                        message_id=message_id,
                        filename=attachment.filename,
                        inferred=inferred_type,
                        detected=detected_type,
                    )
                media_type_str = detected_type
            else:
                # Unrecognized format - skip analysis
                log.warning(
                    "media_type_unrecognized",
                    message_id=message_id,
                    filename=attachment.filename,
                    first_bytes=image_data[:12].hex() if len(image_data) >= 12 else image_data.hex(),
                )
                return

            # Call vision model
            llm = self._get_llm_client()
            result = await llm.analyze_image(
                image_base64=image_base64,
                media_type=media_type_str,
                prompt=VISION_PROMPT,
                model_profile="vision",
            )

            # Determine media type enum from content type
            if "gif" in media_type_str:
                media_type = MediaType.GIF
            else:
                media_type = MediaType.IMAGE

            # Store analysis
            analysis = MediaAnalysis(
                id=generate_id(),
                message_id=message_id,
                media_type=media_type,
                url=attachment.url,
                filename=attachment.filename,
                width=attachment.width,
                height=attachment.height,
                description=result.text,
                analyzed_at=datetime.now(timezone.utc),
                analysis_model=result.model,
            )

            self._insert_media_analysis(analysis)

            log.info(
                "media_analyzed",
                message_id=message_id,
                media_type=media_type.value,
                tokens_in=result.usage.input_tokens,
                tokens_out=result.usage.output_tokens,
            )

        except Exception as e:
            log.warning(
                "media_analysis_failed",
                message_id=message_id,
                filename=attachment.filename,
                error=str(e),
            )
            # Don't re-raise - media analysis failure shouldn't block observation

    def _insert_media_analysis(self, analysis: MediaAnalysis) -> None:
        """Insert a media analysis record into the database.

        Args:
            analysis: MediaAnalysis model to insert.
        """
        if self.engine is None:
            return

        analysis_dict = model_to_dict(analysis)
        # Convert enum to string for database
        analysis_dict["media_type"] = analysis.media_type.value

        with self.engine.connect() as conn:
            conn.execute(media_analysis.insert().values(**analysis_dict))
            conn.commit()

    def _get_media_analysis_for_message(
        self,
        message_id: str,
    ) -> list[MediaAnalysis]:
        """Get all media analysis records for a message.

        Args:
            message_id: Message ID to look up.

        Returns:
            List of MediaAnalysis models for this message.
        """
        if self.engine is None:
            return []

        with self.engine.connect() as conn:
            result = conn.execute(
                select(media_analysis).where(
                    media_analysis.c.message_id == message_id
                )
            ).fetchall()

            return [
                MediaAnalysis(
                    id=row.id,
                    message_id=row.message_id,
                    media_type=MediaType(row.media_type),
                    url=row.url,
                    filename=row.filename,
                    width=row.width,
                    height=row.height,
                    duration_seconds=row.duration_seconds,
                    description=row.description,
                    analyzed_at=row.analyzed_at,
                    analysis_model=row.analysis_model,
                )
                for row in result
            ]

    async def graceful_shutdown(self) -> None:
        """Perform graceful shutdown.

        Completes current topic processing (if any), then disconnects.
        Per design decision: finish the topic being processed, then shutdown.
        Insights should be complete, not abandoned mid-reflection.
        """
        log.info("shutdown_initiated")
        self._shutdown_requested = True

        # Cancel the background tasks
        if self.poll_messages.is_running():
            self.poll_messages.cancel()
            log.debug("poll_messages_cancelled")

        if self._media_analysis_task is not None:
            self._media_analysis_task.cancel()
            try:
                await self._media_analysis_task
            except asyncio.CancelledError:
                pass
            log.debug("media_analysis_task_cancelled")

        # Close the LLM client if initialized
        if self._llm_client is not None:
            await self._llm_client.close()

        # Close the Discord connection
        await self.close()
        await asyncio.sleep(0)  # Allow pending aiohttp callbacks to finalize
        log.info("shutdown_complete")


def setup_signal_handlers(bot: ZosBot, loop: asyncio.AbstractEventLoop) -> None:
    """Setup graceful shutdown handlers for SIGINT and SIGTERM.

    Args:
        bot: The ZosBot instance to shut down.
        loop: The event loop to add signal handlers to.
    """

    def handle_signal(sig: signal.Signals) -> None:
        """Handle shutdown signal."""
        log.info("signal_received", signal=sig.name)
        # Schedule the shutdown coroutine
        loop.create_task(bot.graceful_shutdown())

    # Register handlers for both signals
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: handle_signal(s))

    log.debug("signal_handlers_registered", signals=["SIGINT", "SIGTERM"])


async def run_bot(
    config: Config,
    engine: Engine | None = None,
    scheduler: "ReflectionScheduler | None" = None,
) -> None:
    """Run the Discord observation bot.

    This is the main entry point for the observe command.
    Sets up signal handlers and runs the bot until shutdown.

    Args:
        config: Application configuration with discord_token.
        engine: SQLAlchemy database engine for message storage.
        scheduler: Optional ReflectionScheduler for reflection commands.
    """
    bot = ZosBot(config, engine, scheduler)
    loop = asyncio.get_running_loop()

    # Setup signal handlers for graceful shutdown
    setup_signal_handlers(bot, loop)

    try:
        log.info("bot_starting")
        await bot.start(config.discord_token)  # type: ignore[arg-type]
    except asyncio.CancelledError:
        log.debug("bot_cancelled")
    finally:
        if not bot.is_closed():
            await bot.close()
