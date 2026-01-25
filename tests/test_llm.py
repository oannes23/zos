"""Tests for the LLM client.

Covers:
- Rate limiter functionality
- Model profile resolution
- Vision analysis method signature
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zos.config import Config, ModelProfile, ModelsConfig
from zos.llm import CompletionResult, ModelClient, RateLimiter, Usage, estimate_cost


class TestUsage:
    """Tests for Usage dataclass."""

    def test_total_tokens(self) -> None:
        """Total tokens is sum of input and output."""
        usage = Usage(input_tokens=100, output_tokens=50)
        assert usage.total_tokens == 150

    def test_zero_tokens(self) -> None:
        """Zero tokens are handled."""
        usage = Usage(input_tokens=0, output_tokens=0)
        assert usage.total_tokens == 0


class TestRateLimiter:
    """Tests for the rate limiter."""

    @pytest.mark.asyncio
    async def test_allows_calls_under_limit(self) -> None:
        """Rate limiter allows calls when under the limit."""
        limiter = RateLimiter(calls_per_minute=10)

        start = datetime.now(timezone.utc)
        for _ in range(5):
            await limiter.acquire()
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()

        assert elapsed < 1.0
        assert len(limiter.calls) == 5

    @pytest.mark.asyncio
    async def test_tracks_calls(self) -> None:
        """Rate limiter tracks call timestamps."""
        limiter = RateLimiter(calls_per_minute=10)

        await limiter.acquire()
        await limiter.acquire()

        assert len(limiter.calls) == 2

    def test_default_calls_per_minute(self) -> None:
        """Default rate limit is 50 calls per minute."""
        limiter = RateLimiter()
        assert limiter.calls_per_minute == 50


class TestEstimateCost:
    """Tests for cost estimation."""

    def test_known_anthropic_model(self) -> None:
        """Cost estimation works for known Anthropic models."""
        cost = estimate_cost(
            provider="anthropic",
            model="claude-3-5-haiku-20241022",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        # Haiku: $0.25/M input + $1.25/M output = $1.50
        assert cost == pytest.approx(1.50, rel=0.01)

    def test_unknown_model_uses_default(self) -> None:
        """Unknown models use default pricing."""
        cost = estimate_cost(
            provider="anthropic",
            model="unknown-model",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        # Default: $1/M input + $3/M output = $4
        assert cost == pytest.approx(4.0, rel=0.01)

    def test_unknown_provider_uses_default(self) -> None:
        """Unknown providers use default pricing."""
        cost = estimate_cost(
            provider="unknown",
            model="whatever",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        # Default: $1/M input + $3/M output = $4
        assert cost == pytest.approx(4.0, rel=0.01)

    def test_zero_tokens(self) -> None:
        """Zero tokens cost zero."""
        cost = estimate_cost(
            provider="anthropic",
            model="claude-3-5-haiku-20241022",
            input_tokens=0,
            output_tokens=0,
        )
        assert cost == 0.0


class TestModelClient:
    """Tests for the ModelClient class."""

    def test_initialization(self) -> None:
        """ModelClient initializes with config."""
        config = Config()
        client = ModelClient(config)

        assert client.config is config
        assert client._anthropic is None
        assert client._rate_limiters == {}

    def test_rate_limiter_creation(self) -> None:
        """Rate limiter is created lazily per provider."""
        config = Config()
        client = ModelClient(config)

        limiter = client._get_rate_limiter("anthropic")
        assert limiter.calls_per_minute == 50

        # Same provider returns same limiter
        limiter2 = client._get_rate_limiter("anthropic")
        assert limiter is limiter2

        # Different provider creates new limiter
        limiter3 = client._get_rate_limiter("openai")
        assert limiter3 is not limiter

    def test_api_key_from_config(self) -> None:
        """API key is retrieved from config."""
        config = Config()
        config.models = ModelsConfig(
            profiles={"default": ModelProfile(provider="anthropic", model="claude")},
            providers={"anthropic": {"api_key_env": "ANTHROPIC_API_KEY"}},
        )
        client = ModelClient(config)

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            key = client._get_api_key("anthropic")
            assert key == "test-key"

    def test_api_key_fallback_to_default(self) -> None:
        """API key falls back to default env var naming."""
        config = Config()
        # No models config
        client = ModelClient(config)

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fallback-key"}):
            key = client._get_api_key("anthropic")
            assert key == "fallback-key"


class TestModelClientVision:
    """Tests for vision-related ModelClient functionality."""

    @pytest.mark.asyncio
    async def test_analyze_image_requires_vision_provider(self) -> None:
        """analyze_image raises for non-vision providers."""
        config = Config()
        config.models = ModelsConfig(
            profiles={
                "vision": ModelProfile(provider="unknown_provider", model="some-model")
            },
            providers={},
        )
        client = ModelClient(config)

        with pytest.raises(ValueError, match="doesn't support vision"):
            await client.analyze_image(
                image_base64="abc123",
                media_type="image/png",
                prompt="Describe this",
                model_profile="vision",
            )

    @pytest.mark.asyncio
    async def test_analyze_image_applies_rate_limiting(self) -> None:
        """analyze_image applies rate limiting before API call."""
        config = Config()
        config.models = ModelsConfig(
            profiles={
                "vision": ModelProfile(
                    provider="anthropic", model="claude-3-5-haiku-20241022"
                )
            },
            providers={"anthropic": {"api_key_env": "ANTHROPIC_API_KEY"}},
        )
        client = ModelClient(config)

        # Mock the rate limiter
        mock_limiter = MagicMock()
        mock_limiter.acquire = AsyncMock()
        client._rate_limiters["anthropic"] = mock_limiter

        # Mock the Anthropic client
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.object(client, "_get_anthropic") as mock_get_anthropic:
                mock_anthropic = MagicMock()
                mock_response = MagicMock()
                mock_response.content = [MagicMock(text="A sunset image")]
                mock_response.usage.input_tokens = 100
                mock_response.usage.output_tokens = 50
                mock_anthropic.messages.create = AsyncMock(return_value=mock_response)
                mock_get_anthropic.return_value = mock_anthropic

                await client.analyze_image(
                    image_base64="abc123",
                    media_type="image/png",
                    prompt="Describe this",
                    model_profile="vision",
                )

        # Rate limiter should have been called
        mock_limiter.acquire.assert_awaited_once()


class TestCompletionResult:
    """Tests for CompletionResult dataclass."""

    def test_creation(self) -> None:
        """CompletionResult is created with all fields."""
        usage = Usage(input_tokens=100, output_tokens=50)
        result = CompletionResult(
            text="Hello world",
            usage=usage,
            model="claude-3-5-haiku",
            provider="anthropic",
        )

        assert result.text == "Hello world"
        assert result.usage.total_tokens == 150
        assert result.model == "claude-3-5-haiku"
        assert result.provider == "anthropic"
