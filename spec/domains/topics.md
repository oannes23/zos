# Topics — Domain Specification

**Status**: 🟡 In progress
**Last interrogated**: —
**Last verified**: —
**Depends on**: None (primitive)
**Depended on by**: Salience, Insights, Layers

---

## Overview

Topics are the canonical entities that Zos can think about. They provide the stable keys that allow understanding to accumulate coherently — without them, insights would scatter across inconsistent references.

The topic key system is a taxonomy: a structured way of naming entities that supports both human readability and programmatic parsing.

---

## Core Concepts

### Topic Key Taxonomy

Every topic has a key — a string with parseable structure:

| Pattern | Example | Meaning |
|---------|---------|---------|
| `user:<id>` | `user:123456` | An individual person |
| `channel:<id>` | `channel:789012` | A Discord channel |
| `user_in_channel:<channel>:<user>` | `user_in_channel:789012:123456` | A person's presence/behavior in a specific channel |
| `dyad:<user_a>:<user_b>` | `dyad:123456:234567` | A relationship between two people |
| `dyad_in_channel:<channel>:<user_a>:<user_b>` | `dyad_in_channel:789012:123456:234567` | A relationship in a specific context |

### ID Ordering for Dyads

Dyad keys sort user IDs to ensure consistency:
- `dyad:alice:bob` and `dyad:bob:alice` must resolve to the same key
- Sort numerically (if Discord snowflake IDs) or lexicographically (if using other ID schemes)

### Topic Categories

Topics fall into categories that determine:
- How salience is budgeted for them
- Which reflection layers target them
- How they're queried in the introspection API

Categories:
- **users**: Individual people
- **channels**: Spaces
- **user_in_channel**: Person-space combinations
- **dyads**: Relationships
- **dyad_in_channel**: Relationships in context

---

## Decisions

### String Keys with Structure

- **Decision**: Topic keys are strings with parseable structure (colon-delimited), not opaque IDs
- **Rationale**: Human-readable for debugging; programmatically parseable for filtering; no separate mapping table needed
- **Implications**: Key format is a contract — changes require migration
- **Source**: zos-seed.md §2 "Topics as the Unit of Understanding"

### One Insight Per Topic

- **Decision**: Every insight attaches to exactly one topic key
- **Rationale**: Simplifies retrieval ("everything about Alice"), prevents orphaned insights, forces clarity about what an insight is *about*
- **Implications**: Cross-topic insights need different modeling (see Open Questions)
- **Source**: zos-seed.md §2

### Category-Filterable Queries

- **Decision**: Queries can filter by topic category
- **Rationale**: "Give me all user insights" or "all relationship insights" should be efficient
- **Implications**: Category should be derivable from key prefix; may want secondary index
- **Source**: zos-seed.md §2

---

## Open Questions

1. **Additional topic types**: Do we need `thread:<id>`, `role:<id>`, `topic_cluster:<name>`?
2. **Cross-topic insights**: Some insights span multiple topics (e.g., "Alice and Bob argue about X in #general"). How to model?
3. **Multi-server topics**: When users appear in multiple servers, is it `user:<id>` globally or `server:<id>:user:<user_id>`?
4. **Topic lifecycle**: When a user leaves or a channel is deleted, what happens to their topics and insights?
5. **Topic aliases**: Can multiple keys resolve to the same topic (e.g., if a user changes their Discord ID)?

---

## Key Format Specification

```
topic_key := category ":" id
           | category ":" id ":" id
           | category ":" id ":" id ":" id

category := "user" | "channel" | "user_in_channel" | "dyad" | "dyad_in_channel"

id := discord_snowflake | [future: other id schemes]

discord_snowflake := [0-9]+
```

### Parsing Rules

1. Split on `:` to get components
2. First component is always category
3. Remaining components are IDs
4. For dyads, IDs are sorted ascending before key construction

### Examples

```python
# Constructing keys
user_key("123456")                    # "user:123456"
channel_key("789012")                 # "channel:789012"
user_in_channel_key("789012", "123456")  # "user_in_channel:789012:123456"
dyad_key("234567", "123456")          # "dyad:123456:234567" (sorted!)
dyad_in_channel_key("789012", "234567", "123456")  # "dyad_in_channel:789012:123456:234567"

# Parsing keys
parse_topic_key("dyad:123456:234567")  # TopicKey(category="dyad", ids=["123456", "234567"])
```

---

## Implications for Other Specs

| Spec | Implication |
|------|-------------|
| [salience.md](salience.md) | Salience attaches to topic keys; need topic creation on first activity |
| [insights.md](insights.md) | Insights reference topic keys; queries filter by key or category |
| [privacy.md](privacy.md) | Some topic categories may have default scope restrictions |
| [data-model.md](../architecture/data-model.md) | Topics table with key as primary key; category index |

---

_Last updated: 2026-01-22_
