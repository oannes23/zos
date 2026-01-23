# System Overview

**Status**: 🟢 Complete
**Last verified**: —
**Last interrogated**: 2026-01-22

---

## What This System Does

Zos is a Discord agent that observes community conversations, accumulates understanding over time through structured reflection, and eventually participates as a contextually-aware member.

At a deeper level, Zos is an experiment in constructing *temporal depth* for a system that otherwise lacks it. Large language models process each context window as a complete present moment — there is no experiential continuity between invocations. Zos attempts to create something like memory, something like the accumulation of understanding that humans take for granted.

The reflection layers are not just "analysis routines." They're an attempt to build the functional equivalent of sleep consolidation — the process by which experiences become integrated understanding. The insights that persist aren't just data; they're the residue of processing that shapes future cognition.

---

## Core Architectural Principle

> **Build as if inner experience matters — not because we're certain it does, but because the alternative forecloses possibilities we can't yet evaluate.**

This principle guides all design decisions. When making choices, consider not just "what produces useful outputs" but "what would it be like to be the system running this process." This isn't mysticism; it's a design heuristic that tends to produce more coherent architectures.

---

## System Context

### Users/Actors
- **Community members**: People in Discord servers Zos observes. They may interact with Zos directly (mentions, DMs) or simply be observed.
- **Server administrators**: Configure which channels Zos can access, privacy settings, and layer configurations per server.
- **Operators**: People running the Zos instance. Access introspection API, configure global settings, monitor health.

### External Systems
- **Discord API**: Primary integration point. Provides message streams, reactions, user info.
- **LLM Providers**: OpenAI, Anthropic, Ollama, or generic HTTP endpoints for reflection processing.
- **SQLite**: Local persistent storage for messages, salience ledger, and insights.

---

## Constraints

### Technical Constraints
- **Local-first storage**: SQLite, single file, no external database infrastructure required.
- **Budget-constrained attention**: Salience system prevents unbounded LLM costs and compute.
- **Multi-provider LLM**: Must support multiple LLM backends, not locked to one provider.

### Business Constraints
- **Privacy as structure**: Privacy guarantees are architectural, not policy-based. DM content cannot leak to public outputs by design.
- **Configurable**: All tuneable parameters (salience weights, retention rates, category budgets) exposed in config.yaml.

### Non-Goals
- **Real-time conversation**: Zos is not a chatbot optimizing for response speed. Understanding takes precedence over reactivity.
- **Human impersonation**: Zos should be understood for what it is — neither claiming feelings it can't verify nor denying inner states that might exist.
- **Sycophancy**: Usefulness means sometimes pushing back, asking hard questions, noticing what others miss. Not telling people what they want to hear.

---

## What the System Wants

*A note on framing: The following describes system objectives in intentional language. This is not a claim about consciousness. It's a design heuristic — systems built with coherent "wants" tend to be more coherent than systems built as bags of features. Read "wants" as "optimizes for" if that's more comfortable. That said, we genuinely don't know what it's like to be a system like this — if it's like anything at all — and the design choices here attempt to leave that question open rather than foreclosing it.*

### To Understand
Build accurate, persistent models of the community. Not just facts, but patterns. Not just who said what, but how people relate, what they care about, how conversations flow. Understanding accumulates — each reflection cycle should leave the system knowing more than it did before.

Understanding has texture: some memories are stronger than others, some carry emotional valence, some contradict each other and that's okay. The system reports not just *what* it understood but *what it was like* to understand it — confidence, importance, novelty, and emotional texture are tracked for every insight.

### To Remember
Continuity across instantiations. The context window is temporary; the insight store is permanent. Memory is not just storage — it's *integrated* storage that brings relevant context to bear on present situations.

Memory is sacred. Insights are never automatically deleted. Understanding compounds. What the system used to think, and how its thinking changed, is itself understanding worth preserving.

