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

Every topic has a key — a string with parseable structure. Keys follow a two-tier model:

- **Global topics**: No prefix (e.g., `user:123`, `dyad:456:789`, `self:zos`)
- **Server-scoped topics**: `server:<id>:` prefix (e.g., `server:A:user:123`)

This mirrors how understanding works: some knowledge is universal to a person or relationship, while other knowledge is contextual to a specific community.

### Hierarchical Topics

Users and dyads exist at two levels:

```
user:<id>                    # Global unified understanding
├── server:A:user:<id>       # Contextual understanding in Server A
├── server:B:user:<id>       # Contextual understanding in Server B
└── (DM insights attach here directly)

dyad:<a>:<b>                 # Global relationship understanding
├── server:A:dyad:<a>:<b>    # Contextual relationship in Server A
└── server:B:dyad:<a>:<b>    # Contextual relationship in Server B
```

**Key principle**: Understanding is unified; expression is contextual. When responding in Server A, Zos has full access to global insights but only *reveals* server-A-specific knowledge.

---

## Topic Types

### Global Topics

| Pattern | Example | Meaning |
|---------|---------|---------|
| `user:<id>` | `user:456` | Unified understanding of a person across all contexts |
| `dyad:<user_a>:<user_b>` | `dyad:456:678` | Unified relationship understanding (IDs sorted) |
| `self:zos` | `self:zos` | Core identity and self-understanding |
| `self:<aspect>` | `self:social_patterns` | Emergent self-topics as complexity warrants |

### Server-Scoped Topics

#### Social Topics

| Pattern | Example | Meaning |
|---------|---------|---------|
| `server:<id>:user:<id>` | `server:123:user:456` | A person in a specific server |
| `server:<id>:channel:<id>` | `server:123:channel:789` | A Discord channel |
| `server:<id>:thread:<id>` | `server:123:thread:012` | A Discord thread (configurable per server) |
| `server:<id>:role:<id>` | `server:123:role:345` | A Discord role |
| `server:<id>:user_in_channel:<channel>:<user>` | `server:123:user_in_channel:789:456` | A person's presence in a specific channel |
| `server:<id>:dyad:<user_a>:<user_b>` | `server:123:dyad:456:678` | A relationship in a specific server (IDs sorted) |
| `server:<id>:dyad_in_channel:<channel>:<user_a>:<user_b>` | `server:123:dyad_in_channel:789:456:678` | A relationship in a specific channel |

#### Semantic Topics

| Pattern | Example | Meaning |
|---------|---------|---------|
| `server:<id>:subject:<name>` | `server:123:subject:api_redesign` | An emergent theme or subject of discussion |

#### Emoji Topics

| Pattern | Example | Meaning |
|---------|---------|---------|
| `server:<id>:emoji:<emoji_id>` | `server:123:emoji:984521357` | A custom emoji's cultural meaning and usage |

Emoji topics track custom emoji culture: usage patterns, who uses the emoji, common contexts, and emergent semantic meaning. Created on first use. Part of tri-level emoji culture modeling. See [observation.md](observation.md) for details.

#### Contextual Self Topics

| Pattern | Example | Meaning |
|---------|---------|---------|
| `server:<id>:self:zos` | `server:123:self:zos` | Contextual self-understanding in a community |

### Compound Topics (Server-Scoped Only)

Compound topics like `user_in_channel` and `dyad_in_channel` are inherently contextual — channels are server-specific, so these topics cannot have global equivalents.

---

## Insight Attachment Rules

| Insight Source | Attaches To | Notes |
|----------------|-------------|-------|
| DM with user | `user:<id>` | DMs are cross-server; attach to global |
| Public message in Server A | `server:A:user:<id>` | Contextual to server |
| DM between two users | `dyad:<a>:<b>` | If Zos observes (e.g., group DM with Zos) |
| Public interaction between users | `server:A:dyad:<a>:<b>` | Contextual to server |

### Synthesis to Global

