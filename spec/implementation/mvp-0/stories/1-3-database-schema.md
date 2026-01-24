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
| `messages` | id, channel_id, author_id, content, has_media, has_links | Raw observations |
| `reactions` | id, message_id, user_id, emoji, is_custom | Reaction tracking |
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

**Requires**: Story 1.2 (config for DB path)
**Blocks**: Story 1.4 (migrations), Story 1.5 (Pydantic models)
