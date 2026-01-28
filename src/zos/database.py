"""Database schema and connection management for Zos.

Uses SQLAlchemy Core (not ORM) for explicit SQL control.
All tables defined here match the spec in architecture/data-model.md.
"""

from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    text,
)
from sqlalchemy.engine import Engine
from ulid import ULID

from zos.config import Config

# Shared metadata for all tables
metadata = MetaData()


# =============================================================================
# Core Entities
# =============================================================================

servers = Table(
    "servers",
    metadata,
    Column("id", String, primary_key=True),  # Discord snowflake
    Column("name", String, nullable=True),
    Column("privacy_gate_role", String, nullable=True),
    Column("disabled_layers", JSON, nullable=True),
    Column("threads_as_topics", Boolean, nullable=False, default=True),
    Column("chattiness_config", JSON, nullable=True),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
)

users = Table(
    "users",
    metadata,
    Column("id", String, primary_key=True),  # Discord snowflake
    Column("first_dm_acknowledged", Boolean, nullable=False, default=False),
    Column("first_dm_at", DateTime, nullable=True),
)

user_profiles = Table(
    "user_profiles",
    metadata,
    Column("id", String, primary_key=True),  # ULID
    Column("user_id", String, nullable=False),
    Column("server_id", String, ForeignKey("servers.id"), nullable=True),  # NULL for global (DM) profiles
    Column("display_name", String, nullable=False),
    Column("username", String, nullable=False),
    Column("discriminator", String, nullable=True),
    Column("avatar_url", String, nullable=True),
    Column("is_bot", Boolean, nullable=False, default=False),
    Column("joined_at", DateTime, nullable=True),  # NULL for global profiles
    Column("account_created_at", DateTime, nullable=True),
    Column("roles", JSON, nullable=True),  # JSON array, NULL for global profiles
    Column("bio", Text, nullable=True),  # From fetch_profile()
    Column("pronouns", String, nullable=True),  # From fetch_profile()
    Column("captured_at", DateTime, nullable=False, default=datetime.utcnow),
    Index("ix_user_profiles_user_server", "user_id", "server_id", unique=True),
    Index("ix_user_profiles_captured", "captured_at"),
)

user_server_tracking = Table(
    "user_server_tracking",
    metadata,
    Column("user_id", String, nullable=False),
    Column("server_id", String, nullable=False),
    Column("first_seen_at", DateTime, nullable=False, default=datetime.utcnow),
    # Composite primary key
    Index("pk_user_server_tracking", "user_id", "server_id", unique=True),
    Index("ix_user_server_tracking_user", "user_id"),
)

channels = Table(
    "channels",
    metadata,
    Column("id", String, primary_key=True),  # Discord snowflake
    Column("server_id", String, ForeignKey("servers.id"), nullable=False),
    Column("name", String, nullable=True),
    Column("type", String, nullable=False),  # text, voice, dm, group_dm, thread
    Column("parent_id", String, nullable=True),  # For threads
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
)

messages = Table(
    "messages",
    metadata,
    Column("id", String, primary_key=True),  # Discord snowflake
    Column("channel_id", String, ForeignKey("channels.id"), nullable=False),
    Column("server_id", String, ForeignKey("servers.id"), nullable=True),  # Null for DMs
    Column("author_id", String, nullable=False),  # Always real Discord ID
    Column("content", Text, nullable=False),
    Column("created_at", DateTime, nullable=False),
    Column("visibility_scope", String, nullable=False),  # 'public' or 'dm'
    Column("reactions_aggregate", JSON, nullable=True),
    Column("reply_to_id", String, nullable=True),
    Column("thread_id", String, nullable=True),
    Column("has_media", Boolean, nullable=False, default=False),
    Column("has_links", Boolean, nullable=False, default=False),
    Column("ingested_at", DateTime, nullable=False, default=datetime.utcnow),
    Column("deleted_at", DateTime, nullable=True),  # Soft delete tombstone
    Index("ix_messages_channel_created", "channel_id", "created_at"),
    Index("ix_messages_author_created", "author_id", "created_at"),
    Index("ix_messages_server_created", "server_id", "created_at"),
)

