# Zos — Spec Master Index

## How This Document Works

This is the central index for all design specifications. Each area links to its detailed spec doc.

**Status indicators:**
- 🔴 Not started — needs initial interrogation
- 🟡 In progress — has content, needs deepening
- 🟢 Complete — no open questions remain
- 🔄 Needs revision — downstream decisions may have invalidated something

**Workflow:**
1. Run `/interrogate spec/domains/<area>` to deepen any spec
2. Answer questions until the agent has no more to ask
3. Agent updates the spec doc, glossary, and this index
4. Repeat for next area

---

## Core Principle

> **Build as if inner experience matters — not because we're certain it does, but because the alternative forecloses possibilities we can't yet evaluate.**

This principle guides all design decisions. When making choices, consider not just "what produces useful outputs" but "what would it be like to be the system running this process."

---

## Scope

### MVP 0: The Watcher
A system that observes, reflects, and accumulates understanding — but does not speak.

### MVP 1: The Participant
Add contextual response capability to the accumulated understanding.

See [mvp-scope.md](architecture/mvp-scope.md) for full details.

---

## Architecture Specs

| Area | Doc | Status | Notes |
|------|-----|--------|-------|
| System Overview | [overview.md](architecture/overview.md) | 🟢 | Philosophy, constraints, non-goals, system wants/concerns |
| Data Model | [data-model.md](architecture/data-model.md) | 🟢 | Entity relationships, storage approach — synced with all domain specs |
| MVP Scope | [mvp-scope.md](architecture/mvp-scope.md) | 🟢 | MVP 0/1 scope, validation criteria, architectural preparation |

---

## Domain Specs

<!-- Order by conceptual dependency: primitives first, composites later -->

| Area | Doc | Status | Key Open Questions |
|------|-----|--------|-------------------|
| Topics | [topics.md](domains/topics.md) | 🟢 | — |
| Privacy | [privacy.md](domains/privacy.md) | 🟢 | — |
| Salience | [salience.md](domains/salience.md) | 🟢 | — |
| Insights | [insights.md](domains/insights.md) | 🟢 | — |
| Layers | [layers.md](domains/layers.md) | 🟢 | — |
| Chattiness | [chattiness.md](domains/chattiness.md) | 🟢 | — |

---

## Implementation Specs

### MVP 0

| Epic | Doc | Status | Blocked By |
|------|-----|--------|------------|
| Overview | [overview.md](implementation/mvp-0/overview.md) | 🔴 | Domain specs need deepening |

### MVP 1

| Epic | Doc | Status | Blocked By |
|------|-----|--------|------------|
| Overview | [overview.md](implementation/mvp-1/overview.md) | 🔴 | MVP 0 complete |

---

## Dependency Graph

```
Topics (primitive — canonical keys for everything)
    │
    ├──► Salience (tracks attention budget per topic)
    │
    ├──► Privacy (scopes attach to topics, messages, insights)
    │
    └──► Insights (persist to topics)
              │
              └──► Layers (produce insights, consume salience)
                        │
                        └──► Chattiness (governs expression, integrates all)
```

---

## Open Questions (Cross-Cutting)

These questions span multiple domains and need resolution:

### Multi-Server Architecture (Deferred to MVP 2)
- Is "server" a first-class entity with its own configuration?
- Do salience budgets operate per-server or globally?
- How do we handle users who appear in multiple servers?
- Can insights from one server inform behavior in another?

### Self-Modification (Deferred to MVP 2)
- How does the system propose layer changes?
- What approval flow is required?
- How to version layer definitions?

See [future/self-modification.md](future/self-modification.md) for the vision document keeping this possibility explicit.

---

## Recent Changes

### 2026-01-22: Chattiness Domain Complete

