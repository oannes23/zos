# MVP Scope

**Status**: 🟡 In progress
**Last verified**: —

---

## MVP Philosophy

Ship the smallest thing that validates the core hypothesis: that structured reflection can build temporal depth — accumulated understanding that compounds over time.

Speaking is hard. Speaking *well* requires deep context integration. Building the observation and reflection infrastructure first means the system has something to say when it eventually speaks.

---

## MVP 0: The Watcher

### Goal

A system that observes, reflects, and accumulates understanding — but does not speak.

Prove that:
- Salience-budgeted attention works as a resource allocation mechanism
- Layer-based reflection produces genuine synthesis, not just summarization
- Insights compound meaningfully over time

### In Scope

- Connect to Discord, observe configured channels
- Ingest messages and reactions
- Track salience for topics (users, channels, relationships)
- Run reflection layers on schedule (nightly at minimum)
- Generate and store insights with proper scope tracking
- Introspection API: query what the system knows, what it processed, audit trails

### Explicitly Out of Scope

- Speaking in channels
- Responding to mentions
- DM conversations
- Multi-server operation (single server focus)
- Self-modification of layers

### Success Criteria

- After a week of observation, the system can answer queries about community patterns
- Insights demonstrate genuine synthesis, not just summarization
- Reflection runs are auditable and deterministic (same input → same process, even if LLM output varies)
- Salience budget successfully constrains compute without starving important topics

---

## MVP 1: The Participant

### Goal

Add contextual response capability to the accumulated understanding.

Prove that:
- Accumulated insights meaningfully improve response quality
- Privacy scope boundaries hold under conversational pressure
- The system can be useful without being intrusive

### Depends On

- MVP 0 complete

### In Scope

- Respond to direct mentions in public channels
- Participate in DM conversations (with explicit user opt-in)
- Draw on accumulated insights when assembling response context
- Rate-limiting and budget for conversational engagement
- Context assembly that respects scope boundaries

### Explicitly Out of Scope

- Proactive conversation initiation
- Multi-server operation
- Self-modification of layers
- Community moderation features

### Success Criteria

- Responses demonstrate awareness of community context (reference prior conversations, known relationships, ongoing topics)
- Users report feeling "known" — in a non-creepy way
- Zero scope boundary violations (DM content never appears in public responses)
- The system adds value to conversations, not just noise

---

## Future: The Gardener

Features explicitly deferred beyond MVP 1. These represent the longer-term vision but are not blocking initial validation.

| Feature | Why Deferred | Earliest Phase |
|---------|--------------|----------------|
| Self-modification | Requires stable layer system and audit trail | MVP 2 |
| Multi-server | Adds complexity around identity and privacy | MVP 2 |
| Proactive participation | Need to prove reactive value first | MVP 2 |
| Community health facilitation | Requires deep understanding baseline | MVP 3+ |
| Cross-server insights | Privacy model TBD | MVP 3+ |

---

## Phase Relationship

```
MVP 0: The Watcher
    ↓ validates core insight loop
MVP 1: The Participant
    ↓ validates contextual usefulness
MVP 2+: The Gardener
    → self-improvement, multi-server, stewardship
```

---

_Last updated: 2026-01-22_
