"""Tests for message polling functionality.

Covers Story 2.2 acceptance criteria:
- Poll configured channels on interval
- Store messages with all fields from data-model.md
- Track last-polled timestamp per channel (incremental)
- Handle message edits (update existing)
- Handle message deletes (mark or remove)
- Respect privacy gate role (mark non-opted users)
- `<chat>` users get anonymized author_id
- DMs handled separately from guild messages
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest
from sqlalchemy import select

from zos.config import Config
from zos.database import (
    channels,
    create_tables,
    get_engine,
    messages,
    poll_state,
    servers,
    users,
)
from zos.models import VisibilityScope
from zos.observation import ZosBot, URL_PATTERN


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
def now():
    """Return current time in UTC (timezone-aware)."""
    return datetime.now(timezone.utc)


def create_mock_author(user_id: int = 555555555, display_name: str = "TestUser", username: str = "testuser") -> MagicMock:
    """Create a properly configured mock Discord user/member for tests.

    This helper ensures all required string fields are set to avoid
    pydantic validation errors when creating UserProfile objects.
    """
    author = MagicMock()
    author.id = user_id
    author.display_name = display_name
    author.name = username
    author.discriminator = "0"
    author.avatar = None
    author.bot = False
    author.created_at = datetime.now(timezone.utc)
    author.joined_at = None
    author.roles = []
    return author


# =============================================================================
# URL Detection Tests
# =============================================================================


class TestURLDetection:
    """Tests for URL detection in message content."""

    def test_detects_http_url(self) -> None:
        """Should detect http:// URLs."""
        assert URL_PATTERN.search("Check out http://example.com")

    def test_detects_https_url(self) -> None:
        """Should detect https:// URLs."""
        assert URL_PATTERN.search("Visit https://example.com/page")

    def test_detects_www_url(self) -> None:
        """Should detect www. URLs."""
        assert URL_PATTERN.search("Go to www.example.com")

    def test_no_false_positive_regular_text(self) -> None:
        """Should not detect URLs in regular text."""
        assert not URL_PATTERN.search("Hello world, how are you?")

    def test_multiple_urls(self) -> None:
        """Should detect multiple URLs."""
        matches = URL_PATTERN.findall(
            "Check https://a.com and http://b.com"
        )
        assert len(matches) == 2

    def test_contains_links_method(self, bot: ZosBot) -> None:
        """Bot's _contains_links method should work correctly."""
        assert bot._contains_links("Visit https://example.com") is True
        assert bot._contains_links("Hello world") is False


# =============================================================================
# Anonymous ID Tests
# =============================================================================


class TestAnonymousID:
    """Tests for anonymous ID generation."""

    def test_get_anonymous_id_format(self, bot: ZosBot) -> None:
        """Anonymous ID should have correct format."""
        anon_id = bot._get_anonymous_id("123456789", "server1")
        assert anon_id.startswith("<chat_")
        assert anon_id.endswith(">")

    def test_anonymous_id_consistency_same_day(self, bot: ZosBot) -> None:
        """Same user+context should get same ID on same day."""
        id1 = bot._get_anonymous_id("123456789", "server1")
        id2 = bot._get_anonymous_id("123456789", "server1")
        assert id1 == id2

    def test_anonymous_id_differs_by_user(self, bot: ZosBot) -> None:
        """Different users should get different IDs.

        Note: Uses carefully selected test values that don't collide
        under the mod 1000 hash. The anonymization algorithm could
        produce collisions for some user ID pairs - this tests the
        general uniqueness property.
        """
        id1 = bot._get_anonymous_id("12345", "server1")
        id2 = bot._get_anonymous_id("67890", "server1")
        assert id1 != id2

    def test_anonymous_id_differs_by_context(self, bot: ZosBot) -> None:
        """Same user in different contexts should get different IDs."""
        id1 = bot._get_anonymous_id("123456789", "server1")
        id2 = bot._get_anonymous_id("123456789", "server2")
        assert id1 != id2

    def test_anonymous_id_number_in_range(self, bot: ZosBot) -> None:
        """Anonymous ID number should be in range 0-999."""
        anon_id = bot._get_anonymous_id("123456789", "server1")
        # Extract number from <chat_N>
        num_str = anon_id[6:-1]  # Remove "<chat_" and ">"
        num = int(num_str)
        assert 0 <= num <= 999


