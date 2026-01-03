"""FetchInsights node for retrieving existing insights."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from zos.insights import InsightRepository
from zos.layer.nodes.base import BaseNode, NodeResult
from zos.logging import get_logger

if TYPE_CHECKING:
    from zos.layer.context import PipelineContext
    from zos.layer.schema import FetchInsightsConfig

logger = get_logger("layer.nodes.fetch_insights")


class FetchInsightsNode(BaseNode):
    """Fetch existing insights for the current topic.

    Retrieves insights from the database for the current topic,
    applying filters based on configuration.

    Stores the insights in context as "insights".
    """

    config: FetchInsightsConfig

    @property
    def node_type(self) -> str:
        return "fetch_insights"

    async def execute(self, context: PipelineContext) -> NodeResult:
        """Fetch insights for the current topic.

        Args:
            context: Pipeline context.

        Returns:
            NodeResult with list of insights.
        """
        topic = context.current_topic

        if topic is None:
            logger.debug("fetch_insights: no current topic, returning empty list")
            context.set("insights", [])
            return NodeResult.ok(data=[])

        # Create repository
        repo = InsightRepository(context.db)

        # Calculate since time if configured
        since = None
        if self.config.since_hours:
            since = datetime.now(UTC) - timedelta(hours=self.config.since_hours)

        # Determine scope filter
        scope = self.config.scope if self.config.scope != "all" else None

        # Fetch insights
        insights = repo.get_insights(
            topic_key=topic,
            limit=self.config.max_insights,
            since=since,
            scope=scope,
        )

        # Convert to dicts for context
        insight_dicts = [
            {
                "insight_id": i.insight_id,
                "topic_key": i.topic_key,
                "created_at": i.created_at.isoformat(),
                "summary": i.summary,
                "payload": i.payload,
                "source_refs": i.source_refs,
                "sources_scope_max": i.sources_scope_max,
                "run_id": i.run_id,
                "layer": i.layer,
            }
            for i in insights
        ]

        context.set("insights", insight_dicts)

        logger.debug(
            f"Fetched {len(insights)} insights for {topic.key} "
            f"(limit={self.config.max_insights}, scope={self.config.scope})"
        )

        return NodeResult.ok(data=insight_dicts)
