"""FetchInsights node for retrieving existing insights.

Note: This is a stub implementation until Phase 8 (Insights Storage).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from zos.layer.nodes.base import BaseNode, NodeResult
from zos.logging import get_logger

if TYPE_CHECKING:
    from zos.layer.context import PipelineContext
    from zos.layer.schema import FetchInsightsConfig

logger = get_logger("layer.nodes.fetch_insights")


class FetchInsightsNode(BaseNode):
    """Fetch existing insights for the current topic.

    Note: This is a stub implementation that returns an empty list.
    Full implementation will be added in Phase 8 (Insights Storage).

    Stores the insights in context as "insights".
    """

    config: FetchInsightsConfig

    @property
    def node_type(self) -> str:
        return "fetch_insights"

    async def execute(self, context: PipelineContext) -> NodeResult:
        """Fetch insights for the current topic.

        Currently a stub that returns empty list.

        Args:
            context: Pipeline context.

        Returns:
            NodeResult with empty list and skip status.
        """
        topic = context.current_topic

        logger.debug(
            f"fetch_insights stub: would fetch {self.config.max_insights} "
            f"insights for {topic.key if topic else 'global'}"
        )

        # Store empty insights in context
        context.set("insights", [])

        return NodeResult.skip(reason="Insights not implemented (Phase 8)")