# =============================================================================
# Privacy Gate Tests
# =============================================================================


class TestPrivacyGate:
    """Tests for privacy gate role handling."""

    def test_dm_always_uses_real_id(self, bot: ZosBot) -> None:
        """DMs should always use real Discord ID."""
        mock_user = MagicMock()
        mock_user.id = 123456789

        result = bot._resolve_author_id(mock_user, None)
        assert result == "123456789"

    def test_no_privacy_gate_uses_real_id(
        self, test_config: Config, engine
    ) -> None:
        """No privacy gate role means all users tracked."""
        bot = ZosBot(test_config, engine)

        mock_member = MagicMock(spec=['id', 'roles'])
        mock_member.id = 123456789

        result = bot._resolve_author_id(mock_member, "server1")
        assert result == "123456789"

    def test_privacy_gate_user_with_role(self, tmp_path: Path, engine) -> None:
        """User with privacy gate role should use real ID."""
        config = Config(
            data_dir=tmp_path,
            servers={"server1": {"privacy_gate_role": "111222333"}},
        )
        bot = ZosBot(config, engine)

        # Mock a member with the privacy gate role
        # Role IDs in Discord are integers, but we store/compare as strings
        mock_role = MagicMock()
        mock_role.id = 111222333  # Integer, will be converted to string

        mock_member = MagicMock(spec=['id', 'roles'])
        mock_member.id = 123456789
        mock_member.roles = [mock_role]

        result = bot._resolve_author_id(mock_member, "server1")
        assert result == "123456789"

    def test_privacy_gate_user_without_role(
        self, tmp_path: Path, engine
    ) -> None:
        """User without privacy gate role should get anonymous ID."""
        config = Config(
            data_dir=tmp_path,
            servers={"server1": {"privacy_gate_role": "role_id_123"}},
        )
        bot = ZosBot(config, engine)

        # Mock a member without the privacy gate role
        mock_role = MagicMock()
        mock_role.id = "different_role"

        mock_member = MagicMock(spec=['id', 'roles'])
        mock_member.id = 123456789
        mock_member.roles = [mock_role]

        result = bot._resolve_author_id(mock_member, "server1")
        assert result.startswith("<chat_")


# =============================================================================
# Database Operation Tests
# =============================================================================


