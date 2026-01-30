"""Pydantic models for Zos entities.

These models bridge between the database (SQLAlchemy Core) and application code,
providing validation and serialization.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from ulid import ULID


# =============================================================================
# Enums
# =============================================================================


class VisibilityScope(str, Enum):
    """Message visibility scope."""

    PUBLIC = "public"
    DM = "dm"


class ChannelType(str, Enum):
    """Discord channel types."""

    TEXT = "text"
    VOICE = "voice"
    DM = "dm"
    GROUP_DM = "group_dm"
    THREAD = "thread"


class TopicCategory(str, Enum):
    """Topic category types."""

    USER = "user"
    CHANNEL = "channel"
    THREAD = "thread"
    ROLE = "role"
    DYAD = "dyad"
    USER_IN_CHANNEL = "user_in_channel"
    DYAD_IN_CHANNEL = "dyad_in_channel"
    SUBJECT = "subject"
    EMOJI = "emoji"
    SELF = "self"


class TransactionType(str, Enum):
    """Salience transaction types."""

    EARN = "earn"
    SPEND = "spend"
    RESET = "reset"
    RETAIN = "retain"
    DECAY = "decay"
    PROPAGATE = "propagate"
    SPILLOVER = "spillover"
    WARM = "warm"


class ChattinessTransactionType(str, Enum):
    """Chattiness transaction types."""

    EARN = "earn"
    SPEND = "spend"
    DECAY = "decay"
    FLOOD = "flood"


class ImpulsePool(str, Enum):
    """Chattiness impulse pools."""

    ADDRESS = "address"
    INSIGHT = "insight"
    CONVERSATIONAL = "conversational"
    CURIOSITY = "curiosity"
    PRESENCE = "presence"


class LayerRunStatus(str, Enum):
    """Layer run status values."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    DRY = "dry"


class MediaType(str, Enum):
    """Media types for analysis."""

    IMAGE = "image"
    VIDEO = "video"
    GIF = "gif"
    EMBED = "embed"


class ContentType(str, Enum):
    """Link content types."""

    ARTICLE = "article"
    VIDEO = "video"
    IMAGE = "image"
    AUDIO = "audio"
    OTHER = "other"


class LLMCallType(str, Enum):
    """LLM call types for auditing."""

    REFLECTION = "reflection"
    VISION = "vision"
    CONVERSATION = "conversation"
    SYNTHESIS = "synthesis"
    OTHER = "other"


# =============================================================================
# Helper Functions
# =============================================================================


def generate_id() -> str:
    """Generate a new ULID for entities."""
    return str(ULID())


def utcnow() -> datetime:
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


# =============================================================================
# Core Entity Models
# =============================================================================


class Server(BaseModel):
    """Discord server entity."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str | None = None
    privacy_gate_role: str | None = None
    disabled_layers: list[str] | None = None
    threads_as_topics: bool = True
    chattiness_config: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utcnow)


class User(BaseModel):
    """Discord user entity."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    first_dm_acknowledged: bool = False
    first_dm_at: datetime | None = None


class UserServerTracking(BaseModel):
    """Tracks user presence across servers for global topic warming."""

    model_config = ConfigDict(from_attributes=True)

    user_id: str
    server_id: str
    first_seen_at: datetime = Field(default_factory=utcnow)


class UserProfile(BaseModel):
    """User profile snapshot for enriching reflections with identity context."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=generate_id)
    user_id: str
    server_id: str | None  # None for global profiles
    display_name: str
    username: str
    discriminator: str | None = None
    avatar_url: str | None = None
    is_bot: bool = False
    joined_at: datetime | None = None
    account_created_at: datetime | None = None
    roles: list[str] | None = None
    bio: str | None = None
    pronouns: str | None = None
    captured_at: datetime = Field(default_factory=utcnow)


class Channel(BaseModel):
    """Discord channel entity."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    server_id: str
    name: str | None = None
    type: ChannelType
    parent_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Message(BaseModel):
    """Discord message entity - raw observation input."""

    model_config = ConfigDict(from_attributes=True)

    id: str  # Discord snowflake
    channel_id: str
    server_id: str | None = None
    author_id: str
    content: str
    created_at: datetime
    visibility_scope: VisibilityScope
    reactions_aggregate: dict[str, int] | None = None
    reply_to_id: str | None = None
    thread_id: str | None = None
    has_media: bool = False
    has_links: bool = False
    ingested_at: datetime = Field(default_factory=utcnow)
    deleted_at: datetime | None = None  # Soft delete tombstone


