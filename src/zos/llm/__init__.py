"""LLM abstraction layer for Zos.

This module provides a unified interface for calling multiple LLM providers
with cost tracking, retry logic, and prompt templating.

Note: LLMClient is not imported here to avoid circular imports.
Import it directly: `from zos.llm.client import LLMClient`
"""

from zos.llm.config import (
    AnthropicProviderConfig,
    GenericHTTPProviderConfig,
    LLMConfig,
    OllamaProviderConfig,
    OpenAIProviderConfig,
    RetryConfig,
)
from zos.llm.provider import LLMProvider, LLMResponse, Message, MessageRole

__all__ = [
    # Config
    "LLMConfig",
    "RetryConfig",
    "OpenAIProviderConfig",
    "AnthropicProviderConfig",
    "OllamaProviderConfig",
    "GenericHTTPProviderConfig",
    # Core types
    "LLMProvider",
    "LLMResponse",
    "Message",
    "MessageRole",
]
