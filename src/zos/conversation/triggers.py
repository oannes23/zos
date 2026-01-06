"""Trigger detection for conversation responses.

Detects when Zos should respond to a message based on:
- Direct @mentions
- Replies to Zos's messages
- Keyword patterns
- Direct messages
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from zos.logging import get_logger

if TYPE_CHECKING:
    import discord

    from zos.config import TriggerConfig

logger = get_logger("conversation.triggers")


class TriggerType(Enum):
    """Types of triggers that can activate a response."""

    MENTION = "mention"
    REPLY = "reply"
    KEYWORD = "keyword"
    DM = "dm"


@dataclass(frozen=True)
class TriggerResult:
    """Result of trigger detection.

    Attributes:
        triggered: Whether the message triggered a response.
        trigger_type: Type of trigger that fired (if any).
        matched_keyword: The keyword that matched (for keyword triggers).
        context: Additional context about the trigger.
    """

    triggered: bool
    trigger_type: TriggerType | None = None
    matched_keyword: str | None = None
    context: str = ""

    @classmethod
    def no_trigger(cls, reason: str = "") -> TriggerResult:
        """Create a non-triggered result."""
        return cls(triggered=False, context=reason)

    @classmethod
    def triggered_by(
        cls,
        trigger_type: TriggerType,
        matched_keyword: str | None = None,
        context: str = "",
    ) -> TriggerResult:
        """Create a triggered result."""
        return cls(
            triggered=True,
            trigger_type=trigger_type,
            matched_keyword=matched_keyword,
            context=context,
        )


class TriggerDetector:
    """Detects whether a message should trigger a response.

    Checks various trigger conditions in priority order:
    1. DM (if enabled)
    2. Direct mention
    3. Reply to Zos's message
    4. Keyword match
    """

    def __init__(self, config: TriggerConfig, bot_user_id: int) -> None:
        """Initialize the trigger detector.

        Args:
            config: Trigger configuration.
            bot_user_id: The bot's user ID (for mention detection).
        """
        self.config = config
        self.bot_user_id = bot_user_id
        self._compiled_keywords: list[re.Pattern[str]] | None = None

    @property
    def compiled_keywords(self) -> list[re.Pattern[str]]:
        """Get compiled keyword patterns (cached)."""
        if self._compiled_keywords is None:
            self._compiled_keywords = []
            for pattern in self.config.keywords:
                try:
                    self._compiled_keywords.append(
                        re.compile(pattern, re.IGNORECASE)
                    )
                except re.error as e:
                    logger.warning(f"Invalid keyword pattern '{pattern}': {e}")
        return self._compiled_keywords

    def check(self, message: discord.Message) -> TriggerResult:
        """Check if a message should trigger a response.

        Args:
            message: The Discord message to check.

        Returns:
            TriggerResult indicating whether and why to respond.
        """
        # Never respond to our own messages
        if message.author.id == self.bot_user_id:
            return TriggerResult.no_trigger("own message")

        # Never respond to bots
        if message.author.bot:
            return TriggerResult.no_trigger("bot message")

        # Check DM
        if message.guild is None:
            if self.config.respond_to_dm:
                logger.debug(f"Triggered by DM from {message.author}")
                return TriggerResult.triggered_by(
                    TriggerType.DM,
                    context=f"DM from {message.author}",
                )
            return TriggerResult.no_trigger("DM responses disabled")

        # Check direct mention
        if self.config.respond_to_mentions:
            for user in message.mentions:
                if user.id == self.bot_user_id:
                    logger.debug(f"Triggered by mention from {message.author}")
                    return TriggerResult.triggered_by(
                        TriggerType.MENTION,
                        context=f"mentioned by {message.author}",
                    )

        # Check reply to Zos
        if self.config.respond_to_replies and message.reference:
            # Try to get the referenced message author
            ref = message.reference.resolved
            if ref and hasattr(ref, "author") and ref.author.id == self.bot_user_id:
                logger.debug(f"Triggered by reply from {message.author}")
                return TriggerResult.triggered_by(
                    TriggerType.REPLY,
                    context=f"reply from {message.author}",
                )

        # Check keyword patterns
        if self.config.respond_to_keywords and self.compiled_keywords:
            for pattern in self.compiled_keywords:
                match = pattern.search(message.content)
                if match:
                    logger.debug(
                        f"Triggered by keyword '{pattern.pattern}' "
                        f"from {message.author}"
                    )
                    return TriggerResult.triggered_by(
                        TriggerType.KEYWORD,
                        matched_keyword=pattern.pattern,
                        context=f"keyword '{match.group()}' from {message.author}",
                    )

        return TriggerResult.no_trigger("no trigger matched")

    def is_output_channel(self, channel_id: int, output_channels: list[int]) -> bool:
        """Check if a channel is in the output channels list.

        Args:
            channel_id: The channel ID to check.
            output_channels: List of allowed output channel IDs.

        Returns:
            True if the channel is allowed for output.
        """
        # If no output channels configured, allow all (for DMs primarily)
        if not output_channels:
            return True
        return channel_id in output_channels
