"""Data models for run management and scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class RunStatus(str, Enum):
    """Status of a layer execution run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TriggerType(str, Enum):
    """How a run was triggered."""

    SCHEDULE = "schedule"
    MANUAL = "manual"
    API = "api"


@dataclass
class Run:
    """Represents a layer execution run.

    Tracks the full lifecycle of a layer execution from creation
    through completion or failure.
    """

    run_id: str
    layer_name: str
    triggered_by: TriggerType
    status: RunStatus
    started_at: datetime
    window_start: datetime
    window_end: datetime
    schedule_expression: str | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    targets_total: int = 0
    targets_processed: int = 0
    targets_skipped: int = 0
    tokens_used: int = 0
    estimated_cost_usd: float = 0.0
    salience_spent: float = 0.0

    @property
    def duration_seconds(self) -> float | None:
        """Calculate run duration in seconds."""
        if self.completed_at is None:
            return None
        return (self.completed_at - self.started_at).total_seconds()

    @property
    def is_finished(self) -> bool:
        """Check if run has finished (completed, failed, or cancelled)."""
        return self.status in (
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        )


@dataclass
class TraceEntry:
    """A single entry in the execution trace.

    Records the execution of one node for one target.
    """

    run_id: str
    node_name: str
    success: bool
    executed_at: datetime
    topic_key: str | None = None
    skipped: bool = False
    skip_reason: str | None = None
    error: str | None = None
    tokens_used: int = 0
