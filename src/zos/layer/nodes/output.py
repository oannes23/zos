"""Output node for sending results to destinations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zos.layer.nodes.base import BaseNode, NodeResult
from zos.logging import get_logger

if TYPE_CHECKING:
    from zos.layer.context import PipelineContext
    from zos.layer.schema import OutputConfig
    from zos.topics.topic_key import TopicKey

logger = get_logger("layer.nodes.output")


class OutputNode(BaseNode):
    """Send output to a destination.

    Supported destinations:
    - log: Log the output (always works)
    - discord: Send to Discord channel (stub - logs what would be sent)
    - none: Do nothing

    Reads from "llm_output" or "reduced_output" in context.
    """

    config: OutputConfig

    @property
    def node_type(self) -> str:
        return "output"

    async def execute(self, context: PipelineContext) -> NodeResult:
        """Send output to destination.

        Args:
            context: Pipeline context with output data.

        Returns:
            NodeResult indicating success.
        """
        # Get output to send (prefer reduced_output, fall back to llm_output)
        output = context.get("reduced_output") or context.get("llm_output", "")
        topic = context.current_topic

        if self.config.destination == "none":
            logger.debug(f"Output suppressed for {topic.key if topic else 'global'}")
            return NodeResult.skip(reason="Output destination is 'none'")

        if self.config.destination == "log":
            return self._output_to_log(output, topic)

        if self.config.destination == "discord":
            return self._output_to_discord(output, topic)

        return NodeResult.fail(f"Unknown destination: {self.config.destination}")

    def _output_to_log(self, output: str, topic: TopicKey | None) -> NodeResult:
        """Log the output."""
        topic_str = topic.key if topic else "global"

        if output:
            logger.info(f"Layer output for {topic_str}:\n{output}")
        else:
            logger.info(f"No output to log for {topic_str}")

        return NodeResult.ok(data=output)

    def _output_to_discord(self, output: str, topic: TopicKey | None) -> NodeResult:
        """Send to Discord (stub implementation).

        Full Discord integration will be implemented in Phase 11.
        """
        topic_str = topic.key if topic else "global"
        channel_id = self.config.channel_id

        if not channel_id:
            return NodeResult.fail("Discord output requires channel_id")

        if output:
            preview = output[:500] + "..." if len(output) > 500 else output
            logger.info(
                f"Discord output stub: would send to channel {channel_id} "
                f"for {topic_str}:\n{preview}"
            )
        else:
            logger.debug(f"No output to send to Discord for {topic_str}")

        return NodeResult.skip(reason="Discord output not yet implemented (Phase 11)")

    def validate(self, context: PipelineContext) -> list[str]:  # noqa: ARG002
        """Validate configuration."""
        errors = []

        if self.config.destination == "discord" and not self.config.channel_id:
            errors.append("discord destination requires channel_id")

        return errors
