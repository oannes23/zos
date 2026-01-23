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
| System Overview | [overview.md](architecture/overview.md) | 🟡 | Philosophy, constraints, non-goals |
| Data Model | [data-model.md](architecture/data-model.md) | 🔄 | Entity relationships, storage approach; **needs**: server-aware keys, provisional flag |
| MVP Scope | [mvp-scope.md](architecture/mvp-scope.md) | 🟡 | MVP 0 vs MVP 1 boundaries |

---

## Domain Specs

<!-- Order by conceptual dependency: primitives first, composites later -->

| Area | Doc | Status | Key Open Questions |
|------|-----|--------|-------------------|
| Topics | [topics.md](domains/topics.md) | 🟢 | — |
| Privacy | [privacy.md](domains/privacy.md) | 🟡 | Consent granularity, revocation policy, per-server models |
| Salience | [salience.md](domains/salience.md) | 🔄 | Decay model, importance dimensions, overflow behavior; **needs**: propagation rules |
| Insights | [insights.md](domains/insights.md) | 🟢 | — |
| Layers | [layers.md](domains/layers.md) | 🔄 | DAG pipelines, conditionals, self-modification flow; **needs**: synthesis layer type, metrics request, retrieval config |

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

---

## Recent Changes

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
_2026-01-22 — Seed document ingested._
