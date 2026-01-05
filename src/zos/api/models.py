"""Pydantic models for API responses."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel

# --- Health ---


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    version: str = "0.1.0"
    database: bool = True


# --- Config (redacted) ---


class RedactedConfig(BaseModel):
    """Full config with secrets redacted."""

    discord: dict[str, Any]
    database: dict[str, Any]
    budget: dict[str, Any]
    salience: dict[str, Any]
    logging: dict[str, Any]
    llm: dict[str, Any] | None
    layers_dir: str
    enabled_layers: list[str]
    api: dict[str, Any]


# --- Layers ---


class LayerSummary(BaseModel):
    """Summary of a layer definition."""

    name: str
    description: str | None
    schedule: str | None
    target_categories: list[str]
    node_count: int


class LayersResponse(BaseModel):
    """Response for /layers endpoint."""

    layers: list[LayerSummary]
    enabled: list[str]


# --- Runs ---


class RunSummary(BaseModel):
    """Summary of a run for list view."""

    run_id: str
    layer_name: str
    status: str
    triggered_by: str
    started_at: datetime
    completed_at: datetime | None
    targets_processed: int
    targets_total: int
    tokens_used: int


class TraceEntryResponse(BaseModel):
    """Single trace entry."""

    node_name: str
    topic_key: str | None
    success: bool
    skipped: bool
    skip_reason: str | None
    error: str | None
    tokens_used: int
    executed_at: datetime


class RunDetail(BaseModel):
    """Detailed run info including trace."""

    run_id: str
    layer_name: str
    status: str
    triggered_by: str
    started_at: datetime
    completed_at: datetime | None
    schedule_expression: str | None
    window_start: datetime
    window_end: datetime
    error_message: str | None
    targets_total: int
    targets_processed: int
    targets_skipped: int
    tokens_used: int
    estimated_cost_usd: float
    salience_spent: float
    trace: list[TraceEntryResponse] | None = None


class PaginatedRuns(BaseModel):
    """Paginated list of runs."""

    runs: list[RunSummary]
    total: int
    offset: int
    limit: int


# --- Insights ---


class InsightSummary(BaseModel):
    """Summary of an insight."""

    insight_id: str
    topic_key: str
    created_at: datetime
    summary: str
    sources_scope_max: str
    run_id: str | None
    layer: str | None
    source_count: int


class InsightDetail(BaseModel):
    """Full insight with payload."""

    insight_id: str
    topic_key: str
    created_at: datetime
    summary: str
    sources_scope_max: str
    run_id: str | None
    layer: str | None
    source_count: int
    payload: dict[str, Any] | None
    source_refs: list[int]


class PaginatedInsights(BaseModel):
    """Paginated list of insights."""

    insights: list[InsightSummary]
    total: int
    offset: int
    limit: int


# --- Salience ---


class TopicBalance(BaseModel):
    """Salience balance for a topic."""

    topic_key: str
    category: str
    earned: float
    spent: float
    balance: float


class SalienceResponse(BaseModel):
    """Salience balances by category."""

    category: str
    topics: list[TopicBalance]
    total_count: int


# --- Audit ---


class LLMCallRecord(BaseModel):
    """Record of an LLM API call."""

    id: int
    run_id: str
    topic_key: str | None
    layer: str
    node: str | None
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float | None
    created_at: datetime


class PaginatedAudit(BaseModel):
    """Paginated audit log."""

    records: list[LLMCallRecord]
    total: int
    offset: int
    limit: int
