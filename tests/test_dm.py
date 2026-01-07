"""Tests for DM handling and opt-in verification."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zos.config import (
    ConversationConfig,
    DiscordConfig,
    RateLimitConfig,
    ResponseConfig,
    TriggerConfig,
)


# --- DM Opt-In Check Tests ---


class TestDMOptInCheck:
    """Tests for DM opt-in verification."""

    def create_mock_client(
        self,
        tracking_role: str | None = None,
        guilds: list[MagicMock] | None = None,
    ) -> MagicMock:
        """Create a mock Discord client with configured role."""
        from zos.discord.client import ZosDiscordClient

        config = DiscordConfig(
            token="test-token",
            tracking_opt_in_role=tracking_role,
        )

        # Create a mock client without calling __init__
        client = MagicMock(spec=ZosDiscordClient)
        client.config = config
        client.guilds = guilds or []

        # Bind the actual method to the mock
        from zos.discord.client import ZosDiscordClient as RealClient

        client._is_dm_opted_in = lambda user: RealClient._is_dm_opted_in(client, user)

        return client

    def test_user_with_role_is_opted_in(self):
        """Test that a user with the tracking role is opted in."""
        # Create a mock guild
        guild = MagicMock()
        guild.id = 12345

        # Create a mock member with the required role
        role = MagicMock()
        role.name = "Zos Participant"
        member = MagicMock()
        member.roles = [role]

        # Guild.get_member returns the member
        guild.get_member = MagicMock(return_value=member)

        # Create client with the role configured
        client = self.create_mock_client(
            tracking_role="Zos Participant",
            guilds=[guild],
        )

        # Create a user
        user = MagicMock()
        user.id = 99999

        result = client._is_dm_opted_in(user)
        assert result is True

    def test_user_without_role_is_not_opted_in(self):
        """Test that a user without the tracking role is not opted in."""
        # Create a mock guild
        guild = MagicMock()
        guild.id = 12345

        # Create a mock member without the required role
        other_role = MagicMock()
        other_role.name = "Other Role"
        member = MagicMock()
        member.roles = [other_role]

        # Guild.get_member returns the member
        guild.get_member = MagicMock(return_value=member)

        # Create client with the role configured
        client = self.create_mock_client(
            tracking_role="Zos Participant",
            guilds=[guild],
        )

        # Create a user
        user = MagicMock()
        user.id = 99999

        result = client._is_dm_opted_in(user)
        assert result is False

    def test_no_role_configured_all_users_opted_in(self):
        """Test that all users are opted in when no role is configured."""
        # Create client with no role configured
        client = self.create_mock_client(tracking_role=None)

        # Create a user
        user = MagicMock()
        user.id = 99999

        result = client._is_dm_opted_in(user)
        assert result is True

    def test_user_in_multiple_guilds_role_in_one(self):
        """Test that a user with role in one of multiple shared guilds is opted in."""
        # Create first guild where user doesn't have role
        guild1 = MagicMock()
        guild1.id = 11111
        member1 = MagicMock()
        member1.roles = []
        guild1.get_member = MagicMock(return_value=member1)

        # Create second guild where user has the role
        guild2 = MagicMock()
        guild2.id = 22222
        role = MagicMock()
        role.name = "Zos Participant"
        member2 = MagicMock()
        member2.roles = [role]
        guild2.get_member = MagicMock(return_value=member2)

        # Create client with both guilds
        client = self.create_mock_client(
            tracking_role="Zos Participant",
            guilds=[guild1, guild2],
        )

        # Create a user
        user = MagicMock()
        user.id = 99999

        result = client._is_dm_opted_in(user)
        assert result is True

    def test_user_not_in_any_guild_is_not_opted_in(self):
        """Test that a user not in any shared guild is not opted in."""
        # Create a guild where user is not a member
        guild = MagicMock()
        guild.id = 12345
        guild.get_member = MagicMock(return_value=None)

        # Create client with role configured
        client = self.create_mock_client(
            tracking_role="Zos Participant",
            guilds=[guild],
        )

        # Create a user
        user = MagicMock()
        user.id = 99999

        result = client._is_dm_opted_in(user)
        assert result is False


# --- DM Conversation Tests ---


class TestDMConversation:
    """Tests for DM conversation handling."""

    @pytest.fixture
    def conversation_config(self) -> ConversationConfig:
        """Create a test conversation configuration."""
        return ConversationConfig(
            enabled=True,
            triggers=TriggerConfig(
                respond_to_mentions=True,
                respond_to_replies=True,
                respond_to_dm=True,
            ),
            rate_limit=RateLimitConfig(
                enabled=True,
                max_responses_per_channel=5,
                window_seconds=60,
                cooldown_seconds=0,
            ),
            response=ResponseConfig(
                max_length=2000,
                max_tokens=500,
                context_messages=20,
                dm_context_messages=30,
            ),
        )

    @pytest.fixture
    def mock_dm_message(self) -> MagicMock:
        """Create a mock DM message (no guild)."""
        message = MagicMock()
        message.id = 1234567890
        message.content = "Hello Zos!"
        message.author = MagicMock()
        message.author.id = 99999
        message.author.bot = False
        message.author.display_name = "TestUser"
        message.channel = MagicMock()
        message.channel.id = 88888
        message.channel.name = "DM"
        message.channel.send = AsyncMock()
        message.guild = None  # DM indicator
        message.mentions = []
        message.reference = None
        return message

    @pytest.mark.asyncio
    async def test_dm_triggers_response_for_opted_user(
        self,
        conversation_config: ConversationConfig,
        mock_dm_message: MagicMock,
        test_db,
    ):
        """Test that DM triggers a response for an opted-in user."""
        from zos.conversation.handler import ConversationHandler
        from zos.conversation.triggers import TriggerType
        from zos.discord.repository import MessageRepository
        from zos.insights.repository import InsightRepository

        # Create mock LLM client
        mock_llm_client = MagicMock()
        response = MagicMock()
        response.content = "Hello! How can I help you?"
        response.prompt_tokens = 100
        response.completion_tokens = 50
        mock_llm_client.complete = AsyncMock(return_value=response)

        handler = ConversationHandler(
            config=conversation_config,
            output_channels=[],  # Empty, DMs bypass this check
            bot_user_id=12345,
            db=test_db,
            message_repo=MessageRepository(test_db),
            insight_repo=InsightRepository(test_db),
            llm_client=mock_llm_client,
        )

        result = await handler.handle_message(mock_dm_message)

        assert result.responded is True
        assert result.trigger_result is not None
        assert result.trigger_result.trigger_type == TriggerType.DM

    @pytest.mark.asyncio
    async def test_dm_context_uses_dm_context_messages(
        self,
        conversation_config: ConversationConfig,
        mock_dm_message: MagicMock,
        test_db,
    ):
        """Test that DM conversations use dm_context_messages setting."""
        from zos.conversation.responder import Responder
        from zos.conversation.triggers import TriggerResult, TriggerType
        from zos.discord.repository import MessageRepository
        from zos.insights.repository import InsightRepository

        # Set different values for channel and DM context
        conversation_config.response.context_messages = 10
        conversation_config.response.dm_context_messages = 50

        mock_llm_client = MagicMock()
        response = MagicMock()
        response.content = "Hello!"
        response.prompt_tokens = 100
        response.completion_tokens = 50
        mock_llm_client.complete = AsyncMock(return_value=response)

        responder = Responder(
            config=conversation_config,
            db=test_db,
            message_repo=MessageRepository(test_db),
            insight_repo=InsightRepository(test_db),
            llm_client=mock_llm_client,
        )

        # Create a DM trigger result
        trigger_result = TriggerResult.triggered_by(
            TriggerType.DM,
            context="DM message",
        )

        # Mock _fetch_recent_messages to capture the limit parameter
        original_fetch = responder._fetch_recent_messages
        calls = []

        def mock_fetch(channel_id: int, limit: int = 20):
            calls.append({"channel_id": channel_id, "limit": limit})
            return []

        responder._fetch_recent_messages = mock_fetch

        # Assemble context
        await responder._assemble_context(mock_dm_message, trigger_result)

        # Verify dm_context_messages was used
        assert len(calls) == 1
        assert calls[0]["limit"] == 50  # dm_context_messages value


# --- DM Decline Message Tests ---


class TestDMDeclineMessage:
    """Tests for DM decline message functionality."""

    @pytest.mark.asyncio
    async def test_decline_message_sent(self):
        """Test that decline message is sent to non-opted users."""
        from zos.discord.client import ZosDiscordClient

        # Create a mock message
        message = MagicMock()
        message.author = MagicMock()
        message.author.id = 99999
        message.channel = MagicMock()
        message.channel.send = AsyncMock()
        message.guild = None

        # Create a mock client
        config = DiscordConfig(
            token="test-token",
            tracking_opt_in_role="Zos Participant",
        )

        # Create mock client instance manually
        client = MagicMock(spec=ZosDiscordClient)
        client.config = config

        # Call the actual _send_dm_decline method
        with patch("zos.discord.client.get_config") as mock_get_config:
            mock_config = MagicMock()
            mock_config.conversation.dm_decline_message = (
                "To chat with me, please get the {role_name} role."
            )
            mock_get_config.return_value = mock_config

            await ZosDiscordClient._send_dm_decline(client, message)

        # Verify message was sent
        message.channel.send.assert_called_once()
        sent_message = message.channel.send.call_args[0][0]
        assert "Zos Participant" in sent_message

    def test_decline_message_role_placeholder_replaced(self):
        """Test that {role_name} placeholder is replaced correctly."""
        from zos.config import ConversationConfig

        config = ConversationConfig(
            dm_decline_message="Please get the {role_name} role to chat.",
        )

        role_name = "Test Role"
        formatted = config.dm_decline_message.replace("{role_name}", role_name)

        assert "{role_name}" not in formatted
        assert "Test Role" in formatted


# --- HandleResult Tests ---


class TestHandleResultDMDeclined:
    """Tests for HandleResult.dm_declined factory method."""

    def test_dm_declined_result(self):
        """Test creating a DM declined result."""
        from zos.conversation.handler import HandleResult
        from zos.conversation.triggers import TriggerResult, TriggerType

        trigger = TriggerResult.triggered_by(TriggerType.DM)
        result = HandleResult.dm_declined(trigger)

        assert result.responded is False
        assert result.trigger_result == trigger
        assert "opt-in" in result.error.lower()

    def test_dm_declined_result_no_trigger(self):
        """Test creating a DM declined result without trigger."""
        from zos.conversation.handler import HandleResult

        result = HandleResult.dm_declined()

        assert result.responded is False
        assert result.trigger_result is None
        assert "opt-in" in result.error.lower()
