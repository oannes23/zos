"""LLM client wrapper for Zos.

Provides a thin wrapper around LLM providers (primarily Anthropic) with:
- Model profile resolution from configuration
- Rate limiting per provider
- Token usage tracking
- Cost estimation
- LLM call auditing (when layer_run_id is provided)

This implementation supports text completion, vision analysis, and optional
database auditing for all LLM calls.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from zos.logging import get_logger
from zos.models import LLMCall, LLMCallType

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic
    from sqlalchemy.engine import Engine

    from zos.config import Config

log = get_logger("llm")


@dataclass
class Usage:
    """Token usage from an LLM call."""

    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        """Total tokens used."""
        return self.input_tokens + self.output_tokens


@dataclass
class CompletionResult:
    """Result from an LLM completion."""

    text: str
    usage: Usage
    model: str
    provider: str


class RateLimiter:
    """Simple token bucket rate limiter.

    Tracks calls within a sliding window and blocks when the limit
    is reached until calls expire from the window.
    """

    def __init__(self, calls_per_minute: int = 50) -> None:
        """Initialize the rate limiter.

        Args:
            calls_per_minute: Maximum calls allowed per minute.
        """
        self.calls_per_minute = calls_per_minute
        self.calls: list[datetime] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until rate limit allows another call."""
        async with self._lock:
            now = datetime.now(timezone.utc)
            minute_ago = now - timedelta(minutes=1)

            # Remove old calls outside the window
            self.calls = [t for t in self.calls if t > minute_ago]

            if len(self.calls) >= self.calls_per_minute:
                # Wait for oldest call to expire from window
                wait_time = (self.calls[0] - minute_ago).total_seconds()
                if wait_time > 0:
                    log.debug(
                        "rate_limit_waiting",
                        wait_seconds=wait_time,
                        calls_in_window=len(self.calls),
                    )
                    await asyncio.sleep(wait_time)
                # Refresh the list after waiting
                now = datetime.now(timezone.utc)
                minute_ago = now - timedelta(minutes=1)
                self.calls = [t for t in self.calls if t > minute_ago]

            self.calls.append(now)


# Cost per million tokens (input, output) - approximate prices
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-4-20250514": (15.0, 75.0),
    "claude-sonnet-4-20250514": (3.0, 15.0),
    "claude-3-5-haiku-20241022": (0.25, 1.25),
    "claude-3-haiku-20240307": (0.25, 1.25),
    "claude-3-5-sonnet-20241022": (3.0, 15.0),
}


