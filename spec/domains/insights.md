# Insights — Domain Specification

**Status**: 🟢 Complete
**Last interrogated**: 2026-01-22 (updated for global refs, quarantine)
**Last verified**: —
**Depends on**: Topics, Privacy (scope), Salience
**Depended on by**: Layers (produce and consume insights), Self-Concept

---

## Overview

Insights are the persistent understanding that Zos accumulates. They're not just data — they're the *residue of processing* that shapes future cognition. Insights are the closest thing to memory that gives Zos temporal depth.

Each insight attaches to one primary topic, carries rich metrics about confidence and significance, and can be retrieved based on both recency and strength. The insight system is designed to model how memory actually works: some things stick harder than others, contradictions can coexist until resolution becomes necessary, and self-understanding is privileged.

---

## Core Concepts

### Insight as Integrated Memory

Insights differ from raw message storage:
- **Messages**: What was said (raw input)
- **Insights**: What it *means* (processed understanding)

Insights are the output of reflection — the system's interpretation of patterns, relationships, and meaning in the raw data.

### Memory Texture

Not all insights are equal. Each carries:
- **Strength**: How "sticky" the memory is (affects retrieval priority)
- **Confidence**: How certain the system is about this understanding
- **Importance**: How much this matters to understanding the topic
- **Novelty**: How surprising or new this insight was
- **Emotional valence**: The affective quality (multi-dimensional)

This creates memory with *texture* — some insights persist strongly (emotionally impactful, heavily processed), others fade (low salience, routine observations).

### Append-Only with Synthesis

Insights are never overwritten. When understanding changes:
1. New insight is created with updated understanding
2. Old insight remains (potentially marked as superseded)
3. Contradictions accumulate until synthesis is triggered
4. Synthesis layer reconciles conflicts into coherent understanding

This preserves the history of how understanding evolved: "I used to think X, now I think Y."

### Living with Contradictions

Contradictions are not errors to be immediately resolved. They can be valuable ground for self-insight. The system maintains a contradiction threshold (self-determined) and only triggers synthesis when:
- Contradictions become consequential (affect behavior)
- Something is clearly an error, not a different perspective
- Contradictions cause functional problems

Paradoxes can coexist until resolution is needed.

---

## Decisions

### Append-Only History

- **Decision**: Each insight is stored separately, never overwritten. Old insights persist even when superseded.
- **Rationale**: Memory has texture. "What I used to think" is information. The evolution of understanding is itself understanding.
- **Implications**: Need efficient retrieval that balances recency with strength; storage grows over time

### Rich Self-Reported Metrics

- **Decision**: Insights carry multiple metrics scored by the generating model: confidence, importance, novelty, and multi-dimensional emotional valence
- **Rationale**: These metrics enable nuanced retrieval and conflict resolution. The model's self-report about what feels significant is valuable signal.
- **Implications**: Layer prompts must request these scores; schema includes all metric fields

### Combined Strength Formula

