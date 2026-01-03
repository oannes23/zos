"""StoreInsight node for persisting insights."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from zos.insights import InsightRepository
from zos.layer.nodes.base import BaseNode, NodeResult
from zos.layer.privacy import PrivacyEnforcer
from zos.logging import get_logger

if TYPE_CHECKING:
    from zos.layer.context import PipelineContext
    from zos.layer.schema import StoreInsightConfig

logger = get_logger("layer.nodes.store_insight")


class StoreInsightNode(BaseNode):
    """Store generated insight in the database.

    Reads from "llm_output" or "reduced_output" in context and
    persists the insight with source tracking and privacy scope.
    """

    config: StoreInsightConfig

    @property
    def node_type(self) -> str:
        return "store_insight"

    async def execute(self, context: PipelineContext) -> NodeResult:
        """Store insight in the database.

        Args:
            context: Pipeline context with LLM output.

        Returns:
            NodeResult with stored insight data.
        """
        topic = context.current_topic

        if topic is None:
            return NodeResult.fail("No current topic set - cannot store insight")

        # Get output to store (prefer reduced_output, fall back to llm_output)
        output = context.get("reduced_output") or context.get("llm_output", "")

        if not output:
            logger.debug(
                f"store_insight: no output to store for {topic.key}"
            )
            return NodeResult.skip(reason="No output to store")

        # Extract source references from messages in context
        messages: list[dict[str, Any]] = context.get("messages", [])
        source_refs = [m["message_id"] for m in messages if "message_id" in m]

        # Determine privacy scope from source messages
        sources_scope_max = PrivacyEnforcer.get_max_scope(messages)

        # Build optional payload if configured
        payload = None
        if self.config.include_payload:
            payload = {
                "messages_count": len(messages),
                "source_message_ids": source_refs[:100],  # Limit for payload
            }

        # Store the insight
        repo = InsightRepository(context.db)
        insight = repo.store(
            topic_key=topic,
            summary=output,
            source_refs=source_refs,
            sources_scope_max=sources_scope_max,
            run_id=context.run_id,
            layer=context.layer_name,
            payload=payload,
        )

        logger.info(
            f"Stored insight {insight.insight_id} for {topic.key} "
            f"(scope={sources_scope_max}, sources={len(source_refs)})"
        )

        # Store insight ID in context for downstream nodes
        context.set("stored_insight_id", insight.insight_id)

        return NodeResult.ok(data={
            "insight_id": insight.insight_id,
            "topic_key": insight.topic_key,
            "sources_scope_max": insight.sources_scope_max,
            "source_count": len(source_refs),
        })
