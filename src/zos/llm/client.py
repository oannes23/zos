"""High-level LLM client facade.

Provides a unified interface for LLM completions with:
- Automatic model resolution (node > layer > global)
- Retry with exponential backoff
- Cost estimation and tracking
- Provider abstraction
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from zos.budget.models import LLMCallRecord
from zos.budget.tracker import CostTracker
from zos.exceptions import LLMError
from zos.llm.config import LLMConfig
from zos.llm.prompt import PromptLoader
from zos.llm.provider import LLMProvider, LLMResponse, Message
from zos.llm.resolver import resolve_model
from zos.llm.retry import with_retry
from zos.logging import get_logger
from zos.topics.topic_key import TopicKey

if TYPE_CHECKING:
    from zos.db import Database

logger = get_logger("llm.client")


class LLMClient:
    """High-level LLM client with automatic retry, cost tracking, and model resolution.

    This is the primary interface for making LLM calls from layers.
    It handles provider selection, retries, and cost recording.
    """

    def __init__(
        self,
        config: LLMConfig,
        db: Database,
        layers_dir: Path,
    ) -> None:
        """Initialize the LLM client.

        Args:
            config: LLM configuration with provider settings.
            db: Database for cost tracking.
            layers_dir: Directory containing layer definitions (for prompts).
        """
        self.config = config
        self._db = db
        self._cost_tracker = CostTracker(db)
        self._prompt_loader = PromptLoader(layers_dir)
        self._providers: dict[str, LLMProvider] = {}

    @property
    def prompts(self) -> PromptLoader:
        """Get the prompt loader for rendering templates."""
        return self._prompt_loader

    def _get_provider(self, provider_name: str) -> LLMProvider:
        """Get or create a provider instance.

        Args:
            provider_name: Name of the provider.

        Returns:
            LLMProvider instance.

        Raises:
            LLMError: If provider is not configured.
        """
        if provider_name in self._providers:
            return self._providers[provider_name]

        provider = self._create_provider(provider_name)
        self._providers[provider_name] = provider
        return provider

    def _create_provider(self, provider_name: str) -> LLMProvider:
        """Create a new provider instance.

        Args:
            provider_name: Name of the provider.

        Returns:
            New LLMProvider instance.

        Raises:
            LLMError: If provider is not configured or unknown.
        """
        if provider_name == "openai":
            if not self.config.openai:
                raise LLMError("OpenAI provider not configured")
            from zos.llm.providers.openai import OpenAIProvider

            return OpenAIProvider(self.config.openai)

        elif provider_name == "anthropic":
            if not self.config.anthropic:
                raise LLMError("Anthropic provider not configured")
            from zos.llm.providers.anthropic import AnthropicProvider

            return AnthropicProvider(self.config.anthropic)

        elif provider_name == "ollama":
            if not self.config.ollama:
                raise LLMError("Ollama provider not configured")
            from zos.llm.providers.ollama import OllamaProvider

            return OllamaProvider(self.config.ollama)

        elif provider_name in self.config.generic:
            from zos.llm.providers.generic import GenericHTTPProvider

            return GenericHTTPProvider(
                self.config.generic[provider_name],
                provider_name,
            )

        else:
            raise LLMError(f"Unknown provider: {provider_name}")

    async def complete(
        self,
        messages: list[Message],
        *,
        run_id: str,
        layer: str,
        node: str | None = None,
        topic_key: TopicKey | None = None,
        provider: str | None = None,
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a completion with automatic retry and cost tracking.

        Args:
            messages: List of conversation messages.
            run_id: Run ID for cost tracking.
            layer: Layer name for cost tracking.
            node: Node name within the layer (optional).
            topic_key: Topic being processed (optional).
            provider: Provider override (uses resolution if None).
            model: Model override (uses resolution if None).
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.
            **kwargs: Additional provider-specific options.

        Returns:
            LLMResponse with content and token counts.

        Raises:
            LLMError: On API errors after retry exhaustion.
        """
        # Resolve model selection
        selection = resolve_model(
            self.config,
            layer_provider=None,  # TODO: Load from layer config
            layer_model=None,
            node_provider=provider,
            node_model=model,
        )

        logger.debug(
            f"Resolved model: provider={selection.provider}, "
            f"model={selection.model}, source={selection.source}"
        )

        # Get the provider
        llm_provider = self._get_provider(selection.provider)

        # Execute with retry
        async def do_complete() -> LLMResponse:
            return await llm_provider.complete(
                messages,
                model=selection.model,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs,
            )

        response = await with_retry(
            do_complete,
            self.config.retry,
            operation_name=f"{selection.provider}/{selection.model}",
        )

        # Estimate cost
        estimated_cost = llm_provider.estimate_cost(
            response.model,
            response.prompt_tokens,
            response.completion_tokens,
        )

        # Record the call
        record = LLMCallRecord(
            run_id=run_id,
            topic_key=topic_key,
            layer=layer,
            node=node,
            model=response.model,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            estimated_cost_usd=estimated_cost,
        )
        self._cost_tracker.record_call(record)

        logger.info(
            f"LLM call: {response.model} "
            f"[{response.prompt_tokens}+{response.completion_tokens} tokens] "
            f"[${estimated_cost:.4f}]" if estimated_cost else ""
        )

        return response

    async def complete_with_prompt(
        self,
        layer_name: str,
        prompt_name: str,
        context: dict[str, Any],
        *,
        run_id: str,
        node: str | None = None,
        topic_key: TopicKey | None = None,
        system_prompt_name: str | None = "system",
        prompt_version: int | None = None,
        provider: str | None = None,
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a completion using prompt templates.

        Convenience method that loads and renders prompts before calling complete().

        Args:
            layer_name: Name of the layer (for prompt lookup).
            prompt_name: Name of the user prompt template.
            context: Variables to pass to the prompt templates.
            run_id: Run ID for cost tracking.
            node: Node name within the layer (optional).
            topic_key: Topic being processed (optional).
            system_prompt_name: Name of system prompt (None to skip).
            prompt_version: Version of prompts to use (optional).
            provider: Provider override.
            model: Model override.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.
            **kwargs: Additional provider-specific options.

        Returns:
            LLMResponse with content and token counts.
        """
        from zos.llm.provider import MessageRole

        messages: list[Message] = []

        # Load and render system prompt
        if system_prompt_name and self._prompt_loader.prompt_exists(
            layer_name, system_prompt_name, prompt_version
        ):
            system_content = self._prompt_loader.load(
                layer_name, system_prompt_name, context, prompt_version
            )
            messages.append(Message(role=MessageRole.SYSTEM, content=system_content))

        # Load and render user prompt
        user_content = self._prompt_loader.load(
            layer_name, prompt_name, context, prompt_version
        )
        messages.append(Message(role=MessageRole.USER, content=user_content))

        return await self.complete(
            messages,
            run_id=run_id,
            layer=layer_name,
            node=node,
            topic_key=topic_key,
            provider=provider,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )

    async def close(self) -> None:
        """Close all provider connections."""
        for provider in self._providers.values():
            if hasattr(provider, "close"):
                await provider.close()
        self._providers.clear()

    def get_run_cost(self, run_id: str) -> dict[str, Any]:
        """Get total cost for a run.

        Args:
            run_id: The run to query.

        Returns:
            Dict with token totals and estimated cost.
        """
        return self._cost_tracker.get_run_totals(run_id)

    def get_calls_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """Get all LLM calls for a run.

        Args:
            run_id: The run to query.

        Returns:
            List of call records.
        """
        return self._cost_tracker.get_calls_for_run(run_id)