class TestDatabaseOperations:
    """Tests for database operations."""

    @pytest.mark.asyncio
    async def test_ensure_server(self, bot: ZosBot, engine, now) -> None:
        """_ensure_server should create server record."""
        mock_guild = MagicMock()
        mock_guild.id = 123456789
        mock_guild.name = "Test Server"

        await bot._ensure_server(mock_guild)

        with engine.connect() as conn:
            result = conn.execute(
                select(servers).where(servers.c.id == "123456789")
            ).fetchone()
            assert result is not None
            assert result.name == "Test Server"

    @pytest.mark.asyncio
    async def test_ensure_server_upsert(self, bot: ZosBot, engine) -> None:
        """_ensure_server should update name on conflict."""
        mock_guild = MagicMock()
        mock_guild.id = 123456789
        mock_guild.name = "Original Name"

        await bot._ensure_server(mock_guild)

        mock_guild.name = "Updated Name"
        await bot._ensure_server(mock_guild)

        with engine.connect() as conn:
            result = conn.execute(
                select(servers).where(servers.c.id == "123456789")
            ).fetchone()
            assert result.name == "Updated Name"

    @pytest.mark.asyncio
    async def test_ensure_channel(self, bot: ZosBot, engine, now) -> None:
        """_ensure_channel should create channel record."""
        # First create a server
        mock_guild = MagicMock()
        mock_guild.id = 111111111
        mock_guild.name = "Test Server"
        await bot._ensure_server(mock_guild)

        # Then create a channel
        mock_channel = MagicMock(spec=['id', 'name'])
        mock_channel.id = 222222222
        mock_channel.name = "test-channel"

        await bot._ensure_channel(mock_channel, "111111111")

        with engine.connect() as conn:
            result = conn.execute(
                select(channels).where(channels.c.id == "222222222")
            ).fetchone()
            assert result is not None
            assert result.name == "test-channel"
            assert result.type == "text"

    @pytest.mark.asyncio
    async def test_ensure_channel_dm(self, bot: ZosBot, engine) -> None:
        """_ensure_channel should handle DM channels."""
        import discord

        mock_dm = MagicMock(spec=discord.DMChannel)
        mock_dm.id = 333333333

        await bot._ensure_channel(mock_dm, None)

        with engine.connect() as conn:
            # Check DM pseudo-server was created
            server_result = conn.execute(
                select(servers).where(servers.c.id == "dm")
            ).fetchone()
            assert server_result is not None
            assert server_result.name == "Direct Messages"

            # Check channel was created
            channel_result = conn.execute(
                select(channels).where(channels.c.id == "333333333")
            ).fetchone()
            assert channel_result is not None
            assert channel_result.type == "dm"

    @pytest.mark.asyncio
    async def test_ensure_user(self, bot: ZosBot, engine) -> None:
        """_ensure_user should create user record."""
        await bot._ensure_user("999999999")

        with engine.connect() as conn:
            result = conn.execute(
                select(users).where(users.c.id == "999999999")
            ).fetchone()
            assert result is not None
            assert result.first_dm_acknowledged is False

    def test_get_last_polled_none(self, bot: ZosBot) -> None:
        """_get_last_polled should return None for unpollled channels."""
        result = bot._get_last_polled("unknown_channel")
        assert result is None

    def test_set_and_get_last_polled(self, bot: ZosBot, engine) -> None:
        """_set_last_polled and _get_last_polled should work together."""
        channel_id = "test_channel_123"
        timestamp = datetime.now(timezone.utc)

        bot._set_last_polled(channel_id, timestamp)
        result = bot._get_last_polled(channel_id)

        assert result is not None
        # Compare without microseconds due to SQLite precision
        assert abs((result - timestamp).total_seconds()) < 1


# =============================================================================
# Message Storage Tests
# =============================================================================


