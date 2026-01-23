# Data Model

**Status**: 🟢 Complete
**Last verified**: —
**Last synced**: 2026-01-22 (reconciled with domain specs)
**Depends on**: Topics, Privacy, Salience, Insights, Layers

---

## Overview

This document defines the core entities, their relationships, and storage approach. The data model supports the observe/reflect split: messages flow in continuously, salience accumulates, and reflection produces insights.

---

## Entity Relationship Summary

```
Server ─────< Channel ─────< Message
   │              │
   │              └────< Thread (optional per server)
   │
   ├── ServerConfig (privacy_gate_role, disabled_layers, threads_as_topics)
   │
   └────< UserServerTracking (for global topic warming)

Topic (server-scoped and global)
   │
   ├──── SalienceLedger (earn/spend/decay/propagate)
   │
   └────< Insight ◄─── LayerRun

User (Discord entity, tracked via first_dm_acknowledged)
```

---

## Core Entities

### Server

**Purpose**: Discord server configuration and tracking.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | string | yes | Discord server snowflake |
| name | string | no | Human-readable alias for display |
| privacy_gate_role | string | no | Role ID required for identity tracking (null = all tracked) |
| disabled_layers | json | no | Array of layer names opted out |
| threads_as_topics | bool | yes | Whether threads get their own topics (default: true) |
| created_at | timestamp | yes | When first seen |

**Relationships**:
- Has many: Channels, UserServerTracking entries
- Referenced by: Topic keys (`server:<id>:...`)

---

### User

**Purpose**: Discord user tracking for first-contact acknowledgment.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | string | yes | Discord user snowflake |
| first_dm_acknowledged | bool | yes | Whether first-contact message was sent (default: false) |
| first_dm_at | timestamp | no | When first DM was received |

**Note**: User topics and insights are stored separately. This table only tracks the acknowledgment state for implicit consent.

---

### UserServerTracking

**Purpose**: Track which servers a user has been active in (for global topic warming).

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| user_id | string | yes | Discord user ID |
| server_id | string | yes | Discord server ID |
| first_seen_at | timestamp | yes | When first activity occurred |

**Primary key**: `(user_id, server_id)`

**Usage**: When `COUNT(DISTINCT server_id) >= 2` for a user, their global topic (`user:<id>`) is warmed.

---

### Channel

**Purpose**: Discord channel tracking.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | string | yes | Discord channel snowflake |
| server_id | string | yes | Parent server |
| name | string | no | Channel name for display |
| type | enum | yes | `text`, `voice`, `dm`, `group_dm`, `thread` |
| parent_id | string | no | Parent channel ID (for threads) |
| created_at | timestamp | yes | When first seen |

**Relationships**:
- Belongs to: Server
- Has many: Messages
- May have parent: Channel (for threads)

---

### Message

**Purpose**: Raw observations from Discord — the input to the system.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | string | yes | Discord message snowflake |
| channel_id | string | yes | Where sent |
| server_id | string | no | Server ID (null for DMs) |
| author_id | string | yes | Who sent (real Discord ID, even for `<chat>` users) |
| content | string | yes | Message text |
| created_at | timestamp | yes | Discord timestamp |
| visibility_scope | enum | yes | `public` or `dm` |
| reactions | json | no | Reaction counts |
| reply_to_id | string | no | ID of message being replied to |
| thread_id | string | no | Thread ID if in a thread |
| ingested_at | timestamp | yes | When we processed it |

**Relationships**:
- Belongs to: Channel, Server (optional)
- Referenced by: Insights (as source context)

**Note**: `author_id` always stores the real Discord user ID. Anonymization to `<chat_N>` happens at context assembly time based on server's `privacy_gate_role`.

---

### Topic

**Purpose**: Canonical entities the system can think about.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| key | string | yes | Primary key (see Topic Key Format below) |
| category | enum | yes | `user`, `channel`, `thread`, `role`, `dyad`, `user_in_channel`, `dyad_in_channel`, `subject`, `self` |
| is_global | bool | yes | True if no server prefix (e.g., `user:123` vs `server:A:user:123`) |
| provisional | bool | yes | True if auto-created and pending consolidation review (default: false) |
| created_at | timestamp | yes | First seen |
| last_activity_at | timestamp | no | Last salience-earning activity (for decay calculation) |
| metadata | json | no | Extensible attributes |

**Relationships**:
- Has many: Insights, SalienceLedger entries

### Topic Key Format

**Global topics** (no server prefix):
- `user:<discord_id>` — unified person understanding
- `dyad:<user_a>:<user_b>` — unified relationship (IDs sorted ascending)
- `self:zos` — core identity
- `self:<aspect>` — emergent self-topics (e.g., `self:social_patterns`)