reactions = Table(
    "reactions",
    metadata,
    Column("id", String, primary_key=True),  # ULID
    Column("message_id", String, ForeignKey("messages.id"), nullable=False),
    Column("user_id", String, nullable=False),  # Discord user ID
    Column("emoji", String, nullable=False),  # Unicode or custom emoji ID
    Column("is_custom", Boolean, nullable=False),
    Column("server_id", String, nullable=True),  # For custom emoji topics
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
    Column("removed_at", DateTime, nullable=True),  # Soft delete
    Index("ix_reactions_message", "message_id"),
    Index("ix_reactions_user_created", "user_id", "created_at"),
    Index("ix_reactions_emoji_server", "emoji", "server_id"),
)

poll_state = Table(
    "poll_state",
    metadata,
    Column("channel_id", String, primary_key=True),  # Discord snowflake
    Column("last_message_at", DateTime, nullable=True),
    Column("last_polled_at", DateTime, nullable=False),
)

media_analysis = Table(
    "media_analysis",
    metadata,
    Column("id", String, primary_key=True),  # ULID
    Column("message_id", String, ForeignKey("messages.id"), nullable=False),
    Column("media_type", String, nullable=False),  # image, video, gif, embed
    Column("url", String, nullable=False),
    Column("filename", String, nullable=True),
    Column("width", Integer, nullable=True),
    Column("height", Integer, nullable=True),
    Column("duration_seconds", Integer, nullable=True),
    Column("description", Text, nullable=False),  # Phenomenological description
    Column("analyzed_at", DateTime, nullable=False, default=datetime.utcnow),
    Column("analysis_model", String, nullable=True),
    Index("ix_media_analysis_message", "message_id"),
)

link_analysis = Table(
    "link_analysis",
    metadata,
    Column("id", String, primary_key=True),  # ULID
    Column("message_id", String, ForeignKey("messages.id"), nullable=False),
    Column("url", Text, nullable=False),
    Column("domain", String, nullable=False),
    Column("content_type", String, nullable=False),  # article, video, image, audio, other
    Column("title", String, nullable=True),
    Column("summary", Text, nullable=True),
    Column("is_youtube", Boolean, nullable=False, default=False),
    Column("duration_seconds", Integer, nullable=True),
    Column("transcript_available", Boolean, nullable=True),
    Column("fetched_at", DateTime, nullable=True),
    Column("fetch_failed", Boolean, nullable=False, default=False),
    Column("fetch_error", String, nullable=True),
    Index("ix_link_analysis_message", "message_id"),
    Index("ix_link_analysis_domain_created", "domain", "fetched_at"),
)


# =============================================================================
# Topic & Salience
# =============================================================================

topics = Table(
    "topics",
    metadata,
    Column("key", String, primary_key=True),  # Topic key format
    Column("category", String, nullable=False),  # user, channel, dyad, subject, etc.
    Column("is_global", Boolean, nullable=False),
    Column("provisional", Boolean, nullable=False, default=False),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
    Column("last_activity_at", DateTime, nullable=True),
    Column("metadata", JSON, nullable=True),
    Index("ix_topics_category", "category"),
    Index("ix_topics_global", "is_global"),
    Index("ix_topics_provisional", "provisional"),
)

salience_ledger = Table(
    "salience_ledger",
    metadata,
    Column("id", String, primary_key=True),  # ULID
    Column("topic_key", String, ForeignKey("topics.key"), nullable=False),
    Column("transaction_type", String, nullable=False),  # earn, spend, retain, decay, propagate, spillover, warm
    Column("amount", Float, nullable=False),
    Column("reason", String, nullable=True),
    Column("source_topic", String, nullable=True),  # For propagation/spillover
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
    Index("ix_salience_ledger_topic_created", "topic_key", "created_at"),
)


