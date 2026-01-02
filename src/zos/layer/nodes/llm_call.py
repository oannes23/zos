"""LLMCall node for executing LLM completions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from zos.exceptions import LLMError
from zos.layer.nodes.base import BaseNode, NodeResult
from zos.logging import get_logger

if TYPE_CHECKING:
    from zos.layer.context import PipelineContext
    from zos.layer.schema import LLMCallConfig

logger = get_logger("layer.nodes.llm_call")

# Default token estimation for budget checking
DEFAULT_ESTIMATED_TOKENS = 500


class LLMCallNode(BaseNode):
    """Execute an LLM completion using prompt templates.

    Loads prompts from the layer's prompts/ directory, renders them
    with context data, and calls the LLM.

    Checks budget before calling and tracks token spending.
    Stores the LLM output in context as "llm_output".
    """

    config: LLMCallConfig

    @property
    def node_type(self) -> str:
        return "llm_call"

    async def execute(self, context: PipelineContext) -> NodeResult:
        """Execute the LLM call.

        Args:
            context: Pipeline context with LLM client and data.

        Returns:
            NodeResult with LLM response content.
        """
        topic = context.current_topic

        # Estimate tokens for budget check
        estimated = self.estimate_tokens(context)

        # Check budget before calling
        if topic and not context.token_ledger.can_afford(topic, estimated):
            remaining = context.token_ledger.get_remaining(topic)
            logger.info(
                f"Skipping LLM call for {topic.key}: "
                f"estimated {estimated} tokens, remaining {remaining}"
            )
            return NodeResult.skip(
                reason=f"Insufficient budget (need ~{estimated}, have {remaining})"
            )

        # Build prompt context from pipeline context
        prompt_context = self._build_prompt_context(context)

        # Resolve model settings
        provider = self._resolve_provider(context)
        model = self._resolve_model(context)
        temperature = self._resolve_temperature(context)
        max_tokens = self._resolve_max_tokens(context)

        try:
            response = await context.llm_client.complete_with_prompt(
                layer_name=context.layer_name,
                prompt_name=self.config.prompt,
                context=prompt_context,
                run_id=context.run_id,
                node=self.name,
                topic_key=topic,
                system_prompt_name=self.config.system_prompt,
                provider=provider,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except LLMError as e:
            logger.error(f"LLM call failed for {topic.key if topic else 'global'}: {e}")
            return NodeResult.fail(str(e))

        # Track spending
        tokens_used = response.prompt_tokens + response.completion_tokens
        if topic:
            context.token_ledger.spend(topic, tokens_used, enforce=False)

        # Store output for downstream nodes
        context.set("llm_output", response.content)

        logger.debug(
            f"LLM call completed for {topic.key if topic else 'global'}: "
            f"{tokens_used} tokens"
        )

        return NodeResult.ok(data=response.content, tokens_used=tokens_used)

    def _build_prompt_context(self, context: PipelineContext) -> dict[str, Any]:
        """Build the context dict for prompt rendering.

        Includes topic info, messages, insights, and any prior output.
        """
        prompt_ctx: dict[str, Any] = {}

        # Topic information
        if context.current_topic:
            prompt_ctx["topic"] = context.current_topic
            prompt_ctx["topic_key"] = context.current_topic.key
            prompt_ctx["topic_category"] = context.current_topic.category.value

        # Messages from fetch_messages node
        if context.has("messages"):
            messages = context.get("messages", [])
            prompt_ctx["messages"] = messages
            prompt_ctx["message_count"] = len(messages)

            # Also provide formatted messages for convenience
            prompt_ctx["messages_text"] = self._format_messages(messages)

        # Insights from fetch_insights node
        if context.has("insights"):
            prompt_ctx["insights"] = context.get("insights", [])

        # Prior LLM output (for multi-step pipelines)
        if context.has("llm_output"):
            prompt_ctx["prior_output"] = context.get("llm_output")

        # Run metadata
        prompt_ctx["run_id"] = context.run_id
        prompt_ctx["layer_name"] = context.layer_name
        prompt_ctx["run_start"] = context.run_start.isoformat()

        return prompt_ctx

    def _format_messages(self, messages: list[dict[str, Any]]) -> str:
        """Format messages as readable text for prompts."""
        lines = []
        for msg in messages:
            author = msg.get("author_name", "Unknown")
            content = msg.get("content", "")
            created = msg.get("created_at", "")
            lines.append(f"[{created}] {author}: {content}")
        return "\n".join(lines)

    def _resolve_provider(self, context: PipelineContext) -> str | None:
        """Resolve provider: node > layer > None (use global)."""
        if self.config.provider:
            return self.config.provider
        if context.model_defaults and context.model_defaults.provider:
            return context.model_defaults.provider
        return None

    def _resolve_model(self, context: PipelineContext) -> str | None:
        """Resolve model: node > layer > None (use global)."""
        if self.config.model:
            return self.config.model
        if context.model_defaults and context.model_defaults.model:
            return context.model_defaults.model
        return None

    def _resolve_temperature(self, context: PipelineContext) -> float:
        """Resolve temperature: node > layer."""
        if self.config.temperature is not None:
            return self.config.temperature
        if context.model_defaults:
            return context.model_defaults.temperature
        return 0.7

    def _resolve_max_tokens(self, context: PipelineContext) -> int:
        """Resolve max_tokens: node > layer."""
        if self.config.max_tokens is not None:
            return self.config.max_tokens
        if context.model_defaults:
            return context.model_defaults.max_tokens
        return 1024

    def estimate_tokens(self, context: PipelineContext) -> int:
        """Estimate tokens for budget checking.

        Uses a heuristic based on message count and max_tokens setting.
        """
        max_out = self._resolve_max_tokens(context)

        # Estimate input tokens from messages
        messages = context.get("messages", [])
        if messages:
            # Rough estimate: ~4 chars per token, messages have content
            total_chars = sum(len(m.get("content", "")) for m in messages)
            input_estimate = total_chars // 4
        else:
            input_estimate = 200  # Base prompt overhead

        # Total estimate: input + expected output
        return input_estimate + max_out

    def validate(self, context: PipelineContext) -> list[str]:
        """Validate prompt templates exist."""
        errors = []

        # Check user prompt exists
        if not context.llm_client.prompts.prompt_exists(
            context.layer_name, self.config.prompt
        ):
            errors.append(
                f"Missing prompt template: {context.layer_name}/prompts/{self.config.prompt}.j2"
            )

        # Check system prompt exists (if specified)
        if self.config.system_prompt and not context.llm_client.prompts.prompt_exists(
            context.layer_name, self.config.system_prompt
        ):
            errors.append(
                f"Missing system prompt: {context.layer_name}/prompts/{self.config.system_prompt}.j2"
            )

        return errors
