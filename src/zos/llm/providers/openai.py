"""OpenAI-compatible LLM provider."""

from typing import Any

import httpx

from zos.exceptions import LLMError
from zos.llm.config import OpenAIProviderConfig
from zos.llm.provider import LLMProvider, LLMResponse, Message
from zos.llm.retry import RetryableError
from zos.logging import get_logger

logger = get_logger("llm.openai")

# Pricing per 1M tokens (as of late 2024)
# Format: {model: (input_price, output_price)}
PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "o1": (15.00, 60.00),
    "o1-mini": (3.00, 12.00),
}


class OpenAIProvider(LLMProvider):
    """OpenAI-compatible LLM provider.

    Works with:
    - OpenAI API
    - Azure OpenAI (with different base_url)
    - Local OpenAI-compatible servers (LM Studio, etc.)
    """

    def __init__(self, config: OpenAIProviderConfig) -> None:
        """Initialize the OpenAI provider.

        Args:
            config: Provider configuration.
        """
        self.config = config
        self._client: httpx.AsyncClient | None = None

    @property
    def name(self) -> str:
        return "openai"

    @property
    def default_model(self) -> str:
        return self.config.default_model

    def is_available(self) -> bool:
        """Check if API key is configured."""
        return bool(self.config.api_key)

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
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
        """Generate a completion from OpenAI.

        Args:
            messages: List of conversation messages.
            model: Model to use (None = provider default).
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature (0.0 - 2.0).
            **kwargs: Additional OpenAI API options.

        Returns:
            LLMResponse with content and token counts.

        Raises:
            LLMError: On API errors.
        """
        model = model or self.config.default_model
        client = self._get_client()

        # Build request body
        request_body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role.value, "content": m.content} for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        request_body.update(kwargs)

        try:
            response = await client.post("/chat/completions", json=request_body)

            # Handle error responses
            if response.status_code >= 400:
                error_body = response.text
                if response.status_code in (429, 500, 502, 503, 504):
                    raise RetryableError(
                        f"OpenAI API error {response.status_code}: {error_body}",
                        status_code=response.status_code,
                    )
                raise LLMError(f"OpenAI API error {response.status_code}: {error_body}")

            data = response.json()

        except httpx.HTTPStatusError as e:
            if e.response.status_code in (429, 500, 502, 503, 504):
                raise RetryableError(
                    f"OpenAI API error {e.response.status_code}",
                    status_code=e.response.status_code,
                ) from e
            raise LLMError(f"OpenAI API error: {e}") from e
        except httpx.RequestError as e:
            raise LLMError(f"OpenAI request failed: {e}") from e

        # Parse response
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
            finish_reason = choice.get("finish_reason", "unknown")

            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)

            return LLMResponse(
                content=content,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                finish_reason=finish_reason,
                model=data.get("model", model),
                raw_response=data,
            )
        except (KeyError, IndexError) as e:
            raise LLMError(f"Invalid OpenAI response format: {e}") from e

    def estimate_cost(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> float | None:
        """Estimate cost in USD.

        Args:
            model: Model identifier.
            prompt_tokens: Input token count.
            completion_tokens: Output token count.

        Returns:
            Estimated cost in USD, or None if model pricing unknown.
        """
        # Try exact match first
        if model in PRICING:
            input_price, output_price = PRICING[model]
        else:
            # Try prefix match (for dated model versions like gpt-4o-2024-08-06)
            base_model = None
            for known_model in PRICING:
                if model.startswith(known_model):
                    base_model = known_model
                    break
            if base_model is None:
                logger.debug(f"Unknown pricing for model: {model}")
                return None
            input_price, output_price = PRICING[base_model]

        # Prices are per 1M tokens
        input_cost = (prompt_tokens / 1_000_000) * input_price
        output_cost = (completion_tokens / 1_000_000) * output_price

        return input_cost + output_cost
