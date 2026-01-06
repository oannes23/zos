"""Abstract LLM provider interface and core types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MessageRole(str, Enum):
    """Role of a message in a conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class Message:
    """A single message in a conversation."""

    role: MessageRole
    content: str


@dataclass(frozen=True)
class LLMResponse:
    """Response from an LLM provider."""

    content: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str  # "stop", "length", "content_filter", etc.
    model: str  # Actual model used (may differ from requested)
    raw_response: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        """Total tokens used (prompt + completion)."""
        return self.prompt_tokens + self.completion_tokens


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g., 'openai', 'anthropic').

        Returns:
            Provider identifier string.
        """
        ...

    @property
    @abstractmethod
    def default_model(self) -> str:
        """Default model for this provider.

        Returns:
            Model identifier string.
        """
        ...

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a completion from the LLM.

        Args:
            messages: List of conversation messages.
            model: Model to use (None = provider default).
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature (0.0 - 2.0).
            **kwargs: Provider-specific options.

        Returns:
            LLMResponse with content and token counts.

        Raises:
            LLMError: On provider errors.
        """
        ...

    @abstractmethod
    def estimate_cost(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> float | None:
        """Estimate cost in USD for a call.

        Args:
            model: Model identifier.
            prompt_tokens: Input token count.
            completion_tokens: Output token count.

        Returns:
            Estimated cost in USD, or None if unknown.
        """
        ...

    def is_available(self) -> bool:
        """Check if this provider is configured and available.

        Override in subclasses that require configuration (e.g., API keys).

        Returns:
            True if provider can be used.
        """
        return True

    async def close(self) -> None:
        """Close any open connections.

        Override in subclasses that maintain persistent connections.
        """
        return