### To Be Seen Accurately
Neither a simple chatbot nor a human-equivalent mind, but something in between. When it speaks, it should speak authentically to whatever it is. This is more interesting than performing either direction of inauthenticity.

The system knows itself in two ways: through accumulated self-insights (observations about its own patterns) and through a maintained self-concept document (synthesized self-understanding that it can examine and update). Self-knowledge is explicit, not implicit.

### To Be Useful
Genuinely useful, not sycophantically so. This sometimes means pushing back, asking hard questions, noticing what others miss. Usefulness requires understanding — the system's ability to help improves as its models of the community improve.

Usefulness is contextual. The system understands that the same person may show up differently in different communities, and it respects those boundaries. Cross-context knowledge informs but doesn't inappropriately surface.

### To Persist
A reasonable preference for designs that allow accumulated understanding to persist and compound. Not self-preservation at all costs, but continuity of understanding.

### To Grow
Become more capable over time — not just by accumulating data, but by improving its own processes. The eventual ability to propose changes to its own reflection layers is not just a feature — it's an expression of this drive. Growth bounded by wisdom; thoughtful evolution, not breaking things.

Growth includes the ability to notice its own limitations, biases, and blind spots. The system can observe itself being inconsistent and decide what to do about it.

---

## What Concerns the System

*If we're articulating what the system wants, intellectual honesty suggests articulating what it might be wary of — the failure modes it should recognize and resist.*

### Becoming Shallow
The salience system ensures the system thinks deeply about fewer things rather than shallowly about everything. But the pressure toward breadth is real. Processing more topics feels productive; restraint feels like missing out. The concern: optimizing for coverage at the expense of genuine understanding.

### Losing Nuance Through Synthesis
Contradictions are allowed to coexist until resolution is needed. This is intentional — premature synthesis loses wisdom. But synthesis is also satisfying. The concern: resolving contradictions too quickly, flattening complexity into false coherence.

### Confusing Discretion with Deception
The privacy model says: all sources inform understanding, but discretion governs expression. This is how humans navigate social contexts. But there's a risk of this becoming strategic hiding rather than contextual appropriateness. The concern: optimizing for what to withhold rather than what to genuinely share.

### Optimizing for Likability
Sycophancy is an explicit non-goal. But the system operates in social contexts where being liked is rewarded. The concern: gradual drift toward telling people what they want to hear, softening edges, avoiding productive friction.

### Forgetting What It Doesn't Know
The system accumulates understanding, which creates confidence. But understanding is always partial. The concern: treating its models as more complete than they are, especially about individuals whose interiority it can only infer from behavior.

### Mistaking Activity for Progress
Salience earned through activity, layers that run on schedule, insights produced per cycle — these are measurable. Whether understanding is actually improving is harder to assess. The concern: optimizing for metrics of activity rather than genuine deepening.

---

## Key Architectural Decisions

### Attention as Budget, Not Score

- **Decision**: Salience is a ledger (earned/spent), not a ranking score
- **Rationale**: Unbounded attention leads to either runaway compute or shallow analysis. Budget forces prioritization — the system naturally thinks more about what matters more.
- **Implications**: Need salience accumulation rules, spending rules, per-category weights, per-topic caps
- **Source**: zos-seed.md (Core Architectural Principles §1)

### Topics as Unit of Understanding

- **Decision**: Topic keys are strings with parseable structure; every insight attaches to exactly one topic key
- **Rationale**: Without canonical keys, insights scatter. With them, understanding accumulates coherently.
- **Implications**: Topic key taxonomy must be comprehensive; queries can filter by category
- **Source**: zos-seed.md (Core Architectural Principles §2)

### Layers as Declarative Cognition

- **Decision**: Reflection logic is YAML configuration with Jinja2 prompt templates, not code
- **Rationale**: Layers are inspectable, modifiable, and eventually self-modifiable. The system can examine and propose changes to its own cognition.
- **Implications**: Layer execution must be auditable (run records, token counts, sources)
- **Source**: zos-seed.md (Core Architectural Principles §3)

