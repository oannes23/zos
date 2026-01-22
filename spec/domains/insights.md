# Insights — Domain Specification

**Status**: 🟡 In progress
**Last interrogated**: —
**Last verified**: —
**Depends on**: Topics, Privacy (scope)
**Depended on by**: Layers (produce and consume insights)

---

## Overview

Insights are the persistent understanding that Zos accumulates. They're not just data — they're the *residue of processing* that shapes future cognition.

Each insight is attached to exactly one topic, has a privacy scope, and can be retrieved to inform future reflection or conversation.

---

## Core Concepts

### Insight as Integrated Memory

Insights differ from raw message storage:
- **Messages**: What was said (raw input)
- **Insights**: What it *means* (processed understanding)

Insights are the output of reflection — the system's interpretation of patterns, relationships, and meaning in the raw data.

### Topic Attachment

Every insight attaches to exactly one topic key. This ensures:
- Coherent accumulation: "everything about Alice" is a simple query
- No orphans: insights always have context
- Clear ownership: when querying, you know what you're getting

### Scope Inheritance

Insights track the privacy scope of their sources:
- An insight derived from public messages is `public`
- An insight derived from DM content is `dm`
- An insight derived from mixed sources is `derived` and inherits the most restrictive scope

### Lifecycle

Insights can have:
- **TTL (time-to-live)**: Expire after N days (for short-term observations)
- **No expiry**: Persist indefinitely (for durable understanding)
- **Supersession**: Newer insights can explicitly supersede older ones

---

## Decisions

### One Topic Per Insight

- **Decision**: Every insight attaches to exactly one topic key
- **Rationale**: Simplifies retrieval and prevents insight sprawl; if an insight is about multiple topics, it should be split or the topic model extended
- **Implications**: Need clear guidelines for what topic an insight belongs to; cross-topic observations need different modeling
- **Source**: zos-seed.md §2

### Scope Tracking

- **Decision**: Every insight tracks `sources_scope_max` — the maximum (most restrictive) scope of any source that informed it
- **Rationale**: Privacy is structural; an insight tainted by DM content must never surface in public output, even if the insight itself seems innocuous
- **Implications**: Scope flows through the entire pipeline; context assembly must filter by scope
- **Source**: zos-seed.md §4

### Category Taxonomy

- **Decision**: Insights have categories that reflect what layer produced them and their semantic type
- **Rationale**: Enables filtered retrieval ("get user_reflection insights but not user_summary insights")
- **Implications**: Categories should be defined in layer config; extensible but controlled

---

## Open Questions

1. **Cross-topic insights**: Some observations span multiple topics. Model as insight-with-references? Duplicate to each topic? New topic type?
2. **Insight versioning**: When the system's understanding of Alice changes, do we update the old insight or create a new one? History vs current truth?
3. **Confidence levels**: Should insights have confidence/certainty scores? How would these be used?
4. **Insight conflict**: If two insights about the same topic contradict, how is this resolved?
5. **Insight retrieval ranking**: When fetching insights for context, how to rank them? Recency? Relevance? Both?

---

## Insight Schema

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Unique identifier (UUID or ULID) |
| `topic_key` | string | yes | What this insight is about |
| `category` | string | yes | What type of insight (e.g., `user_reflection`) |
| `content` | string | yes | The actual understanding |
| `sources_scope_max` | enum | yes | `public`, `dm`, or `derived` |
| `created_at` | timestamp | yes | When generated |
| `expires_at` | timestamp | no | When to auto-delete (null = never) |
| `layer_run_id` | string | yes | Which layer run produced this |
| `supersedes` | string | no | ID of insight this replaces |
| `metadata` | json | no | Extensible metadata (confidence, tags, etc.) |

---

## Example Insights

### User Reflection

```json
{
  "id": "insight_abc123",
  "topic_key": "user:123456",
  "category": "user_reflection",
  "content": "Alice tends to be most active in #general during evening hours. Her recent messages show enthusiasm about the upcoming project launch, though she expressed some concern about timeline pressures in a conversation with Bob.",
  "sources_scope_max": "public",
  "created_at": "2026-01-22T03:15:00Z",
  "expires_at": "2026-02-05T03:15:00Z",
  "layer_run_id": "run_xyz789"
}
```

### Relationship Observation

```json
{
  "id": "insight_def456",
  "topic_key": "dyad:123456:234567",
  "category": "dyad_reflection",
  "content": "Alice and Bob have developed a collaborative dynamic. They frequently build on each other's ideas and seem to share a technical communication style. Recent tension around project scope appears to be professional disagreement, not personal friction.",
  "sources_scope_max": "public",
  "created_at": "2026-01-22T03:20:00Z",
  "expires_at": null,
  "layer_run_id": "run_xyz789"
}
```

---

## Retrieval Patterns

### By Topic

```python
# Get all insights about a user
insights = fetch_insights(topic_key="user:123456")

# Get recent insights about a user
insights = fetch_insights(topic_key="user:123456", max_age_days=7)
```

### By Category

```python
# Get all user reflections
insights = fetch_insights(category="user_reflection")

# Get user reflections for a specific user
insights = fetch_insights(topic_key="user:123456", categories=["user_reflection"])
```

### By Scope (for context assembly)

```python
# Get only public insights for public channel response
insights = fetch_insights(topic_key="user:123456", max_scope="public")

# Get all insights including DM-derived for DM response
insights = fetch_insights(topic_key="user:123456", max_scope="dm")
```

---

## Implications for Other Specs

| Spec | Implication |
|------|-------------|
| [topics.md](topics.md) | Topic keys are the foreign key for insights |
| [layers.md](layers.md) | Layers produce insights via `store_insight` node |
| [privacy.md](privacy.md) | Scope field connects to privacy system |
| [data-model.md](../architecture/data-model.md) | Need insights table with indexes on topic_key, category, created_at |

---

_Last updated: 2026-01-22_
