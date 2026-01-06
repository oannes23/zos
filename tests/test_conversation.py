"""Tests for the conversation module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zos.config import (
    ConversationConfig,
    RateLimitConfig,
    ResponseConfig,
    TriggerConfig,
)
from zos.conversation.rate_limiter import RateLimiter, RateLimitResult
from zos.conversation.triggers import TriggerDetector, TriggerResult, TriggerType


# --- Trigger Detection Tests ---


class TestTriggerDetector:
    """Tests for trigger detection."""

    @pytest.fixture
    def trigger_config(self) -> TriggerConfig:
        """Default trigger configuration."""
        return TriggerConfig(
            respond_to_mentions=True,
            respond_to_replies=True,
            respond_to_dm=True,
            respond_to_keywords=False,
            keywords=[],
        )

    @pytest.fixture
    def detector(self, trigger_config: TriggerConfig) -> TriggerDetector:
        """Create a trigger detector."""
        return TriggerDetector(trigger_config, bot_user_id=12345)

    def test_ignores_own_messages(self, detector: TriggerDetector):
        """Test that bot's own messages are not triggered."""
        message = MagicMock()
        message.author.id = 12345  # Same as bot_user_id
        message.author.bot = False

        result = detector.check(message)
        assert result.triggered is False
        assert result.context == "own message"

    def test_ignores_bot_messages(self, detector: TriggerDetector):
        """Test that other bot messages are not triggered."""
        message = MagicMock()
        message.author.id = 99999
        message.author.bot = True

        result = detector.check(message)
        assert result.triggered is False
        assert result.context == "bot message"

    def test_triggers_on_dm(self, detector: TriggerDetector):
        """Test that DMs trigger a response."""
        message = MagicMock()
        message.author.id = 99999
        message.author.bot = False
        message.guild = None  # DM

        result = detector.check(message)
        assert result.triggered is True
        assert result.trigger_type == TriggerType.DM

    def test_dm_disabled(self, trigger_config: TriggerConfig):
        """Test that DMs can be disabled."""
        trigger_config.respond_to_dm = False
        detector = TriggerDetector(trigger_config, bot_user_id=12345)

        message = MagicMock()
        message.author.id = 99999
        message.author.bot = False
        message.guild = None

        result = detector.check(message)
        assert result.triggered is False
        assert result.context == "DM responses disabled"

    def test_triggers_on_mention(self, detector: TriggerDetector):
        """Test that @mentions trigger a response."""
        message = MagicMock()
        message.author.id = 99999
        message.author.bot = False
        message.guild = MagicMock()

        bot_user = MagicMock()
        bot_user.id = 12345
        message.mentions = [bot_user]

        result = detector.check(message)
        assert result.triggered is True
        assert result.trigger_type == TriggerType.MENTION

    def test_mention_disabled(self, trigger_config: TriggerConfig):
        """Test that mentions can be disabled."""
        trigger_config.respond_to_mentions = False
        detector = TriggerDetector(trigger_config, bot_user_id=12345)

        message = MagicMock()
        message.author.id = 99999
        message.author.bot = False
        message.guild = MagicMock()

        bot_user = MagicMock()
        bot_user.id = 12345
        message.mentions = [bot_user]
        message.reference = None

        result = detector.check(message)
        assert result.triggered is False

    def test_triggers_on_reply(self, detector: TriggerDetector):
        """Test that replies to bot messages trigger a response."""
        message = MagicMock()
        message.author.id = 99999
        message.author.bot = False
        message.guild = MagicMock()
        message.mentions = []

        # Set up reply reference
        ref = MagicMock()
        ref.resolved = MagicMock()
        ref.resolved.author.id = 12345  # Reply to bot
        message.reference = ref

        result = detector.check(message)
        assert result.triggered is True
        assert result.trigger_type == TriggerType.REPLY

    def test_no_trigger_on_other_reply(self, detector: TriggerDetector):
        """Test that replies to other users don't trigger."""
        message = MagicMock()
        message.author.id = 99999
        message.author.bot = False
        message.guild = MagicMock()
        message.mentions = []

        ref = MagicMock()
        ref.resolved = MagicMock()
        ref.resolved.author.id = 88888  # Reply to someone else
        message.reference = ref

        result = detector.check(message)
        assert result.triggered is False

    def test_triggers_on_keyword(self):
        """Test keyword pattern matching."""
        config = TriggerConfig(
            respond_to_mentions=False,
            respond_to_replies=False,
            respond_to_dm=False,
            respond_to_keywords=True,
            keywords=["hello.*bot", "hey zos"],
        )
        detector = TriggerDetector(config, bot_user_id=12345)

        message = MagicMock()
        message.author.id = 99999
        message.author.bot = False
        message.guild = MagicMock()
        message.mentions = []
        message.reference = None
        message.content = "Hello my bot friend!"

        result = detector.check(message)
        assert result.triggered is True
        assert result.trigger_type == TriggerType.KEYWORD
        assert result.matched_keyword == "hello.*bot"

    def test_keyword_case_insensitive(self):
        """Test that keyword matching is case-insensitive."""
        config = TriggerConfig(
            respond_to_mentions=False,
            respond_to_replies=False,
            respond_to_dm=False,
            respond_to_keywords=True,
            keywords=["HEY ZOS"],
        )
        detector = TriggerDetector(config, bot_user_id=12345)

        message = MagicMock()
        message.author.id = 99999
        message.author.bot = False
        message.guild = MagicMock()
        message.mentions = []
        message.reference = None
        message.content = "hey zos, what's up?"

        result = detector.check(message)
        assert result.triggered is True

    def test_no_trigger_when_no_match(self, detector: TriggerDetector):
        """Test that no trigger fires for normal messages."""
        message = MagicMock()
        message.author.id = 99999
        message.author.bot = False
        message.guild = MagicMock()
        message.mentions = []
        message.reference = None
        message.content = "just a regular message"

        result = detector.check(message)
        assert result.triggered is False
        assert result.context == "no trigger matched"

    def test_output_channel_check(self, detector: TriggerDetector):
        """Test output channel validation."""
        assert detector.is_output_channel(123, [123, 456]) is True
        assert detector.is_output_channel(789, [123, 456]) is False
        assert detector.is_output_channel(123, []) is True  # Empty = all allowed


