"""Conversation module for interactive Discord responses.

This module handles Zos's conversational behavior:
- Trigger detection (mentions, replies, keywords, DMs)
- Rate limiting per channel
- Context assembly for response generation
- Response generation via LLM
"""

from zos.conversation.handler import ConversationHandler
from zos.conversation.rate_limiter import RateLimiter
from zos.conversation.triggers import TriggerDetector, TriggerResult, TriggerType

__all__ = [
    "ConversationHandler",
    "RateLimiter",
    "TriggerDetector",
    "TriggerResult",
    "TriggerType",
]
