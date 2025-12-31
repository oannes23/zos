"""Tests for LLM abstraction layer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from zos.llm import (
    LLMConfig,
    LLMResponse,
    Message,
    MessageRole,
    OpenAIProviderConfig,
)
from zos.llm.config import (
    AnthropicProviderConfig,
    GenericHTTPProviderConfig,
    OllamaProviderConfig,
    RetryConfig,
)
from zos.llm.providers.mock import MockProvider
from zos.llm.resolver import ModelSelection, get_available_providers, resolve_model


# =============================================================================
# Mock Provider Tests
# =============================================================================


class TestMockProvider:
    """Tests for MockProvider."""

    @pytest.fixture
    def provider(self) -> MockProvider:
        """Create a mock provider."""
        return MockProvider()

    @pytest.mark.asyncio
    async def test_default_response(self, provider: MockProvider) -> None:
        """Test that mock returns default response."""
        messages = [Message(role=MessageRole.USER, content="Hello")]
        response = await provider.complete(messages)

        assert response.content == "This is a mock response."
        assert response.prompt_tokens == 10
        assert response.completion_tokens == 20
        assert response.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_call_tracking(self, provider: MockProvider) -> None:
        """Test that calls are tracked."""
        messages = [Message(role=MessageRole.USER, content="Hello")]
        await provider.complete(messages)
        await provider.complete(messages, model="custom-model")

        assert provider.call_count == 2
        assert provider.last_call is not None
        assert provider.last_call.model == "custom-model"
        assert provider.calls[0].model is None

    @pytest.mark.asyncio
    async def test_queue_response(self, provider: MockProvider) -> None:
        """Test queued responses."""
        provider.queue_response("First response")
        provider.queue_response("Second response")

        messages = [Message(role=MessageRole.USER, content="Hello")]
        response1 = await provider.complete(messages)
        response2 = await provider.complete(messages)
        response3 = await provider.complete(messages)

        assert response1.content == "First response"
        assert response2.content == "Second response"
        assert response3.content == "This is a mock response."  # Default

    @pytest.mark.asyncio
    async def test_queue_error(self, provider: MockProvider) -> None:
        """Test queued errors."""
        provider.queue_response(error=ValueError("Test error"))

        messages = [Message(role=MessageRole.USER, content="Hello")]
        with pytest.raises(ValueError, match="Test error"):
            await provider.complete(messages)

    @pytest.mark.asyncio
    async def test_set_error(self, provider: MockProvider) -> None:
        """Test set error."""
        provider.set_error(RuntimeError("Persistent error"))

        messages = [Message(role=MessageRole.USER, content="Hello")]
        with pytest.raises(RuntimeError, match="Persistent error"):
            await provider.complete(messages)

        # Error is cleared after raising
        response = await provider.complete(messages)
        assert response.content == "This is a mock response."

    @pytest.mark.asyncio
    async def test_custom_response(self, provider: MockProvider) -> None:
        """Test custom LLMResponse."""
        custom = LLMResponse(
            content="Custom content",
            prompt_tokens=100,
            completion_tokens=200,
            finish_reason="length",
            model="custom-model",
        )
        provider.queue_response(response=custom)

        messages = [Message(role=MessageRole.USER, content="Hello")]
        response = await provider.complete(messages)

        assert response.content == "Custom content"
        assert response.prompt_tokens == 100
        assert response.completion_tokens == 200
        assert response.finish_reason == "length"

    def test_estimate_cost(self, provider: MockProvider) -> None:
        """Test mock cost estimation."""
        cost = provider.estimate_cost("any-model", 1000, 500)
        assert cost == 0.0

    def test_provider_properties(self, provider: MockProvider) -> None:
        """Test provider properties."""
        assert provider.name == "mock"
        assert provider.default_model == "mock-model"

    @pytest.mark.asyncio
    async def test_reset(self, provider: MockProvider) -> None:
        """Test reset clears state."""
        messages = [Message(role=MessageRole.USER, content="Hello")]
        await provider.complete(messages)
        provider.queue_response("queued")
        provider.set_error(ValueError("error"))

        provider.reset()

        assert provider.call_count == 0
        assert provider.last_call is None
        # Queued response should be cleared
        response = await provider.complete(messages)
        assert response.content == "This is a mock response."


# =============================================================================
# Model Resolver Tests
# =============================================================================


class TestModelResolver:
    """Tests for model resolution."""

    @pytest.fixture
    def config(self) -> LLMConfig:
        """Create a test LLM config."""
        return LLMConfig(
            default_provider="openai",
            default_model="gpt-4o",
            openai=OpenAIProviderConfig(
                api_key="test-key",
                default_model="gpt-4o-mini",
            ),
            anthropic=AnthropicProviderConfig(
                api_key="test-key",
                default_model="claude-sonnet-4-20250514",
            ),
        )

    def test_global_defaults(self, config: LLMConfig) -> None:
        """Test resolution uses global defaults."""
        selection = resolve_model(config)

        assert selection.provider == "openai"
        assert selection.model == "gpt-4o"  # Global default model
        assert selection.source == "global"

    def test_layer_override(self, config: LLMConfig) -> None:
        """Test layer settings override global."""
        selection = resolve_model(
            config,
            layer_provider="anthropic",
            layer_model="claude-3-opus-20240229",
        )

        assert selection.provider == "anthropic"
        assert selection.model == "claude-3-opus-20240229"
        assert selection.source == "layer"

    def test_node_override(self, config: LLMConfig) -> None:
        """Test node settings override layer."""
        selection = resolve_model(
            config,
            layer_provider="anthropic",
            layer_model="claude-3-opus-20240229",
            node_provider="openai",
            node_model="gpt-4-turbo",
        )

        assert selection.provider == "openai"
        assert selection.model == "gpt-4-turbo"
        assert selection.source == "node"

    def test_provider_default_model(self, config: LLMConfig) -> None:
        """Test falling back to provider default model."""
        config.default_model = None  # No global default

        selection = resolve_model(config)

        assert selection.provider == "openai"
        assert selection.model == "gpt-4o-mini"  # OpenAI provider default
        assert selection.source == "provider_default"

    def test_get_available_providers(self, config: LLMConfig) -> None:
        """Test getting available providers."""
        providers = get_available_providers(config)

        assert "openai" in providers
        assert "anthropic" in providers
        assert "ollama" not in providers  # Not configured

    def test_get_available_providers_with_ollama(self) -> None:
        """Test Ollama doesn't require API key."""
        config = LLMConfig(
            ollama=OllamaProviderConfig(
                base_url="http://localhost:11434",
            ),
        )

        providers = get_available_providers(config)
        assert "ollama" in providers


