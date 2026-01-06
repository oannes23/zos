"""Ollama local LLM provider."""

from typing import Any

import httpx

from zos.exceptions import LLMError
from zos.llm.config import OllamaProviderConfig
from zos.llm.provider import LLMProvider, LLMResponse, Message
from zos.llm.retry import RetryableError
from zos.logging import get_logger

logger = get_logger("llm.ollama")


class OllamaProvider(LLMProvider):
    """Ollama local LLM provider.

    Connects to a local Ollama server for running open-source models
    like Llama, Mistral, etc.
    """

    def __init__(self, config: OllamaProviderConfig) -> None:
        """Initialize the Ollama provider.

        Args:
            config: Provider configuration.
        """
        self.config = config
        self._client: httpx.AsyncClient | None = None

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def default_model(self) -> str:
        return self.config.default_model

    def is_available(self) -> bool:
        """Check if Ollama server is likely available.

        Note: This doesn't actually check connectivity, just returns True
        since Ollama doesn't require API keys.
        """
        return True

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                headers={"Content-Type": "application/json"},
                timeout=httpx.Timeout(self.config.timeout_seconds),
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def complete(
        self,
        messages: list[Message],
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a completion from Ollama.

        Args:
            messages: List of conversation messages.
            model: Model to use (None = provider default).
            max_tokens: Maximum tokens to generate (mapped to num_predict).
            temperature: Sampling temperature.
            **kwargs: Additional Ollama API options.

        Returns:
            LLMResponse with content and token counts.

        Raises:
            LLMError: On API errors.
        """
        model = model or self.config.default_model
        client = self._get_client()

        # Convert messages to Ollama format
        api_messages = [
            {"role": m.role.value, "content": m.content}
            for m in messages
        ]

        # Build request body
        # Ollama uses /api/chat endpoint with options object
        request_body: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "stream": False,  # We don't support streaming
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }

        # Add any extra kwargs to options
        if kwargs:
            request_body["options"].update(kwargs)

        try:
            response = await client.post("/api/chat", json=request_body)

            # Handle error responses
            if response.status_code >= 400:
                error_body = response.text
                if response.status_code in (500, 502, 503, 504):
                    raise RetryableError(
                        f"Ollama API error {response.status_code}: {error_body}",
                        status_code=response.status_code,
                    )
                raise LLMError(f"Ollama API error {response.status_code}: {error_body}")

            data = response.json()

        except httpx.HTTPStatusError as e:
            if e.response.status_code in (500, 502, 503, 504):
                raise RetryableError(
                    f"Ollama API error {e.response.status_code}",
                    status_code=e.response.status_code,
                ) from e
            raise LLMError(f"Ollama API error: {e}") from e
        except httpx.ConnectError as e:
            raise LLMError(
                f"Cannot connect to Ollama at {self.config.base_url}. "
                "Is Ollama running? Start with: ollama serve"
            ) from e
        except httpx.RequestError as e:
            raise LLMError(f"Ollama request failed: {e}") from e

        # Parse response
        try:
            message = data.get("message", {})
            content = message.get("content", "")
            done_reason = data.get("done_reason", "stop")

            # Ollama provides token counts in response
            prompt_tokens = data.get("prompt_eval_count", 0)
            completion_tokens = data.get("eval_count", 0)

            return LLMResponse(
                content=content,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                finish_reason=done_reason,
                model=data.get("model", model),
                raw_response=data,
            )
        except (KeyError, TypeError) as e:
            raise LLMError(f"Invalid Ollama response format: {e}") from e

    def estimate_cost(
        self,
        _model: str,
        _prompt_tokens: int,
        _completion_tokens: int,
    ) -> float | None:
        """Estimate cost in USD.

        Ollama runs locally, so cost is always 0.

        Args:
            _model: Model identifier (ignored).
            _prompt_tokens: Input token count (ignored).
            _completion_tokens: Output token count (ignored).

        Returns:
            0.0 (local models have no API cost).
        """
        return 0.0
