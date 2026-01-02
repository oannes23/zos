"""Tests for layer schema models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from zos.layer.schema import (
    FetchInsightsConfig,
    FetchMessagesConfig,
    LayerDefinition,
    LLMCallConfig,
    ModelDefaults,
    OutputConfig,
    PipelineConfig,
    ReduceConfig,
    SalienceRulesConfig,
    StoreInsightConfig,
    TargetConfig,
)


class TestTargetConfig:
    """Tests for TargetConfig model."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = TargetConfig()
        assert config.categories == []
        assert config.min_salience == 0.0
        assert config.max_targets is None

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = TargetConfig(
            categories=["user", "channel"],
            min_salience=10.0,
            max_targets=20,
        )
        assert config.categories == ["user", "channel"]
        assert config.min_salience == 10.0
        assert config.max_targets == 20

    def test_min_salience_validation(self) -> None:
        """Test min_salience must be non-negative."""
        with pytest.raises(ValidationError):
            TargetConfig(min_salience=-1.0)

    def test_max_targets_validation(self) -> None:
        """Test max_targets must be positive if set."""
        with pytest.raises(ValidationError):
            TargetConfig(max_targets=0)


class TestSalienceRulesConfig:
    """Tests for SalienceRulesConfig model."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = SalienceRulesConfig()
        assert config.spend_per_target == 0.0
        assert config.spend_on_output == 0.0

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = SalienceRulesConfig(
            spend_per_target=1.5,
            spend_on_output=2.0,
        )
        assert config.spend_per_target == 1.5
        assert config.spend_on_output == 2.0


class TestModelDefaults:
    """Tests for ModelDefaults model."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = ModelDefaults()
        assert config.provider is None
        assert config.model is None
        assert config.temperature == 0.7
        assert config.max_tokens == 1024

    def test_temperature_range(self) -> None:
        """Test temperature validation."""
        # Valid range
        ModelDefaults(temperature=0.0)
        ModelDefaults(temperature=2.0)

        # Invalid range
        with pytest.raises(ValidationError):
            ModelDefaults(temperature=-0.1)
        with pytest.raises(ValidationError):
            ModelDefaults(temperature=2.1)


class TestNodeConfigs:
    """Tests for node configuration models."""

    def test_fetch_messages_config(self) -> None:
        """Test FetchMessagesConfig."""
        config = FetchMessagesConfig(type="fetch_messages")
        assert config.type == "fetch_messages"
        assert config.lookback_hours == 24
        assert config.max_messages == 100
        assert config.scope == "public"

    def test_fetch_messages_custom(self) -> None:
        """Test FetchMessagesConfig with custom values."""
        config = FetchMessagesConfig(
            type="fetch_messages",
            name="get_messages",
            lookback_hours=48,
            max_messages=200,
            scope="all",
        )
        assert config.name == "get_messages"
        assert config.lookback_hours == 48
        assert config.max_messages == 200
        assert config.scope == "all"

    def test_fetch_insights_config(self) -> None:
        """Test FetchInsightsConfig."""
        config = FetchInsightsConfig(type="fetch_insights")
        assert config.type == "fetch_insights"
        assert config.max_insights == 10

    def test_llm_call_config(self) -> None:
        """Test LLMCallConfig."""
        config = LLMCallConfig(type="llm_call", prompt="summarize")
        assert config.type == "llm_call"
        assert config.prompt == "summarize"
        assert config.system_prompt == "system"
        assert config.provider is None
        assert config.model is None

    def test_llm_call_config_requires_prompt(self) -> None:
        """Test LLMCallConfig requires prompt field."""
        with pytest.raises(ValidationError):
            LLMCallConfig(type="llm_call")  # Missing prompt

    def test_reduce_config(self) -> None:
        """Test ReduceConfig."""
        config = ReduceConfig(type="reduce")
        assert config.type == "reduce"
        assert config.strategy == "concatenate"
        assert config.separator == "\n\n---\n\n"

    def test_reduce_config_summarize(self) -> None:
        """Test ReduceConfig with summarize strategy."""
        config = ReduceConfig(
            type="reduce",
            strategy="summarize",
            prompt="summarize_outputs",
        )
        assert config.strategy == "summarize"
        assert config.prompt == "summarize_outputs"

    def test_store_insight_config(self) -> None:
        """Test StoreInsightConfig."""
        config = StoreInsightConfig(type="store_insight")
        assert config.type == "store_insight"

    def test_output_config(self) -> None:
        """Test OutputConfig."""
        config = OutputConfig(type="output")
        assert config.type == "output"
        assert config.destination == "log"
        assert config.channel_id is None

    def test_output_config_discord(self) -> None:
        """Test OutputConfig with discord destination."""
        config = OutputConfig(
            type="output",
            destination="discord",
            channel_id=12345,
        )
        assert config.destination == "discord"
        assert config.channel_id == 12345


