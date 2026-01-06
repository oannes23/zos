"""Response generation for conversations.

Handles:
- Context assembly from recent messages and insights
- Response generation via LLM
- Response formatting and length limiting
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from zos.conversation.triggers import TriggerResult, TriggerType
from zos.logging import get_logger

if TYPE_CHECKING:
    import discord

    from zos.config import ConversationConfig
    from zos.db import Database
    from zos.discord.repository import MessageRepository
    from zos.insights.repository import InsightRepository
    from zos.llm.client import LLMClient
    from zos.llm.provider import LLMResponse

logger = get_logger("conversation.responder")


@dataclass
class ConversationContext:
    """Context assembled for response generation.

    Attributes:
        messages: Recent messages from the channel.
        insights: Relevant insights about the channel/user.
        trigger_message: The message that triggered the response.
        trigger_result: The trigger detection result.
        channel_name: Name of the channel (for prompting).
        author_name: Name of the user who triggered (for prompting).
    """

    messages: list[dict[str, Any]]
    insights: list[dict[str, Any]]
    trigger_message: discord.Message
    trigger_result: TriggerResult
    channel_name: str
    author_name: str


@dataclass(frozen=True)
class ResponseResult:
    """Result of response generation.

    Attributes:
        success: Whether response was generated successfully.
        content: The response text (if successful).
        error: Error message (if failed).
        tokens_used: Tokens used for generation.
        run_id: Run ID for tracking.
    """

    success: bool
    content: str = ""
    error: str = ""
    tokens_used: int = 0
    run_id: str = ""

    @classmethod
    def ok(cls, content: str, tokens_used: int, run_id: str) -> ResponseResult:
        """Create a successful result."""
        return cls(
            success=True,
            content=content,
            tokens_used=tokens_used,
            run_id=run_id,
        )

    @classmethod
    def fail(cls, error: str) -> ResponseResult:
        """Create a failed result."""
        return cls(success=False, error=error)


class Responder:
    """Generates responses to conversation triggers.

    Assembles context from recent messages and insights,
    then generates a response using the configured LLM.
    """

    def __init__(
        self,
        config: ConversationConfig,
        db: Database,
        message_repo: MessageRepository,
        insight_repo: InsightRepository,
        llm_client: LLMClient,
    ) -> None:
        """Initialize the responder.

        Args:
            config: Conversation configuration.
            db: Database connection.
            message_repo: Repository for fetching messages.
            insight_repo: Repository for fetching insights.
            llm_client: LLM client for response generation.
        """
        self.config = config
        self.db = db
        self.message_repo = message_repo
        self.insight_repo = insight_repo
        self.llm_client = llm_client

    async def generate_response(
        self,
        message: discord.Message,
        trigger_result: TriggerResult,
    ) -> ResponseResult:
        """Generate a response to a triggered message.

        Args:
            message: The Discord message that triggered the response.
            trigger_result: The trigger detection result.

        Returns:
            ResponseResult with the generated response or error.
        """
        run_id = str(uuid.uuid4())

        try:
            # Assemble context
            context = await self._assemble_context(message, trigger_result)

            # Generate response
            response = await self._call_llm(context, run_id)

            # Format and truncate response
            content = self._format_response(response.content)

            tokens_used = response.prompt_tokens + response.completion_tokens
            logger.info(
                f"Generated response: {tokens_used} tokens, "
                f"{len(content)} chars, run_id={run_id}"
            )

            return ResponseResult.ok(content, tokens_used, run_id)

        except Exception as e:
            logger.error(f"Response generation failed: {e}")
            return ResponseResult.fail(str(e))

    async def _assemble_context(
        self,
        message: discord.Message,
        trigger_result: TriggerResult,
    ) -> ConversationContext:
        """Assemble context for response generation.

        Args:
            message: The triggering message.
            trigger_result: The trigger detection result.

        Returns:
            ConversationContext with messages and insights.
        """
        channel_id = message.channel.id
        channel_name = getattr(message.channel, "name", "DM")
        author_name = message.author.display_name

        # Fetch recent messages from the channel
        messages = self._fetch_recent_messages(
            channel_id,
            limit=self.config.response.context_messages,
        )

        # Fetch relevant insights (if enabled)
        insights: list[dict[str, Any]] = []
        if self.config.response.include_insights:
            insights = self._fetch_relevant_insights(channel_id, message.author.id)

        return ConversationContext(
            messages=messages,
            insights=insights,
            trigger_message=message,
            trigger_result=trigger_result,
            channel_name=channel_name,
            author_name=author_name,
        )

    def _fetch_recent_messages(
        self,
        channel_id: int,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Fetch recent messages from the channel.

        Args:
            channel_id: The channel to fetch from.
            limit: Maximum number of messages.

        Returns:
            List of message dicts.
        """
        # Use the message repository to fetch recent messages
        query = """
            SELECT message_id, author_id, author_name, content, created_at
            FROM messages
            WHERE channel_id = ?
            AND is_deleted = 0
            ORDER BY created_at DESC
            LIMIT ?
        """
        rows = self.db.execute(query, (channel_id, limit)).fetchall()

        # Reverse to get chronological order
        messages = []
        for row in reversed(rows):
            messages.append({
                "message_id": row["message_id"],
                "author_id": row["author_id"],
                "author_name": row["author_name"],
                "content": row["content"],
                "created_at": row["created_at"],
            })

        return messages

    def _fetch_relevant_insights(
        self,
        channel_id: int,
        user_id: int,
    ) -> list[dict[str, Any]]:
        """Fetch relevant insights for context.

        Args:
            channel_id: The channel ID.
            user_id: The user ID who triggered.

        Returns:
            List of insight dicts.
        """
        from zos.topics.topic_key import TopicKey

        # Fetch insights for the channel and user
        # Look for insights in the last 7 days
        since = datetime.now(UTC) - timedelta(days=7)

        channel_topic = TopicKey.channel(channel_id)
        user_topic = TopicKey.user(user_id)

        insights = []

        # Get channel insights
        try:
            channel_insights = self.insight_repo.get_insights(
                topic_key=channel_topic,
                since=since,
                limit=3,
            )
            for insight in channel_insights:
                insights.append({
                    "topic": insight.topic_key,
                    "summary": insight.summary,
                    "created_at": insight.created_at,
                })
        except Exception as e:
            logger.debug(f"Failed to fetch channel insights: {e}")

        # Get user insights
        try:
            user_insights = self.insight_repo.get_insights(
                topic_key=user_topic,
                since=since,
                limit=2,
            )
            for insight in user_insights:
                insights.append({
                    "topic": insight.topic_key,
                    "summary": insight.summary,
                    "created_at": insight.created_at,
                })
        except Exception as e:
            logger.debug(f"Failed to fetch user insights: {e}")

        return insights

    async def _call_llm(
        self,
        context: ConversationContext,
        run_id: str,
    ) -> LLMResponse:
        """Call the LLM to generate a response.

        Args:
            context: Assembled conversation context.
            run_id: Run ID for tracking.

        Returns:
            LLMResponse with the generated content.
        """
        from zos.llm.provider import Message, MessageRole

        # Build the prompt
        system_prompt = self._build_system_prompt(context)
        user_prompt = self._build_user_prompt(context)

        messages = [
            Message(role=MessageRole.SYSTEM, content=system_prompt),
            Message(role=MessageRole.USER, content=user_prompt),
        ]

        return await self.llm_client.complete(
            messages,
            run_id=run_id,
            layer="conversation",
            node="respond",
            provider=self.config.response.provider,
            model=self.config.response.model,
            max_tokens=self.config.response.max_tokens,
            temperature=self.config.response.temperature,
        )

    def _build_system_prompt(self, context: ConversationContext) -> str:
        """Build the system prompt for response generation.

        Args:
            context: The conversation context.

        Returns:
            System prompt string.
        """
        parts = [self.config.persona_prompt]

        # Add context about the trigger
        if context.trigger_result.trigger_type == TriggerType.DM:
            parts.append(
                "\nYou are in a private DM conversation. Be personable and direct."
            )
        elif context.trigger_result.trigger_type == TriggerType.MENTION:
            parts.append(
                "\nYou were directly mentioned. Address the user's question or comment."
            )
        elif context.trigger_result.trigger_type == TriggerType.REPLY:
            parts.append(
                "\nThe user replied to your previous message. Continue the conversation naturally."
            )

        # Add insights if available
        if context.insights:
            parts.append("\n\nRelevant context from your observations:")
            for insight in context.insights[:3]:
                parts.append(f"- {insight['summary']}")

        return "\n".join(parts)

    def _build_user_prompt(self, context: ConversationContext) -> str:
        """Build the user prompt with conversation history.

        Args:
            context: The conversation context.

        Returns:
            User prompt string.
        """
        parts = []

        # Add recent conversation context
        if context.messages:
            parts.append("Recent conversation in this channel:")
            for msg in context.messages[-10:]:  # Last 10 messages
                author = msg["author_name"]
                content = msg["content"]
                # Truncate long messages
                if len(content) > 200:
                    content = content[:200] + "..."
                parts.append(f"{author}: {content}")
            parts.append("")

        # Add the triggering message
        parts.append(f"Now {context.author_name} said: {context.trigger_message.content}")
        parts.append("")
        parts.append("Respond naturally and concisely.")

        return "\n".join(parts)

    def _format_response(self, content: str) -> str:
        """Format and truncate the response.

        Args:
            content: Raw LLM response.

        Returns:
            Formatted response within length limits.
        """
        # Clean up the response
        content = content.strip()

        # Truncate if too long (Discord limit is 2000)
        max_length = self.config.response.max_length
        if len(content) > max_length:
            # Try to truncate at a sentence boundary
            truncated = content[:max_length - 3]
            last_period = truncated.rfind(".")
            if last_period > max_length // 2:
                content = truncated[:last_period + 1]
            else:
                content = truncated + "..."

        return content