# --- Rate Limiter Tests ---


class TestRateLimiter:
    """Tests for rate limiting."""

    @pytest.fixture
    def rate_config(self) -> RateLimitConfig:
        """Default rate limit configuration."""
        return RateLimitConfig(
            enabled=True,
            max_responses_per_channel=3,
            window_seconds=60,
            cooldown_seconds=0,  # Disable cooldown for these tests
        )

    @pytest.fixture
    def rate_limiter(self, rate_config: RateLimitConfig) -> RateLimiter:
        """Create a rate limiter."""
        return RateLimiter(rate_config)

    def test_allows_first_response(self, rate_limiter: RateLimiter):
        """Test that first response is allowed."""
        result = rate_limiter.check(channel_id=123)
        assert result.allowed is True

    def test_allows_multiple_responses_within_limit(self, rate_limiter: RateLimiter):
        """Test that responses within limit are allowed."""
        for _ in range(3):
            result = rate_limiter.check(channel_id=123)
            assert result.allowed is True
            rate_limiter.record_response(123)

    def test_blocks_after_limit_exceeded(self, rate_limiter: RateLimiter):
        """Test that responses are blocked after limit is reached."""
        for _ in range(3):
            rate_limiter.record_response(123)

        result = rate_limiter.check(channel_id=123)
        assert result.allowed is False
        assert "rate limit" in result.reason

    def test_cooldown_enforcement(self):
        """Test cooldown between responses."""
        config = RateLimitConfig(
            enabled=True,
            max_responses_per_channel=5,
            window_seconds=60,
            cooldown_seconds=5,  # Enable cooldown for this test
        )
        rate_limiter = RateLimiter(config)
        rate_limiter.record_response(123)

        # Immediately after, should be in cooldown
        result = rate_limiter.check(channel_id=123)
        assert result.allowed is False
        assert "cooldown" in result.reason
        assert result.retry_after_seconds > 0

    def test_disabled_rate_limiting(self, rate_config: RateLimitConfig):
        """Test that disabled rate limiting allows all."""
        rate_config.enabled = False
        limiter = RateLimiter(rate_config)

        # Record many responses
        for _ in range(100):
            limiter.record_response(123)

        result = limiter.check(channel_id=123)
        assert result.allowed is True

    def test_separate_channels(self, rate_limiter: RateLimiter):
        """Test that channels have separate limits."""
        for _ in range(3):
            rate_limiter.record_response(123)

        # Channel 123 should be limited
        result = rate_limiter.check(channel_id=123)
        assert result.allowed is False

        # Channel 456 should still be allowed
        result = rate_limiter.check(channel_id=456)
        assert result.allowed is True

    def test_reset_channel(self, rate_limiter: RateLimiter):
        """Test resetting a channel's rate limit state."""
        for _ in range(3):
            rate_limiter.record_response(123)

        rate_limiter.reset_channel(123)

        result = rate_limiter.check(channel_id=123)
        assert result.allowed is True

    def test_reset_all(self, rate_limiter: RateLimiter):
        """Test resetting all rate limit state."""
        rate_limiter.record_response(123)
        rate_limiter.record_response(456)

        rate_limiter.reset_all()

        result = rate_limiter.check(channel_id=123)
        assert result.allowed is True
        result = rate_limiter.check(channel_id=456)
        assert result.allowed is True

    def test_get_channel_state(self, rate_limiter: RateLimiter):
        """Test getting channel state for debugging."""
        rate_limiter.record_response(123)
        rate_limiter.record_response(123)

        state = rate_limiter.get_channel_state(123)
        assert state["response_count"] == 2
        assert state["max_responses"] == 3
        assert state["window_seconds"] == 60


