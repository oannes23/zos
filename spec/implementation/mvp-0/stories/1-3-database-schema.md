# Story 1.3: Database Schema

**Epic**: Foundation
**Status**: 🔴 Not Started
**Estimated complexity**: Large

## Goal

Define all SQLAlchemy Core tables matching the data model specification, with proper indexes and constraints.

## Acceptance Criteria

- [ ] All entities from `data-model.md` have corresponding tables
- [ ] Indexes defined for common query patterns
- [ ] Constraints enforce data integrity (foreign keys, check constraints)
- [ ] Tables can be created on fresh database
- [ ] Schema matches spec exactly (field names, types)

## Tables to Create

From `spec/architecture/data-model.md`:

### Core Entities

| Table | Key Fields | Notes |
|-------|------------|-------|
| `servers` | id, name, privacy_gate_role, chattiness_config | Discord servers |
| `users` | id, first_dm_acknowledged, first_dm_at | Discord users |
| `user_server_tracking` | user_id, server_id, first_seen_at | Multi-server presence |
| `channels` | id, server_id, name, type, parent_id | Discord channels |
| `messages` | id, channel_id, author_id, content, has_media, has_links, deleted_at | Raw observations |
| `reactions` | id, message_id, user_id, emoji, is_custom, removed_at | Reaction tracking |
| `poll_state` | channel_id (PK), last_message_at, last_polled_at | Polling state tracking |
| `media_analysis` | id, message_id, media_type, description | Vision analysis |
| `link_analysis` | id, message_id, url, domain, summary | Link fetching |

### Topic & Salience

| Table | Key Fields | Notes |
|-------|------------|-------|
| `topics` | key (PK), category, is_global, provisional | Topic registry |
| `salience_ledger` | id, topic_key, transaction_type, amount | Salience transactions |

### Insights & Reflection

| Table | Key Fields | Notes |
|-------|------------|-------|
| `insights` | id, topic_key, category, content, strength, valence_* | Accumulated understanding |
| `layer_runs` | id, layer_name, layer_hash, status, model_*, tokens_* | Audit trail |

### Chattiness (MVP 1 prep, create tables now)

| Table | Key Fields | Notes |
|-------|------------|-------|
| `chattiness_ledger` | id, pool, channel_id, topic_key, amount | Impulse tracking |
| `speech_pressure` | id, amount, trigger, server_id | Global threshold modifier |
| `conversation_log` | id, message_id, channel_id, layer_name | Zos's messages |
| `draft_history` | id, channel_id, content, discard_reason | Discarded drafts |

## Technical Notes

### SQLAlchemy Core Style

Use SQLAlchemy Core (not ORM) for explicit SQL:

```python
# src/zos/database.py
from sqlalchemy import (
    MetaData, Table, Column,
    String, Integer, Float, Boolean, DateTime, JSON,
    ForeignKey, Index, CheckConstraint,
    create_engine, text
)
from datetime import datetime

metadata = MetaData()

# Example: messages table
messages = Table(
    "messages",
    metadata,
    Column("id", String, primary_key=True),  # Discord snowflake
    Column("channel_id", String, ForeignKey("channels.id"), nullable=False),
    Column("server_id", String, ForeignKey("servers.id"), nullable=True),  # Null for DMs
    Column("author_id", String, nullable=False),
    Column("content", String, nullable=False),
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

# Example: insights table with valence constraint
insights = Table(
    "insights",
    metadata,
    Column("id", String, primary_key=True),  # ULID
    Column("topic_key", String, ForeignKey("topics.key"), nullable=False),
    Column("category", String, nullable=False),
    Column("content", String, nullable=False),
    Column("sources_scope_max", String, nullable=False),
    Column("created_at", DateTime, nullable=False),
    Column("layer_run_id", String, ForeignKey("layer_runs.id"), nullable=False),
    Column("supersedes", String, nullable=True),
    Column("quarantined", Boolean, nullable=False, default=False),

    # Strength and metrics
    Column("salience_spent", Float, nullable=False),
    Column("strength_adjustment", Float, nullable=False),
    Column("strength", Float, nullable=False),  # Computed: salience_spent * adjustment
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

    Index("ix_insights_topic_created", "topic_key", "created_at"),
    Index("ix_insights_category_created", "category", "created_at"),
    Index("ix_insights_quarantined", "quarantined"),
    Index("ix_insights_layer_run", "layer_run_id"),

    # At least one valence must be set
    CheckConstraint(
        "valence_joy IS NOT NULL OR valence_concern IS NOT NULL OR "
        "valence_curiosity IS NOT NULL OR valence_warmth IS NOT NULL OR "
        "valence_tension IS NOT NULL",
        name="ck_insights_valence_required"
    ),
)
```

