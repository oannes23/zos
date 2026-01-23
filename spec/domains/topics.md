# Topics — Domain Specification

**Status**: 🟢 Complete
**Last interrogated**: 2026-01-22
**Last verified**: —
**Depends on**: None (primitive)
**Depended on by**: Salience, Insights, Layers, Privacy

---

## Overview

Topics are the canonical entities that Zos can think about. They provide the stable keys that allow understanding to accumulate coherently — without them, insights would scatter across inconsistent references.

The topic key system is a taxonomy: a structured way of naming entities that supports both human readability and programmatic parsing. Topics define Zos's ontology of attention — what it *can* think about shapes what it *does* think about.

---

## Core Concepts

### Topic Key Taxonomy

Every topic has a key — a string with parseable structure. Keys are server-aware from the start to support multi-server operation in MVP 2+.

#### Social Topics

| Pattern | Example | Meaning |
|---------|---------|---------|
| `server:<id>:user:<id>` | `server:123:user:456` | A person in a server |
| `server:<id>:channel:<id>` | `server:123:channel:789` | A Discord channel |
| `server:<id>:thread:<id>` | `server:123:thread:012` | A Discord thread (configurable per server) |
| `server:<id>:role:<id>` | `server:123:role:345` | A Discord role |
| `server:<id>:user_in_channel:<channel>:<user>` | `server:123:user_in_channel:789:456` | A person's presence in a specific channel |
| `server:<id>:dyad:<user_a>:<user_b>` | `server:123:dyad:456:678` | A relationship (IDs sorted) |
| `server:<id>:dyad_in_channel:<channel>:<user_a>:<user_b>` | `server:123:dyad_in_channel:789:456:678` | A relationship in context |

#### Semantic Topics

| Pattern | Example | Meaning |
|---------|---------|---------|
| `server:<id>:subject:<name>` | `server:123:subject:api_redesign` | An emergent theme or subject of discussion |

#### Self Topics

| Pattern | Example | Meaning |
|---------|---------|---------|
| `self:zos` | `self:zos` | Global self-understanding (core identity) |
| `server:<id>:self:zos` | `server:123:self:zos` | Contextual self-understanding in a community |
| `self:<aspect>` | `self:social_patterns` | (Future) Emergent self-topics as complexity warrants |

### ID Conventions

- **Storage**: Discord snowflake IDs used in keys for precision and stability
- **Display**: When insights are shown to LLMs or humans, IDs are replaced with human-readable names (usernames, channel names, etc.)
- **Dyad ordering**: User IDs sorted numerically ascending before key construction

### Topic Categories

Topics fall into categories for budgeting, targeting, and querying:

- **users**: Individual people (`server:*:user:*`)
- **channels**: Spaces (`server:*:channel:*`)
- **threads**: Nested conversations (`server:*:thread:*`) — configurable per server
- **roles**: Discord roles (`server:*:role:*`)
- **user_in_channel**: Person-space combinations
- **dyads**: Relationships
- **dyad_in_channel**: Relationships in context
- **subjects**: Semantic topics (`server:*:subject:*`)
- **self**: Self-understanding (`self:*` and `server:*:self:*`)

---

## Decisions

### Server-Aware Keys from Start

- **Decision**: All topic keys include server context, even in MVP 0 (single server)
- **Rationale**: Avoids migration pain when multi-server support arrives in MVP 2. Format is ready.
- **Implications**: Keys are longer, but consistent; server extraction is trivial

### Explicit Self-Topic

- **Decision**: Zos has an explicit `self:zos` topic for self-understanding, plus per-server `server:<id>:self:zos` for contextual self-awareness
- **Rationale**: Self-reflection is a first-class cognitive activity. The system should be able to accumulate understanding about its own patterns, nature, and development.
- **Implications**: Layers can target self-reflection; introspection queries are natural
- **Extension**: If self-understanding becomes too complex for a single topic, Zos is explicitly permitted to create additional self-topics (e.g., `self:social_patterns`, `self:creative_voice`)

### Semantic Topics with Consolidation Pressure

- **Decision**: `subject:<name>` topics track emergent themes, but with strong consolidation mechanisms
- **Rationale**: Semantic understanding is valuable, but topic proliferation is a failure mode (analogous to Discord channel sprawl). Less is more.
- **Implications**: Need consolidation/merge process for subjects; layers should be conservative about creating new subjects; prefer enriching existing subjects over spawning new ones

### Threads Configurable Per Server

- **Decision**: Thread-level topics (`thread:<id>`) are configurable per server
- **Rationale**: Large servers benefit from thread-level understanding; small servers can roll up to channel level
- **Implications**: Server configuration includes `threads_as_topics: bool`; when false, thread messages inherit parent channel

### Roles as Topics

- **Decision**: Discord roles are trackable as `role:<server>:<id>` topics
- **Rationale**: Enables insights like "moderators in this server tend to..." Roles shape how people show up.
- **Implications**: Note that role-gated channels create overlap between role and channel topics; this is an insight opportunity, not a problem
- **Note**: User reflection should consider role context; role-user relationship is many-to-many

### Primary Topic + Links for Cross-Topic Insights

