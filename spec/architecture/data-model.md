# Data Model

**Status**: 🟢 Complete
**Last verified**: 2026-02-13
**Last synced**: 2026-02-13 (reconciled spec ↔ code)
**Depends on**: Observation, Topics, Privacy, Salience, Insights, Layers, Chattiness

---

## Overview

This document defines the core entities, their relationships, and storage approach. The data model supports the observe/reflect split: messages flow in continuously, salience accumulates, and reflection produces insights.

---

## Entity Relationship Summary

```
Server ─────< Channel ─────< Message ─────< Reaction
   │              │              │
   │              │              ├────< MediaAnalysis
   │              │              │
   │              │              └────< LinkAnalysis
   │              │
   │              └────< Thread (optional per server)
   │
   ├── ServerConfig (privacy_gate_role, disabled_layers, threads_as_topics, chattiness)
   │
   └────< UserServerTracking (for global topic warming)

Topic (server-scoped and global, including emoji topics)
   │
   ├──── SalienceLedger (earn/spend/decay/propagate)
   │
   └────< Insight ◄─── LayerRun

User (Discord entity, tracked via first_dm_acknowledged)

ChattinessLedger (pool × channel × topic impulse tracking)
   │
   └────< SpeechPressure (global threshold modifier after speaking)
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
| chattiness_config | json | no | Chattiness settings (threshold bounds, output channel, pool enables) |
| created_at | timestamp | yes | When first seen |

**Relationships**:
- Has many: Channels, UserServerTracking entries
- Referenced by: Topic keys (`server:<id>:...`)

### Server Chattiness Config Schema

```json
{
  "threshold_min": 30,
  "threshold_max": 80,
  "output_channel": null,
  "pools_enabled": {
    "address": true,
    "insight": true,
    "conversational": true,
    "curiosity": true,
    "reaction": true
  }
}
```

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
| reactions_aggregate | json | no | Reaction counts for quick access (denormalized) |
| reply_to_id | string | no | ID of message being replied to |
| thread_id | string | no | Thread ID if in a thread |
| has_media | bool | yes | Whether message contains images/videos (default: false) |
| has_links | bool | yes | Whether message contains URLs (default: false) |
| ingested_at | timestamp | yes | When we processed it |
| deleted_at | timestamp | no | When message was deleted (soft delete tombstone) |

**Relationships**:
- Belongs to: Channel, Server (optional)
- Has many: Reactions, MediaAnalysis, LinkAnalysis
- Referenced by: Insights (as source context)

**Note**: `author_id` always stores the real Discord user ID. Anonymization to `<chat_N>` happens at context assembly time based on server's `privacy_gate_role`.

**Delete handling**: When a message is deleted by the user, `deleted_at` is set rather than removing the row. Deleted messages are excluded from new reflection but preserved for audit. Zos experiences deletions as "unsayings."

---

### Reaction

**Purpose**: Full reaction tracking for relationship inference.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | string | yes | ULID |
| message_id | string | yes | Which message was reacted to |
| user_id | string | yes | Who reacted (real Discord ID) |
| emoji | string | yes | Emoji used (Unicode or custom emoji ID) |
| is_custom | bool | yes | Whether this is a server custom emoji |
| server_id | string | no | Server where reaction occurred (for custom emoji topics) |
| created_at | timestamp | yes | When reaction was added |

**Relationships**:
- Belongs to: Message
- Links to: User, potentially Emoji Topic (`server:<id>:emoji:<emoji_id>`)

**Privacy note**: For users without privacy gate role, reactions are tracked in `Message.reactions_aggregate` only (aggregate counts), not in this table.

---

### MediaAnalysis

**Purpose**: Vision analysis results for images and videos.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | string | yes | ULID |
| message_id | string | yes | Which message contained this media |
| media_type | enum | yes | `image`, `video`, `gif`, `embed` |
| url | string | yes | Original media URL |
| filename | string | no | Original filename if available |
| width | int | no | Width in pixels |
| height | int | no | Height in pixels |
| duration_seconds | int | no | For video/gif (null for images) |
| description | string | yes | Phenomenological description ("I see...") |
| analyzed_at | timestamp | yes | When analysis completed |
| analysis_model | string | no | Which vision model was used |

**Relationships**:
- Belongs to: Message

**Note**: Raw media files are not stored — only descriptions. Zos remembers what it saw, not the actual files.

---

### LinkAnalysis

**Purpose**: Fetched link content and summaries.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | string | yes | ULID |
| message_id | string | yes | Which message contained this link |
| url | string | yes | Full URL |
| domain | string | yes | Extracted domain for pattern analysis |
| content_type | enum | yes | `article`, `video`, `image`, `audio`, `other` |
| title | string | no | Page/video title |
| summary | string | no | Brief content summary |
| is_youtube | bool | yes | Whether this is a YouTube link (special handling) |
| duration_seconds | int | no | For video content |
| transcript_available | bool | no | Whether transcript was fetched (YouTube) |
| fetched_at | timestamp | no | When content was retrieved |
| fetch_failed | bool | yes | Whether fetch attempt failed (default: false) |
| fetch_error | string | no | Error message if fetch failed |

**Relationships**:
- Belongs to: Message

**Note**: Videos > 30 minutes get metadata only (TLDW principle). Transcript extraction for YouTube content when available.

---

### Topic

**Purpose**: Canonical entities the system can think about.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| key | string | yes | Primary key (see Topic Key Format below) |
| category | enum | yes | `user`, `channel`, `thread`, `role`, `dyad`, `user_in_channel`, `dyad_in_channel`, `subject`, `emoji`, `self` |
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
- `server:<id>:emoji:<emoji_id>` — custom emoji cultural meaning
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

### SubjectMessageSources

**Purpose**: Junction table linking subject topics to the Discord messages that were in the context window when the subject was identified. Enables subject reflections to retrieve relevant messages directly instead of relying on keyword search (which fails for semantically-identified themes).

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | string | yes | ULID |
| subject_topic_key | string | yes | FK to topics.key — the subject topic |
| message_id | string | yes | FK to messages.id — a message in the original context window |
| source_topic_key | string | yes | The user/channel/dyad topic that surfaced this subject |
| layer_run_id | string | yes | Which reflection run identified the subject |
| created_at | timestamp | yes | When the association was recorded |

**Relationships**:
- Belongs to: Topic (subject), Message
- Unique constraint on (subject_topic_key, message_id) — prevents duplicates across reflection runs

**Usage**: At subject reflection time, two-phase retrieval:
1. **Junction table** — directly associated messages from past reflection context windows
2. **Source topic re-query** — recent messages from users/channels that originally surfaced the subject (via salience_ledger.source_topic)

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
| sources_scope_max | enum | yes | `public`, `dm`, or `derived` (🔴 `derived` deferred — not yet in code) |
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
| original_topic_salience | float | yes | Topic salience at time of insight creation (for decay calculation) |
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
| valence_awe | float | at least one | 🟡 0.0 - 1.0, encountering the numinous |
| valence_grief | float | at least one | 🟡 0.0 - 1.0, loss, endings |
| valence_longing | float | at least one | 🟡 0.0 - 1.0, desire not yet achieved |
| valence_peace | float | at least one | 🟡 0.0 - 1.0, settledness, equanimity |
| valence_gratitude | float | at least one | 🟡 0.0 - 1.0, appreciation, value |

### Insight Cross-Topic Links (Optional)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| context_channel | string | no | Channel topic key where this emerged |
| context_thread | string | no | Thread topic key if applicable |
| subject | string | no | Subject topic key if applicable |
| participants | json | no | Array of topic keys for all entities involved |

### Insight Prospective Curiosity (🟡 Open Issue)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| open_questions | json | no | 🟡 Array of strings — what the model is curious to learn more about |

**Note**: Open questions capture forward-looking curiosity, not predictions. See [insights.md](../domains/insights.md) for the "curiosity not prediction" framing.

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
| model_profile | string | no | Model profile used (e.g., `moderate`, `complex`) |
| model_provider | string | no | Actual provider (e.g., `anthropic`, `openai`) |
| model_name | string | no | Actual model (e.g., `claude-sonnet-4-20250514`) |
| tokens_input | int | no | Input/prompt tokens consumed |
| tokens_output | int | no | Output/completion tokens consumed |
| tokens_total | int | no | Total tokens (input + output) |
| estimated_cost_usd | float | no | Estimated cost based on token pricing |
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

### ChattinessLedger

**Purpose**: Full transaction history for impulse tracking across five pools.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | string | yes | ULID |
| pool | enum | yes | `address`, `insight`, `conversational`, `curiosity`, `reaction` |
| channel_id | string | no | Channel scope (null for global pool-level) |
| topic_key | string | no | Topic scope (null for channel-level only) |
| transaction_type | enum | yes | `earn`, `spend`, `decay`, `flood`, `reset` |
| amount | float | yes | Delta (positive for earn/flood, negative for spend/decay) |
| trigger | string | no | What caused this (message_id, ping, insight_id, etc.) |
| created_at | timestamp | yes | When |

**Relationships**:
- May link to: Channel, Topic

**Note**: Three-dimensional tracking: pool × channel × topic. Allows queries like "impulse in #general for user topics" or "total address impulse across all channels."

### Chattiness Transaction Types

| Type | Direction | Cause |
|------|-----------|-------|
| `earn` | positive | Activity trigger (message, mention of relevant topic, etc.) |
| `spend` | negative | Speech consumed the impulse |
| `decay` | negative | Time-based decay |
| `flood` | positive | Overwhelming trigger (direct ping, DM) |
| `reset` | negative | Zero out impulse after speaking (MVP 1 simplified model) |

---

### SpeechPressure

**Purpose**: Track global speech pressure (threshold modifier after Zos speaks).

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | string | yes | ULID |
| amount | float | yes | Pressure added (positive) or decayed (negative) |
| trigger | string | no | Which layer/output caused this |
| server_id | string | no | Server where speech occurred (null for global) |
| created_at | timestamp | yes | When |

**Usage**: Current pressure = `SUM(amount) WHERE created_at > NOW() - pressure_decay_window`

Pressure decays over time (configurable, default 30 minutes to baseline). Higher pressure raises effective threshold for all impulse pools.

---

### ConversationLog

**Purpose**: Track Zos's own messages for conversation context and reflection.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | string | yes | ULID |
| message_id | string | yes | Discord message ID of Zos's message |
| channel_id | string | yes | Where sent |
| server_id | string | no | Server (null for DMs) |
| content | string | yes | What Zos said |
| layer_name | string | yes | Which conversation layer produced this |
| trigger_type | string | yes | What triggered the response (ping, impulse, etc.) |
| impulse_pool | enum | yes | Which pool drove the speech |
| impulse_spent | float | yes | How much impulse was consumed |
| priority_flagged | bool | yes | Whether flagged for priority reflection (default: false) |
| created_at | timestamp | yes | When sent |

**Relationships**:
- Links to: Channel, Message (Zos's own)

---

### LLMCallLog

**Purpose**: Comprehensive audit of every LLM API call for debugging, cost analysis, and potential future fine-tuning.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | string | yes | ULID |
| layer_run_id | string | no | Which layer run this call was part of (null for non-reflection calls) |
| call_type | enum | yes | `reflection`, `vision`, `conversation`, `synthesis`, `other` |
| model_profile | string | yes | Profile name used (e.g., `moderate`, `complex`, `vision`) |
| model_provider | string | yes | Actual provider (e.g., `anthropic`, `openai`) |
| model_name | string | yes | Actual model (e.g., `claude-sonnet-4-20250514`) |
| request_prompt | text | yes | Full prompt sent (may be large) |
| response_content | text | yes | Full response received |
| tokens_input | int | yes | Input/prompt tokens |
| tokens_output | int | yes | Output/completion tokens |
| tokens_total | int | yes | Total tokens (input + output) |
| estimated_cost_usd | float | yes | Cost estimate based on token pricing |
| latency_ms | int | yes | Request duration in milliseconds |
| success | bool | yes | Whether call succeeded (default: true) |
| error_message | string | no | Error details if failed |
| created_at | timestamp | yes | When call was made |

**Relationships**:
- May belong to: LayerRun
- Referenced by: Insight (via layer_run_id chain)

**Note**: Request and response are stored in full for auditability. This table will grow large; consider archival strategy for production.

---

### DraftHistory

**Purpose**: Track discarded drafts for "things I almost said" context.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | string | yes | ULID |
| channel_id | string | yes | Conversation context |
| thread_id | string | no | Thread context if applicable |
| content | string | yes | The discarded draft |
| layer_name | string | yes | Which layer generated it |
| discard_reason | string | no | Why it was discarded (review fail, self-censored, etc.) |
| created_at | timestamp | yes | When generated |

**Relationships**:
- Scoped to: Channel/Thread conversation

**Note**: Drafts are cleared between conversation threads. They inform subsequent generation within the same conversation.

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
| Reaction | `(message_id)` | Fetch reactions for a message |
| Reaction | `(user_id, created_at)` | Fetch user's reaction history |
| Reaction | `(emoji, server_id)` | Emoji usage patterns per server |
| MediaAnalysis | `(message_id)` | Fetch media for a message |
| LinkAnalysis | `(message_id)` | Fetch links for a message |
| LinkAnalysis | `(domain, created_at)` | Domain sharing patterns |
| ChattinessLedger | `(pool, channel_id, created_at)` | Impulse calculation per pool/channel |
| ChattinessLedger | `(pool, topic_key, created_at)` | Impulse calculation per pool/topic |
| SpeechPressure | `(created_at)` | Current pressure calculation |
| ConversationLog | `(channel_id, created_at)` | Zos's messages in a conversation |
| DraftHistory | `(channel_id, thread_id, created_at)` | Drafts for a conversation |
| LLMCallLog | `(layer_run_id)` | All calls for a layer run |
| LLMCallLog | `(model_provider, created_at)` | Cost analysis by provider |
| LLMCallLog | `(call_type, created_at)` | Analysis by call type |

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

### Current Impulse per Pool

```sql
CREATE VIEW current_impulse AS
SELECT
    pool,
    channel_id,
    topic_key,
    SUM(amount) as impulse