# --- TriggerResult Tests ---


class TestTriggerResult:
    """Tests for TriggerResult dataclass."""

    def test_no_trigger(self):
        """Test creating a no-trigger result."""
        result = TriggerResult.no_trigger("test reason")
        assert result.triggered is False
        assert result.trigger_type is None
        assert result.context == "test reason"

    def test_triggered_by(self):
        """Test creating a triggered result."""
        result = TriggerResult.triggered_by(
            TriggerType.MENTION,
            context="mentioned by user"
        )
        assert result.triggered is True
        assert result.trigger_type == TriggerType.MENTION
        assert result.context == "mentioned by user"

    def test_triggered_with_keyword(self):
        """Test triggered result with keyword match."""
        result = TriggerResult.triggered_by(
            TriggerType.KEYWORD,
            matched_keyword="hello",
            context="keyword match"
        )
        assert result.triggered is True
        assert result.trigger_type == TriggerType.KEYWORD
        assert result.matched_keyword == "hello"


# --- RateLimitResult Tests ---


class TestRateLimitResult:
    """Tests for RateLimitResult dataclass."""

    def test_allow(self):
        """Test creating an allowed result."""
        result = RateLimitResult.allow()
        assert result.allowed is True
        assert result.reason == ""

    def test_deny(self):
        """Test creating a denied result."""
        result = RateLimitResult.deny("test reason", retry_after=5.0)
        assert result.allowed is False
        assert result.reason == "test reason"
        assert result.retry_after_seconds == 5.0


# --- Integration Tests ---