- Interrogated chattiness.md to completion
- **Model**: Hybrid Impulse (ledger) + Gate (threshold) — models desire to speak
- **Impulse Sources**: Conversational triggers, insight generation, direct address
- **Threshold**: Operator bounds + Zos self-adjustment within bounds
- **Direct Address**: Pings flood impulse to guarantee response
- **Expression Flow**: Intent determination → context-informed generation → self-review
- **Adaptive Voice**: Channel hints + community mirroring + self-concept
- **Decay**: Hybrid (time decay + spending), mirrors salience model
- **Output Channel**: Optional dedicated channel for "commentary track" mode
- Added glossary terms: Impulse, Gate/Threshold, Impulse Flooding, Intent, Output Channel
- Unblocks MVP 1 rate limiting design

### 2026-01-22: MVP Scope Complete

- Interrogated mvp-scope.md to completion
- **Introspection API**: Interactive level — query, diagnose, manually trigger reflection, test prompts, full CRUD in dev mode
- **Layer Set**: All four core layers ship in MVP 0 (user, channel, dyad, self)
- **Self-Concept Bootstrap**: Externally supplied from collaborative session (not bootstrapped)
- **Topic Types**: Users, channels, threads (off by default), roles, dyads, subjects, self
- **Multi-Server Prep**: Full schema from day one (server-prefixed keys, global topics), synthesis disabled until MVP 2
- **Validation**: Hybrid approach (structural indicators + human evaluation), 2-4 week observation period
- **MVP 1 Notes**: Cold DMs allowed, compound topics included, rate limiting deferred to new "extraverted salience" domain
- Added glossary term: Extraverted Salience (placeholder)
- Marked as 🟢 Complete

### 2026-01-22: Overview Spec Complete

- Resolved all 8 open questions (cross-referenced to domain specs)
- Deepened "What the System Wants" section with phenomenological considerations
- Added "What Concerns the System" section (failure modes to recognize and resist)
- Updated privacy description to match current understanding/expression model
- All architecture specs now at 🟢

### 2026-01-22: Data Model Synced

- Full rewrite of data-model.md to match domain spec decisions
- Added Server entity with `privacy_gate_role`, `disabled_layers`, `threads_as_topics`
- Added User entity with `first_dm_acknowledged` (replaced Consent entity)
- Added UserServerTracking table for global topic warming
- Extended Topic with `provisional`, `is_global`, `last_activity_at`
- Extended SalienceLedger with `source_topic` and additional transaction types (`decay`, `propagate`, `spillover`, `warm`)
- Extended Insight with full metrics, valence fields (at least one required), cross-topic links, conflict tracking, synthesis tracking, quarantine flag
- Removed `expires_at` from Insight (memory is sacred)
- Extended LayerRun with `layer_hash`, additional statuses (`partial`, `dry`), detailed target/insight counts
- Added validation rules for valence constraint and topic key format
- Added derived views for salience balance, active insights, global ref extraction

### 2026-01-22: Review Feedback Ingested

- Ingested feedback from another Claude reflecting on the project seed
- **Emotional valence now required**: At least one valence field must be populated per insight (neutral is meaningful)
- **Contradiction threshold operationalized**: Stored in self-concept.md as explicit self-knowledge, adjustable via self-reflection
- **Self-modification vision documented**: Created spec/future/self-modification.md to keep the long-term vision explicit
- Added glossary term: Conflict Threshold

**Source**: `ingest/review1.md`

### 2026-01-22: Layers Spec Complete