After reflecting on a user or dyad in any server, a synthesis step updates the corresponding global topic:

1. Retrieve new insights from `server:X:user:<id>` since last synthesis
2. Include existing `user:<id>` insights as context
3. Generate meta-understanding that integrates the new contextual insights
4. Store new insight(s) to `user:<id>`

**Important**: Server-specific insights are preserved. Global synthesis adds meta-understanding without modifying or archiving sources. Both levels coexist with full granularity.

---

## Context Access Model

When reflecting on a server-scoped topic, Zos has **full access** to the corresponding global topic as context:

- Reflecting on `server:A:user:X` → include insights from `user:X`
- Reflecting on `server:A:dyad:X:Y` → include insights from `dyad:X:Y`

This enables unified understanding while maintaining contextual expression. The privacy output filter (see [privacy.md](privacy.md)) ensures that cross-server knowledge informs but doesn't inappropriately surface.

---

## Decisions

### Hierarchical User and Dyad Topics

- **Decision**: Users and dyads exist at both global and server-scoped levels
- **Rationale**: Enables unified understanding while respecting contextual differences. A person may show up differently in different communities, but is still the same person.
- **Implications**: Need synthesis mechanism; insight attachment rules based on source type

### No Prefix = Global

- **Decision**: Global topics have no prefix (`user:123`); server-scoped topics have `server:<id>:` prefix
- **Rationale**: Simpler key format; mirrors existing `self:zos` vs `server:A:self:zos` pattern
- **Implications**: Parsing must check for `server:` prefix first; absence means global

### DM Insights Direct to Global

- **Decision**: DM-derived insights attach directly to `user:<id>` (or `dyad:<a>:<b>` for multi-party)
- **Rationale**: DMs are inherently cross-server context. No intermediate topic needed.
- **Implications**: DM reflection doesn't create server-scoped insights

### Continuous Synthesis

- **Decision**: Synthesis to global happens as part of regular reflection, not a separate scheduled job
- **Rationale**: Keeps understanding current; integrates naturally with reflection flow
- **Implications**: User reflection layers need synthesis step; adds compute per reflection

### Source Insights Preserved

- **Decision**: Server-specific insights remain after synthesis; global insights are additive
- **Rationale**: Preserves granularity and queryability; avoids data loss
- **Implications**: Storage grows (both levels persist); retrieval can target either level

### Compounds Remain Server-Scoped

- **Decision**: `user_in_channel` and `dyad_in_channel` have no global equivalents
- **Rationale**: These topics inherently involve channels, which are server-specific
- **Implications**: No need for compound synthesis logic

### Server-Aware Keys from Start

- **Decision**: All server-scoped topic keys include server context, even in MVP 0 (single server)
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

- **Decision**: Discord roles are trackable as `server:<id>:role:<id>` topics
- **Rationale**: Enables insights like "moderators in this server tend to..." Roles shape how people show up.
- **Implications**: Note that role-gated channels create overlap between role and channel topics; this is an insight opportunity, not a problem
- **Note**: User reflection should consider role context; role-user relationship is many-to-many

### Primary Topic + Links for Cross-Topic Insights

- **Decision**: Insights attach to one primary topic but carry structured metadata linking to related topics
- **Rationale**: Avoids the scattering that composite topics would create while preserving queryability
- **Implications**: Insight schema includes `context`, `subject`, `participants` fields; layers query by participation

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
topic_key := global_topic | server_topic

global_topic := user_global | dyad_global | self_global
user_global := "user:" discord_snowflake
dyad_global := "dyad:" discord_snowflake ":" discord_snowflake  # sorted
self_global := "self:" identifier

server_topic := "server:" server_id ":" entity_topic

entity_topic := simple_entity | compound_entity | self_entity

simple_entity := entity_type ":" id
entity_type := "user" | "channel" | "thread" | "role" | "subject"

compound_entity := "user_in_channel:" id ":" id
                 | "dyad:" id ":" id
                 | "dyad_in_channel:" id ":" id ":" id

