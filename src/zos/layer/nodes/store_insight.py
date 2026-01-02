"""StoreInsight node for persisting insights.

Note: This is a stub implementation until Phase 8 (Insights Storage).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from zos.layer.nodes.base import BaseNode, NodeResult
from zos.logging import get_logger

if TYPE_CHECKING:
    from zos.layer.context import PipelineContext
    from zos.layer.schema import StoreInsightConfig

logger = get_logger("layer.nodes.store_insight")


class StoreInsightNode(BaseNode):
    """Store generated insight in the database.

    Note: This is a stub implementation that logs what would be stored.
    Full implementation will be added in Phase 8 (Insights Storage).

    Reads from "llm_output" or "reduced_output" in context.
    """

    config: StoreInsightConfig

    @property
    def node_type(self) -> str:
        return "store_insight"

    async def execute(self, context: PipelineContext) -> NodeResult:
        """Store insight (stub implementation).

        Currently logs what would be stored.

        Args:
            context: Pipeline context with LLM output.

        Returns:
            NodeResult with skip status.
        """
        topic = context.current_topic

        # Get output to store (prefer reduced_output, fall back to llm_output)
        output = context.get("reduced_output") or context.get("llm_output", "")

        if output:
            preview = output[:200] + "..." if len(output) > 200 else output
            logger.info(
                f"store_insight stub: would store insight for "
                f"{topic.key if topic else 'global'}:\n{preview}"
            )
        else:
            logger.debug(
                f"store_insight stub: no output to store for "
                f"{topic.key if topic else 'global'}"
            )

        return NodeResult.skip(reason="Insights storage not implemented (Phase 8)")
