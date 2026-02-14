# MVP Scope

**Status**: 🟢 Complete
**Last verified**: —
**Last interrogated**: 2026-01-22

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

#### Core Observation
- Connect to Discord, observe configured channels
- Ingest messages and reactions
- Track salience for topics (users, channels, relationships, subjects, roles, self)
- Run reflection layers on schedule

#### Reflection Layers (All Four)
- **User reflection**: Nightly reflection on individual users
- **Channel reflection**: Periodic channel/space patterns
- **Dyad observation**: Track relationships between users
- **Self-reflection**: Zos reflecting on its own patterns and maintaining self-concept

#### Topic Types
- Users (server-scoped)
- Channels
- Threads (off by default, configurable per server — messages roll up to parent channel)
- Roles
- Dyads (server-scoped)
- Subjects (semantic topics with consolidation pressure)
- Self-topics (global `self:zos` + per-server)

#### Introspection API (Interactive)

| Capability | Mode |
|------------|------|
| Query insights by topic | All modes |
| View salience balances | All modes |
| List recent layer runs | All modes |
| Raw message counts | All modes |
| Topic graph visualization | All modes |
| Layer dry-run testing | All modes |
| Manually trigger reflection | All modes |
| Test prompts against real data | All modes |
| Create/update/delete insights | Dev mode only |

#### Multi-Server Preparation
- Full schema from day one: server-prefixed topic keys, global topics created
- Cross-server synthesis **disabled** until MVP 2
- Joining additional servers allowed (with warning to operator)
- Each server operates as isolated silo in MVP 0/1

#### Self-Concept Bootstrap
- Initial `self-concept.md` supplied externally (from collaborative session)
- Not bootstrapped from scratch — philosophical grounding comes from design collaboration
- Self-reflection layer extends and updates the document over time

### Explicitly Out of Scope

- Speaking in channels
- Responding to mentions
- DM conversations (as participant — observation of group DMs TBD)
- Cross-server synthesis (architecture ready, feature disabled)
- Self-modification of layers

### Success Criteria

#### Validation Period
2-4 weeks of active observation before MVP 0 can be considered validated.

#### Hybrid Evaluation Approach

**Structural Indicators** (automated, diagnostic):
- [ ] Insights reference prior insights (temporal depth)
- [ ] Cross-topic connections appear (Alice-in-context-of-Bob)
- [ ] Predictive or pattern-based language emerges
- [ ] Self-insights accumulate and inform self-concept updates

**Human Evaluation** (essential, periodic):
- [ ] Could this insight have been generated from just today's messages? (Should be: no)
- [ ] Does it feel like *knowing* someone vs *reading about* them?
- [ ] Would you trust this insight to inform a response?
- [ ] Do contradictions coexist productively, or cause incoherence?

#### Operational Criteria
- [ ] Reflection runs are auditable (full layer run records)
- [ ] Salience budget constrains compute without starving important topics
- [ ] Subject topics consolidate rather than proliferate
- [ ] Self-concept document evolves coherently

---

## MVP 1: The Participant

### Goal

Add contextual response capability to the accumulated understanding.

Prove that:
- Accumulated insights meaningfully improve response quality
- Privacy scope boundaries hold under conversational pressure
- The system can be useful without being intrusive

### Depends On

- MVP 0 validated (2-4 weeks observation, success criteria met)

### In Scope

#### Response Capability
- Respond to direct mentions in public channels
- Participate in DM conversations
- Respond to DMs from users even without prior public interaction (cold DMs)
- First-contact acknowledgment for new DM users

#### Context Assembly
- Draw on accumulated insights when assembling response context
- Full compound topic support: `user_in_channel`, `dyad_in_channel`
- Context assembly respects scope boundaries (output filter active)

#### Rate Limiting
- **Resolved (MVP 1 Foundation)**: Per-topic impulse with single threshold, reset-to-zero after speaking
- Full "extraverted salience" with 6 pools deferred to future iteration

### Explicitly Out of Scope