class TestMessageStorage:
    """Tests for message storage."""

    @pytest.mark.asyncio
    async def test_store_message(self, bot: ZosBot, engine) -> None:
        """_store_message should store message with all fields."""
        # Setup: create server and channel
        mock_guild = MagicMock()
        mock_guild.id = 111111111
        mock_guild.name = "Test Server"
        await bot._ensure_server(mock_guild)

        mock_channel = MagicMock(spec=['id', 'name'])
        mock_channel.id = 222222222
        mock_channel.name = "test-channel"
        await bot._ensure_channel(mock_channel, "111111111")

        # Create mock Discord message
        mock_message = MagicMock()
        mock_message.id = 444444444
        mock_message.channel = mock_channel
        mock_message.author = create_mock_author(555555555)
        mock_message.content = "Hello world"
        mock_message.created_at = datetime.now(timezone.utc)
        mock_message.attachments = []
        mock_message.embeds = []
        mock_message.reference = None
        mock_message.thread = None

        # Store the message
        await bot._store_message(mock_message, "111111111")

        # Verify
        with engine.connect() as conn:
            result = conn.execute(
                select(messages).where(messages.c.id == "444444444")
            ).fetchone()
            assert result is not None
            assert result.content == "Hello world"
            assert result.author_id == "555555555"
            assert result.channel_id == "222222222"
            assert result.visibility_scope == "public"
            assert result.has_media is False
            assert result.has_links is False

    @pytest.mark.asyncio
    async def test_store_message_with_media(self, bot: ZosBot, engine) -> None:
        """_store_message should detect media attachments."""
        # Setup
        mock_guild = MagicMock()
        mock_guild.id = 111111111
        mock_guild.name = "Test Server"
        await bot._ensure_server(mock_guild)

        mock_channel = MagicMock(spec=['id', 'name'])
        mock_channel.id = 222222222
        mock_channel.name = "test-channel"
        await bot._ensure_channel(mock_channel, "111111111")

        # Message with attachments
        mock_message = MagicMock()
        mock_message.id = 444444444
        mock_message.channel = mock_channel
        mock_message.author = create_mock_author(555555555)
        mock_message.content = "Check this out"
        mock_message.created_at = datetime.now(timezone.utc)
        mock_message.attachments = [MagicMock()]  # Has attachment
        mock_message.embeds = []
        mock_message.reference = None
        mock_message.thread = None

        await bot._store_message(mock_message, "111111111")

        with engine.connect() as conn:
            result = conn.execute(
                select(messages).where(messages.c.id == "444444444")
            ).fetchone()
            assert result.has_media is True

    @pytest.mark.asyncio
    async def test_store_message_with_links(self, bot: ZosBot, engine) -> None:
        """_store_message should detect URLs in content."""
        # Setup
        mock_guild = MagicMock()
        mock_guild.id = 111111111
        mock_guild.name = "Test Server"
        await bot._ensure_server(mock_guild)

        mock_channel = MagicMock(spec=['id', 'name'])
        mock_channel.id = 222222222
        mock_channel.name = "test-channel"
        await bot._ensure_channel(mock_channel, "111111111")

        # Message with URL
        mock_message = MagicMock()
        mock_message.id = 444444444
        mock_message.channel = mock_channel
        mock_message.author = create_mock_author(555555555)
        mock_message.content = "Check out https://example.com"
        mock_message.created_at = datetime.now(timezone.utc)
        mock_message.attachments = []
        mock_message.embeds = []
        mock_message.reference = None
        mock_message.thread = None

        await bot._store_message(mock_message, "111111111")

        with engine.connect() as conn:
            result = conn.execute(
                select(messages).where(messages.c.id == "444444444")
            ).fetchone()
            assert result.has_links is True

    @pytest.mark.asyncio
    async def test_store_message_with_reply(self, bot: ZosBot, engine) -> None:
        """_store_message should capture reply_to_id."""
        # Setup
        mock_guild = MagicMock()
        mock_guild.id = 111111111
        mock_guild.name = "Test Server"
        await bot._ensure_server(mock_guild)

        mock_channel = MagicMock(spec=['id', 'name'])
        mock_channel.id = 222222222
        mock_channel.name = "test-channel"
        await bot._ensure_channel(mock_channel, "111111111")

        # Message with reply
        mock_reference = MagicMock()
        mock_reference.message_id = 333333333

        mock_message = MagicMock()
        mock_message.id = 444444444
        mock_message.channel = mock_channel
        mock_message.author = create_mock_author(555555555)
        mock_message.content = "I agree!"
        mock_message.created_at = datetime.now(timezone.utc)
        mock_message.attachments = []
        mock_message.embeds = []
        mock_message.reference = mock_reference
        mock_message.thread = None

        await bot._store_message(mock_message, "111111111")

        with engine.connect() as conn:
            result = conn.execute(
                select(messages).where(messages.c.id == "444444444")
            ).fetchone()
            assert result.reply_to_id == "333333333"


# =============================================================================
# Message Update (Edit) Tests
# =============================================================================


class TestMessageEdit:
    """Tests for message edit handling."""

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_message(
        self, bot: ZosBot, engine
    ) -> None:
        """Upserting an existing message should update its content."""
        # Setup
        mock_guild = MagicMock()
        mock_guild.id = 111111111
        mock_guild.name = "Test Server"
        await bot._ensure_server(mock_guild)

        mock_channel = MagicMock(spec=['id', 'name'])
        mock_channel.id = 222222222
        mock_channel.name = "test-channel"
        await bot._ensure_channel(mock_channel, "111111111")

        # Store original message
        mock_message = MagicMock()
        mock_message.id = 444444444
        mock_message.channel = mock_channel
        mock_message.author = create_mock_author(555555555)
        mock_message.content = "Original content"
        mock_message.created_at = datetime.now(timezone.utc)
        mock_message.attachments = []
        mock_message.embeds = []
        mock_message.reference = None
        mock_message.thread = None

        await bot._store_message(mock_message, "111111111")

        # Store edited version
        mock_message.content = "Edited content"
        await bot._store_message(mock_message, "111111111")

        # Verify content was updated
        with engine.connect() as conn:
            result = conn.execute(
                select(messages).where(messages.c.id == "444444444")
            ).fetchone()
            assert result.content == "Edited content"


