"""Pydantic models for layer YAML schema.

Defines the structure of layer definitions loaded from YAML files.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class TargetConfig(BaseModel):
    """Target topic selection configuration."""

    categories: list[str] = Field(
        default_factory=list,
        description="Topic categories to target (user, channel, etc.)",
    )
    min_salience: float = Field(
        default=0.0,
        ge=0.0,
        description="Minimum salience balance to qualify",
    )
    max_targets: int | None = Field(
        default=None,
        ge=1,
        description="Max targets per category (None = all qualifying)",
    )


class SalienceRulesConfig(BaseModel):
    """How salience is spent during layer execution."""

    spend_per_target: float = Field(
        default=0.0,
        ge=0.0,
        description="Salience spent per target processed",
    )
    spend_on_output: float = Field(
        default=0.0,
        ge=0.0,
        description="Additional salience spent when output generated",
    )


class ModelDefaults(BaseModel):
    """Default model settings for the layer."""

    provider: str | None = Field(default=None, description="LLM provider name")
    model: str | None = Field(default=None, description="Model identifier")
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Sampling temperature",
    )
    max_tokens: int = Field(
        default=1024,
        ge=1,
        description="Maximum tokens to generate",
    )


# Node configuration models


class BaseNodeConfig(BaseModel):
    """Base configuration for pipeline nodes."""

    type: str = Field(description="Node type identifier")
    name: str | None = Field(
        default=None,
        description="Optional name for logging/reference",
    )


class FetchMessagesConfig(BaseNodeConfig):
    """Configuration for fetch_messages node."""

    type: Literal["fetch_messages"] = "fetch_messages"
    lookback_hours: int = Field(
        default=24,
        ge=1,
        description="Hours to look back for messages",
    )
    max_messages: int = Field(
        default=100,
        ge=1,
        description="Maximum messages to retrieve",
    )
    scope: Literal["public", "dm", "all"] = Field(
        default="public",
        description="Visibility scope filter",
    )


class FetchInsightsConfig(BaseNodeConfig):
    """Configuration for fetch_insights node."""

    type: Literal["fetch_insights"] = "fetch_insights"
    max_insights: int = Field(
        default=10,
        ge=1,
        description="Maximum insights to retrieve",
    )
    scope: Literal["public", "dm", "all"] = Field(
        default="all",
        description="Filter by privacy scope (public, dm, or all)",
    )
    since_hours: int | None = Field(
        default=None,
        ge=1,
        description="Only fetch insights from the last N hours (None for all time)",
    )


class LLMCallConfig(BaseNodeConfig):
    """Configuration for llm_call node."""

    type: Literal["llm_call"] = "llm_call"
    prompt: str = Field(description="Prompt template name (without .j2)")
    system_prompt: str | None = Field(
        default="system",
        description="System prompt template name (None to skip)",
    )
    provider: str | None = Field(
        default=None,
        description="Provider override (uses layer/global default if None)",
    )
    model: str | None = Field(
        default=None,
        description="Model override (uses layer/global default if None)",
    )
    temperature: float | None = Field(
        default=None,
        description="Temperature override",
    )
    max_tokens: int | None = Field(
        default=None,
        description="Max tokens override",
    )


class ReduceConfig(BaseNodeConfig):
    """Configuration for reduce node."""

    type: Literal["reduce"] = "reduce"
    strategy: Literal["concatenate", "summarize"] = Field(
        default="concatenate",
        description="Reduction strategy",
    )
    separator: str = Field(
        default="\n\n---\n\n",
        description="Separator for concatenation",
    )
    prompt: str | None = Field(
        default=None,
        description="Prompt template for summarize strategy",
    )
    # LLM options for summarize strategy
    provider: str | None = Field(
        default=None,
        description="Provider override for summarize (uses layer/global default if None)",
    )
    model: str | None = Field(
        default=None,
        description="Model override for summarize (uses layer/global default if None)",
    )
    temperature: float | None = Field(
        default=None,
        description="Temperature override for summarize",
    )
    max_tokens: int | None = Field(
        default=None,
        description="Max tokens override for summarize",
    )


class StoreInsightConfig(BaseNodeConfig):
    """Configuration for store_insight node."""

    type: Literal["store_insight"] = "store_insight"
    include_payload: bool = Field(
        default=False,
        description="Include structured payload data in stored insight",
    )


class OutputConfig(BaseNodeConfig):
    """Configuration for output node."""

    type: Literal["output"] = "output"
    destination: Literal["discord", "log", "none"] = Field(
        default="log",
        description="Output destination",
    )
    channel_id: int | None = Field(
        default=None,
        description="Discord channel ID (required for discord destination)",
    )


# Union type for any node config - must be Annotated for Pydantic discriminated union
AnyNodeConfig = Annotated[
    FetchMessagesConfig
    | FetchInsightsConfig
    | LLMCallConfig
    | ReduceConfig
    | StoreInsightConfig
    | OutputConfig,
    Field(discriminator="type"),
]


class PipelineConfig(BaseModel):
    """Pipeline definition with optional for_each expansion."""

    for_each: Literal["target"] | None = Field(
        default=None,
        description="Expand pipeline for each target topic",
    )
    nodes: list[AnyNodeConfig] = Field(
        description="Ordered list of nodes to execute",
    )


class LayerDefinition(BaseModel):
    """Complete layer definition from YAML."""

    name: str = Field(description="Unique layer identifier")
    description: str | None = Field(
        default=None,
        description="Human-readable layer description",
    )
    schedule: str | None = Field(
        default=None,
        description="Cron expression for scheduled execution",
    )
    max_lookback_hours: int = Field(
        default=168,  # 1 week
        ge=1,
        description="Maximum hours to look back for messages (default: 168 = 1 week)",
    )
    targets: TargetConfig = Field(
        default_factory=TargetConfig,
        description="Target topic selection configuration",
    )
    salience_rules: SalienceRulesConfig = Field(
        default_factory=SalienceRulesConfig,
        description="Salience spending rules",
    )
    model_defaults: ModelDefaults = Field(
        default_factory=ModelDefaults,
        description="Default model settings",
    )
    pipeline: PipelineConfig = Field(
        description="Pipeline definition",
    )
