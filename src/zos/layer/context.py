"""Pipeline context for passing data between nodes.

The PipelineContext holds all state needed during pipeline execution,
including dependencies, run metadata, and data passed between nodes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from zos.budget.ledger import TokenLedger
    from zos.db import Database
    from zos.discord.repository import MessageRepository
    from zos.layer.schema import ModelDefaults
    from zos.llm.client import LLMClient
    from zos.salience.repository import SalienceRepository
    from zos.topics.topic_key import TopicKey


@dataclass
class TraceEntry:
    """Entry in the execution trace."""

    node: str
    topic: str | None
    success: bool
    skipped: bool
    skip_reason: str | None
    tokens_used: int
    error: str | None
    timestamp: str


@dataclass
class PipelineContext:
    """Context passed through pipeline execution.

    This context is created at the start of a run and passed to each node.
    Nodes can store data for downstream nodes via set()/get().
    """

    # Run metadata
    run_id: str
    layer_name: str
    run_start: datetime

    # Dependencies (injected)
    db: Database = field(repr=False)
    llm_client: LLMClient = field(repr=False)
    message_repo: MessageRepository = field(repr=False)
    salience_repo: SalienceRepository = field(repr=False)
    token_ledger: TokenLedger = field(repr=False)

    # Current target (for for_each)
    current_topic: TopicKey | None = None

    # Layer configuration
    model_defaults: ModelDefaults | None = field(default=None)

    # Time window for message fetching (set by scheduler/run_manager)
    window_start: datetime | None = field(default=None)
    window_end: datetime | None = field(default=None)

    # Data store for passing between nodes
    _data: dict[str, Any] = field(default_factory=dict, repr=False)

    # Execution trace
    _trace: list[TraceEntry] = field(default_factory=list, repr=False)

    def set(self, key: str, value: Any) -> None:
        """Store data for downstream nodes.

        Args:
            key: Data key.
            value: Data value.
        """
        self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve data from upstream nodes.

        Args:
            key: Data key.
            default: Default value if key not found.

        Returns:
            The stored value, or default if not found.
        """
        return self._data.get(key, default)

    def has(self, key: str) -> bool:
        """Check if data key exists.

        Args:
            key: Data key.

        Returns:
            True if key exists.
        """
        return key in self._data

    def add_trace(
        self,
        node_name: str,
        *,
        success: bool,
        skipped: bool = False,
        skip_reason: str | None = None,
        tokens_used: int = 0,
        error: str | None = None,
    ) -> None:
        """Add node execution to trace.

        Args:
            node_name: Name of the node.
            success: Whether execution succeeded.
            skipped: Whether node was skipped.
            skip_reason: Reason for skipping.
            tokens_used: Tokens consumed.
            error: Error message if any.
        """
        entry = TraceEntry(
            node=node_name,
            topic=self.current_topic.key if self.current_topic else None,
            success=success,
            skipped=skipped,
            skip_reason=skip_reason,
            tokens_used=tokens_used,
            error=error,
            timestamp=datetime.now(UTC).isoformat(),
        )
        self._trace.append(entry)

    def get_trace(self) -> list[dict[str, Any]]:
        """Get full execution trace as list of dicts.

        Returns:
            List of trace entries as dictionaries.
        """
        return [
            {
                "node": e.node,
                "topic": e.topic,
                "success": e.success,
                "skipped": e.skipped,
                "skip_reason": e.skip_reason,
                "tokens_used": e.tokens_used,
                "error": e.error,
                "timestamp": e.timestamp,
            }
            for e in self._trace
        ]

    def fork_for_target(self, topic: TopicKey) -> PipelineContext:
        """Create a new context for a specific target.

        Used when executing for_each over targets.
        The new context has a fresh data store but shares the trace.

        Args:
            topic: The target topic for this fork.

        Returns:
            New PipelineContext for the target.
        """
        return PipelineContext(
            run_id=self.run_id,
            layer_name=self.layer_name,
            run_start=self.run_start,
            db=self.db,
            llm_client=self.llm_client,
            message_repo=self.message_repo,
            salience_repo=self.salience_repo,
            token_ledger=self.token_ledger,
            current_topic=topic,
            model_defaults=self.model_defaults,
            window_start=self.window_start,
            window_end=self.window_end,
            _data={},  # Fresh data store
            _trace=self._trace,  # Shared trace
        )