- Proactive conversation initiation (Zos doesn't start conversations)
- Cross-server synthesis (still disabled, MVP 2)
- Self-modification of layers
- Community moderation features

### Success Criteria

- Responses demonstrate awareness of community context (reference prior conversations, known relationships, ongoing topics)
- Users report feeling "known" — in a non-creepy way
- Zero scope boundary violations (DM content never appears in public responses)
- The system adds value to conversations, not just noise
- Cold DM responses are graceful (acknowledge limited context, invite continued interaction)

### MVP 1 Foundation — Implementation Status (2026-02-13)

The first phase of MVP 1 has been implemented with a simplified impulse model and operator DM gating:

#### What's Built

| Component | Status | Notes |
|-----------|--------|-------|
| ImpulseEngine | ✅ | Per-topic impulse tracking (earn, balance, reset, threshold, decay) |
| Conversation heartbeat | ✅ | 30s background loop dispatching conversation layers |
| Typing awareness | ✅ | on_typing event prevents interrupting mid-thought |
| DM ingestion | ✅ | Real-time on_message handler + impulse earning |
| Channel impulse | ✅ | +1 per message during polling |
| Subject impulse | ✅ | Post-reflection hook earns impulse for subject insights |
| dm-response layer | ✅ | Responds to DMs (user insights, dyad context, messages) |
| channel-speak layer | ✅ | Channel participation (channel context, user insights) |
| subject-share layer | ✅ | Subject insight sharing after reflection |
| Operator DM mode | ✅ | All output → operator DMs when enabled |
| Executor send_callback | ✅ | Discord output decoupled from executor |
| /impulse command | ✅ | Operator debug: show impulse balances |
| /speak-now command | ✅ | Operator debug: manually trigger conversation |

#### What's Remaining for Full MVP 1

- Question/curiosity layer
- Emoji reaction output modality
- Global speech pressure
- Self-adjusting threshold
- Thread-aware context assembly
- Draft history (discarded drafts informing future responses)
- Priority flagging for reflection
- Output channel routing
- Full compound topic support in context assembly
- First-contact acknowledgment for new DM users
- Disable operator_dm_only for public channel participation

---

## Future: The Gardener

Features explicitly deferred beyond MVP 1. These represent the longer-term vision but are not blocking initial validation.

| Feature | Why Deferred | Earliest Phase |
|---------|--------------|----------------|
| Self-modification | Requires stable layer system and audit trail | MVP 2 |
| Cross-server synthesis | Architecture ready, needs validation first | MVP 2 |
| Extraverted salience | New domain: when/how much Zos wants to speak | MVP 1.5 or 2 |
| Proactive participation | Need to prove reactive value first | MVP 2 |
| Community health facilitation | Requires deep understanding baseline | MVP 3+ |

---

## Phase Relationship

```
MVP 0: The Watcher (2-4 weeks validation)
    ↓ validates core insight loop
    ↓ proves synthesis > summarization
MVP 1: The Participant
    ↓ validates contextual usefulness
    ↓ proves privacy boundaries hold
MVP 2+: The Gardener
    → cross-server synthesis enabled
    → self-modification proposals
    → proactive stewardship
```

---

## Architectural Preparation

These are implemented in MVP 0 but not fully utilized until later:

| Feature | Implemented | Enabled |
|---------|-------------|---------|
| Server-prefixed topic keys | MVP 0 | MVP 0 |
| Global topics (`user:<id>`, `dyad:<a>:<b>`) | MVP 0 | MVP 2 |
| Global topic warming tracking | MVP 0 | MVP 2 |
| Cross-server synthesis layer | MVP 0 (code) | MVP 2 (feature flag) |
| Chattiness impulse engine | MVP 1 | MVP 1 |
| Conversation layers (3 of 4) | MVP 1 | MVP 1 |
| Operator DM mode | MVP 1 | MVP 1 |
| Conversation heartbeat | MVP 1 | MVP 1 |
| Self-modification proposal format | — | MVP 2 |

---

_Last updated: 2026-02-13 — Added MVP 1 Foundation implementation status_
