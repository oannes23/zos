"""Base classes for pipeline nodes.

Defines the abstract BaseNode class and NodeResult dataclass that all
pipeline nodes must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from zos.layer.context import PipelineContext
    from zos.layer.schema import BaseNodeConfig


@dataclass(frozen=True)
class NodeResult:
    """Result from node execution.

    Attributes:
        success: Whether execution completed without error.
        data: Output data from the node.
        error: Error message if execution failed.
        tokens_used: LLM tokens consumed by this node.
        skipped: Whether node was skipped (e.g., budget exhausted).
        skip_reason: Reason for skipping.
    """

    success: bool
    data: Any = None
    error: str | None = None
    tokens_used: int = 0
    skipped: bool = False
    skip_reason: str | None = None

    @classmethod
    def ok(cls, data: Any = None, tokens_used: int = 0) -> NodeResult:
        """Create a successful result.

        Args:
            data: Output data.
            tokens_used: Tokens consumed.

        Returns:
            Successful NodeResult.
        """
        return cls(success=True, data=data, tokens_used=tokens_used)

    @classmethod
    def skip(cls, reason: str) -> NodeResult:
        """Create a skipped result.

        Args:
            reason: Why the node was skipped.

        Returns:
            Skipped NodeResult.
        """
        return cls(success=True, skipped=True, skip_reason=reason)

    @classmethod
    def fail(cls, error: str) -> NodeResult:
        """Create a failed result.

        Args:
            error: Error message.

        Returns:
            Failed NodeResult.
        """
        return cls(success=False, error=error)


@dataclass
class BaseNode(ABC):
    """Abstract base class for pipeline nodes.

    Each node type must implement:
    - node_type property returning the type identifier
    - execute() method for async execution
    """

    config: BaseNodeConfig = field(repr=False)

    @property
    def name(self) -> str:
        """Get the node name for logging/tracing.

        Returns the config name if set, otherwise the node type.
        """
        return self.config.name or self.node_type

    @property
    @abstractmethod
    def node_type(self) -> str:
        """Return the node type identifier.

        This must match the 'type' field in the YAML schema.
        """
        ...

    @abstractmethod
    async def execute(self, context: PipelineContext) -> NodeResult:
        """Execute the node with given context.

        Args:
            context: Pipeline context with dependencies and data.

        Returns:
            NodeResult indicating success/failure/skip.
        """
        ...

    def validate(self, context: PipelineContext) -> list[str]:  # noqa: ARG002
        """Validate node configuration.

        Override to add node-specific validation.

        Args:
            context: Pipeline context.

        Returns:
            List of validation error messages (empty if valid).
        """
        return []

    def estimate_tokens(self, context: PipelineContext) -> int:  # noqa: ARG002
        """Estimate tokens this node will consume.

        Override for LLM-calling nodes.

        Args:
            context: Pipeline context.

        Returns:
            Estimated token count.
        """
        return 0
