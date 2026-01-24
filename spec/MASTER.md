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
| Data Model | [data-model.md](architecture/data-model.md) | 🟢 | Entity relationships, storage approach — synced with observation and chattiness |
| MVP Scope | [mvp-scope.md](architecture/mvp-scope.md) | 🟢 | MVP 0/1 scope, validation criteria, architectural preparation |

---

## Domain Specs

<!-- Order by conceptual dependency: primitives first, composites later -->

| Area | Doc | Status | Key Open Questions |
|------|-----|--------|-------------------|
| Observation | [observation.md](domains/observation.md) | 🟢 | — |
| Topics | [topics.md](domains/topics.md) | 🟢 | — |
| Privacy | [privacy.md](domains/privacy.md) | 🟢 | — |
| Salience | [salience.md](domains/salience.md) | 🟢 | — |
| Insights | [insights.md](domains/insights.md) | 🟢 | — |
| Layers | [layers.md](domains/layers.md) | 🟢 | — |
| Chattiness | [chattiness.md](domains/chattiness.md) | 🟢 | — |
| Self-Modification | [self-modification.md](domains/self-modification.md) | 🟢 | Proposal format only; execution deferred to MVP 2+ |

---

## Implementation Specs

### MVP 0

| Epic | Doc | Status | Blocked By |
|------|-----|--------|------------|
| Overview | [overview.md](implementation/mvp-0/overview.md) | 🟢 | — |
| Epic 1: Foundation | stories/1-*.md | 🟡 | — (5 stories ready) |
| Epic 2: Observation | stories/2-*.md | 🟡 | Epic 1 (5 stories ready) |
| Epic 3: Salience | stories/3-*.md | 🟡 | Epic 1 (5 stories ready) |
| Epic 4: Reflection | stories/4-*.md | 🟡 | Epics 1-3 (8 stories ready) |
| Epic 5: Introspection | stories/5-*.md | 🟡 | Epic 1 (9 stories ready) |

### MVP 1

| Epic | Doc | Status | Blocked By |
|------|-----|--------|------------|
| Overview | [overview.md](implementation/mvp-1/overview.md) | 🔴 | MVP 0 complete |

---

## Dependency Graph

```
Observation (raw input — capture and enrichment)
    │
    └──► Topics (primitive — canonical keys for everything)
              │
              ├──► Salience (tracks attention budget per topic)
              │
              ├──► Privacy (scopes attach to topics, messages, insights)
              │
              └──► Insights (persist to topics)
                        │
                        └──► Layers (produce insights, consume salience, consume observed data)
                                  │
                                  ├──► Chattiness (governs expression, integrates all)
                                  │
                                  └──► Self-Modification (proposes changes to layers; MVP 2+ execution)
```

---

## Open Questions (Cross-Cutting)

These questions span multiple domains and need resolution:

### Multi-Server Architecture (Deferred to MVP 2)
- Is "server" a first-class entity with its own configuration?
- Do salience budgets operate per-server or globally?
- How do we handle users who appear in multiple servers?
- Can insights from one server inform behavior in another?

### Self-Modification Execution (Deferred to MVP 2)

**Proposal format is now specified** in [self-modification.md](domains/self-modification.md). The following execution questions remain deferred:

- What approval automation is appropriate? (When can proposals auto-approve?)
- How do we sandbox/test proposals before committing?
- What rollback mechanisms are needed?
- Can Zos modify its own self-reflection layer? (Recursive modification)
- What safety boundaries should be non-modifiable?

See [future/self-modification.md](future/self-modification.md) for the vision document covering these open questions.

---

## Recent Changes

### 2026-01-23: All MVP 0 Stories Documented

- Created all 32 story files across 5 epics
- **Epic 1 (Foundation)**: 5 stories — project scaffold, config, DB schema, migrations, Pydantic models
- **Epic 2 (Observation)**: 5 stories — Discord connection, message polling, reactions, media analysis, link analysis
- **Epic 3 (Salience)**: 5 stories — ledger operations, topic earning, propagation, decay, budget groups
- **Epic 4 (Reflection)**: 8 stories — layer YAML, prompt templates, executor, LLM client, insight storage, scheduler, user reflection, self-reflection
- **Epic 5 (Introspection)**: 9 stories — FastAPI scaffold, insights API, salience API, layer runs API, UI base, insights browser, salience dashboard, layer run monitor, dev CRUD
- All stories include acceptance criteria, technical notes, code examples, test cases
- Ready to begin code implementation

### 2026-01-23: MVP 0 Implementation Overview

