"""Anthropic Claude LLM provider."""

from typing import Any

import httpx

from zos.exceptions import LLMError
from zos.llm.config import AnthropicProviderConfig
from zos.llm.provider import LLMProvider, LLMResponse, Message
from zos.llm.retry import RetryableError
from zos.logging import get_logger

logger = get_logger("llm.anthropic")

# Pricing per 1M tokens (as of late 2024)
# Format: {model: (input_price, output_price)}
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-20250514": (15.00, 75.00),
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-3-5-haiku-20241022": (0.80, 4.00),
    "claude-3-opus-20240229": (15.00, 75.00),
    "claude-3-sonnet-20240229": (3.00, 15.00),
    "claude-3-haiku-20240307": (0.25, 1.25),
}

# Anthropic API version
API_VERSION = "2023-06-01"


class AnthropicProvider(LLMProvider):
    """Anthropic Claude LLM provider.

    Uses the Anthropic Messages API with proper authentication
    and message format handling.
    """

    def __init__(self, config: AnthropicProviderConfig) -> None:
        """Initialize the Anthropic provider.

        Args:
            config: Provider configuration.
        """
        self.config = config
        self._client: httpx.AsyncClient | None = None

    @property
    def name(self) -> str:
        return "anthropic"

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
                base_url="https://api.anthropic.com",
                headers={
                    "x-api-key": self.config.api_key,
                    "anthropic-version": API_VERSION,
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
        """Generate a completion from Anthropic.

        Args:
            messages: List of conversation messages.
            model: Model to use (None = provider default).
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature (0.0 - 1.0).
            **kwargs: Additional Anthropic API options.

        Returns:
            LLMResponse with content and token counts.

        Raises:
            LLMError: On API errors.
        """
        model = model or self.config.default_model
        client = self._get_client()

        # Convert messages to Anthropic format
        # Anthropic requires system message to be separate
        system_content = None
        api_messages = []

        for m in messages:
            if m.role.value == "system":
                # Anthropic takes system as a separate parameter
                system_content = m.content
            else:
                api_messages.append({
                    "role": m.role.value,
                    "content": m.content,
                })

        # Build request body
        request_body: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        if system_content:
            request_body["system"] = system_content

        # Add any extra kwargs (e.g., top_p, stop_sequences)
        request_body.update(kwargs)

        try:
            response = await client.post("/v1/messages", json=request_body)

            # Handle error responses
            if response.status_code >= 400:
                error_body = response.text
                if response.status_code in (429, 500, 502, 503, 504, 529):
                    # 529 is Anthropic's overloaded status
                    raise RetryableError(
                        f"Anthropic API error {response.status_code}: {error_body}",
                        status_code=response.status_code,
                    )
                raise LLMError(f"Anthropic API error {response.status_code}: {error_body}")

            data = response.json()

        except httpx.HTTPStatusError as e:
            if e.response.status_code in (429, 500, 502, 503, 504, 529):
                raise RetryableError(
                    f"Anthropic API error {e.response.status_code}",
                    status_code=e.response.status_code,
                ) from e
            raise LLMError(f"Anthropic API error: {e}") from e
        except httpx.RequestError as e:
            raise LLMError(f"Anthropic request failed: {e}") from e

        # Parse response
        try:
            # Anthropic returns content as a list of content blocks
            content_blocks = data.get("content", [])
            content = ""
            for block in content_blocks:
                if block.get("type") == "text":
                    content += block.get("text", "")

            stop_reason = data.get("stop_reason", "unknown")

            usage = data.get("usage", {})
            prompt_tokens = usage.get("input_tokens", 0)
            completion_tokens = usage.get("output_tokens", 0)

            return LLMResponse(
                content=content,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                finish_reason=stop_reason,
                model=data.get("model", model),
                raw_response=data,
            )
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"Invalid Anthropic response format: {e}") from e

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
            # Try prefix match (for dated model versions)
            base_model = None
            for known_model in PRICING:
                if model.startswith(known_model.rsplit("-", 1)[0]):
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
