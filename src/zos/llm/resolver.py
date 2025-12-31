"""Model resolution for LLM requests.

Implements a hierarchical resolution strategy:
node settings > layer settings > global config
"""

from dataclasses import dataclass
from typing import Literal

from zos.llm.config import LLMConfig


@dataclass(frozen=True)
class ModelSelection:
    """Result of model resolution."""

    provider: str
    model: str
    source: Literal["node", "layer", "global", "provider_default"]


def resolve_model(
    config: LLMConfig,
    *,
    layer_provider: str | None = None,
    layer_model: str | None = None,
    node_provider: str | None = None,
    node_model: str | None = None,
) -> ModelSelection:
    """Resolve which provider and model to use.

    Priority (highest to lowest):
    1. Node-level settings (from layer node config)
    2. Layer-level settings (from layer config)
    3. Global config settings (from LLMConfig)
    4. Provider defaults

    Args:
        config: Global LLM configuration.
        layer_provider: Provider override from layer config.
        layer_model: Model override from layer config.
        node_provider: Provider override from layer node config.
        node_model: Model override from layer node config.

    Returns:
        ModelSelection with resolved provider, model, and source.
    """
    # Determine provider (node > layer > global)
    if node_provider:
        provider = node_provider
        provider_source = "node"
    elif layer_provider:
        provider = layer_provider
        provider_source = "layer"
    else:
        provider = config.default_provider
        provider_source = "global"

    # Determine model (node > layer > global > provider_default)
    if node_model:
        model = node_model
        source: Literal["node", "layer", "global", "provider_default"] = "node"
    elif layer_model:
        model = layer_model
        source = "layer"
    elif config.default_model:
        model = config.default_model
        source = "global"
    else:
        # Use provider's default model
        model = _get_provider_default_model(config, provider)
        source = "provider_default"

    # If source is from provider_source and model came from provider default,
    # the overall source should reflect where we got the provider from
    if source == "provider_default" and provider_source != "global":
        # Model is default but provider was specified at node/layer level
        pass  # Keep source as provider_default for clarity

    return ModelSelection(provider=provider, model=model, source=source)


def _get_provider_default_model(config: LLMConfig, provider: str) -> str:
    """Get the default model for a provider.

    Args:
        config: LLM configuration with provider configs.
        provider: Provider name.

    Returns:
        Default model for the provider.

    Raises:
        ValueError: If provider is not configured.
    """
    if provider == "openai":
        if config.openai:
            return config.openai.default_model
        return "gpt-4o-mini"  # Fallback
    elif provider == "anthropic":
        if config.anthropic:
            return config.anthropic.default_model
        return "claude-sonnet-4-20250514"  # Fallback
    elif provider == "ollama":
        if config.ollama:
            return config.ollama.default_model
        return "llama3.2"  # Fallback
    elif provider in config.generic:
        return config.generic[provider].default_model
    else:
        # Unknown provider, return generic default
        return "default"


def get_available_providers(config: LLMConfig) -> list[str]:
    """Get list of configured providers.

    Args:
        config: LLM configuration.

    Returns:
        List of provider names that are configured (have API keys or URLs).
    """
    providers = []

    if config.openai and config.openai.api_key:
        providers.append("openai")

    if config.anthropic and config.anthropic.api_key:
        providers.append("anthropic")

    if config.ollama:
        # Ollama doesn't need API key
        providers.append("ollama")

    # Add generic providers
    for name in config.generic:
        providers.append(name)

    return providers