- **Decision**: Insights attach to one primary topic but carry structured metadata linking to related topics
- **Rationale**: Avoids the scattering that composite topics would create while preserving queryability
- **Implications**: Insight schema includes `context`, `subject`, `participants` fields; layers query by participation

### Insight Metadata Structure

For cross-topic linking, insights carry:
```yaml
primary_topic: "server:123:dyad:456:678"  # What this insight is fundamentally about
context:
  channel: "server:123:channel:789"       # Where it happened
  thread: "server:123:thread:012"         # If applicable
subject: "server:123:subject:api_debate"  # What it concerned (optional)
participants:                             # All entities involved
  - "server:123:user:456"
  - "server:123:user:678"
```

### Preserve Insights Indefinitely

- **Decision**: When users leave or channels are deleted, accumulated insights persist
- **Rationale**: Understanding should have continuity. If someone returns, the relationship can resume with context. Deletion is a policy choice, not automatic.
- **Implications**: May need archival/cleanup tools for operator choice; no automatic pruning

### Auto-Create with Provisional Flag

- **Decision**: When an insight references a topic that doesn't exist, create it with `provisional: true`
- **Rationale**: Topics should be cheap to create (enables organic growth) but provisionals need review
- **Implications**: Consolidation process reviews provisionals, promotes or merges them

### Subject Names are LLM-Generated

- **Decision**: Semantic topic names are generated by reflection layers, not predefined
- **Rationale**: Subjects emerge from what the community actually discusses; cannot be anticipated
- **Implications**: Names are descriptive strings; naming quality depends on layer prompts

---

## Key Format Specification

```
topic_key := self_topic | server_topic

self_topic := "self:" identifier

server_topic := "server:" server_id ":" entity_topic

entity_topic := simple_entity | compound_entity

simple_entity := entity_type ":" id
entity_type := "user" | "channel" | "thread" | "role" | "subject" | "self"

compound_entity := "user_in_channel:" id ":" id
                 | "dyad:" id ":" id
                 | "dyad_in_channel:" id ":" id ":" id

server_id := discord_snowflake
id := discord_snowflake | identifier
identifier := [a-z_][a-z0-9_]*
discord_snowflake := [0-9]+
```

### Parsing Rules

1. Check for `self:` prefix (global self-topic)
2. Otherwise, expect `server:<id>:` prefix
3. Parse entity type from next component
4. For dyads, sort user IDs ascending before key construction
5. For `user_in_channel` and `dyad_in_channel`, channel ID comes before user IDs

### Key Construction Examples

```python
# Global self
self_key()                                    # "self:zos"
self_key("social_patterns")                   # "self:social_patterns"

# Server-scoped entities
user_key(server, user)                        # "server:123:user:456"
channel_key(server, channel)                  # "server:123:channel:789"
thread_key(server, thread)                    # "server:123:thread:012"
role_key(server, role)                        # "server:123:role:345"
subject_key(server, "api_debate")             # "server:123:subject:api_debate"
server_self_key(server)                       # "server:123:self:zos"

# Compound entities
user_in_channel_key(server, channel, user)    # "server:123:user_in_channel:789:456"
dyad_key(server, user_a, user_b)              # "server:123:dyad:456:678" (sorted!)
dyad_in_channel_key(server, channel, a, b)    # "server:123:dyad_in_channel:789:456:678"
```

---

## Topic Lifecycle

### Creation

Topics are created:
- **On first activity**: When a user sends their first message, `server:X:user:Y` is created
- **On first insight**: When reflection produces an insight about something, create the topic if needed
- **Provisionally**: Auto-created topics marked `provisional: true` for consolidation review

### Persistence

- Topics persist indefinitely by default
- No automatic pruning when users leave or channels are deleted
- Archival/deletion is an operator policy choice

### Consolidation (for subjects)

Subject topics require consolidation to prevent proliferation:
- Periodic review of provisional subjects
- Merge similar subjects (keep richer one, alias the other)
- Promote confirmed subjects (remove provisional flag)
- Consider: subject activity threshold before promotion

---

## Configuration

### Per-Server Settings

```yaml
servers:
  "123456789":  # Discord server ID
    name: "friends"  # Human-readable alias for display
    threads_as_topics: true  # Whether threads get their own topics
    subject_consolidation:
      review_interval_days: 7
      min_insights_to_promote: 3
```

---

## Salience Propagation Note

When activity occurs on compound topics (dyads, user_in_channel), salience should propagate to component topics:
- Dyad activity → both users gain salience
- user_in_channel activity → user and channel gain salience

This is specified in detail in [salience.md](salience.md).

---

## Implications for Other Specs

| Spec | Implication |
|------|-------------|
| [salience.md](salience.md) | Salience propagation from compound to component topics; per-category budgets include new types |
| [insights.md](insights.md) | Insight schema needs `context`, `subject`, `participants` fields; provisional flag for auto-created topics |
| [privacy.md](privacy.md) | Self-topics have special scope considerations; subject topics inherit scope from constituent messages |
| [layers.md](layers.md) | Layers can target self-reflection; subject emergence happens in layers; consolidation as a layer type |
| [data-model.md](../architecture/data-model.md) | Topic table needs `provisional` flag, `category` index, server-aware key format |

---

_Last updated: 2026-01-22_