class TestConversationHandler:
    """Tests for the conversation handler integration."""

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
                cooldown_seconds=1,
            ),
            response=ResponseConfig(
                max_length=2000,
                max_tokens=500,
            ),
        )

    @pytest.fixture
    def mock_db(self, test_db):
        """Get the test database."""
        return test_db

    @pytest.fixture
    def mock_message_repo(self, mock_db):
        """Create a mock message repository."""
        from zos.discord.repository import MessageRepository
        return MessageRepository(mock_db)

    @pytest.fixture
    def mock_insight_repo(self, mock_db):
        """Create a mock insight repository."""
        from zos.insights.repository import InsightRepository
        return InsightRepository(mock_db)

    @pytest.fixture
    def mock_llm_client(self):
        """Create a mock LLM client."""
        client = MagicMock()
        response = MagicMock()
        response.content = "Hello! How can I help you today?"
        response.prompt_tokens = 100
        response.completion_tokens = 50
        client.complete = AsyncMock(return_value=response)
        return client

    @pytest.mark.asyncio
    async def test_handler_responds_to_mention(
        self,
        conversation_config: ConversationConfig,
        mock_db,
        mock_message_repo,
        mock_insight_repo,
        mock_llm_client,
    ):
        """Test that handler responds to mentions."""
        from zos.conversation.handler import ConversationHandler

        handler = ConversationHandler(
            config=conversation_config,
            output_channels=[123],
            bot_user_id=12345,
            db=mock_db,
            message_repo=mock_message_repo,
            insight_repo=mock_insight_repo,
            llm_client=mock_llm_client,
        )

        # Create a mock message mentioning the bot
        message = MagicMock()
        message.author.id = 99999
        message.author.bot = False
        message.author.display_name = "TestUser"
        message.guild = MagicMock()
        message.channel.id = 123
        message.channel.name = "test-channel"
        message.content = "Hey @Zos, how are you?"

        bot_user = MagicMock()
        bot_user.id = 12345
        message.mentions = [bot_user]
        message.reference = None

        # Mock the reply method
        message.reply = AsyncMock()
        message.channel.send = AsyncMock()

        result = await handler.handle_message(message)

        assert result.responded is True
        assert result.trigger_result.trigger_type == TriggerType.MENTION

    @pytest.mark.asyncio
    async def test_handler_respects_output_channels(
        self,
        conversation_config: ConversationConfig,
        mock_db,
        mock_message_repo,
        mock_insight_repo,
        mock_llm_client,
    ):
        """Test that handler only responds in output channels."""
        from zos.conversation.handler import ConversationHandler

        handler = ConversationHandler(
            config=conversation_config,
            output_channels=[123],  # Only channel 123
            bot_user_id=12345,
            db=mock_db,
            message_repo=mock_message_repo,
            insight_repo=mock_insight_repo,
            llm_client=mock_llm_client,
        )

        # Create a message in a non-output channel
        message = MagicMock()
        message.author.id = 99999
        message.author.bot = False
        message.guild = MagicMock()
        message.channel.id = 999  # Not in output_channels

        bot_user = MagicMock()
        bot_user.id = 12345
        message.mentions = [bot_user]

        result = await handler.handle_message(message)

        assert result.responded is False
        assert "channel not in output_channels" in result.error

    @pytest.mark.asyncio
    async def test_handler_rate_limits(
        self,
        conversation_config: ConversationConfig,
        mock_db,
        mock_message_repo,
        mock_insight_repo,
        mock_llm_client,
    ):
        """Test that handler respects rate limits."""
        from zos.conversation.handler import ConversationHandler

        conversation_config.rate_limit.max_responses_per_channel = 1
        conversation_config.rate_limit.cooldown_seconds = 0

        handler = ConversationHandler(
            config=conversation_config,
            output_channels=[123],
            bot_user_id=12345,
            db=mock_db,
            message_repo=mock_message_repo,
            insight_repo=mock_insight_repo,
            llm_client=mock_llm_client,
        )

        # Create a mention message
        def create_message():
            message = MagicMock()
            message.author.id = 99999
            message.author.bot = False
            message.author.display_name = "TestUser"
            message.guild = MagicMock()
            message.channel.id = 123
            message.channel.name = "test-channel"
            message.content = "Hey @Zos"

            bot_user = MagicMock()
            bot_user.id = 12345
            message.mentions = [bot_user]
            message.reference = None
            message.reply = AsyncMock()
            message.channel.send = AsyncMock()
            return message

        # First message should work
        result1 = await handler.handle_message(create_message())
        assert result1.responded is True

        # Second message should be rate limited
        result2 = await handler.handle_message(create_message())
        assert result2.responded is False
        assert result2.rate_limit_result is not None
        assert result2.rate_limit_result.allowed is False

    @pytest.mark.asyncio
    async def test_handler_disabled(
        self,
        conversation_config: ConversationConfig,
        mock_db,
        mock_message_repo,
        mock_insight_repo,
        mock_llm_client,
    ):
        """Test that disabled handler does not respond."""
        from zos.conversation.handler import ConversationHandler

        conversation_config.enabled = False

        handler = ConversationHandler(
            config=conversation_config,
            output_channels=[123],
            bot_user_id=12345,
            db=mock_db,
            message_repo=mock_message_repo,
            insight_repo=mock_insight_repo,
            llm_client=mock_llm_client,
        )

        message = MagicMock()
        message.author.id = 99999
        message.author.bot = False
        message.guild = MagicMock()
        message.channel.id = 123

        bot_user = MagicMock()
        bot_user.id = 12345
        message.mentions = [bot_user]

        result = await handler.handle_message(message)

        assert result.responded is False
        assert "conversation disabled" in result.error