FROM chattiness_ledger
GROUP BY pool, channel_id, topic_key;
```

### Current Speech Pressure

```sql
-- Pressure within decay window (default 30 minutes)
CREATE VIEW current_speech_pressure AS
SELECT
    server_id,
    SUM(amount) as pressure
FROM speech_pressure
WHERE created_at > datetime('now', '-30 minutes')
GROUP BY server_id;
```

### Reaction Patterns (for relationship inference)

```sql
-- Who reacts to whose messages
CREATE VIEW reaction_patterns AS
SELECT
    r.user_id as reactor_id,
    m.author_id as author_id,
    r.server_id,
    COUNT(*) as reaction_count,
    COUNT(DISTINCT r.emoji) as emoji_variety
FROM reactions r
JOIN messages m ON r.message_id = m.id
GROUP BY r.user_id, m.author_id, r.server_id;
```

### Emoji Usage per Server

```sql
CREATE VIEW emoji_usage AS
SELECT
    server_id,
    emoji,
    is_custom,
    COUNT(*) as use_count,
    COUNT(DISTINCT user_id) as unique_users
FROM reactions
GROUP BY server_id, emoji, is_custom;
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
    valence_tension IS NOT NULL OR
    valence_awe IS NOT NULL OR        -- 🟡 Open Issue
    valence_grief IS NOT NULL OR      -- 🟡 Open Issue
    valence_longing IS NOT NULL OR    -- 🟡 Open Issue
    valence_peace IS NOT NULL OR      -- 🟡 Open Issue
    valence_gratitude IS NOT NULL     -- 🟡 Open Issue
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
    r'^server:\d+:emoji:\d+$',                       # emoji
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

## Insight Categories

The `category` field on Insight indicates what type of understanding this represents:

### Reflection Categories (from scheduled layers)
- `user_reflection` — understanding about an individual
- `dyad_observation` — relationship observations
- `channel_reflection` — space/channel patterns
- `subject_reflection` — semantic topic understanding
- `self_reflection` — Zos's self-understanding
- `synthesis` — consolidated understanding from multiple sources
- `appreciation` — 🔴 Deferred — what Zos values, finds meaningful, or is grateful for

### Social Texture Category (from observation analysis)
- `social_texture` — expression patterns, emoji usage, reaction tendencies, communication style

Social texture insights track *how* people communicate, not just *what* they say. These are generated during observation analysis and may attach to user, server, or emoji topics.

---

_Last updated: 2026-02-13 — Reconciled with code: added reset transaction type, marked derived scope and appreciation as deferred, updated pool enum (presence→reaction)_