# =============================================================================
# Message Delete Tests
# =============================================================================


class TestMessageDelete:
    """Tests for message deletion handling."""

    @pytest.mark.asyncio
    async def test_mark_message_deleted(self, bot: ZosBot, engine) -> None:
        """_mark_message_deleted should set deleted_at tombstone."""
        # Setup
        mock_guild = MagicMock()
        mock_guild.id = 111111111
        mock_guild.name = "Test Server"
        await bot._ensure_server(mock_guild)

        mock_channel = MagicMock(spec=['id', 'name'])
        mock_channel.id = 222222222
        mock_channel.name = "test-channel"
        await bot._ensure_channel(mock_channel, "111111111")

        # Store a message
        mock_message = MagicMock()
        mock_message.id = 444444444
        mock_message.channel = mock_channel
        mock_message.author = create_mock_author(555555555)
        mock_message.content = "Will be deleted"
        mock_message.created_at = datetime.now(timezone.utc)
        mock_message.attachments = []
        mock_message.embeds = []
        mock_message.reference = None
        mock_message.thread = None

        await bot._store_message(mock_message, "111111111")

        # Verify message exists without deleted_at
        with engine.connect() as conn:
            result = conn.execute(
                select(messages).where(messages.c.id == "444444444")
            ).fetchone()
            assert result.deleted_at is None

        # Mark as deleted
        await bot._mark_message_deleted("444444444")

        # Verify deleted_at is set
        with engine.connect() as conn:
            result = conn.execute(
                select(messages).where(messages.c.id == "444444444")
            ).fetchone()
            assert result.deleted_at is not None


# =============================================================================
# DM Handling Tests
# =============================================================================


class TestDMHandling:
    """Tests for DM message handling."""

    @pytest.mark.asyncio
    async def test_store_dm_message(self, bot: ZosBot, engine) -> None:
        """DM messages should have visibility_scope = DM and null server_id."""
        import discord

        # Create DM channel
        mock_dm = MagicMock(spec=discord.DMChannel)
        mock_dm.id = 333333333
        await bot._ensure_channel(mock_dm, None)

        # Create mock Discord DM message
        mock_message = MagicMock()
        mock_message.id = 444444444
        mock_message.channel = mock_dm
        mock_message.author = create_mock_author(555555555)
        mock_message.content = "Hello from DM"
        mock_message.created_at = datetime.now(timezone.utc)
        mock_message.attachments = []
        mock_message.embeds = []
        mock_message.reference = None
        mock_message.thread = None

        # Store the DM message
        await bot._store_message(mock_message, None)

        # Verify
        with engine.connect() as conn:
            result = conn.execute(
                select(messages).where(messages.c.id == "444444444")
            ).fetchone()
            assert result is not None
            assert result.visibility_scope == "dm"
            assert result.server_id is None


# =============================================================================
# Poll State Tracking Tests
# =============================================================================


class TestPollStateTracking:
    """Tests for poll state tracking."""

    def test_incremental_polling(self, bot: ZosBot, engine) -> None:
        """Polling should track last message timestamp per channel."""
        channel_id = "test_channel_456"
        first_timestamp = datetime.now(timezone.utc)

        # First poll
        bot._set_last_polled(channel_id, first_timestamp)
        assert bot._get_last_polled(channel_id) is not None

        # Second poll with later timestamp
        second_timestamp = first_timestamp + timedelta(hours=1)
        bot._set_last_polled(channel_id, second_timestamp)

        # Verify updated
        result = bot._get_last_polled(channel_id)
        assert result is not None
        # Should be approximately equal to second_timestamp
        assert abs((result - second_timestamp).total_seconds()) < 1

    def test_poll_state_per_channel(self, bot: ZosBot, engine) -> None:
        """Each channel should have independent poll state."""
        channel1_id = "channel_1"
        channel2_id = "channel_2"
        timestamp1 = datetime.now(timezone.utc)
        timestamp2 = timestamp1 + timedelta(hours=2)

        bot._set_last_polled(channel1_id, timestamp1)
        bot._set_last_polled(channel2_id, timestamp2)

        result1 = bot._get_last_polled(channel1_id)
        result2 = bot._get_last_polled(channel2_id)

        assert result1 is not None
        assert result2 is not None
        # They should be different
        assert abs((result2 - result1).total_seconds()) > 3600  # ~2 hours apart