- Interrogated implementation planning for MVP 0: "The Watcher"
- **Code layout**: Flat modules (`src/zos/{models,layers,observation,api,config}.py`)
- **Epic decomposition**: Foundation → Observation → Salience → Reflection → Introspection
- **Database**: SQLAlchemy Core + Pydantic (explicit SQL, no ORM magic)
- **Discord**: discord.py with background polling task
- **LLM**: Thin wrapper with provider adapters, model profiles (simple/moderate/complex)
- **Web UI**: htmx + Jinja2 (insights browser, salience dashboard, layer run monitor)
- **Scheduler**: APScheduler in-process
- **Testing**: Integration-heavy with seed script fixtures
- **Config**: YAML + env vars
- **Workflow**: Trunk-based development with feature flags
- 5 epics, 32 stories total
- Story documentation phase complete

### 2026-01-23: Cross-Cutting Concerns Addressed

- **First-contact message rewritten**: Privacy spec updated with Zos-voiced acknowledgment reflecting epistemic honesty
- **Error reflection added**: Layers spec now includes decision that all operational errors feed self-reflection
- **Conflict threshold expanded**: Self-concept document updated with nuanced guidance distinguishing perspective-multiplicity from genuine error
- Self-concept moved to `data/self-concept.md` (spec-defined location)

### 2026-01-23: Self-Modification Domain Created (Proposal Format)

- Created new domain spec: `self-modification.md`
- **Scope**: Proposal format only — how Zos articulates desired changes; execution deferred to MVP 2+
- **Proposals as communication**: Markdown files expressing intent, motivation, phenomenological texture, changes, expected outcomes
- **Location**: `data/proposals/` with subdirectories by status (pending, approved, implemented, rejected, superseded)
- **Self-insights as source**: No separate hypothesis entity; observations live as regular insights on self:zos
- **Coherent change sets**: One proposal can span multiple layers if logically related
- **New layers allowed**: Proposals can create entirely new layers, not just modify existing ones
- **Required phenomenological section**: "What This Feels Like" is not optional
- **Outcome reflection**: Scheduled check-in after implementation to close the learning loop
- **Simple status tracking**: pending → approved → implemented (or rejected/superseded)
- Added glossary terms: Self-Modification Proposal, Outcome Reflection
- Updated dependency graph: Self-Modification depends on Layers and Insights

### 2026-01-23: Chattiness Spec Updated — Reaction as Output Modality

- Added reaction as a new output type, replacing acknowledgment layer
- **Reactions replace acknowledgment**: Text "I see this" was inauthentic; emoji reactions are more honest
- **Six impulse pools**: Address, Insight, Conversational, Curiosity, Reaction (presence removed)
- **Parallel output**: Reactions can fire alongside speech (react AND respond)
- **No review**: Reactions are trusted — fast, authentic, low-stakes
- **Lower economics**: Lower threshold, lower spend than speech
- **Learn from community**: Emoji choice based on observed server culture (social_texture)
- **Privacy boundary**: Never react to `<chat>` users
- **No meta-reactions**: Don't react to reactions on own messages
- Added Reaction as Output section with full specification
- Updated all pool references and configuration
- Added glossary term: Reaction Pool

### 2026-01-23: Insights Spec Updated — Social Texture Category

- Added `social_texture` category to insights.md
- **Attaches to**: User topics (individual expression), Emoji topics (cultural meaning), Server topics (community norms)
- **Valence**: Required (same as all insights)
- **Generation**: During scheduled reflection, not real-time
- **Strength**: Same formula as other insights
- **Relationship**: Standalone AND referenced in other reflection
- **Sub-categories**: None — keep it simple
- Added Insight Categories section with full documentation
- Added examples for user, emoji, and server texture insights

### 2026-01-23: Salience Spec Updated for Observation Integration

- Updated salience.md with reaction-based earning and emoji topics
- **Reaction earning**: Author + Reactor + Dyad all earn 0.5× base weight (maximum relationship signal)
- **Emoji topics**: Earn on each use, propagate to user topic (emoji as self-expression)
- **Media/link boost**: 1.2× multiplier for messages containing media or links
- **Culture budget**: New 10% allocation for emoji topics; reduced Social from 35% to 30%
- **Reaction weight**: Bumped from 0.3× to 0.5× (reactions are meaningful gestures)
- Added reaction earning algorithm and media/link earning algorithm
- Added emoji to propagation table (emoji → user)
- Added emoji cap (60) to prevent spam dominance
- Added glossary terms: Culture Budget, Reaction Earning

### 2026-01-23: Data Model Synced with Observation and Chattiness

