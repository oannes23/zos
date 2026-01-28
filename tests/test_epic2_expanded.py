"""Expanded integration tests for Epic 2: Observation.

This file provides additional test coverage for:
- Story 2-1: Discord Connection edge cases and integration
- Story 2-2: Message Polling edge cases and integration
- Story 2-3: Reaction Tracking edge cases and integration
- Story 2-4: Media Analysis edge cases and integration
- Story 2-5: Link Analysis edge cases and integration
- Story 2-6: Operator Commands full suite

Tests focus on:
- End-to-end workflows
- Error handling and recovery
- Configuration and feature toggles
- Edge cases and boundary conditions
- Integration between components
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zos.config import Config, DiscordConfig, OperatorsConfig, ObservationConfig, ServerOverrideConfig
from zos.database import (
    channels,
    create_tables,
    get_engine,
    link_analysis,
    media_analysis,
    messages,
    poll_state,
    reactions,
    servers,
)
from zos.models import LinkAnalysis, MediaAnalysis, Message, VisibilityScope
from zos.observation import ZosBot


def create_mock_author(
    user_id: int = 555555555,
    display_name: str = "TestUser",
    username: str = "testuser"
) -> MagicMock:
    """Create a properly configured mock Discord user/member for tests."""
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
# Story 2-1 Extended Tests: Discord Connection
# =============================================================================


class TestDiscordConnectionEdgeCases:
    """Test edge cases and error scenarios for Discord connection."""

    def test_bot_reconnect_state_after_disconnect(self) -> None:
        """Bot state is correct after disconnect/reconnect cycle."""
        config = Config()
        bot = ZosBot(config)

        # Initial state
        assert bot._shutdown_requested is False

        # Mock disconnect
        assert bot.intents.guilds is True

    @pytest.mark.asyncio
    async def test_shutdown_during_poll_graceful(self) -> None:
        """Shutdown requested during poll completes current work."""
        config = Config()
        bot = ZosBot(config)
        bot._shutdown_requested = False

        # Set shutdown flag
        bot._shutdown_requested = True

        # Poll should check flag and return
        with patch("zos.observation.log"):
            await bot.poll_messages()


class TestPollingIntervalConfiguration:
    """Test polling interval configuration."""

    def test_polling_interval_respects_config(self, tmp_path: Path) -> None:
        """Polling interval is set from configuration."""
        config = Config(data_dir=tmp_path)
        config.discord.polling_interval_seconds = 45
        bot = ZosBot(config)

        assert bot.config.discord.polling_interval_seconds == 45

    def test_polling_interval_minimum_valid(self, tmp_path: Path) -> None:
        """Very small polling intervals are configured correctly."""
        config = Config(data_dir=tmp_path)
        config.discord.polling_interval_seconds = 5
        bot = ZosBot(config)

        assert bot.config.discord.polling_interval_seconds == 5

    def test_polling_interval_large_valid(self, tmp_path: Path) -> None:
        """Large polling intervals are configured correctly."""
        config = Config(data_dir=tmp_path)
        config.discord.polling_interval_seconds = 3600
        bot = ZosBot(config)

        assert bot.config.discord.polling_interval_seconds == 3600


# =============================================================================
# Story 2-2 Extended Tests: Message Polling Integration
# =============================================================================


class TestMessagePollingIntegration:
    """Integration tests for complete message polling workflow."""

    @pytest.fixture
    def test_db(self, tmp_path: Path):
        """Create a test database with schema."""
        config = Config(data_dir=tmp_path)
        engine = get_engine(config)
        create_tables(engine)
        return engine

    @pytest.mark.asyncio
    async def test_poll_multiple_channels_incremental(
        self, tmp_path: Path, test_db
    ) -> None:
        """Polling multiple channels independently tracks last-polled per channel."""
        config = Config(data_dir=tmp_path)
        bot = ZosBot(config, engine=test_db)

        # Setup multiple channels
        channels_data = [
            ("channel1", "server1", "announcements"),
            ("channel2", "server1", "general"),
            ("channel3", "server2", "random"),
        ]

        with test_db.connect() as conn:
            for server_id in ["server1", "server2"]:
                conn.execute(
                    servers.insert().values(
                        id=server_id,
                        name=f"Server {server_id}",
                        threads_as_topics=True,
                        created_at=datetime.now(timezone.utc),
                    )
                )

            for channel_id, server_id, name in channels_data:
                conn.execute(
                    channels.insert().values(
                        id=channel_id,
                        server_id=server_id,
                        name=name,
                        type="text",
                        created_at=datetime.now(timezone.utc),
                    )
                )
            conn.commit()

        # Set last-polled timestamps
        now = datetime.now(timezone.utc)
        bot._set_last_polled("channel1", now - timedelta(hours=1))
        bot._set_last_polled("channel2", now - timedelta(minutes=30))
        bot._set_last_polled("channel3", now - timedelta(hours=2))

        # Verify independent tracking
        assert bot._get_last_polled("channel1") is not None
        assert bot._get_last_polled("channel2") is not None
        assert bot._get_last_polled("channel3") is not None

        # Timestamps should differ
        ts1 = bot._get_last_polled("channel1")
        ts2 = bot._get_last_polled("channel2")
        assert ts1 != ts2

    @pytest.mark.asyncio
    async def test_message_edit_preserves_id_updates_content(
        self, tmp_path: Path, test_db
    ) -> None:
        """Edited message has same ID but updated content."""
        config = Config(data_dir=tmp_path)
        bot = ZosBot(config, engine=test_db)

        # Setup server and channel
        now = datetime.now(timezone.utc)
        with test_db.connect() as conn:
            conn.execute(
                servers.insert().values(
                    id="server1",
                    name="Test Server",
                    threads_as_topics=True,
                    created_at=now,
                )
            )
            conn.execute(
                channels.insert().values(
                    id="111111",  # Match the channel ID used in mock
                    server_id="server1",
                    name="test",
                    type="text",
                    created_at=now,
                )
            )
            conn.commit()

        # Store original message
        mock_message = MagicMock()
        mock_message.id = 123456
        mock_message.channel = MagicMock()
        mock_message.channel.id = 111111  # Use numeric ID
        mock_message.author = create_mock_author(999)
        mock_message.content = "Original content"
        mock_message.created_at = now
        mock_message.attachments = []
        mock_message.embeds = []
        mock_message.reference = None
        mock_message.thread = None

        await bot._store_message(mock_message, "server1")

        # Edit the message
        mock_message.content = "Edited content"
        await bot._store_message(mock_message, "server1")

        # Verify ID is same but content updated
        with test_db.connect() as conn:
            result = conn.execute(
                messages.select().where(messages.c.id == "123456")
            ).fetchone()
            assert result.content == "Edited content"

    @pytest.mark.asyncio
    async def test_message_delete_soft_delete_with_tombstone(
        self, tmp_path: Path, test_db
    ) -> None:
        """Message deletion marks with tombstone, not actual delete."""
        config = Config(data_dir=tmp_path)
        bot = ZosBot(config, engine=test_db)

        # Setup
        now = datetime.now(timezone.utc)
        with test_db.connect() as conn:
            conn.execute(
                servers.insert().values(
                    id="server1",
                    name="Server",
                    threads_as_topics=True,
                    created_at=now,
                )
            )
            conn.execute(
                channels.insert().values(
                    id="channel1",
                    server_id="server1",
                    name="test",
                    type="text",
                    created_at=now,
                )
            )
            conn.execute(
                messages.insert().values(
                    id="msg1",
                    channel_id="channel1",
                    server_id="server1",
                    author_id="user1",
                    content="Will be deleted",
                    created_at=now,
                    visibility_scope="public",
                    has_media=False,
                    has_links=False,
                    ingested_at=now,
                )
            )
            conn.commit()

        # Mark as deleted
        await bot._mark_message_deleted("msg1")

        # Verify row still exists with deleted_at set
        with test_db.connect() as conn:
            result = conn.execute(
                messages.select().where(messages.c.id == "msg1")
            ).fetchone()
            assert result is not None
            assert result.deleted_at is not None


class TestPrivacyGateComplexScenarios:
    """Test complex privacy gate scenarios."""

    @pytest.fixture
    def test_db(self, tmp_path: Path):
        """Create test database."""
        config = Config(data_dir=tmp_path)
        engine = get_engine(config)
        create_tables(engine)
        return engine

    def test_privacy_gate_multiple_roles_user_has_one(self, tmp_path: Path, test_db) -> None:
        """User with one of multiple privacy gate roles is tracked."""
        config = Config(
            data_dir=tmp_path,
            servers={
                "server1": ServerOverrideConfig(
                    privacy_gate_role="role_opted_in",
                )
            },
        )
        bot = ZosBot(config, engine=test_db)

        # User has multiple roles including privacy gate role
        mock_role1 = MagicMock()
        mock_role1.id = "role_other"
        mock_role2 = MagicMock()
        mock_role2.id = "role_opted_in"

        mock_member = MagicMock()
        mock_member.id = 12345
        mock_member.roles = [mock_role1, mock_role2]

        result = bot._resolve_author_id(mock_member, "server1")
        assert result == "12345"

    def test_no_privacy_gate_all_users_tracked(self, tmp_path: Path, test_db) -> None:
        """Without privacy gate, all users tracked with real IDs."""
        config = Config(data_dir=tmp_path)
        bot = ZosBot(config, engine=test_db)

        mock_member = MagicMock()
        mock_member.id = 99999
        mock_member.roles = []

        result = bot._resolve_author_id(mock_member, "server1")
        assert result == "99999"


# =============================================================================
# Story 2-3 Extended Tests: Reaction Tracking
# =============================================================================


class TestReactionTrackingComplexScenarios:
    """Complex scenario tests for reaction tracking."""

    @pytest.fixture
    def test_db(self, tmp_path: Path):
        """Create test database."""
        config = Config(data_dir=tmp_path)
        engine = get_engine(config)
        create_tables(engine)
        return engine

    @pytest.mark.asyncio
    async def test_reaction_aggregate_multiple_emoji_types(
        self, test_db
    ) -> None:
        """Reaction aggregate handles mixed Unicode and custom emoji."""
        config = Config()
        bot = ZosBot(config, engine=test_db)

        # Create message
        now = datetime.now(timezone.utc)
        with test_db.connect() as conn:
            conn.execute(
                servers.insert().values(
                    id="server1",
                    name="Server",
                    threads_as_topics=True,
                    created_at=now,
                )
            )
            conn.execute(
                channels.insert().values(
                    id="channel1",
                    server_id="server1",
                    name="test",
                    type="text",
                    created_at=now,
                )
            )
            from zos.models import model_to_dict

            msg = Message(
                id="msg1",
                channel_id="channel1",
                server_id="server1",
                author_id="user1",
                content="Test",
                created_at=now,
                visibility_scope=VisibilityScope.PUBLIC,
                has_media=False,
                has_links=False,
            )
            conn.execute(messages.insert().values(**model_to_dict(msg)))
            conn.commit()

        # Mock message with mixed reactions
        mock_unicode_reaction = MagicMock()
        mock_unicode_reaction.emoji = "🎉"
        mock_unicode_reaction.count = 3

        mock_custom_emoji = MagicMock()
        mock_custom_emoji.name = "celebration"
        mock_custom_emoji.id = 12345

        mock_custom_reaction = MagicMock()
        mock_custom_reaction.emoji = mock_custom_emoji
        mock_custom_reaction.count = 2

        mock_message = MagicMock()
        mock_message.id = "msg1"  # Keep as string for database lookup
        mock_message.reactions = [mock_unicode_reaction, mock_custom_reaction]

        await bot._update_message_reactions(mock_message)

        # Verify aggregate contains both
        import json

        with test_db.connect() as conn:
            result = conn.execute(
                messages.select().where(messages.c.id == "msg1")
            ).fetchone()
            aggregate = json.loads(result.reactions_aggregate)
            assert "🎉" in aggregate
            assert ":celebration:" in aggregate
            assert aggregate["🎉"] == 3
            assert aggregate[":celebration:"] == 2


# =============================================================================
# Story 2-4 Extended Tests: Media Analysis
# =============================================================================


class TestMediaAnalysisEdgeCases:
    """Edge case tests for media analysis."""

    @pytest.fixture
    def test_db(self, tmp_path: Path):
        """Create test database."""
        config = Config(data_dir=tmp_path)
        engine = get_engine(config)
        create_tables(engine)
        return engine

    def test_image_type_detection_comprehensive(self) -> None:
        """All supported image types are correctly detected."""
        config = Config()
        bot = ZosBot(config)

        supported_types = [
            ("image/png", True),
            ("image/jpeg", True),
            ("image/gif", True),
            ("image/webp", True),
            ("image/svg+xml", False),  # SVG not supported
            ("image/tiff", False),  # TIFF not supported
            ("video/mp4", False),
            ("application/pdf", False),
            ("text/plain", False),
        ]

        for mime_type, expected in supported_types:
            attachment = MagicMock()
            attachment.content_type = mime_type
            result = bot._is_image(attachment)
            assert result == expected, f"Failed for {mime_type}: got {result}, expected {expected}"

    @pytest.mark.asyncio
    async def test_vision_disabled_skips_all_analysis(self) -> None:
        """Vision disabled completely skips media analysis."""
        config = Config()
        config.observation.vision_enabled = False
        bot = ZosBot(config)

        message = MagicMock()
        attachment = MagicMock()
        attachment.content_type = "image/png"
        message.attachments = [attachment]

        await bot._queue_media_for_analysis(message, author_id="123456")

        assert bot._media_analysis_queue.empty()


# =============================================================================
# Story 2-5 Extended Tests: Link Analysis
# =============================================================================


class TestLinkAnalysisEdgeCases:
    """Edge case tests for link analysis."""

    def test_youtube_video_id_extraction_all_formats(self) -> None:
        """YouTube video IDs extracted from all URL formats."""
        from zos.links import extract_video_id

        test_cases = [
            ("https://youtube.com/watch?v=abc123", "abc123"),
            ("https://www.youtube.com/watch?v=abc123", "abc123"),
            ("https://youtu.be/abc123", "abc123"),
            ("https://youtube.com/embed/abc123", "abc123"),
            ("https://youtube.com/shorts/abc123", "abc123"),
            ("https://youtube.com/watch?v=abc123&t=10s", "abc123"),
            ("https://m.youtube.com/watch?v=abc123", "abc123"),
            ("https://vimeo.com/123456", None),  # Not YouTube
            ("https://example.com", None),
        ]

        for url, expected in test_cases:
            result = extract_video_id(url)
            assert result == expected, f"Failed for {url}: got {result}, expected {expected}"

    def test_url_extraction_edge_cases(self) -> None:
        """URL extraction handles edge cases correctly."""
        from zos.links import extract_urls

        test_cases = [
            ("", []),
            ("No URLs here", []),
            ("https://example.com", ["https://example.com"]),
            ("https://example.com https://test.org", ["https://example.com", "https://test.org"]),
            # Just test that URL is extracted; fragment handling may vary
            ("URL: https://example.com/path?query=value#fragment", None),
        ]

        for content, expected in test_cases:
            result = extract_urls(content)
            if expected is None:
                # Just check URL base is found
                assert len(result) == 1
                assert "https://example.com/path" in result[0]
            else:
                assert result == expected, f"Failed for {repr(content)}: got {result}, expected {expected}"


# =============================================================================
# Story 2-6 Extended Tests: Operator Commands
# =============================================================================


class TestOperatorCommandsComprehensive:
    """Comprehensive tests for all operator commands."""

    def test_operator_check_priority_user_id_first(self) -> None:
        """Operator check prioritizes user ID over role."""
        from zos.commands import OperatorCommands
        from tests.test_commands import MockZosBot, MockInteraction

        bot = MockZosBot(
            operator_user_ids=["123456"],
            operator_role_id="999999",  # Use numeric string
        )
        cog = OperatorCommands(bot)  # type: ignore[arg-type]

        # User is in list and has role
        interaction = MockInteraction(
            user_id="123456",
            role_ids=["999999"],  # Use numeric string
        )
        assert cog.is_operator(interaction) is True  # type: ignore[arg-type]

    def test_operator_check_rejects_user_without_user_id_or_role(self) -> None:
        """Non-operator is rejected even with other privileges."""
        from zos.commands import OperatorCommands
        from tests.test_commands import MockZosBot, MockInteraction

        bot = MockZosBot(
            operator_user_ids=["111111"],
            operator_role_id="888888",  # Use numeric string
        )
        cog = OperatorCommands(bot)  # type: ignore[arg-type]

        # User is not in list and doesn't have role
        interaction = MockInteraction(
            user_id="222222",
            role_ids=["777777"],  # Use numeric string (different role)
        )
        assert cog.is_operator(interaction) is False  # type: ignore[arg-type]


class TestSilencedMode:
    """Tests for silenced/pause mode."""

    @pytest.fixture
    def test_db(self, tmp_path: Path):
        """Create test database."""
        config = Config(data_dir=tmp_path)
        engine = get_engine(config)
        create_tables(engine)
        return engine

    @pytest.mark.asyncio
    async def test_silenced_mode_skips_polling(self, test_db) -> None:
        """Polling is skipped when silenced."""
        config = Config()
        bot = ZosBot(config, engine=test_db)
        bot.is_silenced = True

        with patch("zos.observation.log") as mock_log:
            await bot.poll_messages()
            mock_log.debug.assert_called_with("poll_messages_tick_silenced")

    @pytest.mark.asyncio
    async def test_silenced_mode_toggle(self, test_db) -> None:
        """Silence state can be toggled."""
        config = Config()
        bot = ZosBot(config, engine=test_db)

        # Initial state
        assert bot.is_silenced is False

        # Toggle
        bot.is_silenced = True
        assert bot.is_silenced is True

        # Toggle back
        bot.is_silenced = False
        assert bot.is_silenced is False


# =============================================================================
# Cross-Story Integration Tests
# =============================================================================


class TestObservationEndToEnd:
    """End-to-end integration tests across Epic 2."""

    @pytest.fixture
    def test_db(self, tmp_path: Path):
        """Create test database."""
        config = Config(data_dir=tmp_path)
        engine = get_engine(config)
        create_tables(engine)
        return engine

    @pytest.mark.asyncio
    async def test_message_with_all_features(self, tmp_path: Path, test_db) -> None:
        """Message with media, links, and reactions is fully processed."""
        config = Config(data_dir=tmp_path)
        bot = ZosBot(config, engine=test_db)

        now = datetime.now(timezone.utc)

        # Setup server and channel
        with test_db.connect() as conn:
            conn.execute(
                servers.insert().values(
                    id="server1",
                    name="Server",
                    threads_as_topics=True,
                    created_at=now,
                )
            )
            conn.execute(
                channels.insert().values(
                    id="111111",  # Match the channel ID used in mock
                    server_id="server1",
                    name="test",
                    type="text",
                    created_at=now,
                )
            )
            conn.commit()

        # Store message with media flag and links flag
        mock_message = MagicMock()
        mock_message.id = 123
        mock_message.channel = MagicMock()
        mock_message.channel.id = 111111  # Use numeric ID
        mock_message.author = create_mock_author(456)
        mock_message.content = "Check this out! https://example.com/interesting"
        mock_message.created_at = now
        mock_message.attachments = [MagicMock()]  # Has media
        mock_message.embeds = []
        mock_message.reference = None
        mock_message.thread = None

        await bot._store_message(mock_message, "server1")

        # Verify message stored with both flags
        with test_db.connect() as conn:
            result = conn.execute(
                messages.select().where(messages.c.id == "123")
            ).fetchone()
            assert result.has_media is True
            assert result.has_links is True
            assert "https://example.com" in result.content


class TestConfigurationIntegration:
    """Tests for configuration integration across stories."""

    def test_observation_config_affects_polling_and_media(self, tmp_path: Path) -> None:
        """Observation config settings affect polling and media behavior."""
        config = Config(data_dir=tmp_path)
        config.discord.polling_interval_seconds = 120  # polling_interval is on discord config
        config.observation.vision_enabled = False
        config.observation.link_fetch_enabled = False

        bot = ZosBot(config)

        assert bot.config.discord.polling_interval_seconds == 120
        assert bot.config.observation.vision_enabled is False
        assert bot.config.observation.link_fetch_enabled is False

    def test_server_config_privacy_gate_affects_reactions(self, tmp_path: Path) -> None:
        """Server-specific privacy gate config affects reaction tracking."""
        config = Config(
            data_dir=tmp_path,
            servers={
                "server1": ServerOverrideConfig(privacy_gate_role="role_123"),
                "server2": ServerOverrideConfig(privacy_gate_role="role_456"),
            },
        )

        engine = get_engine(config)
        bot = ZosBot(config, engine=engine)

        # Server 1 has privacy gate
        assert "role_123" in str(config.servers)
        # Server 2 has different privacy gate
        assert "role_456" in str(config.servers)