# =============================================================================
# Insights & Reflection
# =============================================================================

layer_runs = Table(
    "layer_runs",
    metadata,
    Column("id", String, primary_key=True),  # ULID
    Column("layer_name", String, nullable=False),
    Column("layer_hash", String, nullable=False),
    Column("started_at", DateTime, nullable=False),
    Column("completed_at", DateTime, nullable=True),
    Column("status", String, nullable=False),  # success, partial, failed, dry
    Column("targets_matched", Integer, nullable=False, default=0),
    Column("targets_processed", Integer, nullable=False, default=0),
    Column("targets_skipped", Integer, nullable=False, default=0),
    Column("insights_created", Integer, nullable=False, default=0),
    Column("model_profile", String, nullable=True),
    Column("model_provider", String, nullable=True),
    Column("model_name", String, nullable=True),
    Column("tokens_input", Integer, nullable=True),
    Column("tokens_output", Integer, nullable=True),
    Column("tokens_total", Integer, nullable=True),
    Column("estimated_cost_usd", Float, nullable=True),
    Column("errors", JSON, nullable=True),
    Index("ix_layer_runs_name_started", "layer_name", "started_at"),
    Index("ix_layer_runs_status", "status"),
)

insights = Table(
    "insights",
    metadata,
    Column("id", String, primary_key=True),  # ULID
    Column("topic_key", String, ForeignKey("topics.key"), nullable=False),
    Column("category", String, nullable=False),  # user_reflection, synthesis, etc.
    Column("content", Text, nullable=False),
    Column("sources_scope_max", String, nullable=False),  # public, dm, derived
    Column("created_at", DateTime, nullable=False),
    Column("layer_run_id", String, ForeignKey("layer_runs.id"), nullable=False),
    Column("supersedes", String, nullable=True),
    Column("quarantined", Boolean, nullable=False, default=False),
    # Strength and metrics
    Column("salience_spent", Float, nullable=False),
    Column("strength_adjustment", Float, nullable=False),
    Column("strength", Float, nullable=False),  # Computed: salience_spent * adjustment
    Column("original_topic_salience", Float, nullable=False),  # For decay calculation
    Column("confidence", Float, nullable=False),
    Column("importance", Float, nullable=False),
    Column("novelty", Float, nullable=False),
    # Valence (at least one must be non-null)
    Column("valence_joy", Float, nullable=True),
    Column("valence_concern", Float, nullable=True),
    Column("valence_curiosity", Float, nullable=True),
    Column("valence_warmth", Float, nullable=True),
    Column("valence_tension", Float, nullable=True),
    # Cross-links
    Column("context_channel", String, nullable=True),
    Column("context_thread", String, nullable=True),
    Column("subject", String, nullable=True),
    Column("participants", JSON, nullable=True),
    # Conflict tracking
    Column("conflicts_with", JSON, nullable=True),
    Column("conflict_resolved", Boolean, nullable=True),
    # Synthesis tracking
    Column("synthesis_source_ids", JSON, nullable=True),
    # Indexes
    Index("ix_insights_topic_created", "topic_key", "created_at"),
    Index("ix_insights_category_created", "category", "created_at"),
    Index("ix_insights_quarantined", "quarantined"),
    Index("ix_insights_layer_run", "layer_run_id"),
    # At least one valence must be set
    CheckConstraint(
        "valence_joy IS NOT NULL OR valence_concern IS NOT NULL OR "
        "valence_curiosity IS NOT NULL OR valence_warmth IS NOT NULL OR "
        "valence_tension IS NOT NULL",
        name="ck_insights_valence_required",
    ),
)