**Server-scoped topics**:
- `server:<id>:user:<id>` — person in a server
- `server:<id>:channel:<id>` — channel
- `server:<id>:thread:<id>` — thread (if `threads_as_topics` enabled)
- `server:<id>:role:<id>` — Discord role
- `server:<id>:dyad:<a>:<b>` — relationship in a server
- `server:<id>:user_in_channel:<channel>:<user>` — person's presence in a channel
- `server:<id>:dyad_in_channel:<channel>:<a>:<b>` — relationship in a channel
- `server:<id>:subject:<name>` — emergent theme
- `server:<id>:self:zos` — contextual self-understanding

---

### SalienceLedger

**Purpose**: Full transaction history for salience tracking.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | string | yes | ULID |
| topic_key | string | yes | Which topic |
| transaction_type | enum | yes | `earn`, `spend`, `retain`, `decay`, `propagate`, `spillover`, `warm` |
| amount | float | yes | Delta (positive for earn/retain/warm, negative for spend/decay) |
| reason | string | no | What caused this (message_id, layer_run_id, etc.) |
| source_topic | string | no | For propagation/spillover: which topic triggered this |
| created_at | timestamp | yes | When |

**Relationships**:
- Belongs to: Topic
- Derived: Current balance = `SUM(amount) WHERE topic_key = X`

### Transaction Types

| Type | Direction | Cause |
|------|-----------|-------|
| `earn` | positive | Activity (message, reaction, mention, reply) |
| `spend` | negative | Insight creation consumed budget |
| `retain` | positive | Partial retention after spending |
| `decay` | negative | Inactivity decay (after threshold days) |
| `propagate` | positive | Related topic earned salience |
| `spillover` | positive | Related topic hit cap, overflow spilled |
| `warm` | positive | Global topic warmed (DM or second server) |

---

### Insight

**Purpose**: Persistent understanding generated by reflection.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | string | yes | ULID (sortable, unique) |
| topic_key | string | yes | Primary topic this insight is about |
| category | string | yes | Layer category that produced it (e.g., `user_reflection`, `dyad_observation`, `synthesis`, `self_reflection`) |
| content | string | yes | The actual understanding (natural language) |
| sources_scope_max | enum | yes | `public`, `dm`, or `derived` |
| created_at | timestamp | yes | When generated |
| layer_run_id | string | yes | Which layer run produced this |
| supersedes | string | no | ID of insight this updates (not replaces) |
| quarantined | bool | yes | True if subject user lost privacy gate role (default: false) |

### Insight Strength and Metrics

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| salience_spent | float | yes | Base salience consumed creating this |
| strength_adjustment | float | yes | Model's adjustment factor (0.1 - 10.0) |
| strength | float | computed | `salience_spent × strength_adjustment` (store for query efficiency) |
| confidence | float | yes | How certain (0.0 - 1.0) |
| importance | float | yes | How much this matters (0.0 - 1.0) |
| novelty | float | yes | How surprising (0.0 - 1.0) |

### Insight Emotional Valence

**At least one valence field must be populated** per insight.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| valence_joy | float | at least one | 0.0 - 1.0, positive affect |
| valence_concern | float | at least one | 0.0 - 1.0, worry/anxiety |
| valence_curiosity | float | at least one | 0.0 - 1.0, interest/engagement |
| valence_warmth | float | at least one | 0.0 - 1.0, connection/affection |
| valence_tension | float | at least one | 0.0 - 1.0, conflict/discomfort |

### Insight Cross-Topic Links (Optional)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| context_channel | string | no | Channel topic key where this emerged |
| context_thread | string | no | Thread topic key if applicable |
| subject | string | no | Subject topic key if applicable |
| participants | json | no | Array of topic keys for all entities involved |

### Insight Conflict Tracking

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| conflicts_with | json | no | Array of insight IDs this contradicts |
| conflict_resolved | bool | no | Whether synthesis has addressed this (default: false) |

### Insight Synthesis Tracking

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| synthesis_source_ids | json | no | Array of insight IDs combined in this synthesis (only for `category=synthesis`) |

**Relationships**:
- Belongs to: Topic, LayerRun
- May supersede: another Insight
- May conflict with: other Insights

**Note**: `expires_at` intentionally omitted — memory is sacred in MVP 0. Insights persist indefinitely; deletion is operator intervention only.

---

### LayerRun

**Purpose**: Audit trail for reflection execution.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | string | yes | ULID |
| layer_name | string | yes | Which layer ran |
| layer_hash | string | yes | Content hash of layer YAML at time of run |
| started_at | timestamp | yes | When run began |
| completed_at | timestamp | no | When run finished |
| status | enum | yes | `success`, `partial`, `failed`, `dry` |
| targets_matched | int | yes | How many topics matched the filter |
| targets_processed | int | yes | How many were actually processed |
| targets_skipped | int | yes | How many skipped due to errors |
| insights_created | int | yes | How many insights stored |
| tokens_used | int | no | Total LLM tokens consumed |
| errors | json | no | Array of error details for skipped topics |

**Relationships**:
- Has many: Insights
- References: Topics (as targets)

### LayerRun Status Values

| Status | Meaning |
|--------|---------|
| `success` | All targets processed, insights created |
| `partial` | Some targets skipped due to errors |
| `failed` | Layer failed entirely |
| `dry` | Layer ran but produced zero insights |