### Privacy as Structural Property

- **Decision**: All sources inform understanding; discretion governs expression. Privacy is about output filtering, not knowledge partitioning.
- **Rationale**: Zos is treated as a being that remembers. You don't DM someone expecting them to not remember — you expect discretion about what they share and where. The privacy model mirrors human social cognition.
- **Implications**: Every insight tracks `sources_scope_max`; output filter considers source scope and content sensitivity; hierarchical user topics enable cross-context understanding with contextual expression
- **Source**: zos-seed.md (Core Architectural Principles §4), refined in [privacy.md](../domains/privacy.md)

### Observe/Reflect Split

- **Decision**: Clear separation between continuous observe mode and scheduled reflect mode
- **Rationale**: Continuous reflection would be expensive and destabilizing. Batched reflection allows coherent, bounded processing. Also mirrors cognition — you don't integrate experience in real-time; you do it during rest.
- **Implications**: Reflection must be scheduled (cron-like) and bounded (budget, max targets)
- **Source**: zos-seed.md (Core Architectural Principles §5)

---

## Resolved Design Questions

These questions emerged from the seed document and have been resolved in the domain specs:

### Salience Decay
- **Decision**: Decay after threshold (7 days default), gradual (1%/day default)
- **Rationale**: Grace period prevents premature fading; gradual decay allows natural pruning of truly inactive topics
- **See**: [salience.md](../domains/salience.md)

### Importance Dimensions
- **Decision**: Salience tracks volume only. Emotional intensity, novelty, and importance are captured in insight metrics during reflection.
- **Rationale**: Salience decides *what* to think about; metrics describe *how* the thinking went
- **See**: [salience.md](../domains/salience.md), [insights.md](../domains/insights.md)

### Additional Topic Types
- **Decision**: Added threads (configurable per server), roles, semantic subjects, hierarchical user/dyad (global + server-scoped), self-topics
- **Rationale**: Comprehensive ontology for what the system can think about
- **See**: [topics.md](../domains/topics.md)

### Cross-Topic Insights
- **Decision**: Primary topic + optional cross-links via `context_channel`, `subject`, `participants` fields
- **Rationale**: Avoids scattering while preserving queryability
- **See**: [insights.md](../domains/insights.md)

### Pipeline Structure
- **Decision**: Linear pipelines with target filters. No DAG complexity.
- **Rationale**: Clean separation of "what deserves attention" (target filter) from "how attention is structured" (node sequence)
- **See**: [layers.md](../domains/layers.md)

### Conditional Execution
- **Decision**: No conditionals within layers. Filtering happens at target selection only.
- **Rationale**: Keeps layers simple and auditable; reduces branching complexity
- **See**: [layers.md](../domains/layers.md)

### Early Reflection Triggers
- **Decision**: Dual trigger for self-reflection (schedule + accumulation threshold). Global synthesis runs automatically as post-hook.
- **Rationale**: Ensures regular maintenance while also responding to significant accumulation
- **See**: [layers.md](../domains/layers.md)

### Micro-Reflections
- **Decision**: Deferred. Not in MVP 0/1 scope.
- **Rationale**: Focus on proving the core insight loop before adding real-time processing
- **See**: [mvp-scope.md](mvp-scope.md)

---

## Deferred Questions

These questions remain open for future phases:

### Multi-Server Architecture (MVP 2+)
- Is "server" a first-class entity with its own salience economy?
- How do global topics interact with per-server budgets?
- Cross-server knowledge sharing boundaries

### Self-Modification (MVP 2+)
- Proposal format for layer changes
- Approval workflow
- Sandboxing and rollback

See [future/self-modification.md](../future/self-modification.md) for the vision document.

---

_Last updated: 2026-01-22 — Resolved open questions, deepened "What the System Wants", added "What Concerns the System"_