llm_calls = Table(
    "llm_calls",
    metadata,
    Column("id", String, primary_key=True),  # ULID
    Column("layer_run_id", String, ForeignKey("layer_runs.id"), nullable=True),
    Column("topic_key", String, nullable=True),
    Column("call_type", String, nullable=False),  # reflection, vision, conversation, synthesis, other
    Column("model_profile", String, nullable=False),
    Column("model_provider", String, nullable=False),
    Column("model_name", String, nullable=False),
    Column("prompt", Text, nullable=False),  # Full prompt text
    Column("response", Text, nullable=False),  # Full response text
    Column("tokens_input", Integer, nullable=False),
    Column("tokens_output", Integer, nullable=False),
    Column("tokens_total", Integer, nullable=False),
    Column("estimated_cost_usd", Float, nullable=True),
    Column("latency_ms", Integer, nullable=True),
    Column("success", Boolean, nullable=False, default=True),
    Column("error_message", String, nullable=True),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
    Index("ix_llm_calls_layer_run", "layer_run_id"),
    Index("ix_llm_calls_created", "created_at"),
    Index("ix_llm_calls_profile", "model_profile"),
    Index("ix_llm_calls_type_created", "call_type", "created_at"),
)


# =============================================================================
# Chattiness (MVP 1 prep)
# =============================================================================

chattiness_ledger = Table(
    "chattiness_ledger",
    metadata,
    Column("id", String, primary_key=True),  # ULID
    Column("pool", String, nullable=False),  # address, insight, conversational, curiosity, presence
    Column("channel_id", String, nullable=True),
    Column("topic_key", String, nullable=True),
    Column("transaction_type", String, nullable=False),  # earn, spend, decay, flood
    Column("amount", Float, nullable=False),
    Column("trigger", String, nullable=True),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
    Index("ix_chattiness_ledger_pool_channel_created", "pool", "channel_id", "created_at"),
    Index("ix_chattiness_ledger_pool_topic_created", "pool", "topic_key", "created_at"),
)

speech_pressure = Table(
    "speech_pressure",
    metadata,
    Column("id", String, primary_key=True),  # ULID
    Column("amount", Float, nullable=False),
    Column("trigger", String, nullable=True),
    Column("server_id", String, nullable=True),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
    Index("ix_speech_pressure_created", "created_at"),
)

conversation_log = Table(
    "conversation_log",
    metadata,
    Column("id", String, primary_key=True),  # ULID
    Column("message_id", String, nullable=False),  # Discord message ID
    Column("channel_id", String, nullable=False),
    Column("server_id", String, nullable=True),
    Column("content", Text, nullable=False),
    Column("layer_name", String, nullable=False),
    Column("trigger_type", String, nullable=False),
    Column("impulse_pool", String, nullable=False),
    Column("impulse_spent", Float, nullable=False),
    Column("priority_flagged", Boolean, nullable=False, default=False),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
    Index("ix_conversation_log_channel_created", "channel_id", "created_at"),
)

draft_history = Table(
    "draft_history",
    metadata,
    Column("id", String, primary_key=True),  # ULID
    Column("channel_id", String, nullable=False),
    Column("thread_id", String, nullable=True),
    Column("content", Text, nullable=False),
    Column("layer_name", String, nullable=False),
    Column("discard_reason", String, nullable=True),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
    Index("ix_draft_history_channel_thread_created", "channel_id", "thread_id", "created_at"),
)


# =============================================================================
# Schema Version (for migrations)
# =============================================================================

schema_version = Table(
    "_schema_version",
    metadata,
    Column("version", Integer, primary_key=True),
    Column("applied_at", DateTime, nullable=False),
    Column("description", String, nullable=True),
)


# =============================================================================
# Helper Functions
# =============================================================================


def generate_id() -> str:
    """Generate a new ULID for entities."""
    return str(ULID())


def get_engine(config: Config) -> Engine:
    """Create SQLAlchemy engine from config.

    Args:
        config: Application configuration.

    Returns:
        SQLAlchemy Engine instance.
    """
    db_path = config.database_path

    # Ensure data directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=config.log_level == "DEBUG",
    )

    # Enable WAL mode for better concurrency
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.commit()

    return engine


def create_tables(engine: Engine) -> None:
    """Create all tables in the database.

    Args:
        engine: SQLAlchemy Engine instance.
    """
    metadata.create_all(engine)
