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
    """Fetch existing insights for the current topic or category.

    Retrieves insights from the database for the current topic,
    applying filters based on configuration. Supports cross-layer
    integration via layer filtering and category override.

    Stores the insights in context. The key is based on the node name
    if provided, otherwise "insights".
    """

    config: FetchInsightsConfig

    @property
    def node_type(self) -> str:
        return "fetch_insights"

    async def execute(self, context: PipelineContext) -> NodeResult:
        """Fetch insights for the current topic or category.

        Args:
            context: Pipeline context.

        Returns:
            NodeResult with list of insights.
        """
        topic = context.current_topic

        # Create repository
        repo = InsightRepository(context.db)

        # Calculate since time if configured
        since = None
        if self.config.since_hours:
            since = datetime.now(UTC) - timedelta(hours=self.config.since_hours)

        # Determine scope filter
        scope = self.config.scope if self.config.scope != "all" else None

        # Get layer filter
        layer = self.config.layer

        # Fetch insights based on configuration
        if self.config.topic_category_override:
            # Fetch from all topics in the specified category
            insights = repo.get_insights_by_category(
                category=self.config.topic_category_override,
                limit=self.config.max_insights,
                since=since,
                scope=scope,
                layer=layer,
            )
            fetch_description = f"category={self.config.topic_category_override}"
        elif topic is None:
            logger.debug("fetch_insights: no current topic, returning empty list")
            context.set(self._get_context_key(), [])
            return NodeResult.ok(data=[])
        else:
            # Fetch for the current topic
            insights = repo.get_insights(
                topic_key=topic,
                limit=self.config.max_insights,
                since=since,
                scope=scope,
                layer=layer,
            )
            fetch_description = f"topic={topic.key}"

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

        # Store with descriptive key based on node name
        context_key = self._get_context_key()
        context.set(context_key, insight_dicts)

        layer_desc = f", layer={layer}" if layer else ""
        logger.debug(
            f"Fetched {len(insights)} insights for {fetch_description} "
            f"(limit={self.config.max_insights}, scope={self.config.scope}{layer_desc}) "
            f"-> context['{context_key}']"
        )

        return NodeResult.ok(data=insight_dicts)

    def _get_context_key(self) -> str:
        """Get the context key for storing insights.

        Uses the node name if provided, otherwise defaults to "insights".
        This allows multiple fetch_insights nodes to store results
        in different keys.
        """
        if self.config.name:
            # Convert node name to snake_case context key
            # e.g., "get_prior_profile" -> "prior_profile" or "get_user_profiles" -> "user_profiles"
            name = self.config.name
            if name.startswith("get_"):
                name = name[4:]
            return name
        return "insights"