def estimate_cost(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Estimate cost in USD for a completion.

    Args:
        provider: Provider name (e.g., 'anthropic').
        model: Model name.
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.

    Returns:
        Estimated cost in USD.
    """
    if provider != "anthropic":
        # Default pricing for unknown providers
        return (input_tokens / 1_000_000) * 1.0 + (output_tokens / 1_000_000) * 3.0

    prices = MODEL_PRICES.get(model, (1.0, 3.0))
    input_cost = (input_tokens / 1_000_000) * prices[0]
    output_cost = (output_tokens / 1_000_000) * prices[1]

    return input_cost + output_cost


class ModelClient:
    """Thin wrapper for LLM calls with multi-provider support.

    Currently supports Anthropic. OpenAI support is optional for MVP 0.

    The client uses lazy initialization - provider clients are only
    created when first needed.

    When an engine is provided, ALL LLM calls are automatically audited
    to the database with full prompt/response, token counts, and cost estimates.
    """

    def __init__(self, config: Config, engine: Engine | None = None) -> None:
        """Initialize the model client.

        Args:
            config: Application configuration with model profiles.
            engine: Optional SQLAlchemy engine for LLM call auditing.
        """
        self.config = config
        self.engine = engine
        self._anthropic: AsyncAnthropic | None = None
        self._rate_limiters: dict[str, RateLimiter] = {}

    def _get_anthropic(self) -> AsyncAnthropic:
        """Get or create the Anthropic client (lazy initialization).

        Returns:
            AsyncAnthropic client instance.

        Raises:
            ValueError: If API key not found in environment.
        """
        if self._anthropic is None:
            from anthropic import AsyncAnthropic

            api_key = self._get_api_key("anthropic")
            if not api_key:
                raise ValueError(
                    "Anthropic API key not found. Set ANTHROPIC_API_KEY environment variable."
                )
            self._anthropic = AsyncAnthropic(api_key=api_key)
        return self._anthropic

    def _get_api_key(self, provider: str) -> str | None:
        """Get API key for a provider from environment.

        Args:
            provider: Provider name (e.g., 'anthropic').

        Returns:
            API key if found, None otherwise.
        """
        if self.config.models is None:
            # Fall back to default environment variable
            return os.environ.get(f"{provider.upper()}_API_KEY")

        return self.config.models.get_api_key(provider)

    def _get_rate_limiter(self, provider: str) -> RateLimiter:
        """Get or create rate limiter for a provider.

        Args:
            provider: Provider name.

        Returns:
            RateLimiter instance for the provider.
        """
        if provider not in self._rate_limiters:
            # Default: 50 requests per minute
            self._rate_limiters[provider] = RateLimiter(calls_per_minute=50)
        return self._rate_limiters[provider]

    async def complete(
        self,
        prompt: str,
        model_profile: str = "simple",
        max_tokens: int = 500,
        temperature: float = 0.7,
        *,
        layer_run_id: str | None = None,
        topic_key: str | None = None,
        call_type: LLMCallType = LLMCallType.OTHER,
    ) -> CompletionResult:
        """Complete a text prompt.

        Args:
            prompt: The prompt text to complete.
            model_profile: Name of the model profile to use.
            max_tokens: Maximum tokens in the response.
            temperature: Sampling temperature (0-1).
            layer_run_id: Optional layer run ID for context (links call to a layer run).
            topic_key: Optional topic key for context (links call to a topic).
            call_type: Type of LLM call for categorization.

        Returns:
            CompletionResult with text, usage, and metadata.

        Raises:
            ValueError: If model profile not found or provider unsupported.

        Note:
            All calls are automatically recorded to the database when
            the client has an engine. layer_run_id and topic_key are optional
            context that helps link the call to other entities.
        """
        # Resolve profile to provider/model
        if self.config.models is None:
            # Default to Anthropic Haiku for simple tasks
            provider = "anthropic"
            model = "claude-3-5-haiku-20241022"
        else:
            profile = self.config.models.resolve_profile(model_profile)
            provider = profile.provider
            model = profile.model

        # Apply rate limiting
        limiter = self._get_rate_limiter(provider)
        await limiter.acquire()

        # Track timing for latency
        start_time = time.monotonic()

        if provider == "anthropic":
            result = await self._anthropic_complete(prompt, model, max_tokens, temperature)
        else:
            raise ValueError(f"Unsupported provider: {provider}")

        # Calculate latency
        latency_ms = int((time.monotonic() - start_time) * 1000)

        # Record LLM call if database engine is available
        if self.engine is not None:
            try:
                await self._record_llm_call(
                    layer_run_id=layer_run_id,
                    topic_key=topic_key,
                    call_type=call_type,
                    model_profile=model_profile,
                    provider=provider,
                    model=model,
                    prompt=prompt,
                    response=result.text,
                    usage=result.usage,
                    latency_ms=latency_ms,
                    success=True,
                    error_message=None,
                )
            except Exception:
                log.warning("llm_call_recording_failed", call_type=call_type.value, exc_info=True)

        return result

    async def _anthropic_complete(
        self,
        prompt: str,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> CompletionResult:
        """Call Anthropic API for text completion.

        Args:
            prompt: The prompt text.
            model: Anthropic model name.
            max_tokens: Maximum response tokens.
            temperature: Sampling temperature.

        Returns:
            CompletionResult with response.
        """
        import anthropic

        client = self._get_anthropic()

        log.debug(
            "llm_call_start",
            provider="anthropic",
            model=model,
            prompt_length=len(prompt),
        )

        try:
            response = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )

            usage = Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )

            log.debug(
                "llm_call_complete",
                provider="anthropic",
                model=model,
                tokens_in=usage.input_tokens,
                tokens_out=usage.output_tokens,
            )

            return CompletionResult(
                text=response.content[0].text,
                usage=usage,
                model=model,
                provider="anthropic",
            )

        except anthropic.RateLimitError:
            log.warning("rate_limit_hit", provider="anthropic")
            # Wait and retry once
            await asyncio.sleep(60)
            return await self._anthropic_complete(prompt, model, max_tokens, temperature)

        except anthropic.APIError as e:
            log.error("api_error", provider="anthropic", error=str(e))
            raise

    async def analyze_image(
        self,
        image_base64: str,
        media_type: str,
        prompt: str,
        model_profile: str = "vision",
        *,
        layer_run_id: str | None = None,
        topic_key: str | None = None,
        call_type: LLMCallType = LLMCallType.VISION,
    ) -> CompletionResult:
        """Analyze an image with vision model.

        Args:
            image_base64: Base64-encoded image data.
            media_type: MIME type of the image (e.g., 'image/png').
            prompt: Analysis prompt.
            model_profile: Name of the model profile to use.
            layer_run_id: Optional layer run ID for context (links call to a layer run).
            topic_key: Optional topic key for context (links call to a topic).
            call_type: Type of LLM call for categorization (defaults to VISION).

        Returns:
            CompletionResult with analysis text and usage.

        Raises:
            ValueError: If provider doesn't support vision.

        Note:
            All calls are automatically recorded to the database when
            the client has an engine. layer_run_id and topic_key are optional
            context that helps link the call to other entities.
        """
        # Resolve profile to provider/model
        if self.config.models is None:
            # Default to Anthropic Haiku for vision
            provider = "anthropic"
            model = "claude-3-5-haiku-20241022"
        else:
            profile = self.config.models.resolve_profile(model_profile)
            provider = profile.provider
            model = profile.model

        # Apply rate limiting
        limiter = self._get_rate_limiter(provider)
        await limiter.acquire()

        # Track timing for latency
        start_time = time.monotonic()

        if provider == "anthropic":
            result = await self._anthropic_vision(image_base64, media_type, prompt, model)
        else:
            raise ValueError(f"Provider {provider} doesn't support vision")

        # Calculate latency
        latency_ms = int((time.monotonic() - start_time) * 1000)

        # For vision calls, the prompt includes image context indicator
        full_prompt = f"[Image: {media_type}]\n{prompt}"

        # Record LLM call if database engine is available
        if self.engine is not None:
            try:
                await self._record_llm_call(
                    layer_run_id=layer_run_id,
                    topic_key=topic_key,
                    call_type=call_type,
                    model_profile=model_profile,
                    provider=provider,
                    model=model,
                    prompt=full_prompt,
                    response=result.text,
                    usage=result.usage,
                    latency_ms=latency_ms,
                    success=True,
                    error_message=None,
                )
            except Exception:
                log.warning("llm_call_recording_failed", call_type=call_type.value, exc_info=True)

        return result

    async def _anthropic_vision(
        self,
        image_base64: str,
        media_type: str,
        prompt: str,
        model: str,
    ) -> CompletionResult:
        """Call Anthropic vision API.

        Args:
            image_base64: Base64-encoded image data.
            media_type: MIME type of the image.
            prompt: Analysis prompt.
            model: Model name.

        Returns:
            CompletionResult with analysis.
        """
        import anthropic

        client = self._get_anthropic()

        log.debug(
            "vision_call_start",
            provider="anthropic",
            model=model,
            media_type=media_type,
        )

        try:
            response = await client.messages.create(
                model=model,
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_base64,
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt,
                            },
                        ],
                    }
                ],
            )

            usage = Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )

            log.debug(
                "vision_call_complete",
                provider="anthropic",
                model=model,
                tokens_in=usage.input_tokens,
                tokens_out=usage.output_tokens,
            )

            return CompletionResult(
                text=response.content[0].text,
                usage=usage,
                model=model,
                provider="anthropic",
            )

        except anthropic.RateLimitError:
            log.warning("rate_limit_hit", provider="anthropic", call_type="vision")
            # Wait and retry once
            await asyncio.sleep(60)
            return await self._anthropic_vision(image_base64, media_type, prompt, model)

        except anthropic.APIError as e:
            log.error("api_error", provider="anthropic", call_type="vision", error=str(e))
            raise

    async def _record_llm_call(
        self,
        layer_run_id: str,
        topic_key: str | None,
        call_type: LLMCallType,
        model_profile: str,
        provider: str,
        model: str,
        prompt: str,
        response: str,
        usage: Usage,
        latency_ms: int,
        success: bool,
        error_message: str | None,
    ) -> None:
        """Record an LLM call to the database for auditing.

        Args:
            layer_run_id: The layer run ID this call is associated with.
            topic_key: Optional topic key for context.
            call_type: Type of LLM call.
            model_profile: Model profile name used.
            provider: Provider name.
            model: Model name.
            prompt: Full prompt text.
            response: Full response text.
            usage: Token usage.
            latency_ms: Request latency in milliseconds.
            success: Whether the call succeeded.
            error_message: Error message if failed.
        """
        from zos.database import generate_id, llm_calls

        # Calculate estimated cost
        cost = estimate_cost(
            provider=provider,
            model=model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )

        # Create the LLM call record as a dict for direct insertion
        # (avoiding Pydantic model to ensure enum serialization)
        llm_call_id = generate_id()
        llm_call_data = {
            "id": llm_call_id,
            "layer_run_id": layer_run_id,
            "topic_key": topic_key,
            "call_type": call_type.value,  # Serialize enum to string
            "model_profile": model_profile,
            "model_provider": provider,
            "model_name": model,
            "prompt": prompt,
            "response": response,
            "tokens_input": usage.input_tokens,
            "tokens_output": usage.output_tokens,
            "tokens_total": usage.total_tokens,
            "estimated_cost_usd": cost,
            "latency_ms": latency_ms,
            "success": success,
            "error_message": error_message,
        }

        # Insert into database
        if self.engine is not None:
            with self.engine.connect() as conn:
                conn.execute(llm_calls.insert().values(**llm_call_data))
                conn.commit()

            log.debug(
                "llm_call_recorded",
                llm_call_id=llm_call_id,
                layer_run_id=layer_run_id,
                call_type=call_type.value,
                tokens_total=usage.total_tokens,
                cost_usd=cost,
                latency_ms=latency_ms,
            )

    async def close(self) -> None:
        """Close the client and release resources."""
        if self._anthropic is not None:
            await self._anthropic.close()
            self._anthropic = None