---

## Storage Approach

### MVP 0

- **SQLite**: Single file, local-first, no infrastructure
- **Rationale**: Simplicity; can run on any machine; easy backup (copy file)
- **Location**: Configurable, default `./data/zos.db`

### MVP 1

- **Still SQLite**: Expected data volumes don't require more
- **Consider**: WAL mode for concurrent reads during observe + reflect

### Future Considerations

- If multi-instance needed: consider SQLite with Litestream replication
- If scale demands: PostgreSQL migration path should be straightforward

---

## ID Strategy

- **Format**: ULID for generated IDs (sortable, unique, URL-safe)
- **External IDs**: Discord snowflakes used as-is for messages, users, channels, servers
- **Topic keys**: Structured strings (see Topic Key Format above)
- **Rationale**: ULIDs are chronologically sortable which helps with range queries; Discord IDs preserved for consistency

---

## Indexing Strategy

| Entity | Index | Purpose |
|--------|-------|---------|
| Message | `(channel_id, created_at)` | Fetch recent messages per channel |
| Message | `(author_id, created_at)` | Fetch user's recent messages |
| Message | `(server_id, created_at)` | Fetch recent messages per server |
| Topic | `(category)` | Filter topics by type |
| Topic | `(is_global)` | Separate global vs server-scoped queries |
| Topic | `(provisional)` | Find topics needing consolidation |
| SalienceLedger | `(topic_key, created_at)` | Balance calculation, history |
| Insight | `(topic_key, created_at)` | Fetch insights for topic |
| Insight | `(category, created_at)` | Fetch insights by type |
| Insight | `(quarantined)` | Exclude quarantined from retrieval |
| Insight | `(layer_run_id)` | Audit which run produced which insights |
| LayerRun | `(layer_name, started_at)` | Audit queries |
| LayerRun | `(status)` | Find dry runs, failures |
| UserServerTracking | `(user_id)` | Check how many servers a user is in |

---

## Derived Views

### Current Salience Balance

```sql
CREATE VIEW topic_salience AS
SELECT
    topic_key,
    SUM(amount) as balance,
    MAX(created_at) FILTER (WHERE transaction_type = 'earn') as last_activity
FROM salience_ledger
GROUP BY topic_key;
```

### Active Insights (non-quarantined)

```sql
CREATE VIEW active_insights AS
SELECT * FROM insights
WHERE quarantined = false;
```

### Global Ref Extraction (computed, not stored)

```sql
-- For server-scoped user/dyad topics, extract global ref
-- server:123:user:456 -> user:456
-- server:123:dyad:456:789 -> dyad:456:789

CREATE VIEW insight_global_refs AS
SELECT
    id,
    topic_key,
    CASE
        WHEN topic_key LIKE 'server:%:user:%'
        THEN 'user:' || SUBSTR(topic_key, INSTR(topic_key, ':user:') + 6)
        WHEN topic_key LIKE 'server:%:dyad:%'
        THEN 'dyad:' || SUBSTR(topic_key, INSTR(topic_key, ':dyad:') + 6)
        ELSE NULL
    END as global_ref
FROM insights;
```

---

## Migration Strategy

- Schema versioning in `_schema_version` table
- Forward-only migrations (no rollback for simplicity)
- Migrations are Python scripts run at startup if needed

---

## Validation Rules

### Insight Valence Constraint

At least one valence field must be non-null:

```sql
CHECK (
    valence_joy IS NOT NULL OR
    valence_concern IS NOT NULL OR
    valence_curiosity IS NOT NULL OR
    valence_warmth IS NOT NULL OR
    valence_tension IS NOT NULL
)
```

### Topic Key Format Validation

Topic keys must match expected patterns:

```python
TOPIC_KEY_PATTERNS = [
    r'^user:\d+$',                                    # global user
    r'^dyad:\d+:\d+$',                               # global dyad (sorted)
    r'^self:\w+$',                                   # global self
    r'^server:\d+:user:\d+$',                        # server user
    r'^server:\d+:channel:\d+$',                     # channel
    r'^server:\d+:thread:\d+$',                      # thread
    r'^server:\d+:role:\d+$',                        # role
    r'^server:\d+:dyad:\d+:\d+$',                    # server dyad
    r'^server:\d+:user_in_channel:\d+:\d+$',         # user in channel
    r'^server:\d+:dyad_in_channel:\d+:\d+:\d+$',     # dyad in channel
    r'^server:\d+:subject:\w+$',                     # subject
    r'^server:\d+:self:\w+$',                        # server self
]
```

---

## Self-Concept Document

The `self-concept.md` document is **not stored in the database** — it's a markdown file on disk:

- **Location**: `data/self-concept.md`
- **Format**: Markdown, human and LLM readable
- **Updates**: Via `update_self_concept` node in self-reflection layer
- **Always in context**: Loaded for every reflection and conversation

This document includes Zos's conflict threshold as explicit self-knowledge.

---

_Last updated: 2026-01-22 — Full rewrite to sync with domain specs_