# =============================================================================
# Silenced Mode Tests
# =============================================================================


class TestSilencedMode:
    """Tests for silenced observation mode."""

    @pytest.mark.asyncio
    async def test_poll_skipped_when_silenced(self, bot: ZosBot) -> None:
        """Polling should skip when is_silenced is True."""
        bot.is_silenced = True

        with patch("zos.observation.log") as mock_log:
            await bot.poll_messages()
            mock_log.debug.assert_called_with("poll_messages_tick_silenced")


# =============================================================================
# Polling Loop Integration Tests
# =============================================================================


class TestPollingLoop:
    """Tests for the main polling loop."""

    @pytest.mark.asyncio
    async def test_poll_skipped_when_shutdown_requested(
        self, bot: ZosBot
    ) -> None:
        """Polling should not start new work when shutdown is requested."""
        bot._shutdown_requested = True

        with patch("zos.observation.log") as mock_log:
            await bot.poll_messages()
            # Should return early without logging poll_messages_tick_start
            for call in mock_log.debug.call_args_list:
                assert "poll_messages_tick_start" not in str(call)

    @pytest.mark.asyncio
    async def test_poll_skipped_when_no_engine(
        self, test_config: Config
    ) -> None:
        """Polling should skip when no database engine is configured."""
        bot = ZosBot(test_config, engine=None)

        with patch("zos.observation.log") as mock_log:
            await bot.poll_messages()
            mock_log.debug.assert_called_with("poll_messages_tick_no_engine")


# =============================================================================
# Bot Initialization Tests
# =============================================================================


class TestBotInitialization:
    """Tests for bot initialization."""

    def test_bot_stores_config(self, test_config: Config) -> None:
        """Bot should store the provided configuration."""
        bot = ZosBot(test_config)
        assert bot.config is test_config

    def test_bot_stores_engine(self, test_config: Config, engine) -> None:
        """Bot should store the provided engine."""
        bot = ZosBot(test_config, engine)
        assert bot.engine is engine

    def test_bot_initializes_silenced_false(
        self, test_config: Config
    ) -> None:
        """Bot should initialize with is_silenced as False."""
        bot = ZosBot(test_config)
        assert bot.is_silenced is False

    def test_bot_initializes_dev_mode_false(
        self, test_config: Config
    ) -> None:
        """Bot should initialize with dev_mode as False."""
        bot = ZosBot(test_config)
        assert bot.dev_mode is False

    def test_bot_initializes_shutdown_flag_false(
        self, test_config: Config
    ) -> None:
        """Bot should initialize with shutdown flag as False."""
        bot = ZosBot(test_config)
        assert bot._shutdown_requested is False

    def test_bot_has_correct_intents(self, test_config: Config) -> None:
        """Bot should have message_content, reactions, and members intents."""
        bot = ZosBot(test_config)
        assert bot.intents.message_content is True
        assert bot.intents.reactions is True
        assert bot.intents.members is True

    def test_bot_initializes_reaction_rate_limiter(
        self, test_config: Config
    ) -> None:
        """Bot should initialize reaction rate limiter."""
        bot = ZosBot(test_config)
        assert bot._reaction_user_limiter is not None

    def test_bot_initializes_media_queue_with_maxsize(
        self, test_config: Config
    ) -> None:
        """Bot should initialize media queue with configured maxsize."""
        bot = ZosBot(test_config)
        assert bot._media_analysis_queue.maxsize == 100