### Database Connection

```python
def get_engine(config: Config):
    """Create SQLAlchemy engine from config."""
    db_path = config.data_dir / "zos.db"
    return create_engine(
        f"sqlite:///{db_path}",
        echo=config.log_level == "DEBUG",
    )

def create_tables(engine):
    """Create all tables."""
    metadata.create_all(engine)
```

### ULID Generation

```python
from ulid import ULID

def generate_id() -> str:
    """Generate a new ULID for entities."""
    return str(ULID())
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/database.py` | All table definitions, connection management |
| `tests/test_database.py` | Schema creation tests |

## Test Cases

1. Tables create successfully on fresh DB
2. Foreign key constraints are enforced
3. Check constraint on insights valence works
4. Indexes are created
5. ULID generation produces valid IDs

## Definition of Done

- [ ] All tables from data-model.md are defined
- [ ] `create_tables()` works on fresh database
- [ ] Constraints enforced (can test with invalid inserts)
- [ ] Indexes created for query patterns

---

## Design Decisions (Resolved 2026-01-23)

### Q1: SQLite Journal Mode
**Decision**: WAL (Write-Ahead Logging)
- Readers don't block writers — good for API + background tasks in unified process
- Creates 3 files (db, wal, shm) but worth it for concurrency
- Backup/copy needs to include all WAL files

### Q2: Message Content Storage
**Decision**: Store full content
- Verbatim preservation, simple implementation
- The raw message is ground truth; insights are interpretation
- Storage cost acceptable for Discord message volumes

### Q3: Timezone Handling
**Decision**: UTC only
- Simple, consistent, all timestamps in UTC
- User's local time context comes from user knowledge and insights, not stored timezone
- "3 AM their time" meaning emerges from understanding the user, not timestamp metadata

### Q4: ULID Consistency
**Decision**: Convention with documentation
- ULIDs for Zos-generated entities, Discord snowflakes for Discord entities
- Document that `ORDER BY id` equals `ORDER BY created_at` for Zos entities (ULIDs are time-sortable)
- No helper function needed — just documented convention

### Q5: JSON Columns
**Decision**: Keep JSON for flexibility
- `reactions_aggregate`, `participants`, `errors` stay as JSON columns
- Document that high-query fields may need extraction to dedicated columns later
- For MVP, flexibility > query performance

---

## Additional Decisions (Resolved 2026-01-24)

### Q6: LLM Calls Audit Table
**Decision**: Full prompt AND full response storage
- Store complete prompt text (useful for fine-tuning, debugging)
- Store complete response (failed parses would otherwise lose raw output)
- Indexes: by layer_run_id, by created_at, by model_profile

**Schema**:
```python
llm_calls = Table(
    "llm_calls",
    metadata,
    Column("id", String, primary_key=True),  # ULID
    Column("layer_run_id", String, ForeignKey("layer_runs.id"), nullable=True),
    Column("topic_key", String, nullable=True),
    Column("model_profile", String, nullable=False),
    Column("model_provider", String, nullable=False),
    Column("model_name", String, nullable=False),
    Column("prompt", String, nullable=False),  # Full prompt text
    Column("response", String, nullable=False),  # Full response text
    Column("tokens_input", Integer, nullable=False),
    Column("tokens_output", Integer, nullable=False),
    Column("estimated_cost_usd", Float, nullable=True),
    Column("latency_ms", Integer, nullable=True),
    Column("created_at", DateTime, nullable=False),

    Index("ix_llm_calls_layer_run", "layer_run_id"),
    Index("ix_llm_calls_created", "created_at"),
    Index("ix_llm_calls_profile", "model_profile"),
)
```

### Q7: Reaction Table — `removed_at` Field
**Decision**: Add `removed_at` timestamp
- Soft delete for reactions, consistent with message tombstone approach
- Field added to reactions table definition

### Q8: Poll State Table
**Decision**: Track polling state per channel
- `poll_state` table tracks last_message_at and last_polled_at per channel
- Used by message polling (Story 2.2) to efficiently fetch only new messages
- Simple primary key on channel_id

**Schema**:
```python
poll_state = Table(
    "poll_state",
    metadata,
    Column("channel_id", String, primary_key=True),  # Discord snowflake
    Column("last_message_at", DateTime, nullable=True),  # Timestamp of most recent message
    Column("last_polled_at", DateTime, nullable=False),  # When we last polled this channel
)
```

---

**Requires**: Story 1.2 (config for DB path)
**Blocks**: Story 1.4 (migrations), Story 1.5 (Pydantic models)