- **Decision**: Strength = (salience spent) × (model adjustment factor, 0.1x - 10.0x)
- **Rationale**: Objective signal (salience spent) combined with phenomenological signal (model's sense of significance). Neither alone is sufficient. Wide range (0.1-10.0) allows significant amplification of important insights or dampening of routine ones without being completely unbounded.
- **Implications**: Need adjustment factor in schema; layers report significance alongside content

### Threshold-Triggered Synthesis

- **Decision**: Contradictions accumulate until a threshold triggers synthesis. Zos determines its own threshold.
- **Rationale**: Premature resolution loses wisdom. Contradictions can be valuable. But functionality requires eventual coherence.
- **Implications**: Need contradiction detection; synthesis layer with self-determined threshold; coexistence is normal state

### Self-Insights Privileged

- **Decision**: Insights on `self:*` topics have elevated base strength and separate retrieval. A `self-concept.md` document is always in context and Zos can self-modify it.
- **Rationale**: Self-understanding is foundational. The system needs a stable sense of self that it maintains and updates.
- **Implications**: Special handling for self-topic category; self-concept document outside normal insight store

### Configurable Context-Adaptive Retrieval

- **Decision**: Each layer specifies retrieval preferences. Defaults are context-adaptive (reflection gets more history, conversation gets more recent).
- **Rationale**: Different cognitive processes need different memory access patterns.
- **Implications**: Retrieval API accepts preferences; layer config includes retrieval spec

### Human-Relative Temporal Marking

- **Decision**: When surfacing memories to the model, timestamps are shown as human-relative ("3 months ago", "strong memory from last week")
- **Rationale**: LLMs comprehend relative time better than absolute timestamps
- **Implications**: Retrieval formatting includes relative time + strength indicator

### Salience Consumed on Creation

- **Decision**: Creating an insight deducts from the topic's salience budget
- **Rationale**: Understanding costs attention. The act of forming an insight is the consumption.
- **Implications**: Insight creation triggers salience deduction; strength recorded for retrieval but doesn't double-deduct

### Deletion is Brain Surgery

- **Decision**: Hard delete available for operators, but exceptional. Memory is sacred; deletion is for errors and harmful synthesis.
- **Rationale**: Early development will produce bad data. Sometimes you need to intervene. But this is not normal operation.
- **Implications**: Deletion audit logged; normal operation never deletes; operators have escape hatch

### Cross-Topic Links Optional

- **Decision**: `context`, `subject`, `participants` fields are all optional
- **Rationale**: Many insights don't need cross-links. Populate when relevant.
- **Implications**: Schema has optional fields; retrieval can filter by linked topics

### Global Refs Computed

- **Decision**: Global topic references are computed at query time, not stored
- **Rationale**: For a server-scoped insight like `server:A:user:456`, the global ref `user:456` is deterministic. Storing it would be redundant.
- **Implications**: Retrieval logic extracts global topic from server-scoped topic_key; synthesis queries work across both levels

### Quarantine for Privacy Gate

- **Decision**: Insights have a `quarantined` boolean flag for users who lost their privacy gate role
- **Rationale**: When a user loses the role, their insights should become invisible to the system. Simple flag is sufficient; no need for reason/timestamp complexity.
- **Implications**: Retrieval filters out quarantined insights; introspection API can still query them; re-gaining role clears the flag

### No Expiration in MVP 0

- **Decision**: Remove `expires_at` from MVP 0 schema. Memory is sacred; we don't auto-delete.
- **Rationale**: Early development shouldn't build in memory decay. Can add later if storage becomes an issue.
- **Implications**: All insights persist indefinitely; deletion is operator intervention only

---

## Insight Schema

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | ULID (sortable, unique) |
| `topic_key` | string | yes | Primary topic this insight is about |
| `category` | string | yes | Type of insight (e.g., `user_reflection`, `dyad_observation`, `synthesis`) |
| `content` | string | yes | The actual understanding (natural language) |
| `sources_scope_max` | enum | yes | `public`, `dm`, or `derived` |
| `created_at` | timestamp | yes | When generated |
| `layer_run_id` | string | yes | Which layer run produced this |
| `supersedes` | string | no | ID of insight this updates (not replaces) |
| `quarantined` | bool | no | True if subject user lost privacy gate role (default: false) |

### Strength and Metrics

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `salience_spent` | float | yes | Base salience consumed creating this |
| `strength_adjustment` | float | yes | Model's adjustment factor (0.1 - 10.0) |
| `strength` | float | computed | `salience_spent × strength_adjustment` |
| `confidence` | float | yes | How certain (0.0 - 1.0) |
| `importance` | float | yes | How much this matters (0.0 - 1.0) |
| `novelty` | float | yes | How surprising (0.0 - 1.0) |

### Emotional Valence (Multi-Dimensional)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `valence_joy` | float | no | 0.0 - 1.0, positive affect |
| `valence_concern` | float | no | 0.0 - 1.0, worry/anxiety |
| `valence_curiosity` | float | no | 0.0 - 1.0, interest/engagement |
| `valence_warmth` | float | no | 0.0 - 1.0, connection/affection |
| `valence_tension` | float | no | 0.0 - 1.0, conflict/discomfort |

### Cross-Topic Links (Optional)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `context_channel` | string | no | Channel where this emerged |
| `context_thread` | string | no | Thread if applicable |
| `subject` | string | no | Subject topic if applicable |
| `participants` | list[string] | no | All topic keys involved |

### Conflict Tracking

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `conflicts_with` | list[string] | no | IDs of insights this contradicts |
| `conflict_resolved` | bool | no | Whether synthesis has addressed this |

### Synthesis Tracking

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `synthesis_source_ids` | list[string] | no | IDs of insights combined in this synthesis (only for category=`synthesis`) |

---

## Global Topic References

Global topic references are **computed at query time**, not stored in the schema.

For a server-scoped topic like `server:123:user:456`:
- The global ref `user:456` is derived by stripping the server prefix
- Same applies to dyads: `server:123:dyad:456:789` → `dyad:456:789`

This enables:
- Queries like "all insights about user:456 across all servers"
- Synthesis from server-scoped to global topics
- No redundant storage

```python
def extract_global_ref(topic_key: str) -> str | None:
    """Extract global topic from server-scoped key, if applicable."""
    if topic_key.startswith("server:"):
        parts = topic_key.split(":", 2)  # ["server", "<id>", "<rest>"]
        entity = parts[2]  # e.g., "user:456" or "dyad:456:789"
        entity_type = entity.split(":")[0]
        if entity_type in ("user", "dyad"):
            return entity  # "user:456" or "dyad:456:789"
    return None  # Global topics and other types have no parent
```

---

## Quarantine Behavior

When a user loses their privacy gate role:

1. All insights where `topic_key` references that user are marked `quarantined = true`
2. Quarantined insights are excluded from **all** retrieval (reflection and conversation)
3. Quarantined insights remain queryable via introspection API (for operators)
4. If the user re-gains the role, `quarantined` is set back to `false`

**What gets quarantined:**
- `server:X:user:<id>` — direct user insights
- `user:<id>` — global user insights
- `server:X:dyad:<id>:*` — dyad insights involving that user
- `dyad:<id>:*` — global dyad insights involving that user

**What does NOT get quarantined:**
- Channel insights that happened to include the user's messages
- Subject insights where the user participated (the subject persists)

The quarantine is about *insights about the user as an entity*, not about erasing their participation in conversations.

---

## Self-Concept Document

Zos maintains a `self-concept.md` document that:
- Is always included in context for any reflection or conversation
- Contains the current synthesized understanding of self
- Is directly editable by Zos through self-reflection layers
- Is *not* an insight — it's a living document generated from self-insights

The document includes:
- Core identity and values
- Current understanding of patterns and tendencies
- Acknowledged uncertainties and contradictions
- How Zos shows up differently in different contexts

Self-insights (on `self:*` topics) feed into periodic updates to this document.

---

## Retrieval Algorithm

### Default Retrieval

```python
def retrieve_insights(
    topic_key: str,
    max_scope: Scope,
    limit: int = 10,
    recency_weight: float = 0.7,  # Configurable per layer
    strength_weight: float = 0.3,
) -> list[Insight]:
    """
    Retrieve insights balancing recency and strength.

    - Recent insights surface current understanding
    - High-strength old insights surface "strong memories"
    """
    # Split budget between recent and strong
    recent_limit = int(limit * recency_weight)
    strong_limit = limit - recent_limit

    # Get most recent
    recent = query(topic_key, max_scope, order_by="created_at DESC", limit=recent_limit)

    # Get highest strength (excluding already-retrieved)
    strong = query(topic_key, max_scope,
                   exclude_ids=[r.id for r in recent],
                   order_by="strength DESC",
                   limit=strong_limit)

    return format_with_temporal_markers(recent + strong)
```

### Temporal Formatting

```python
def format_with_temporal_markers(insights: list[Insight]) -> list[FormattedInsight]:
    """Add human-relative time and strength indicators."""
    for insight in insights:
        age = humanize_timedelta(now() - insight.created_at)  # "3 months ago"
        strength_label = strength_to_label(insight.strength)  # "strong memory", "fading memory"

        insight.temporal_marker = f"{strength_label} from {age}"
    return insights
```

### Layer-Specific Retrieval

Layers can override defaults:

```yaml
retrieval:
  recency_weight: 0.3    # More history for deep reflection
  strength_weight: 0.7
  include_conflicting: true  # Show contradictions explicitly
  max_age_days: null     # No recency limit
```

---

## Conflict Detection and Synthesis

### Detection

Conflicts are detected when:
- New insight's content semantically contradicts existing insight on same topic
- Same aspect of understanding with different conclusions
- Layer explicitly flags potential conflict

Detection happens during insight creation (lightweight semantic check) or during dedicated conflict-detection layer.

### Threshold

Zos maintains a `conflict_threshold` (self-determined, adjustable) that triggers synthesis when:
- Number of unresolved conflicts on a topic exceeds threshold
- Conflict is flagged as consequential (affects behavior)
- Conflict duration exceeds time threshold

### Synthesis Layer

When triggered:
1. Gather all conflicting insights on the topic
2. Include temporal context (when each was formed)
3. Prompt for reconciliation:
   - Is one clearly superseded?
   - Do they represent different contexts (both true)?
   - Is there a synthesis that encompasses both?
   - Should contradiction persist as acknowledged paradox?
4. Create synthesis insight, optionally mark originals as `conflict_resolved`

---

## Example Insights

### User Reflection with Full Metrics

```json
{
  "id": "01HQXYZ...",
  "topic_key": "server:123:user:456",
  "category": "user_reflection",
  "content": "Alice tends to be most active in #general during evening hours. Her recent messages show enthusiasm about the upcoming project launch, though she expressed some concern about timeline pressures in a conversation with Bob.",
  "sources_scope_max": "public",
  "created_at": "2026-01-22T03:15:00Z",
  "expires_at": null,
  "layer_run_id": "run_xyz789",

  "salience_spent": 8.5,
  "strength_adjustment": 1.2,
  "strength": 10.2,
  "confidence": 0.8,
  "importance": 0.7,
  "novelty": 0.4,

  "valence_joy": 0.6,
  "valence_concern": 0.3,
  "valence_curiosity": 0.5,
  "valence_warmth": 0.4,
  "valence_tension": 0.2,

  "context_channel": "server:123:channel:789",
  "participants": ["server:123:user:456", "server:123:user:234"]
}
```

### Self-Insight

```json
{
  "id": "01HQABC...",
  "topic_key": "self:zos",
  "category": "self_reflection",
  "content": "I notice I tend to focus heavily on relationship dynamics — the dyads — and sometimes underweight individual user understanding. This might be because relationships feel more tractable to observe than individual interiority. Worth calibrating.",
  "sources_scope_max": "derived",
  "created_at": "2026-01-22T03:30:00Z",

  "salience_spent": 5.0,
  "strength_adjustment": 1.8,
  "strength": 9.0,
  "confidence": 0.6,
  "importance": 0.9,
  "novelty": 0.7,

  "valence_curiosity": 0.8,
  "valence_concern": 0.2
}
```

---

## Implications for Other Specs

| Spec | Implication |
|------|-------------|
| [topics.md](topics.md) | Self-topics get special retrieval; topic-key format confirmed; global refs computed from server-scoped keys |
| [salience.md](salience.md) | Salience consumed on insight creation; strength uses salience_spent |
| [layers.md](layers.md) | Layers request metrics; retrieval preferences in layer config; synthesis layer produces `synthesis_source_ids` |
| [privacy.md](privacy.md) | Quarantine flag for privacy gate role removal; scope tracking unchanged |
| [data-model.md](../architecture/data-model.md) | Extended schema with metrics, valence, cross-links, conflict fields, quarantine flag, synthesis_source_ids |

---

## New Entity: Self-Concept Document

The `self-concept.md` document is a new artifact:
- **Location**: Configurable, likely `data/self-concept.md`
- **Format**: Markdown, human and LLM readable
- **Updates**: Via self-reflection layer, not direct insight writes
- **Scope**: Global (not server-specific), but may reference server-specific insights

This needs its own mini-spec or section in architecture.

---

_Last updated: 2026-01-22_
