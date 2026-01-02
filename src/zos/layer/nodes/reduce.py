"""Reduce node for combining multiple outputs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zos.exceptions import LLMError
from zos.layer.nodes.base import BaseNode, NodeResult
from zos.logging import get_logger

if TYPE_CHECKING:
    from zos.layer.context import PipelineContext
    from zos.layer.schema import ReduceConfig

logger = get_logger("layer.nodes.reduce")


class ReduceNode(BaseNode):
    """Combine multiple outputs from for_each expansion.

    Supports two strategies:
    - concatenate: Join outputs with a separator
    - summarize: Use LLM to summarize combined outputs

    Reads from "target_outputs" (set by executor after for_each).
    Stores result in "reduced_output".
    """

    config: ReduceConfig

    @property
    def node_type(self) -> str:
        return "reduce"

    async def execute(self, context: PipelineContext) -> NodeResult:
        """Reduce multiple outputs into one.

        Args:
            context: Pipeline context with target_outputs.

        Returns:
            NodeResult with combined output.
        """
        outputs = context.get("target_outputs", [])

        if not outputs:
            logger.debug("No outputs to reduce")
            context.set("reduced_output", "")
            return NodeResult.ok(data="")

        if self.config.strategy == "concatenate":
            return await self._concatenate(context, outputs)
        elif self.config.strategy == "summarize":
            return await self._summarize(context, outputs)
        else:
            return NodeResult.fail(f"Unknown reduce strategy: {self.config.strategy}")

    async def _concatenate(
        self,
        context: PipelineContext,
        outputs: list[str],
    ) -> NodeResult:
        """Concatenate outputs with separator."""
        separator = self.config.separator
        combined = separator.join(str(o) for o in outputs if o)

        context.set("reduced_output", combined)

        logger.debug(f"Concatenated {len(outputs)} outputs")
        return NodeResult.ok(data=combined)

    async def _summarize(
        self,
        context: PipelineContext,
        outputs: list[str],
    ) -> NodeResult:
        """Use LLM to summarize outputs."""
        if not self.config.prompt:
            return NodeResult.fail("summarize strategy requires a prompt template")

        # Build prompt context
        prompt_context = {
            "outputs": outputs,
            "output_count": len(outputs),
            "combined_text": "\n\n---\n\n".join(str(o) for o in outputs if o),
        }

        try:
            response = await context.llm_client.complete_with_prompt(
                layer_name=context.layer_name,
                prompt_name=self.config.prompt,
                context=prompt_context,
                run_id=context.run_id,
                node=self.name,
            )
        except LLMError as e:
            logger.error(f"Reduce summarization failed: {e}")
            return NodeResult.fail(str(e))

        tokens_used = response.prompt_tokens + response.completion_tokens
        context.set("reduced_output", response.content)

        logger.debug(f"Summarized {len(outputs)} outputs ({tokens_used} tokens)")
        return NodeResult.ok(data=response.content, tokens_used=tokens_used)

    def validate(self, context: PipelineContext) -> list[str]:  # noqa: ARG002
        """Validate configuration."""
        errors = []

        if self.config.strategy == "summarize" and not self.config.prompt:
            errors.append("reduce with summarize strategy requires a prompt template")

        return errors