class Reaction(BaseModel):
    """Reaction tracking for relationship inference."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=generate_id)
    message_id: str
    user_id: str
    emoji: str
    is_custom: bool
    server_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    removed_at: datetime | None = None  # Soft delete

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Validate ULID format if provided."""
        if v:
            try:
                ULID.from_str(v)
            except ValueError:
                raise ValueError(f"Invalid ULID: {v}")
        return v


class PollState(BaseModel):
    """Polling state per channel."""

    model_config = ConfigDict(from_attributes=True)

    channel_id: str
    last_message_at: datetime | None = None
    last_polled_at: datetime


class MediaAnalysis(BaseModel):
    """Vision analysis results for images and videos."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=generate_id)
    message_id: str
    media_type: MediaType
    url: str
    filename: str | None = None
    width: int | None = None
    height: int | None = None
    duration_seconds: int | None = None
    description: str  # Phenomenological description
    local_path: str | None = None  # Relative path to saved image file
    analyzed_at: datetime = Field(default_factory=utcnow)
    analysis_model: str | None = None


class LinkAnalysis(BaseModel):
    """Fetched link content and summaries."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=generate_id)
    message_id: str
    url: str
    domain: str
    content_type: ContentType
    title: str | None = None
    summary: str | None = None
    is_youtube: bool = False
    duration_seconds: int | None = None
    transcript_available: bool | None = None
    fetched_at: datetime | None = None
    fetch_failed: bool = False
    fetch_error: str | None = None
    summary_error: str | None = None


# =============================================================================
# Topic & Salience Models
# =============================================================================


class Topic(BaseModel):
    """Canonical entity the system can think about."""

    model_config = ConfigDict(from_attributes=True)

    key: str  # Primary key - validated format
    category: TopicCategory
    is_global: bool
    provisional: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    last_activity_at: datetime | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("key")
    @classmethod
    def validate_topic_key(cls, v: str) -> str:
        """Validate topic key format."""
        # Global patterns (no server prefix)
        if v.startswith("user:") or v.startswith("dyad:") or v.startswith("self:"):
            return v
        # Server-scoped must start with server:
        if v.startswith("server:"):
            return v
        raise ValueError(f"Invalid topic key format: {v}")


class SalienceEntry(BaseModel):
    """Salience ledger transaction entry."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=generate_id)
    topic_key: str
    transaction_type: TransactionType
    amount: float
    reason: str | None = None
    source_topic: str | None = None  # For propagation/spillover
    created_at: datetime = Field(default_factory=utcnow)


# =============================================================================
# Insight & Reflection Models
# =============================================================================


class LayerRun(BaseModel):
    """Audit trail for reflection execution."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=generate_id)
    layer_name: str
    layer_hash: str
    started_at: datetime
    completed_at: datetime | None = None
    status: LayerRunStatus
    targets_matched: int = 0
    targets_processed: int = 0
    targets_skipped: int = 0
    insights_created: int = 0
    model_profile: str | None = None
    model_provider: str | None = None
    model_name: str | None = None
    tokens_input: int | None = None
    tokens_output: int | None = None
    tokens_total: int | None = None
    estimated_cost_usd: float | None = None
    errors: list[dict[str, Any]] | None = None


