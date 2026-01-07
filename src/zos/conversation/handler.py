"""Main conversation handler that orchestrates response logic.

Coordinates:
- Trigger detection
- Output channel validation
- Rate limiting
- Response generation
- Message sending
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from zos.conversation.rate_limiter import RateLimiter, RateLimitResult
from zos.conversation.responder import Responder, ResponseResult
from zos.conversation.triggers import TriggerDetector, TriggerResult, TriggerType
from zos.logging import get_logger

if TYPE_CHECKING:
    import discord

    from zos.config import ConversationConfig
    from zos.db import Database
    from zos.discord.repository import MessageRepository
    from zos.insights.repository import InsightRepository
    from zos.llm.client import LLMClient

logger = get_logger("conversation.handler")


@dataclass(frozen=True)
class HandleResult:
    """Result of handling a message.

    Attributes:
        responded: Whether a response was sent.
        trigger_result: Trigger detection result.
        rate_limit_result: Rate limit check result (if checked).
        response_result: Response generation result (if generated).
        error: Any error that occurred.
    """

    responded: bool
    trigger_result: TriggerResult | None = None
    rate_limit_result: RateLimitResult | None = None
    response_result: ResponseResult | None = None
    error: str = ""

    @classmethod
    def no_response(
        cls,
        trigger_result: TriggerResult | None = None,
        reason: str = "",
    ) -> HandleResult:
        """Create a no-response result."""
        return cls(
            responded=False,
            trigger_result=trigger_result,
            error=reason,
        )

    @classmethod
    def rate_limited(
        cls,
        trigger_result: TriggerResult,
        rate_limit_result: RateLimitResult,
    ) -> HandleResult:
        """Create a rate-limited result."""
        return cls(
            responded=False,
            trigger_result=trigger_result,
            rate_limit_result=rate_limit_result,
        )

    @classmethod
    def success(
        cls,
        trigger_result: TriggerResult,
        rate_limit_result: RateLimitResult,
        response_result: ResponseResult,
    ) -> HandleResult:
        """Create a successful response result."""
        return cls(
            responded=True,
            trigger_result=trigger_result,
            rate_limit_result=rate_limit_result,
            response_result=response_result,
        )

    @classmethod
    def failed(
        cls,
        trigger_result: TriggerResult,
        response_result: ResponseResult,
    ) -> HandleResult:
        """Create a failed response result."""
        return cls(
            responded=False,
            trigger_result=trigger_result,
            response_result=response_result,
            error=response_result.error,
        )

    @classmethod
    def dm_declined(
        cls,
        trigger_result: TriggerResult | None = None,
    ) -> HandleResult:
        """Create a result for declined DM due to missing opt-in role."""
        return cls(
            responded=False,
            trigger_result=trigger_result,
            error="DM declined: user missing opt-in role",
        )


class ConversationHandler:
    """Main handler for conversational interactions.

    Orchestrates the full response pipeline:
    1. Check if message triggers a response
    2. Validate output channel permissions
    3. Check rate limits
    4. Generate response via LLM
    5. Send response to Discord
    """

    def __init__(
        self,
        config: ConversationConfig,
        output_channels: list[int],
        bot_user_id: int,
        db: Database,
        message_repo: MessageRepository,
        insight_repo: InsightRepository,
        llm_client: LLMClient,
    ) -> None:
        """Initialize the conversation handler.

        Args:
            config: Conversation configuration.
            output_channels: List of channel IDs where Zos can respond.
            bot_user_id: The bot's Discord user ID.
            db: Database connection.
            message_repo: Message repository.
            insight_repo: Insight repository.
            llm_client: LLM client for response generation.
        """
        self.config = config
        self.output_channels = output_channels
        self.bot_user_id = bot_user_id

        # Initialize components
        self.trigger_detector = TriggerDetector(config.triggers, bot_user_id)
        self.rate_limiter = RateLimiter(config.rate_limit)
        self.responder = Responder(
            config,
            db,
            message_repo,
            insight_repo,
            llm_client,
        )

    async def handle_message(self, message: discord.Message) -> HandleResult:
        """Handle an incoming message and potentially respond.

        Args:
            message: The Discord message to handle.

        Returns:
            HandleResult indicating what happened.
        """
        # Check if conversation is enabled
        if not self.config.enabled:
            return HandleResult.no_response(reason="conversation disabled")

        # Check for trigger
        trigger_result = self.trigger_detector.check(message)
        if not trigger_result.triggered:
            return HandleResult.no_response(
                trigger_result=trigger_result,
                reason=trigger_result.context,
            )

        # Check output channel permission (DMs always allowed)
        if message.guild is not None and not self.trigger_detector.is_output_channel(
            message.channel.id, self.output_channels
        ):
            logger.debug(
                f"Trigger in non-output channel {message.channel.id}, "
                f"not responding"
            )
            return HandleResult.no_response(
                trigger_result=trigger_result,
                reason="channel not in output_channels",
            )

        # Check rate limit
        rate_limit_result = self.rate_limiter.check(message.channel.id)
        if not rate_limit_result.allowed:
            logger.debug(
                f"Rate limited in channel {message.channel.id}: "
                f"{rate_limit_result.reason}"
            )
            return HandleResult.rate_limited(trigger_result, rate_limit_result)

        # Generate response
        trigger_type_str = (
            trigger_result.trigger_type.value
            if trigger_result.trigger_type
            else "unknown"
        )
        logger.info(
            f"Generating response for {trigger_type_str} "
            f"trigger from {message.author}"
        )
        response_result = await self.responder.generate_response(
            message, trigger_result
        )

        if not response_result.success:
            logger.error(f"Response generation failed: {response_result.error}")
            return HandleResult.failed(trigger_result, response_result)

        # Send the response
        try:
            await self._send_response(message, response_result)
            # Record the response for rate limiting
            self.rate_limiter.record_response(message.channel.id)

            logger.info(
                f"Sent response in channel {message.channel.id}: "
                f"{len(response_result.content)} chars"
            )

            return HandleResult.success(
                trigger_result,
                rate_limit_result,
                response_result,
            )

        except Exception as e:
            logger.error(f"Failed to send response: {e}")
            return HandleResult.no_response(
                trigger_result=trigger_result,
                reason=f"send failed: {e}",
            )

    async def _send_response(
        self,
        message: discord.Message,
        response_result: ResponseResult,
    ) -> None:
        """Send the response to Discord.

        Args:
            message: The original message (for reply threading).
            response_result: The generated response.
        """
        content = response_result.content

        # Decide whether to reply or send a new message
        # Reply to mentions and replies, regular message otherwise
        trigger_type = None
        if (
            hasattr(message, "_trigger_type")
            and message._trigger_type in (TriggerType.MENTION, TriggerType.REPLY)
        ):
            trigger_type = message._trigger_type

        # For mentions and replies, use reply
        if trigger_type in (TriggerType.MENTION, TriggerType.REPLY):
            await message.reply(content, mention_author=False)
        else:
            # For DMs or keywords, just send to the channel
            await message.channel.send(content)

    def get_rate_limit_state(self, channel_id: int) -> dict[str, int | float | None]:
        """Get rate limit state for a channel.

        Args:
            channel_id: The Discord channel ID.

        Returns:
            Dict with rate limit information.
        """
        return self.rate_limiter.get_channel_state(channel_id)

    def reset_rate_limit(self, channel_id: int | None = None) -> None:
        """Reset rate limit state.

        Args:
            channel_id: Channel to reset, or None for all channels.
        """
        if channel_id is None:
            self.rate_limiter.reset_all()
        else:
            self.rate_limiter.reset_channel(channel_id)