# =============================================================================
# Retry Config Tests
# =============================================================================


class TestRetryConfig:
    """Tests for retry configuration."""

    def test_default_values(self) -> None:
        """Test default retry config values."""
        config = RetryConfig()

        assert config.max_attempts == 3
        assert config.base_delay_seconds == 1.0
        assert config.max_delay_seconds == 60.0
        assert config.exponential_base == 2.0
        assert 429 in config.retryable_status_codes
        assert 500 in config.retryable_status_codes

    def test_custom_values(self) -> None:
        """Test custom retry config values."""
        config = RetryConfig(
            max_attempts=5,
            base_delay_seconds=0.5,
            max_delay_seconds=30.0,
            retryable_status_codes=[429, 503],
        )

        assert config.max_attempts == 5
        assert config.base_delay_seconds == 0.5
        assert config.max_delay_seconds == 30.0
        assert config.retryable_status_codes == [429, 503]


# =============================================================================
# LLM Config Tests
# =============================================================================


class TestLLMConfig:
    """Tests for LLM configuration."""

    def test_minimal_config(self) -> None:
        """Test minimal config with defaults."""
        config = LLMConfig()

        assert config.default_provider == "openai"
        assert config.default_model is None
        assert config.openai is None
        assert config.anthropic is None
        assert config.ollama is None

    def test_full_config(self) -> None:
        """Test full config with all providers."""
        config = LLMConfig(
            default_provider="anthropic",
            default_model="claude-sonnet-4-20250514",
            openai=OpenAIProviderConfig(api_key="openai-key"),
            anthropic=AnthropicProviderConfig(api_key="anthropic-key"),
            ollama=OllamaProviderConfig(),
            generic={
                "custom": GenericHTTPProviderConfig(
                    base_url="http://localhost:8000",
                    default_model="local-model",
                )
            },
        )

        assert config.default_provider == "anthropic"
        assert config.openai is not None
        assert config.anthropic is not None
        assert config.ollama is not None
        assert "custom" in config.generic