class Insight(BaseModel):
    """Persistent understanding generated by reflection."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=generate_id)
    topic_key: str
    category: str  # Layer category that produced it
    content: str
    sources_scope_max: VisibilityScope
    created_at: datetime
    layer_run_id: str
    supersedes: str | None = None
    quarantined: bool = False

    # Strength and metrics
    salience_spent: float
    strength_adjustment: float = Field(ge=0.1, le=10.0)
    strength: float  # Computed: salience_spent * adjustment
    original_topic_salience: float  # For decay calculation
    confidence: float = Field(ge=0.0, le=1.0)
    importance: float = Field(ge=0.0, le=1.0)
    novelty: float = Field(ge=0.0, le=1.0)

    # Valence (at least one required)
    valence_joy: float | None = Field(default=None, ge=0.0, le=1.0)
    valence_concern: float | None = Field(default=None, ge=0.0, le=1.0)
    valence_curiosity: float | None = Field(default=None, ge=0.0, le=1.0)
    valence_warmth: float | None = Field(default=None, ge=0.0, le=1.0)
    valence_tension: float | None = Field(default=None, ge=0.0, le=1.0)
    # Expanded valence dimensions (🟡 per spec)
    valence_awe: float | None = Field(default=None, ge=0.0, le=1.0)  # Numinous, exceeding understanding
    valence_grief: float | None = Field(default=None, ge=0.0, le=1.0)  # Loss, endings
    valence_longing: float | None = Field(default=None, ge=0.0, le=1.0)  # Desire not yet achieved
    valence_peace: float | None = Field(default=None, ge=0.0, le=1.0)  # Settledness, equanimity
    valence_gratitude: float | None = Field(default=None, ge=0.0, le=1.0)  # Appreciation, value
    # Prospective curiosity (🟡 per spec)
    open_questions: list[str] | None = None  # Forward-looking curiosity

    # Cross-links
    context_channel: str | None = None
    context_thread: str | None = None
    subject: str | None = None
    participants: list[str] | None = None

    # Conflict tracking
    conflicts_with: list[str] | None = None
    conflict_resolved: bool | None = None

    # Synthesis tracking
    synthesis_source_ids: list[str] | None = None

    @model_validator(mode="after")
    def validate_valence_required(self) -> "Insight":
        """Ensure at least one valence field is set."""
        valences = [
            self.valence_joy,
            self.valence_concern,
            self.valence_curiosity,
            self.valence_warmth,
            self.valence_tension,
            # Expanded valence dimensions
            self.valence_awe,
            self.valence_grief,
            self.valence_longing,
            self.valence_peace,
            self.valence_gratitude,
        ]
        if all(v is None for v in valences):
            raise ValueError("At least one valence field must be set")
        return self

    @field_validator("id")
    @classmethod
    def validate_ulid(cls, v: str) -> str:
        """Validate ULID format."""
        if v:
            try:
                ULID.from_str(v)
            except ValueError:
                raise ValueError(f"Invalid ULID: {v}")
        return v


class LLMCall(BaseModel):
    """LLM API call audit log."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=generate_id)
    layer_run_id: str | None = None
    topic_key: str | None = None
    call_type: LLMCallType
    model_profile: str
    model_provider: str
    model_name: str
    prompt: str
    response: str
    tokens_input: int
    tokens_output: int
    tokens_total: int
    estimated_cost_usd: float | None = None
    latency_ms: int | None = None
    success: bool = True
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


# =============================================================================
# Chattiness Models (MVP 1 prep)
# =============================================================================


class ChattinessEntry(BaseModel):
    """Chattiness ledger transaction entry."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=generate_id)
    pool: ImpulsePool
    channel_id: str | None = None
    topic_key: str | None = None
    transaction_type: ChattinessTransactionType
    amount: float
    trigger: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class SpeechPressure(BaseModel):
    """Global speech pressure tracking."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=generate_id)
    amount: float
    trigger: str | None = None
    server_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class ConversationLogEntry(BaseModel):
    """Log of Zos's own messages."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=generate_id)
    message_id: str
    channel_id: str
    server_id: str | None = None
    content: str
    layer_name: str
    trigger_type: str
    impulse_pool: ImpulsePool
    impulse_spent: float
    priority_flagged: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class DraftHistoryEntry(BaseModel):
    """Discarded drafts for 'things I almost said'."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=generate_id)
    channel_id: str
    thread_id: str | None = None
    content: str
    layer_name: str
    discard_reason: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


# =============================================================================
# Conversion Helpers
# =============================================================================


def row_to_model[T: BaseModel](row, model_class: type[T]) -> T:
    """Convert SQLAlchemy row to Pydantic model.

    Args:
        row: SQLAlchemy row result.
        model_class: Target Pydantic model class.

    Returns:
        Instance of the model class.
    """
    return model_class.model_validate(row._mapping)


def model_to_dict(model: BaseModel, exclude_none: bool = False) -> dict[str, Any]:
    """Convert Pydantic model to dict for database insert.

    Args:
        model: Pydantic model instance.
        exclude_none: If True, exclude None values.

    Returns:
        Dictionary representation.
    """
    return model.model_dump(exclude_none=exclude_none)