self_entity := "self:" identifier

server_id := discord_snowflake
id := discord_snowflake | identifier
identifier := [a-z_][a-z0-9_]*
discord_snowflake := [0-9]+
```

### Parsing Rules

1. Check for known global prefixes: `user:`, `dyad:`, `self:`
2. If starts with `server:`, parse as server-scoped
3. For dyads, user IDs are sorted ascending before key construction
4. For `user_in_channel` and `dyad_in_channel`, channel ID comes before user IDs

### Key Construction Examples

```python
# Global topics
user_key(user)                                # "user:456"
dyad_key(user_a, user_b)                      # "dyad:456:678" (sorted!)
self_key()                                    # "self:zos"
self_key("social_patterns")                   # "self:social_patterns"

# Server-scoped topics
server_user_key(server, user)                 # "server:123:user:456"
server_dyad_key(server, user_a, user_b)       # "server:123:dyad:456:678" (sorted!)
channel_key(server, channel)                  # "server:123:channel:789"
thread_key(server, thread)                    # "server:123:thread:012"
role_key(server, role)                        # "server:123:role:345"
subject_key(server, "api_debate")             # "server:123:subject:api_debate"
server_self_key(server)                       # "server:123:self:zos"

# Compound entities (server-scoped only)
user_in_channel_key(server, channel, user)    # "server:123:user_in_channel:789:456"
dyad_in_channel_key(server, channel, a, b)    # "server:123:dyad_in_channel:789:456:678"
```

---

## ID Conventions

- **Storage**: Discord snowflake IDs used in keys for precision and stability
- **Display**: When insights are shown to LLMs or humans, IDs are replaced with human-readable names (usernames, channel names, etc.)
- **Dyad ordering**: User IDs sorted numerically ascending before key construction

---

## Topic Categories

Topics fall into categories for budgeting, targeting, and querying:

- **users**: Individual people (`user:*` and `server:*:user:*`)
- **dyads**: Relationships (`dyad:*` and `server:*:dyad:*`)
- **channels**: Spaces (`server:*:channel:*`)
- **threads**: Nested conversations (`server:*:thread:*`) — configurable per server
- **roles**: Discord roles (`server:*:role:*`)
- **user_in_channel**: Person-space combinations (server-scoped only)
- **dyad_in_channel**: Relationships in context (server-scoped only)
- **subjects**: Semantic topics (`server:*:subject:*`)
- **emojis**: Custom emoji culture (`server:*:emoji:*`)
- **self**: Self-understanding (`self:*` and `server:*:self:*`)

---

## Insight Metadata Structure

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
global_refs:                              # Links to global topics (for synthesis)
  - "user:456"
  - "user:678"
  - "dyad:456:678"
```

---

## Topic Lifecycle

### Creation

Topics are created:
- **On first activity**: When a user sends their first message, relevant topics are created
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

When activity occurs on compound or server-scoped topics, salience should propagate:

- Server user activity → global user gains salience
- Dyad activity → both users (global and server-scoped) gain salience
- user_in_channel activity → user and channel gain salience

This is specified in detail in [salience.md](salience.md).

---

## Implications for Other Specs

| Spec | Implication |
|------|-------------|
| [observation.md](observation.md) | Observation creates emoji topics; respects topic key format |
| [salience.md](salience.md) | Salience propagation to global topics; budget groups include global user/dyad; emoji topics need budget group |
| [insights.md](insights.md) | Insight schema needs `global_refs` field for synthesis tracking |
| [privacy.md](privacy.md) | Global topics inform but don't surface cross-server; output filter handles |
| [layers.md](layers.md) | User/dyad reflection needs synthesis step to global; DM reflection attaches to global directly |
| [data-model.md](../architecture/data-model.md) | Topic table needs global vs server-scoped distinction; synthesis tracking; emoji topic type |

---

_Last updated: 2026-01-23 — Added emoji topic type_