class TestPipelineConfig:
    """Tests for PipelineConfig model."""

    def test_minimal_pipeline(self) -> None:
        """Test minimal pipeline configuration."""
        config = PipelineConfig(
            nodes=[FetchMessagesConfig(type="fetch_messages")]
        )
        assert config.for_each is None
        assert len(config.nodes) == 1

    def test_for_each_pipeline(self) -> None:
        """Test pipeline with for_each."""
        config = PipelineConfig(
            for_each="target",
            nodes=[
                FetchMessagesConfig(type="fetch_messages"),
                LLMCallConfig(type="llm_call", prompt="summarize"),
            ],
        )
        assert config.for_each == "target"
        assert len(config.nodes) == 2


class TestLayerDefinition:
    """Tests for LayerDefinition model."""

    def test_minimal_layer(self) -> None:
        """Test minimal layer definition."""
        layer = LayerDefinition(
            name="test_layer",
            pipeline=PipelineConfig(
                nodes=[FetchMessagesConfig(type="fetch_messages")]
            ),
        )
        assert layer.name == "test_layer"
        assert layer.description is None
        assert layer.schedule is None
        assert layer.targets.categories == []

    def test_full_layer(self) -> None:
        """Test full layer definition."""
        layer = LayerDefinition(
            name="channel_digest",
            description="Nightly channel summary",
            schedule="0 3 * * *",
            targets=TargetConfig(
                categories=["channel"],
                min_salience=10.0,
                max_targets=20,
            ),
            salience_rules=SalienceRulesConfig(
                spend_per_target=1.0,
            ),
            model_defaults=ModelDefaults(
                temperature=0.7,
                max_tokens=2048,
            ),
            pipeline=PipelineConfig(
                for_each="target",
                nodes=[
                    FetchMessagesConfig(type="fetch_messages", lookback_hours=24),
                    LLMCallConfig(type="llm_call", prompt="summarize"),
                    OutputConfig(type="output", destination="log"),
                ],
            ),
        )
        assert layer.name == "channel_digest"
        assert layer.description == "Nightly channel summary"
        assert layer.schedule == "0 3 * * *"
        assert layer.targets.categories == ["channel"]
        assert layer.salience_rules.spend_per_target == 1.0
        assert layer.model_defaults.max_tokens == 2048
        assert layer.pipeline.for_each == "target"
        assert len(layer.pipeline.nodes) == 3

    def test_layer_from_dict(self) -> None:
        """Test creating layer from dict (like YAML parse)."""
        data = {
            "name": "test_layer",
            "targets": {
                "categories": ["user", "channel"],
            },
            "pipeline": {
                "for_each": "target",
                "nodes": [
                    {"type": "fetch_messages", "lookback_hours": 12},
                    {"type": "llm_call", "prompt": "analyze"},
                ],
            },
        }
        layer = LayerDefinition(**data)
        assert layer.name == "test_layer"
        assert layer.targets.categories == ["user", "channel"]
        assert layer.pipeline.for_each == "target"
        assert len(layer.pipeline.nodes) == 2
