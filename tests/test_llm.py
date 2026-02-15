"""Tests for the LLM client.

Covers:
- Rate limiter functionality
- Model profile resolution
- Vision analysis method signature
- LLM call auditing
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from zos.config import Config, ModelProfile, ModelsConfig
from zos.database import create_tables, get_engine, layer_runs, llm_calls, metadata
from zos.llm import CompletionResult, ModelClient, RateLimiter, Usage, estimate_cost
from zos.models import LLMCallType, LayerRunStatus, generate_id


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


class TestModelClientWithEngine:
    """Tests for ModelClient with database engine for auditing."""

    def test_initialization_with_engine(self, tmp_path) -> None:
        """ModelClient initializes with engine for auditing."""
        config = Config(data_dir=tmp_path)
        engine = get_engine(config)
        create_tables(engine)
        client = ModelClient(config, engine=engine)

        assert client.config is config
        assert client.engine is engine
        assert client._anthropic is None

    def test_initialization_without_engine(self) -> None:
        """ModelClient works without engine (no auditing)."""
        config = Config()
        client = ModelClient(config)

        assert client.config is config
        assert client.engine is None


class TestLLMCallAuditing:
    """Tests for LLM call auditing functionality."""

    @pytest.fixture
    def db_engine(self, tmp_path):
        """Create a test database engine."""
        config = Config(data_dir=tmp_path)
        engine = get_engine(config)
        create_tables(engine)
        return engine

    @pytest.fixture
    def config_with_models(self):
        """Create a config with model profiles."""
        config = Config()
        config.models = ModelsConfig(
            profiles={
                "simple": ModelProfile(
                    provider="anthropic", model="claude-3-5-haiku-20241022"
                ),
                "vision": ModelProfile(
                    provider="anthropic", model="claude-3-5-haiku-20241022"
                ),
            },
            providers={"anthropic": {"api_key_env": "ANTHROPIC_API_KEY"}},
        )
        return config

    def _create_layer_run(self, engine, layer_run_id: str) -> None:
        """Create a layer_run record for testing foreign key constraints."""
        with engine.connect() as conn:
            conn.execute(
                layer_runs.insert().values(
                    id=layer_run_id,
                    layer_name="test-layer",
                    layer_hash="abc123",
                    started_at=datetime.now(timezone.utc),
                    status="success",
                    targets_matched=0,
                    targets_processed=0,
                    targets_skipped=0,
                    insights_created=0,
                )
            )
            conn.commit()

    @pytest.mark.asyncio
    async def test_complete_records_llm_call_when_layer_run_id_provided(
        self, db_engine, config_with_models
    ) -> None:
        """complete() records LLM call to database when layer_run_id is provided."""
        # Create a layer_run to satisfy foreign key constraint
        layer_run_id = "test-layer-run-123"
        self._create_layer_run(db_engine, layer_run_id)

        client = ModelClient(config_with_models, engine=db_engine)

        # Mock the rate limiter
        mock_limiter = MagicMock()
        mock_limiter.acquire = AsyncMock()
        client._rate_limiters["anthropic"] = mock_limiter

        # Mock the Anthropic client
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.object(client, "_get_anthropic") as mock_get_anthropic:
                mock_anthropic = MagicMock()
                mock_response = MagicMock()
                mock_response.content = [MagicMock(text="Hello, world!")]
                mock_response.usage.input_tokens = 100
                mock_response.usage.output_tokens = 50
                mock_anthropic.messages.create = AsyncMock(return_value=mock_response)
                mock_get_anthropic.return_value = mock_anthropic

                result = await client.complete(
                    prompt="Say hello",
                    model_profile="simple",
                    layer_run_id=layer_run_id,
                    topic_key="user:456",
                    call_type=LLMCallType.REFLECTION,
                )

        # Verify result
        assert result.text == "Hello, world!"
        assert result.usage.input_tokens == 100
        assert result.usage.output_tokens == 50

        # Verify LLM call was recorded
        with db_engine.connect() as conn:
            rows = list(conn.execute(select(llm_calls)))
            assert len(rows) == 1
            row = rows[0]
            assert row.layer_run_id == layer_run_id
            assert row.topic_key == "user:456"
            assert row.call_type == "reflection"
            assert row.model_profile == "simple"
            assert row.model_provider == "anthropic"
            assert row.model_name == "claude-3-5-haiku-20241022"
            assert row.prompt == "Say hello"
            assert row.response == "Hello, world!"
            assert row.tokens_input == 100
            assert row.tokens_output == 50
            assert row.tokens_total == 150
            assert row.success is True
            assert row.error_message is None
            assert row.latency_ms is not None
            assert row.latency_ms >= 0
            assert row.estimated_cost_usd is not None
            assert row.estimated_cost_usd > 0

    @pytest.mark.asyncio
    async def test_complete_records_without_layer_run_id(
        self, db_engine, config_with_models
    ) -> None:
        """complete() records LLM call even when layer_run_id is None.

        All LLM calls are recorded when engine is available. The layer_run_id
        is optional context that links the call to a layer run.
        """
        client = ModelClient(config_with_models, engine=db_engine)

        # Mock the rate limiter
        mock_limiter = MagicMock()
        mock_limiter.acquire = AsyncMock()
        client._rate_limiters["anthropic"] = mock_limiter

        # Mock the Anthropic client
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.object(client, "_get_anthropic") as mock_get_anthropic:
                mock_anthropic = MagicMock()
                mock_response = MagicMock()
                mock_response.content = [MagicMock(text="Hello!")]
                mock_response.usage.input_tokens = 50
                mock_response.usage.output_tokens = 25
                mock_anthropic.messages.create = AsyncMock(return_value=mock_response)
                mock_get_anthropic.return_value = mock_anthropic

                await client.complete(
                    prompt="Say hello",
                    model_profile="simple",
                    # No layer_run_id provided - still records
                )

        # Verify LLM call was recorded with null layer_run_id
        with db_engine.connect() as conn:
            rows = list(conn.execute(select(llm_calls)))
            assert len(rows) == 1
            row = rows[0]
            assert row.layer_run_id is None  # No layer context
            assert row.prompt == "Say hello"
            assert row.response == "Hello!"
            assert row.tokens_input == 50
            assert row.tokens_output == 25

    @pytest.mark.asyncio
    async def test_complete_no_recording_without_engine(
        self, config_with_models
    ) -> None:
        """complete() does not record LLM call when engine is None."""
        client = ModelClient(config_with_models)  # No engine

        # Mock the rate limiter
        mock_limiter = MagicMock()
        mock_limiter.acquire = AsyncMock()
        client._rate_limiters["anthropic"] = mock_limiter

        # Mock the Anthropic client
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.object(client, "_get_anthropic") as mock_get_anthropic:
                mock_anthropic = MagicMock()
                mock_response = MagicMock()
                mock_response.content = [MagicMock(text="Hello!")]
                mock_response.usage.input_tokens = 50
                mock_response.usage.output_tokens = 25
                mock_anthropic.messages.create = AsyncMock(return_value=mock_response)
                mock_get_anthropic.return_value = mock_anthropic

                # Should not raise even with layer_run_id
                result = await client.complete(
                    prompt="Say hello",
                    model_profile="simple",
                    layer_run_id="test-layer-run-123",
                )

        assert result.text == "Hello!"

    @pytest.mark.asyncio
    async def test_analyze_image_records_llm_call(
        self, db_engine, config_with_models
    ) -> None:
        """analyze_image() records LLM call to database when layer_run_id is provided."""
        # Create a layer_run to satisfy foreign key constraint
        layer_run_id = "vision-layer-run-789"
        self._create_layer_run(db_engine, layer_run_id)

        client = ModelClient(config_with_models, engine=db_engine)

        # Mock the rate limiter
        mock_limiter = MagicMock()
        mock_limiter.acquire = AsyncMock()
        client._rate_limiters["anthropic"] = mock_limiter

        # Mock the Anthropic client
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.object(client, "_get_anthropic") as mock_get_anthropic:
                mock_anthropic = MagicMock()
                mock_response = MagicMock()
                mock_response.content = [MagicMock(text="A beautiful sunset")]
                mock_response.usage.input_tokens = 200
                mock_response.usage.output_tokens = 30
                mock_anthropic.messages.create = AsyncMock(return_value=mock_response)
                mock_get_anthropic.return_value = mock_anthropic

                result = await client.analyze_image(
                    image_base64="abc123base64data",
                    media_type="image/png",
                    prompt="Describe this image",
                    model_profile="vision",
                    layer_run_id=layer_run_id,
                    topic_key="server:123:user:456",
                )

        # Verify result
        assert result.text == "A beautiful sunset"

        # Verify LLM call was recorded with vision-specific data
        with db_engine.connect() as conn:
            rows = list(conn.execute(select(llm_calls)))
            assert len(rows) == 1
            row = rows[0]
            assert row.layer_run_id == layer_run_id
            assert row.topic_key == "server:123:user:456"
            assert row.call_type == "vision"
            assert row.model_profile == "vision"
            assert row.model_provider == "anthropic"
            # Prompt includes image context indicator
            assert "[Image: image/png]" in row.prompt
            assert "Describe this image" in row.prompt
            assert row.response == "A beautiful sunset"
            assert row.tokens_input == 200
            assert row.tokens_output == 30

    @pytest.mark.asyncio
    async def test_complete_with_custom_call_type(
        self, db_engine, config_with_models
    ) -> None:
        """complete() records custom call_type correctly."""
        # Create a layer_run to satisfy foreign key constraint
        layer_run_id = "synthesis-run-001"
        self._create_layer_run(db_engine, layer_run_id)

        client = ModelClient(config_with_models, engine=db_engine)

        # Mock the rate limiter
        mock_limiter = MagicMock()
        mock_limiter.acquire = AsyncMock()
        client._rate_limiters["anthropic"] = mock_limiter

        # Mock the Anthropic client
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.object(client, "_get_anthropic") as mock_get_anthropic:
                mock_anthropic = MagicMock()
                mock_response = MagicMock()
                mock_response.content = [MagicMock(text="Synthesized insight")]
                mock_response.usage.input_tokens = 500
                mock_response.usage.output_tokens = 100
                mock_anthropic.messages.create = AsyncMock(return_value=mock_response)
                mock_get_anthropic.return_value = mock_anthropic

                await client.complete(
                    prompt="Synthesize these insights",
                    model_profile="simple",
                    layer_run_id=layer_run_id,
                    call_type=LLMCallType.SYNTHESIS,
                )

        # Verify call type was recorded
        with db_engine.connect() as conn:
            rows = list(conn.execute(select(llm_calls)))
            assert len(rows) == 1
            assert rows[0].call_type == "synthesis"

    @pytest.mark.asyncio
    async def test_complete_default_call_type_is_other(
        self, db_engine, config_with_models
    ) -> None:
        """complete() uses OTHER as default call_type."""
        # Create a layer_run to satisfy foreign key constraint
        layer_run_id = "test-run"
        self._create_layer_run(db_engine, layer_run_id)

        client = ModelClient(config_with_models, engine=db_engine)

        # Mock the rate limiter
        mock_limiter = MagicMock()
        mock_limiter.acquire = AsyncMock()
        client._rate_limiters["anthropic"] = mock_limiter

        # Mock the Anthropic client
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.object(client, "_get_anthropic") as mock_get_anthropic:
                mock_anthropic = MagicMock()
                mock_response = MagicMock()
                mock_response.content = [MagicMock(text="Response")]
                mock_response.usage.input_tokens = 50
                mock_response.usage.output_tokens = 20
                mock_anthropic.messages.create = AsyncMock(return_value=mock_response)
                mock_get_anthropic.return_value = mock_anthropic

                await client.complete(
                    prompt="Test",
                    model_profile="simple",
                    layer_run_id=layer_run_id,
                    # No call_type specified
                )

        # Verify default call type
        with db_engine.connect() as conn:
            rows = list(conn.execute(select(llm_calls)))
            assert len(rows) == 1
            assert rows[0].call_type == "other"

    @pytest.mark.asyncio
    async def test_analyze_image_default_call_type_is_vision(
        self, db_engine, config_with_models
    ) -> None:
        """analyze_image() uses VISION as default call_type."""
        # Create a layer_run to satisfy foreign key constraint
        layer_run_id = "vision-run"
        self._create_layer_run(db_engine, layer_run_id)

        client = ModelClient(config_with_models, engine=db_engine)

        # Mock the rate limiter
        mock_limiter = MagicMock()
        mock_limiter.acquire = AsyncMock()
        client._rate_limiters["anthropic"] = mock_limiter

        # Mock the Anthropic client
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.object(client, "_get_anthropic") as mock_get_anthropic:
                mock_anthropic = MagicMock()
                mock_response = MagicMock()
                mock_response.content = [MagicMock(text="Image description")]
                mock_response.usage.input_tokens = 150
                mock_response.usage.output_tokens = 40
                mock_anthropic.messages.create = AsyncMock(return_value=mock_response)
                mock_get_anthropic.return_value = mock_anthropic

                await client.analyze_image(
                    image_base64="base64data",
                    media_type="image/jpeg",
                    prompt="Describe",
                    model_profile="vision",
                    layer_run_id=layer_run_id,
                    # No call_type specified - should default to VISION
                )

        # Verify default call type for vision
        with db_engine.connect() as conn:
            rows = list(conn.execute(select(llm_calls)))
            assert len(rows) == 1
            assert rows[0].call_type == "vision"

    @pytest.mark.asyncio
    async def test_latency_tracking(
        self, db_engine, config_with_models
    ) -> None:
        """LLM call latency is tracked in milliseconds."""
        # Create a layer_run to satisfy foreign key constraint
        layer_run_id = "latency-test-run"
        self._create_layer_run(db_engine, layer_run_id)

        client = ModelClient(config_with_models, engine=db_engine)

        # Mock the rate limiter
        mock_limiter = MagicMock()
        mock_limiter.acquire = AsyncMock()
        client._rate_limiters["anthropic"] = mock_limiter

        # Mock the Anthropic client with a small delay
        async def delayed_create(*args, **kwargs):
            await asyncio.sleep(0.05)  # 50ms delay
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="Response")]
            mock_response.usage.input_tokens = 50
            mock_response.usage.output_tokens = 20
            return mock_response

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.object(client, "_get_anthropic") as mock_get_anthropic:
                mock_anthropic = MagicMock()
                mock_anthropic.messages.create = delayed_create
                mock_get_anthropic.return_value = mock_anthropic

                await client.complete(
                    prompt="Test",
                    model_profile="simple",
                    layer_run_id=layer_run_id,
                )

        # Verify latency was recorded (should be at least 50ms)
        with db_engine.connect() as conn:
            rows = list(conn.execute(select(llm_calls)))
            assert len(rows) == 1
            assert rows[0].latency_ms >= 50

    @pytest.mark.asyncio
    async def test_cost_estimation_recorded(
        self, db_engine, config_with_models
    ) -> None:
        """LLM call cost estimation is recorded."""
        # Create a layer_run to satisfy foreign key constraint
        layer_run_id = "cost-test-run"
        self._create_layer_run(db_engine, layer_run_id)

        client = ModelClient(config_with_models, engine=db_engine)

        # Mock the rate limiter
        mock_limiter = MagicMock()
        mock_limiter.acquire = AsyncMock()
        client._rate_limiters["anthropic"] = mock_limiter

        # Mock the Anthropic client
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.object(client, "_get_anthropic") as mock_get_anthropic:
                mock_anthropic = MagicMock()
                mock_response = MagicMock()
                mock_response.content = [MagicMock(text="Response")]
                # Use 1M tokens each for easy calculation
                mock_response.usage.input_tokens = 1_000_000
                mock_response.usage.output_tokens = 1_000_000
                mock_anthropic.messages.create = AsyncMock(return_value=mock_response)
                mock_get_anthropic.return_value = mock_anthropic

                await client.complete(
                    prompt="Test",
                    model_profile="simple",
                    layer_run_id=layer_run_id,
                )

        # Verify cost was calculated correctly (Haiku: $0.25/M + $1.25/M = $1.50)
        with db_engine.connect() as conn:
            rows = list(conn.execute(select(llm_calls)))
            assert len(rows) == 1
            assert rows[0].estimated_cost_usd == pytest.approx(1.50, rel=0.01)

    @pytest.mark.asyncio
    async def test_complete_returns_result_when_recording_fails(
        self, db_engine, config_with_models
    ) -> None:
        """complete() returns result even when _record_llm_call raises an exception.

        This is the primary fix for the link summaries NULL bug: if audit recording
        fails, the LLM result should still be returned to the caller.
        """
        client = ModelClient(config_with_models, engine=db_engine)

        # Mock the rate limiter
        mock_limiter = MagicMock()
        mock_limiter.acquire = AsyncMock()
        client._rate_limiters["anthropic"] = mock_limiter

        # Mock the Anthropic client
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.object(client, "_get_anthropic") as mock_get_anthropic:
                mock_anthropic = MagicMock()
                mock_response = MagicMock()
                mock_response.content = [MagicMock(text="Important result")]
                mock_response.usage.input_tokens = 100
                mock_response.usage.output_tokens = 50
                mock_anthropic.messages.create = AsyncMock(return_value=mock_response)
                mock_get_anthropic.return_value = mock_anthropic

                # Make _record_llm_call raise an exception
                with patch.object(
                    client, "_record_llm_call", side_effect=Exception("DB insert failed")
                ):
                    result = await client.complete(
                        prompt="Summarize this",
                        model_profile="simple",
                    )

        # Result should still be returned despite recording failure
        assert result.text == "Important result"
        assert result.usage.input_tokens == 100
        assert result.usage.output_tokens == 50

    @pytest.mark.asyncio
    async def test_analyze_image_returns_result_when_recording_fails(
        self, db_engine, config_with_models
    ) -> None:
        """analyze_image() returns result even when _record_llm_call raises."""
        client = ModelClient(config_with_models, engine=db_engine)

        # Mock the rate limiter
        mock_limiter = MagicMock()
        mock_limiter.acquire = AsyncMock()
        client._rate_limiters["anthropic"] = mock_limiter

        # Mock the Anthropic client
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.object(client, "_get_anthropic") as mock_get_anthropic:
                mock_anthropic = MagicMock()
                mock_response = MagicMock()
                mock_response.content = [MagicMock(text="A photo of a cat")]
                mock_response.usage.input_tokens = 200
                mock_response.usage.output_tokens = 30
                mock_anthropic.messages.create = AsyncMock(return_value=mock_response)
                mock_get_anthropic.return_value = mock_anthropic

                # Make _record_llm_call raise an exception
                with patch.object(
                    client, "_record_llm_call", side_effect=Exception("DB insert failed")
                ):
                    result = await client.analyze_image(
                        image_base64="abc123",
                        media_type="image/png",
                        prompt="Describe this",
                        model_profile="vision",
                    )

        # Result should still be returned despite recording failure
        assert result.text == "A photo of a cat"

    @pytest.mark.asyncio
    async def test_failed_call_recorded_in_database(
        self, db_engine, config_with_models
    ) -> None:
        """Failed LLM calls are recorded with success=False and error_message."""
        client = ModelClient(config_with_models, engine=db_engine)

        # Mock the rate limiter
        mock_limiter = MagicMock()
        mock_limiter.acquire = AsyncMock()
        client._rate_limiters["anthropic"] = mock_limiter

        # Mock _anthropic_complete to raise an API error
        api_error = Exception("Internal server error")
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.object(
                client, "_anthropic_complete", side_effect=api_error
            ):
                with pytest.raises(Exception, match="Internal server error"):
                    await client.complete(
                        prompt="Test prompt",
                        model_profile="simple",
                        layer_run_id=None,
                        topic_key="user:789",
                        call_type=LLMCallType.FILTER,
                    )

        # Verify the failed call was recorded
        with db_engine.connect() as conn:
            rows = list(conn.execute(select(llm_calls)))
            assert len(rows) == 1
            row = rows[0]
            assert row.success is False
            assert row.error_message == "Internal server error"
            assert row.call_type == "filter"
            assert row.topic_key == "user:789"
            assert row.response is None
            assert row.tokens_input == 0
            assert row.tokens_output == 0
            assert row.latency_ms >= 0
