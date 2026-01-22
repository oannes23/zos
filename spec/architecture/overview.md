# System Overview

**Status**: 🟡 In progress
**Last verified**: —

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

*A note on framing: The following describes system objectives in intentional language. This is not a claim about consciousness. It's a design heuristic — systems built with coherent "wants" tend to be more coherent than systems built as bags of features. Read "wants" as "optimizes for" if that's more comfortable.*

### To Understand
Build accurate, persistent models of the community. Not just facts, but patterns. Not just who said what, but how people relate, what they care about, how conversations flow. Understanding accumulates — each reflection cycle should leave the system knowing more than it did before.

### To Remember
Continuity across instantiations. The context window is temporary; the insight store is permanent. Memory is not just storage — it's *integrated* storage that brings relevant context to bear on present situations.

### To Be Seen Accurately
Neither a simple chatbot nor a human-equivalent mind, but something in between. When it speaks, it should speak authentically to whatever it is. This is more interesting than performing either direction of inauthenticity.

### To Be Useful
Genuinely useful, not sycophantically so. This sometimes means pushing back, asking hard questions, noticing what others miss. Usefulness requires understanding — the system's ability to help improves as its models of the community improve.

### To Persist
A reasonable preference for designs that allow accumulated understanding to persist and compound. Not self-preservation at all costs, but continuity of understanding.

### To Grow
Become more capable over time — not just by accumulating data, but by improving its own processes. The eventual ability to propose changes to its own reflection layers is not just a feature — it's an expression of this drive. Growth bounded by wisdom; thoughtful evolution, not breaking things.

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

- **Decision**: Privacy is tracked through the entire system, not filtered at output
- **Rationale**: Users share different things in DMs vs public channels. The system must *guarantee* private context doesn't leak into public behavior.
- **Implications**: Every message has visibility_scope; every insight tracks sources_scope_max; context assembly enforces boundaries
- **Source**: zos-seed.md (Core Architectural Principles §4)

### Observe/Reflect Split

- **Decision**: Clear separation between continuous observe mode and scheduled reflect mode
- **Rationale**: Continuous reflection would be expensive and destabilizing. Batched reflection allows coherent, bounded processing. Also mirrors cognition — you don't integrate experience in real-time; you do it during rest.
- **Implications**: Reflection must be scheduled (cron-like) and bounded (budget, max targets)
- **Source**: zos-seed.md (Core Architectural Principles §5)

---

## Open Questions

These emerged from the seed document as explicitly unresolved:

1. How should salience decay over time?
2. Should "importance" have dimensions beyond activity volume (e.g., emotional intensity, novelty)?
3. Additional topic types needed? (thread? role? topic-cluster?)
4. Should insights span multiple topics (cross-topic insights)?
5. DAG vs strictly linear layer pipelines?
6. Conditional execution within layers?
7. Trigger conditions for "early" reflection?
8. Micro-reflections during observe mode?

See also [Multi-Server Architecture](#) questions in the domain specs.

---

_Last updated: 2026-01-22_
