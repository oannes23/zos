"""Tests for LLM abstraction layer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from zos.config import DatabaseConfig
from zos.db import Database
from zos.exceptions import LLMError
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
from zos.llm.resolver import get_available_providers, resolve_model
from zos.llm.retry import (
    RetryableError,
    calculate_delay,
    is_retryable_error,
    with_retry,
)

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
        from zos.llm.client import LLMClient

        client = LLMClient(config, mock_db, tmp_path)

        with pytest.raises(LLMError, match="Unknown provider"):
            client._get_provider("unknown")


# =============================================================================
# Retry Logic Tests
# =============================================================================


class TestRetryLogic:
    """Tests for retry logic functions."""

    @pytest.fixture
    def config(self) -> RetryConfig:
        """Create a test retry config."""
        return RetryConfig(
            max_attempts=3,
            base_delay_seconds=1.0,
            max_delay_seconds=60.0,
            exponential_base=2.0,
            retryable_status_codes=[429, 500, 502, 503, 504],
        )

    # calculate_delay tests

    def test_calculate_delay_first_attempt(self, config: RetryConfig) -> None:
        """First attempt delay is around base delay (with jitter)."""
        with patch("zos.llm.retry.random.random", return_value=0.5):
            delay = calculate_delay(1, config)
            # base_delay * (2^0) = 1.0, jitter at 0.5 means 0 offset
            assert delay == 1.0

    def test_calculate_delay_exponential_growth(self, config: RetryConfig) -> None:
        """Delay grows exponentially with attempts."""
        with patch("zos.llm.retry.random.random", return_value=0.5):
            delay1 = calculate_delay(1, config)  # 1.0 * 2^0 = 1.0
            delay2 = calculate_delay(2, config)  # 1.0 * 2^1 = 2.0
            delay3 = calculate_delay(3, config)  # 1.0 * 2^2 = 4.0

            assert delay1 == 1.0
            assert delay2 == 2.0
            assert delay3 == 4.0

    def test_calculate_delay_capped_at_max(self, config: RetryConfig) -> None:
        """Delay never exceeds max_delay_seconds."""
        config.max_delay_seconds = 5.0
        with patch("zos.llm.retry.random.random", return_value=0.5):
            # Attempt 10: 1.0 * 2^9 = 512, but capped at 5.0
            delay = calculate_delay(10, config)
            assert delay == 5.0

    def test_calculate_delay_has_jitter(self, config: RetryConfig) -> None:
        """Delay varies with ±25% jitter."""
        # Min jitter (random=0): delay - 25%
        with patch("zos.llm.retry.random.random", return_value=0.0):
            min_delay = calculate_delay(1, config)
            assert min_delay == pytest.approx(0.75, rel=0.01)  # 1.0 - 0.25

        # Max jitter (random=1): delay + 25%
        with patch("zos.llm.retry.random.random", return_value=1.0):
            max_delay = calculate_delay(1, config)
            assert max_delay == pytest.approx(1.25, rel=0.01)  # 1.0 + 0.25

    # is_retryable_error tests

    def test_retryable_error_with_429(self, config: RetryConfig) -> None:
        """RetryableError with 429 is retryable."""
        error = RetryableError("Rate limited", status_code=429)
        assert is_retryable_error(error, config) is True

    def test_retryable_error_with_500(self, config: RetryConfig) -> None:
        """RetryableError with 500 is retryable."""
        error = RetryableError("Server error", status_code=500)
        assert is_retryable_error(error, config) is True

    def test_retryable_error_with_400_not_retryable(self, config: RetryConfig) -> None:
        """RetryableError with 400 is not retryable."""
        error = RetryableError("Bad request", status_code=400)
        assert is_retryable_error(error, config) is False

    def test_httpx_status_error_retryable(self, config: RetryConfig) -> None:
        """httpx.HTTPStatusError with 429 is retryable."""
        request = httpx.Request("GET", "https://api.example.com")
        response = httpx.Response(429, request=request)
        error = httpx.HTTPStatusError("Rate limited", request=request, response=response)
        assert is_retryable_error(error, config) is True

    def test_httpx_connect_error_retryable(self, config: RetryConfig) -> None:
        """httpx.ConnectError is retryable."""
        error = httpx.ConnectError("Connection refused")
        assert is_retryable_error(error, config) is True

    def test_httpx_timeout_retryable(self, config: RetryConfig) -> None:
        """httpx.ReadTimeout and WriteTimeout are retryable."""
        read_error = httpx.ReadTimeout("Read timed out")
        write_error = httpx.WriteTimeout("Write timed out")

        assert is_retryable_error(read_error, config) is True
        assert is_retryable_error(write_error, config) is True

    def test_generic_exception_not_retryable(self, config: RetryConfig) -> None:
        """Generic exceptions are not retryable."""
        error = ValueError("Some error")
        assert is_retryable_error(error, config) is False

    # with_retry tests

    @pytest.mark.asyncio
    async def test_with_retry_success_first_try(self, config: RetryConfig) -> None:
        """Successful call returns immediately."""
        call_count = 0

        async def success_fn() -> str:
            nonlocal call_count
            call_count += 1
            return "success"

        result = await with_retry(success_fn, config)
        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_with_retry_success_after_retries(self, config: RetryConfig) -> None:
        """Call succeeds after transient failures."""
        call_count = 0
        config.base_delay_seconds = 0.01  # Fast retries for test

        async def flaky_fn() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RetryableError("Transient error", status_code=429)
            return "success"

        result = await with_retry(flaky_fn, config)
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_with_retry_exhausts_attempts(self, config: RetryConfig) -> None:
        """Raises LLMError after max attempts."""
        call_count = 0
        config.base_delay_seconds = 0.01

        async def always_fail() -> str:
            nonlocal call_count
            call_count += 1
            raise RetryableError("Always fails", status_code=429)

        with pytest.raises(LLMError, match="failed after 3 attempts"):
            await with_retry(always_fail, config)

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_with_retry_non_retryable_raises_immediately(
        self, config: RetryConfig
    ) -> None:
        """Non-retryable errors raise without retry."""
        call_count = 0

        async def bad_request() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("Invalid input")

        with pytest.raises(ValueError, match="Invalid input"):
            await with_retry(bad_request, config)

        assert call_count == 1  # No retries


# =============================================================================
# LLM Client Complete Tests
# =============================================================================


class TestLLMClientComplete:
    """Tests for LLMClient.complete() method."""

    @pytest.fixture
    def test_db(self, tmp_path: Path) -> Database:
        """Create a test database."""
        config = DatabaseConfig(path=tmp_path / "test.db")
        db = Database(config)
        db.initialize()
        return db

    @pytest.fixture
    def config(self) -> LLMConfig:
        """Create a test LLM config with mock provider."""
        return LLMConfig(
            default_provider="mock",
            default_model="mock-model",
        )

    @pytest.fixture
    def layers_dir(self, tmp_path: Path) -> Path:
        """Create a temporary layers directory."""
        return tmp_path / "layers"

    @pytest.mark.asyncio
    async def test_complete_returns_response(
        self, config: LLMConfig, test_db: Database, layers_dir: Path
    ) -> None:
        """complete() returns LLMResponse with content."""
        from zos.llm.client import LLMClient

        client = LLMClient(config, test_db, layers_dir)
        # Inject mock provider
        mock_provider = MockProvider()
        mock_provider.queue_response("Test response")
        client._providers["mock"] = mock_provider

        messages = [Message(role=MessageRole.USER, content="Hello")]
        response = await client.complete(
            messages, run_id="test-run", layer="test-layer"
        )

        assert response.content == "Test response"
        await client.close()

    @pytest.mark.asyncio
    async def test_complete_records_cost(
        self, config: LLMConfig, test_db: Database, layers_dir: Path
    ) -> None:
        """complete() records call to CostTracker."""
        from zos.llm.client import LLMClient

        client = LLMClient(config, test_db, layers_dir)
        mock_provider = MockProvider()
        client._providers["mock"] = mock_provider

        messages = [Message(role=MessageRole.USER, content="Hello")]
        await client.complete(messages, run_id="test-run", layer="test-layer")

        # Check that cost was recorded in database
        result = test_db.execute(
            "SELECT run_id, layer, prompt_tokens, completion_tokens FROM llm_calls"
        ).fetchone()

        assert result is not None
        assert result["run_id"] == "test-run"
        assert result["layer"] == "test-layer"
        assert result["prompt_tokens"] == 10  # MockProvider default
        assert result["completion_tokens"] == 20  # MockProvider default

        await client.close()

    @pytest.mark.asyncio
    async def test_complete_uses_model_resolution(
        self, test_db: Database, layers_dir: Path
    ) -> None:
        """complete() uses resolved provider/model."""
        from zos.llm.client import LLMClient

        config = LLMConfig(
            default_provider="mock",
            default_model="default-model",
        )
        client = LLMClient(config, test_db, layers_dir)
        mock_provider = MockProvider()
        client._providers["mock"] = mock_provider

        messages = [Message(role=MessageRole.USER, content="Hello")]
        await client.complete(messages, run_id="test-run", layer="test-layer")

        # Check that the resolved model was passed to provider
        assert mock_provider.last_call is not None
        assert mock_provider.last_call.model == "default-model"

        await client.close()

    @pytest.mark.asyncio
    async def test_complete_with_model_override(
        self, config: LLMConfig, test_db: Database, layers_dir: Path
    ) -> None:
        """Model parameter overrides default."""
        from zos.llm.client import LLMClient

        client = LLMClient(config, test_db, layers_dir)
        mock_provider = MockProvider()
        client._providers["mock"] = mock_provider

        messages = [Message(role=MessageRole.USER, content="Hello")]
        await client.complete(
            messages,
            run_id="test-run",
            layer="test-layer",
            model="override-model",
        )

        assert mock_provider.last_call is not None
        assert mock_provider.last_call.model == "override-model"

        await client.close()

    @pytest.mark.asyncio
    async def test_complete_with_retry_on_failure(
        self, config: LLMConfig, test_db: Database, layers_dir: Path
    ) -> None:
        """complete() retries on transient errors."""
        from zos.llm.client import LLMClient

        # Fast retries for test
        config.retry = RetryConfig(
            max_attempts=3,
            base_delay_seconds=0.01,
        )

        client = LLMClient(config, test_db, layers_dir)
        mock_provider = MockProvider()
        # Queue an error then a success
        mock_provider.queue_response(error=RetryableError("Transient", status_code=429))
        mock_provider.queue_response("Success after retry")
        client._providers["mock"] = mock_provider

        messages = [Message(role=MessageRole.USER, content="Hello")]
        response = await client.complete(
            messages, run_id="test-run", layer="test-layer"
        )

        assert response.content == "Success after retry"
        assert mock_provider.call_count == 2

        await client.close()


# =============================================================================
# LLM Client Complete With Prompt Tests
# =============================================================================


class TestLLMClientCompleteWithPrompt:
    """Tests for LLMClient.complete_with_prompt() method."""

    @pytest.fixture
    def test_db(self, tmp_path: Path) -> Database:
        """Create a test database."""
        config = DatabaseConfig(path=tmp_path / "test.db")
        db = Database(config)
        db.initialize()
        return db

    @pytest.fixture
    def config(self) -> LLMConfig:
        """Create a test LLM config with mock provider."""
        return LLMConfig(
            default_provider="mock",
            default_model="mock-model",
        )

    @pytest.fixture
    def layers_dir(self, tmp_path: Path) -> Path:
        """Create a temporary layers directory with prompts."""
        layer_dir = tmp_path / "test_layer" / "prompts"
        layer_dir.mkdir(parents=True)

        # Create system.j2
        (layer_dir / "system.j2").write_text(
            "You are an assistant for {{ topic }}."
        )

        # Create main.j2
        (layer_dir / "main.j2").write_text(
            "Process this: {{ content }}"
        )

        return tmp_path

    @pytest.mark.asyncio
    async def test_complete_with_prompt_renders_template(
        self, config: LLMConfig, test_db: Database, layers_dir: Path
    ) -> None:
        """Prompt templates are rendered with context."""
        from zos.llm.client import LLMClient

        client = LLMClient(config, test_db, layers_dir)
        mock_provider = MockProvider()
        client._providers["mock"] = mock_provider

        await client.complete_with_prompt(
            layer_name="test_layer",
            prompt_name="main",
            context={"content": "Hello World", "topic": "testing"},
            run_id="test-run",
        )

        # Check that the user message was rendered
        assert mock_provider.last_call is not None
        messages = mock_provider.last_call.messages
        user_message = next(m for m in messages if m.role == MessageRole.USER)
        assert user_message.content == "Process this: Hello World"

        await client.close()

    @pytest.mark.asyncio
    async def test_complete_with_prompt_includes_system(
        self, config: LLMConfig, test_db: Database, layers_dir: Path
    ) -> None:
        """System prompt is included when it exists."""
        from zos.llm.client import LLMClient

        client = LLMClient(config, test_db, layers_dir)
        mock_provider = MockProvider()
        client._providers["mock"] = mock_provider

        await client.complete_with_prompt(
            layer_name="test_layer",
            prompt_name="main",
            context={"content": "Hello", "topic": "testing"},
            run_id="test-run",
        )

        messages = mock_provider.last_call.messages
        system_message = next(
            (m for m in messages if m.role == MessageRole.SYSTEM), None
        )
        assert system_message is not None
        assert system_message.content == "You are an assistant for testing."

        await client.close()

    @pytest.mark.asyncio
    async def test_complete_with_prompt_no_system(
        self, config: LLMConfig, test_db: Database, layers_dir: Path
    ) -> None:
        """No system message when system_prompt_name=None."""
        from zos.llm.client import LLMClient

        client = LLMClient(config, test_db, layers_dir)
        mock_provider = MockProvider()
        client._providers["mock"] = mock_provider

        await client.complete_with_prompt(
            layer_name="test_layer",
            prompt_name="main",
            context={"content": "Hello", "topic": "testing"},
            run_id="test-run",
            system_prompt_name=None,  # Explicitly no system prompt
        )

        messages = mock_provider.last_call.messages
        system_messages = [m for m in messages if m.role == MessageRole.SYSTEM]
        assert len(system_messages) == 0

        await client.close()