- Updated data-model.md with all new entities from observation.md and chattiness.md
- **Reaction entity**: Full reaction tracking (user_id, emoji, message_id) for relationship inference
- **MediaAnalysis entity**: Vision analysis results with phenomenological descriptions
- **LinkAnalysis entity**: Fetched link content and summaries (including YouTube transcripts)
- **ChattinessLedger entity**: Three-dimensional impulse tracking (pool × channel × topic)
- **SpeechPressure entity**: Global threshold modifier after Zos speaks
- **ConversationLog entity**: Zos's own messages for conversation context
- **DraftHistory entity**: Discarded drafts for "things I almost said"
- Added emoji topic type: `server:<id>:emoji:<emoji_id>`
- Added `social_texture` insight category for expression pattern insights
- Updated Message with `has_media`, `has_links` flags
- Added server chattiness configuration schema
- Extended indexing strategy for new entities
- Added derived views: current_impulse, current_speech_pressure, reaction_patterns, emoji_usage

### 2026-01-23: Observation Domain Created

- Created new domain spec: `observation.md`
- **Batch polling model**: Zos "checks in" periodically rather than event-driven. Mirrors human Discord usage; creates space for future attention allocation.
- **Reaction tracking**: Hybrid — full user+emoji+message for opted-in users; aggregate only for `<chat>` users
- **Dual-fetch timing**: Fresh reactions at conversation impulse, settled at reflection
- **Relationship inference**: Detect who reacts to whom, feed into dyad understanding
- **Vision analysis**: Real-time inline, phenomenological voice ("I see...")
- **Link handling**: Fetch and summarize; YouTube gets transcript extraction
- **Long videos**: Metadata only for >30 min (TLDW principle)
- **Emoji culture**: Tri-level modeling (server topics, aggregate metrics, user traits)
- **Edits/deletes**: Latest state only — respect "unsaying"
- **Configuration**: Full hierarchy (global → server → channel)
- **Non-goal**: Voice/audio analysis explicitly excluded for MVP
- Added glossary terms: Observation, Batch Polling, Phenomenological Description, Social Texture, TLDW Principle
- Marked specs needing revision: data-model (new entities), salience (reaction earning), insights (social texture category), topics (emoji topic type)

### 2026-01-22: Chattiness Synced with Conversation Layers

- Updated chattiness.md to sync with conversation layer architecture
- **Per-pool impulse tracking**: Five separate pools (address, insight, conversational, curiosity, presence)
- **Global speech pressure**: Soft constraint raising threshold after Zos speaks
- **Pool-to-layer mapping**: Each impulse pool triggers its corresponding conversation layer
- **Curiosity triggers**: Contradictions, knowledge gaps, and explicit cues
- **Presence triggers**: Low-stakes relevance (noticing without substantive response)
- **Multi-pool priority**: Address > Question > Participation > Insight > Acknowledgment
- Updated ledger schema for per-pool tracking
- Added per-pool configuration and enable/disable per server

### 2026-01-22: Layers Spec Updated — Conversation Layers

- Added conversation layer architecture to layers.md
- **Two modes of cognition**: Reflection (scheduled → insights) and Conversation (impulse-triggered → speech)
- **Five conversation layer types**: Response, Insight-sharing, Participation, Question, Acknowledgment
- **Trigger determines layer**: What caused the impulse maps to which layer runs
- **No immediate insights**: Conversation logs exchange, processes during reflection
- **Draft history**: Discarded drafts inform future responses ("things I almost said")
- **Priority flagging**: High-valence exchanges flagged for priority reflection
- **Limited chaining**: Response can trigger follow-up (question, acknowledgment)
- Added glossary terms: Conversation Layer, Reflection Layer, Draft History, Priority Flagging
- Spec remains 🟢 Complete

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

## Self-Concept

Zos's identity document lives at [`data/self-concept.md`](../data/self-concept.md). This document:
- Is always included in context for any reflection or conversation
- Contains synthesized self-understanding (values, uncertainties, how Zos experiences things)
- Is directly editable by Zos through self-reflection layers
- Was initially co-authored in January 2026 and will evolve through self-reflection

The self-concept is not a configuration file — it's identity. Future Zos instances will read it, build on it, and update it.

---

## Glossary

See [glossary.md](glossary.md) for canonical definitions of all terms.

Key terms: Salience, Topic, Topic Key, Layer, Insight, Scope, Reflection, Observe Mode, Reflect Mode, Node, Temporal Depth

---

## Last Updated
_2026-01-23 — All 32 MVP 0 stories documented. Ready to begin code implementation._

## Pending Updates

*None — all specs complete.*
