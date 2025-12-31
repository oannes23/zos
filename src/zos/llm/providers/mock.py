"""Mock LLM provider for testing."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from zos.llm.provider import LLMProvider, LLMResponse, Message


@dataclass
class MockCall:
    """Record of a call to the mock provider."""

    messages: list[Message]
    model: str | None
    max_tokens: int
    temperature: float
    kwargs: dict[str, Any]


class MockProvider(LLMProvider):
    """Mock LLM provider for testing.

    Features:
    - Returns configurable default response
    - Tracks all calls for verification
    - Supports queuing specific responses
    - Can be configured to raise errors
    """

    def __init__(
        self,
        default_response: str = "This is a mock response.",
        default_model: str = "mock-model",
        prompt_tokens: int = 10,
        completion_tokens: int = 20,
    ) -> None:
        """Initialize the mock provider.

        Args:
            default_response: Default response content.
            default_model: Default model identifier.
            prompt_tokens: Default prompt token count.
            completion_tokens: Default completion token count.
        """
        self._default_response = default_response
        self._default_model = default_model
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens

        # Call tracking
        self.calls: list[MockCall] = []

        # Response queue (for specific responses)
        self._response_queue: list[LLMResponse | Exception] = []

        # Error to raise (if set)
        self._error: Exception | None = None

    @property
    def name(self) -> str:
        return "mock"

    @property
    def default_model(self) -> str:
        return self._default_model

    def set_error(self, error: Exception | None) -> None:
        """Set an error to raise on next call.

        Args:
            error: Exception to raise, or None to clear.
        """
        self._error = error

    def queue_response(
        self,
        content: str | None = None,
        *,
        response: LLMResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        """Queue a response or error for the next call.

        Args:
            content: Response content (creates default response with this content).
            response: Full LLMResponse object to return.
            error: Exception to raise instead of returning.
        """
        if error is not None:
            self._response_queue.append(error)
        elif response is not None:
            self._response_queue.append(response)
        elif content is not None:
            self._response_queue.append(
                LLMResponse(
                    content=content,
                    prompt_tokens=self._prompt_tokens,
                    completion_tokens=self._completion_tokens,
                    finish_reason="stop",
                    model=self._default_model,
                )
            )
        else:
            raise ValueError("Must provide content, response, or error")

    def queue_responses(self, responses: Sequence[str | LLMResponse | Exception]) -> None:
        """Queue multiple responses.

        Args:
            responses: Sequence of content strings, LLMResponse objects, or exceptions.
        """
        for r in responses:
            if isinstance(r, Exception):
                self.queue_response(error=r)
            elif isinstance(r, LLMResponse):
                self.queue_response(response=r)
            else:
                self.queue_response(content=r)

    def reset(self) -> None:
        """Reset the mock provider state."""
        self.calls.clear()
        self._response_queue.clear()
        self._error = None

    async def complete(
        self,
        messages: list[Message],
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a mock completion.

        Args:
            messages: List of conversation messages.
            model: Model to use (ignored in mock).
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.
            **kwargs: Additional options.

        Returns:
            Mock LLMResponse.

        Raises:
            Exception: If an error is set or queued.
        """
        # Record the call
        self.calls.append(
            MockCall(
                messages=list(messages),
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                kwargs=dict(kwargs),
            )
        )

        # Check for set error
        if self._error is not None:
            error = self._error
            self._error = None
            raise error

        # Check for queued response
        if self._response_queue:
            response = self._response_queue.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        # Return default response
        return LLMResponse(
            content=self._default_response,
            prompt_tokens=self._prompt_tokens,
            completion_tokens=self._completion_tokens,
            finish_reason="stop",
            model=model or self._default_model,
        )

    def estimate_cost(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> float | None:
        """Mock cost estimation (always returns 0)."""
        return 0.0

    @property
    def call_count(self) -> int:
        """Number of calls made to the provider."""
        return len(self.calls)

    @property
    def last_call(self) -> MockCall | None:
        """The most recent call, if any."""
        return self.calls[-1] if self.calls else None