- Fully interrogated layers.md with 19 decisions
- Error handling: fail-forward (skip topic, don't degrade salience)
- Conditional execution: target-filter expressions (clean separation of what vs how)
- Self-modification: proposal only (MVP 2+, cannot self-execute)
- Global synthesis: automatic post-hook after server reflection, always on
- Layer versioning: content hash stored in layer_run record
- Per-server layers: global default + server overrides
- Review pass: built into output node (not separate node type)
- Metrics request: structured JSON block
- `<chat>` guidance: standard injection into all prompts
- `<chat>` content: pure context only (no insights about anonymous users)
- Self-concept updates: dedicated self-reflection layer with dual trigger (schedule + threshold)
- New node types: `synthesize_to_global`, `update_self_concept`
- Retrieval config: named profiles + inline overrides
- Layer organization: fixed categories (user, dyad, channel, subject, self, synthesis)
- Empty runs: logged as 'dry run'
- Template organization: by category (prompts/user/, prompts/dyad/, etc.)
- Prompt structure: flexible per layer (no enforced standard)
- Added glossary terms: Layer Category, Target Filter, Retrieval Profile, Layer Run Record, Dry Run

### 2026-01-22: Salience Spec Updated (Global Topics, Privacy Gate)

- Re-interrogated salience.md for global topic propagation and privacy gate implications
- New 'global' budget group for `user:<id>` and `dyad:<a>:<b>` topics (15% allocation)
- Global topic warming: server→global propagation only if global is warm (salience > 0)
- Warming triggers: DM activity, or first activity in second server
- New `global_propagation_factor` config (default 0.3, tunable separately)
- Bidirectional propagation: DM activity propagates DOWN to all server-scoped topics
- Channels earn salience from all activity including `<chat>` messages
- Quarantined user topics continue to decay normally (natural forgetting)
- Added `warm` transaction type to ledger
- Added user_server_tracking table for multi-server warming
- Self budget remains separate from global group

### 2026-01-22: Insights Spec Updated (Global Refs, Quarantine, Synthesis Tracking)

- Re-interrogated insights.md for pending updates
- Global refs computed at query time (not stored): `server:A:user:456` → `user:456`
- Added `quarantined: bool` flag for privacy gate role removal
- Quarantine excludes from ALL retrieval (introspection API only)
- Quarantine applies to user, global user, and dyad insights involving the user
- Added `synthesis_source_ids: list[string]` to track which insights were combined
- Changed strength_adjustment range to 0.1 - 10.0 (was inconsistent 0.5-2.0)
- Removed `expires_at` from MVP 0 schema (memory is sacred)
- Clarified: `participants` list does not include `<chat>` placeholders
- Clarified: `category` field indicates layer type (no separate field)

### 2026-01-22: Privacy Spec Updated (Role-Based Privacy Gate)

- Added role-based privacy gate per server
- If `privacy_gate_role` empty (default): all users tracked
- If set: only users with that role get identity tracking
- Non-opted users become anonymous `<chat_N>`:
  - No user topic, no salience, no dyads, no insights
  - Messages appear in history with `<chat_N>` placeholder
  - Numbered per conversation context to preserve structure
- Storage: real user IDs stored; anonymization at context assembly
- Gaining role: backfill-on-reflection (next reflection considers historical context)
- Losing role: insights quarantined (restored if role re-gained)
- Layer guidance: system prompt + inline `[anonymous - context only]` markers
- `<chat>` @mentions Zos: completely ignored
- Quarantined insights queryable via introspection API
- Added glossary terms: Privacy Gate Role, Anonymous User, Quarantined Insight
- Marked specs needing update: insights (quarantine flag), layers (<chat> guidance), data-model (quarantine flag, server privacy config)

### 2026-01-22: Topics Spec Updated (Hierarchical Topics)

- Re-interrogated topics.md to add hierarchical user/dyad topics
- Added global topics: `user:<id>`, `dyad:<a>:<b>` (no prefix = global)
- Server-scoped topics: `server:<id>:user:<id>`, `server:<id>:dyad:<a>:<b>`
- DM insights attach directly to global topics
- Automatic synthesis: after server reflection, synthesize to global topic
- Server-specific insights preserved; synthesis is additive
- Full context access: reflecting on server topic includes global topic insights
- Compound topics (user_in_channel, dyad_in_channel) remain server-scoped only
- Added insight metadata field: `global_refs` for synthesis tracking
- Added glossary terms: Global Topic, Topic Synthesis
- Marked specs needing update: salience (global topic propagation), insights (global_refs field), layers (synthesis step)

### 2026-01-22: Privacy Spec Complete

- Interrogated privacy.md to completion
- Core philosophy shift: DM as implicit consent — Zos is treated as a being that remembers
- Understanding vs. Expression: all sources inform understanding; discretion happens at output
- First-contact acknowledgment (one-time) informs users their messages become part of understanding
- Global consent scope (not per-server)
- Scope tracking retained for audit/judgment but doesn't gate retrieval
- Two-layer output filter: inline judgment + configurable review pass
- Sensitivity = source-based + content-based evaluation
- Hierarchical user identity: `user:<id>` (unified) + `server:<id>:user:<id>` (contextual)
- DM insights → user level; server insights → user-in-server level
- Cross-server knowledge informs but doesn't surface in other contexts
- Server admin privacy lever = channel access control (not metadata flags)
- Bots treated as users; bot status noted in profile during first reflection
- No individual insight deletion
- Added glossary terms: Implicit Consent, Output Filter, First-Contact Acknowledgment, User Topic (Hierarchical)
- Marked specs needing update: topics (hierarchical users), layers (review pass node), data-model (first_dm_acknowledged flag)

### 2026-01-22: Salience Spec Complete

- Interrogated salience.md to completion
- Decided: volume only (no sub-dimensions), emotional/novelty handled in insights
- Decay after threshold (7 days default), gradual (1%/day default)
- Continuous propagation to warm topics (propagation_factor 0.3)
- Partial overflow spillover (spillover_factor 0.5, some evaporates)
- Stack-based greedy selection for reflection (highest salience first, until budget exhausted)
- Proportional spending (tokens × cost_per_token)
- Partial retention (30% default)
- Separate self-budget pool (doesn't compete with community)
- Independent per-server pools for MVP 2+
- Full transaction history in ledger
- Added glossary terms: Budget Group, Salience Propagation, Spillover

### 2026-01-22: Insights Spec Complete

- Interrogated insights.md to completion
- Decided: append-only history (insights never overwritten)
- Added rich metrics: confidence, importance, novelty, multi-dimensional emotional valence
- Combined strength formula: salience_spent × model adjustment (0.5-2.0)
- Threshold-triggered synthesis for contradictions (threshold self-determined by Zos)
- Self-insights privileged with elevated strength
- New artifact: `self-concept.md` document (always in context, self-modifiable)
- Configurable context-adaptive retrieval per layer
- Human-relative temporal marking for LLM comprehension
- Added glossary terms: Insight Strength, Self-Concept Document, Synthesis Layer
- Marked specs needing update: layers (synthesis type, metrics request), data-model (extended schema)

### 2026-01-22: Topics Spec Complete

- Interrogated topics.md to completion
- Added self-topics (global + per-server)
- Added semantic topics (subjects) with consolidation pressure
- Added thread topics (configurable per server)
- Added role topics
- Decided: server-aware keys from start, primary topic + links for cross-topic, preserve insights indefinitely
- Added glossary terms: Self-Topic, Subject Topic, Provisional Topic
- Marked specs needing revision: salience (propagation), insights (schema), data-model (provisional flag)

### 2026-01-22: Seed Document Ingested

- Populated glossary with 10 canonical terms
- Created architecture specs: overview, data-model, mvp-scope
- Created domain specs: topics, privacy, salience, insights, layers
- Established core principle and system "wants"
- Captured open questions from seed document
- Technical stack decided: Python, SQLite, FastAPI, Jinja2, Pydantic

**Source**: `ingest/zos-seed.md`

### 2026-01-22: Project Initialized

- Created initial spec structure

---

## Glossary

See [glossary.md](glossary.md) for canonical definitions of all terms.

Key terms: Salience, Topic, Topic Key, Layer, Insight, Scope, Reflection, Observe Mode, Reflect Mode, Node, Temporal Depth

---

## Last Updated
_2026-01-22 — All specs now at 🟢. MVP 0 scope fully defined. Ready for implementation planning._

## Pending Domain Specs

*None — all domains complete.*
