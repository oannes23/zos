"""Tests for backfill protection and cost spiral prevention.

Covers:
- First poll initialization with/without backfill
- Poll state initialization for guild channels
- Poll state initialization for DM channels
- Subsequent polls after initialization
- Reaction rate limiting
- Media queue size limits
- Queue depth monitoring
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from zos.config import Config
from zos.database import (
    channels,
    create_tables,
    get_engine,
    poll_state,
    servers,
)
from zos.observation import ZosBot


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def test_config(tmp_path: Path) -> Config:
    """Create a test configuration with temp database."""
    return Config(
        data_dir=tmp_path,
        log_level="DEBUG",
    )


@pytest.fixture
def test_config_backfill_enabled(tmp_path: Path) -> Config:
    """Create a test configuration with backfill enabled."""
    config = Config(
        data_dir=tmp_path,
        log_level="DEBUG",
    )
    config.observation.allow_backfill_on_startup = True
    return config


@pytest.fixture
def engine(test_config: Config):
    """Create a test database engine with all tables."""
    eng = get_engine(test_config)
    create_tables(eng)
    return eng


@pytest.fixture
def bot(test_config: Config, engine):
    """Create a ZosBot with test config and engine."""
    return ZosBot(test_config, engine)


@pytest.fixture
def bot_backfill_enabled(test_config_backfill_enabled: Config, engine):
    """Create a ZosBot with backfill enabled."""
    return ZosBot(test_config_backfill_enabled, engine)


@pytest.fixture
def now():
    """Return current time in UTC (timezone-aware)."""
    return datetime.now(timezone.utc)


# =============================================================================
# First Poll Initialization Tests
# =============================================================================


class TestFirstPollInitialization:
    """Tests for poll_state initialization on first poll."""

    @pytest.mark.asyncio
    async def test_first_poll_no_backfill_guild_channel(
        self, bot: ZosBot, engine, now
    ) -> None:
        """First poll should initialize poll_state without fetching messages."""
        # Setup: create server and channel
        mock_guild = MagicMock()
        mock_guild.id = 111111111
        mock_guild.name = "Test Server"
        mock_guild.me = MagicMock()
        await bot._ensure_server(mock_guild)

        mock_channel = MagicMock()
        mock_channel.id = 222222222
        mock_channel.name = "test-channel"

        # Mock the history iterator to verify it's not called
        history_mock = AsyncMock()
        mock_channel.history = MagicMock(return_value=history_mock)
        history_mock.__aiter__ = MagicMock(return_value=AsyncMock())

        # First poll - should initialize without fetching
        count = await bot._poll_channel(mock_channel, "111111111")

        # Should return 0 messages (nothing fetched)
        assert count == 0

        # Poll state should be initialized
        last_polled = bot._get_last_polled("222222222")
        assert last_polled is not None
        # Should be recent (within last second)
        assert (datetime.now(timezone.utc) - last_polled).total_seconds() < 2

    @pytest.mark.asyncio
    async def test_first_poll_no_backfill_dm_channel(
        self, bot: ZosBot, engine, now
    ) -> None:
        """First poll should initialize poll_state for DM channels."""
        import discord

        mock_dm = MagicMock(spec=discord.DMChannel)
        mock_dm.id = 333333333
        mock_dm.recipient = MagicMock()
        mock_dm.recipient.id = 444444444

        # Mock the history iterator
        history_mock = AsyncMock()
        mock_dm.history = MagicMock(return_value=history_mock)
        history_mock.__aiter__ = MagicMock(return_value=AsyncMock())

        # First poll - should initialize without fetching
        count = await bot._poll_dm_channel(mock_dm)

        # Should return 0 messages (nothing fetched)
        assert count == 0

        # Poll state should be initialized
        last_polled = bot._get_last_polled("333333333")
        assert last_polled is not None
        # Should be recent
        assert (datetime.now(timezone.utc) - last_polled).total_seconds() < 2

    @pytest.mark.asyncio
    async def test_first_poll_with_backfill_enabled(
        self, bot_backfill_enabled: ZosBot, engine
    ) -> None:
        """When backfill enabled, first poll should fetch historical messages."""
        # Setup
        mock_guild = MagicMock()
        mock_guild.id = 111111111
        mock_guild.name = "Test Server"
        await bot_backfill_enabled._ensure_server(mock_guild)

        mock_channel = MagicMock()
        mock_channel.id = 222222222
        mock_channel.name = "test-channel"
        await bot_backfill_enabled._ensure_channel(mock_channel, "111111111")

        # Create mock messages
        mock_message = MagicMock()
        mock_message.id = 555555555
        mock_message.channel = mock_channel
        mock_message.author = MagicMock()
        mock_message.author.id = 666666666
        mock_message.content = "Historical message"
        mock_message.created_at = datetime.now(timezone.utc) - timedelta(days=1)
        mock_message.attachments = []
        mock_message.embeds = []
        mock_message.reference = None
        mock_message.thread = None
        mock_message.reactions = []

        # Mock history to return one message
        async def mock_history_iter():
            yield mock_message

        history_mock = MagicMock()
        history_mock.__aiter__ = lambda self: mock_history_iter()
        mock_channel.history = MagicMock(return_value=history_mock)

        # Poll with backfill enabled
        count = await bot_backfill_enabled._poll_channel(mock_channel, "111111111")

        # Should have fetched the historical message
        assert count == 1

    @pytest.mark.asyncio
    async def test_subsequent_poll_after_initialization(
        self, bot: ZosBot, engine
    ) -> None:
        """After initialization, subsequent polls should work normally."""
        # Setup
        mock_guild = MagicMock()
        mock_guild.id = 111111111
        mock_guild.name = "Test Server"
        await bot._ensure_server(mock_guild)

        mock_channel = MagicMock()
        mock_channel.id = 222222222
        mock_channel.name = "test-channel"
        await bot._ensure_channel(mock_channel, "111111111")

        # Mock history - empty for first poll
        async def empty_history():
            return
            yield  # Make it a generator

        history_mock = MagicMock()
        history_mock.__aiter__ = lambda self: empty_history()
        mock_channel.history = MagicMock(return_value=history_mock)

        # First poll - initializes
        count1 = await bot._poll_channel(mock_channel, "111111111")
        assert count1 == 0

        # Create a new message
        mock_message = MagicMock()
        mock_message.id = 777777777
        mock_message.channel = mock_channel
        mock_message.author = MagicMock()
        mock_message.author.id = 888888888
        mock_message.content = "New message"
        mock_message.created_at = datetime.now(timezone.utc)
        mock_message.attachments = []
        mock_message.embeds = []
        mock_message.reference = None
        mock_message.thread = None
        mock_message.reactions = []

        # Mock history to return the new message
        async def new_message_history():
            yield mock_message

        history_mock.__aiter__ = lambda self: new_message_history()

        # Second poll - should fetch new messages normally
        count2 = await bot._poll_channel(mock_channel, "111111111")
        assert count2 == 1


# =============================================================================
# Reaction Rate Limiting Tests
# =============================================================================


class TestReactionRateLimiting:
    """Tests for reaction user fetching rate limits."""

    @pytest.mark.asyncio
    async def test_reaction_rate_limiter_initialized(
        self, bot: ZosBot
    ) -> None:
        """Bot should initialize reaction rate limiter."""
        assert bot._reaction_user_limiter is not None
        assert bot._reaction_user_limiter.calls_per_minute == 20

    @pytest.mark.asyncio
    async def test_reaction_rate_limiter_custom_config(
        self, tmp_path: Path, engine
    ) -> None:
        """Reaction rate limiter should use configured rate."""
        config = Config(
            data_dir=tmp_path,
            log_level="DEBUG",
        )
        config.observation.reaction_user_rate_limit_per_minute = 50
        bot = ZosBot(config, engine)

        assert bot._reaction_user_limiter.calls_per_minute == 50

    @pytest.mark.asyncio
    async def test_reaction_sync_calls_rate_limiter(
        self, bot: ZosBot, engine
    ) -> None:
        """_sync_reactions should call rate limiter before fetching users."""
        # Setup
        mock_guild = MagicMock()
        mock_guild.id = 111111111
        mock_guild.name = "Test Server"
        await bot._ensure_server(mock_guild)

        mock_channel = MagicMock()
        mock_channel.id = 222222222
        mock_channel.name = "test-channel"
        await bot._ensure_channel(mock_channel, "111111111")

        # Create and store a message first
        mock_message = MagicMock()
        mock_message.id = 333333333
        mock_message.channel = mock_channel
        mock_message.author = MagicMock()
        mock_message.author.id = 444444444
        mock_message.content = "Test message"
        mock_message.created_at = datetime.now(timezone.utc)
        mock_message.attachments = []
        mock_message.embeds = []
        mock_message.reference = None
        mock_message.thread = None
        mock_message.reactions = []

        # Store the message in database
        await bot._store_message(mock_message, "111111111")

        # Now add reactions
        mock_user = MagicMock()
        mock_user.id = 444444444

        async def mock_users_iter():
            yield mock_user

        mock_reaction = MagicMock()
        mock_reaction.emoji = "\u2764\ufe0f"  # Heart emoji
        mock_reaction.count = 1  # Add count attribute for _update_message_reactions
        users_mock = MagicMock()
        users_mock.__aiter__ = lambda self: mock_users_iter()
        mock_reaction.users = MagicMock(return_value=users_mock)

        mock_message.reactions = [mock_reaction]

        # Patch the rate limiter to verify it's called
        with patch.object(bot._reaction_user_limiter, 'acquire', new=AsyncMock()) as mock_acquire:
            await bot._sync_reactions(mock_message, "111111111")
            # Should have called acquire once (one reaction)
            assert mock_acquire.call_count == 1


# =============================================================================
# Media Queue Tests
# =============================================================================


class TestMediaQueueLimits:
    """Tests for media queue size limits and monitoring."""

    def test_media_queue_initialized_with_maxsize(
        self, bot: ZosBot
    ) -> None:
        """Media queue should be initialized with maxsize."""
        assert bot._media_analysis_queue.maxsize == 100

    def test_media_queue_custom_config(
        self, tmp_path: Path, engine
    ) -> None:
        """Media queue should use configured max size."""
        config = Config(
            data_dir=tmp_path,
            log_level="DEBUG",
        )
        config.observation.media_queue_max_size = 50
        bot = ZosBot(config, engine)

        assert bot._media_analysis_queue.maxsize == 50

    @pytest.mark.asyncio
    async def test_queue_near_full_warning_logged(
        self, bot: ZosBot, engine
    ) -> None:
        """Should log warning when queue is near full."""
        # Setup
        mock_message = MagicMock()
        mock_message.id = 111111111

        # Mock image attachment
        mock_attachment = MagicMock()
        mock_attachment.filename = "test.png"
        mock_attachment.content_type = "image/png"

        mock_message.attachments = [mock_attachment]

        # Fill queue to 85% (trigger warning threshold)
        max_size = bot.config.observation.media_queue_max_size
        fill_count = int(max_size * 0.85)

        for i in range(fill_count):
            await bot._media_analysis_queue.put((str(i), mock_attachment))

        # Now queue another item - should trigger warning
        with patch("zos.observation.log") as mock_log:
            await bot._queue_media_for_analysis(mock_message, "123456789")
            # Should have logged warning
            mock_log.warning.assert_called()
            call_args = mock_log.warning.call_args
            assert "media_queue_near_full" in str(call_args)

    @pytest.mark.asyncio
    async def test_queue_depth_in_poll_messages_log(
        self, bot: ZosBot
    ) -> None:
        """poll_messages should log queue depth."""
        # Mock guilds and private_channels properties
        with patch.object(type(bot), 'guilds', new_callable=lambda: property(lambda self: [])):
            with patch.object(type(bot), 'private_channels', new_callable=lambda: property(lambda self: [])):
                with patch("zos.observation.log") as mock_log:
                    await bot.poll_messages()
                    # Check that queue depth was logged
                    for call in mock_log.debug.call_args_list:
                        if "poll_messages_tick_complete" in str(call):
                            # Verify media_queue_depth is in the call
                            assert "media_queue_depth" in str(call)
                            return
                    pytest.fail("poll_messages_tick_complete log not found")

    @pytest.mark.asyncio
    async def test_anonymous_user_media_not_queued(
        self, bot: ZosBot
    ) -> None:
        """Media from anonymous users should not be queued."""
        mock_message = MagicMock()
        mock_message.id = 999999999

        mock_attachment = MagicMock()
        mock_attachment.filename = "test.png"
        mock_attachment.content_type = "image/png"
        mock_message.attachments = [mock_attachment]

        # Queue for anonymous user
        initial_size = bot._media_analysis_queue.qsize()
        await bot._queue_media_for_analysis(mock_message, "<chat_123>")

        # Queue size should not change
        assert bot._media_analysis_queue.qsize() == initial_size


# =============================================================================
# Configuration Tests
# =============================================================================


class TestBackfillConfiguration:
    """Tests for backfill-related configuration."""

    def test_default_config_no_backfill(self, test_config: Config) -> None:
        """Default config should have backfill disabled."""
        assert test_config.observation.allow_backfill_on_startup is False

    def test_default_reaction_rate_limit(self, test_config: Config) -> None:
        """Default config should have reaction rate limit set."""
        assert test_config.observation.reaction_user_rate_limit_per_minute == 20

    def test_default_media_queue_max_size(self, test_config: Config) -> None:
        """Default config should have media queue max size set."""
        assert test_config.observation.media_queue_max_size == 100