# =============================================================================
# Prompt Loader Tests
# =============================================================================


class TestPromptLoader:
    """Tests for prompt loading."""

    @pytest.fixture
    def layers_dir(self, tmp_path: Path) -> Path:
        """Create a temporary layers directory with prompts."""
        layer_dir = tmp_path / "test_layer" / "prompts"
        layer_dir.mkdir(parents=True)

        # Create system.j2
        (layer_dir / "system.j2").write_text(
            "You are a helpful assistant for {{ topic }}."
        )

        # Create main.j2
        (layer_dir / "main.j2").write_text(
            "Summarize the following:\n\n{{ content }}"
        )

        # Create versioned prompt
        (layer_dir / "main_v2.j2").write_text(
            "V2: Summarize this content:\n\n{{ content }}"
        )

        return tmp_path

    def test_load_prompt(self, layers_dir: Path) -> None:
        """Test loading and rendering a prompt."""
        from zos.llm.prompt import PromptLoader

        loader = PromptLoader(layers_dir)
        result = loader.load("test_layer", "system", {"topic": "testing"})

        assert result == "You are a helpful assistant for testing."

    def test_load_versioned_prompt(self, layers_dir: Path) -> None:
        """Test loading a versioned prompt."""
        from zos.llm.prompt import PromptLoader

        loader = PromptLoader(layers_dir)
        result = loader.load("test_layer", "main", {"content": "Hello"}, version=2)

        assert result == "V2: Summarize this content:\n\nHello"

    def test_prompt_not_found(self, layers_dir: Path) -> None:
        """Test error when prompt not found."""
        from zos.exceptions import LLMError
        from zos.llm.prompt import PromptLoader

        loader = PromptLoader(layers_dir)

        with pytest.raises(LLMError, match="Prompt template not found"):
            loader.load("test_layer", "nonexistent", {})

    def test_list_prompts(self, layers_dir: Path) -> None:
        """Test listing prompts for a layer."""
        from zos.llm.prompt import PromptLoader

        loader = PromptLoader(layers_dir)
        prompts = loader.list_prompts("test_layer")

        assert "system" in prompts
        assert "main" in prompts
        assert "main_v2" in prompts

    def test_list_prompt_versions(self, layers_dir: Path) -> None:
        """Test listing versions of a prompt."""
        from zos.llm.prompt import PromptLoader

        loader = PromptLoader(layers_dir)
        versions = loader.list_prompt_versions("test_layer", "main")

        assert None in versions  # Base version
        assert 2 in versions  # v2

    def test_prompt_exists(self, layers_dir: Path) -> None:
        """Test checking if prompt exists."""
        from zos.llm.prompt import PromptLoader

        loader = PromptLoader(layers_dir)

        assert loader.prompt_exists("test_layer", "system")
        assert loader.prompt_exists("test_layer", "main", version=2)
        assert not loader.prompt_exists("test_layer", "nonexistent")


# =============================================================================
# LLM Client Tests
# =============================================================================


class TestLLMClient:
    """Tests for LLM client facade."""

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Create a mock database."""
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = None
        return db

    @pytest.fixture
    def config(self) -> LLMConfig:
        """Create a test LLM config."""
        return LLMConfig(
            default_provider="openai",
            openai=OpenAIProviderConfig(
                api_key="test-key",
                default_model="gpt-4o-mini",
            ),
        )

    @pytest.mark.asyncio
    async def test_client_creates_provider(
        self, config: LLMConfig, mock_db: MagicMock, tmp_path: Path
    ) -> None:
        """Test client creates provider instances."""
        from zos.llm.client import LLMClient

        client = LLMClient(config, mock_db, tmp_path)

        # Provider should be created lazily
        assert len(client._providers) == 0

        # Access the provider
        provider = client._get_provider("openai")
        assert provider is not None
        assert len(client._providers) == 1

        await client.close()

    def test_client_unknown_provider(
        self, config: LLMConfig, mock_db: MagicMock, tmp_path: Path
    ) -> None:
        """Test error for unknown provider."""
        from zos.exceptions import LLMError
        from zos.llm.client import LLMClient

        client = LLMClient(config, mock_db, tmp_path)

        with pytest.raises(LLMError, match="Unknown provider"):
            client._get_provider("unknown")
