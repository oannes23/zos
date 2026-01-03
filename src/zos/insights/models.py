"""Data models for the insights system."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Insight:
    """Represents a stored insight from a reflection run.

    Insights are the output of reflection layers, stored with source tracking
    and privacy scope information.
    """

    insight_id: str
    topic_key: str
    created_at: datetime
    summary: str
    payload: dict[str, object] | None
    source_refs: list[int]
    sources_scope_max: str
    run_id: str | None
    layer: str | None
