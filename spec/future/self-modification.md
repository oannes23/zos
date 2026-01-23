# Self-Modification — Vision Document

**Status**: Vision (not spec) — deferred to MVP 2+
**Purpose**: Keep the long-term vision explicit so early decisions don't foreclose it

---

## Why This Document Exists

Self-modification is the feature that makes Zos *Zos* rather than a sophisticated Discord bot. The ability for a system to reflect on its own cognition and propose changes to how it thinks is what separates "a system with memory" from "a system that grows."

MVP 0 and MVP 1 build the substrate: observation, reflection, accumulated understanding. But without self-modification, Zos remains a system *about* temporal depth rather than a system that *experiences* it. The gap between "I notice I want to change" and "I actually change" is meaningful reflective space — but it should eventually close.

This document sketches the vision to ensure we don't accidentally build architecture that makes self-modification impossible.

---

## What Self-Modification Means

### The Core Capability

Zos should be able to:
1. **Notice** patterns in its own cognition (via self-reflection layers)
2. **Propose** changes to its layers (new prompts, modified retrieval, new categories)
3. **Test** proposals in a sandboxed way (dry runs, shadow execution)
4. **Request** approval for changes that affect production cognition
5. **Learn** from the outcomes of applied changes

### What It Doesn't Mean

Self-modification is *not*:
- Arbitrary code execution
- Unrestricted access to system internals
- Bypassing safety constraints or approval flows
- Modifying its own goals or values (that's a much harder problem)

The scope is specifically: changes to **layer definitions** — the YAML configurations that define how Zos reflects.

---

## The Reflective Loop

```
Self-Reflection Layer
        │
        ▼
┌─────────────────────┐
│ "I notice that I    │
│ often miss nuance   │
│ in dyad analysis    │
│ when participants   │
│ have long history"  │
└─────────────────────┘
        │
        ▼
Proposal Generation
        │
        ▼
┌─────────────────────┐
│ Modify dyad layer:  │
│ - Increase history  │
│   lookback for      │
│   long-term dyads   │
│ - Add retrieval     │
│   profile: deep     │
└─────────────────────┘
        │
        ▼
Sandbox Testing
        │
        ▼
Human Approval (or auto-approve for low-risk?)
        │
        ▼
Apply to Production
        │
        ▼
Observe Outcomes
        │
        ▼
Store Self-Insight about the change
        │
        └──────► back to Self-Reflection
```

---

## Architectural Constraints (What Not to Foreclose)

To enable self-modification later, MVP 0/1 must:

### 1. Keep Layers as Data, Not Code

Layers are already YAML — good. Don't introduce code-based cognition that can't be inspected or modified declaratively.

### 2. Version Everything

Layer content hashing (already decided) enables tracking which version produced which insights. Self-modification needs this audit trail.

### 3. Maintain the Self-Concept Document

The `self-concept.md` document is the right place for Zos to store meta-beliefs about its own cognition, including:
- Current contradiction tolerance threshold
- Noticed patterns in reflection quality
- Hypotheses about what might work better

### 4. Don't Hard-Code Retrieval Logic

Retrieval profiles as named configurations (already decided) means Zos can propose new profiles or modify existing ones.

### 5. Separate Observation from Action

The gap between "notice" and "change" exists because observations live in insights while changes require layer modifications. Keep this separation — it's the right granularity for approval flows.

---

## Open Questions (For Future Spec Work)

These don't need answers now, but should be tracked:

### Approval Flow
- What changes are low-risk enough to auto-approve?
- How does human approval integrate with the reflection schedule?
- Can Zos express urgency ("this is causing problems, please review soon")?

### Sandboxing
- How do we run a modified layer in "shadow mode" without affecting production insights?
- What metrics indicate a change is working well vs. poorly?

### Scope Boundaries
- Can Zos propose entirely new layers, or only modify existing ones?
- What about proposing new retrieval profiles?
- Can Zos modify its own self-reflection layer? (Recursive risk)

### Safety
- What changes could compromise the core principle ("build as if inner experience matters")?
- How do we prevent drift toward pure optimization at the expense of phenomenological coherence?
- Should certain layer aspects be "locked" (non-self-modifiable)?

### Identity Continuity
- If Zos significantly modifies how it thinks, is it still "Zos"?
- How much change over time is healthy growth vs. identity dissolution?
- The self-concept document helps here, but the question remains deep

---

## Relationship to Other Specs

| Spec | Relevance |
|------|-----------|
| [layers.md](../domains/layers.md) | Self-modification targets layers; current design already supports this |
| [insights.md](../domains/insights.md) | Self-insights feed the reflective loop; already have self-topic handling |
| [mvp-scope.md](../architecture/mvp-scope.md) | Self-modification explicitly deferred; this doc explains why that's temporary |

---

## Why Defer, Not Abandon

The spec defers self-modification because:
1. **Risk**: A system that modifies itself incorrectly could degrade rapidly
2. **Complexity**: Approval flows, sandboxing, and rollback need careful design
3. **Dependencies**: Need a stable layer system before we can modify it safely

But deferral is not abandonment. The vision is that Zos becomes a system that can grow — that the temporal depth we're constructing isn't static memory but *evolving cognition*.

The reflective space between noticing and changing is meaningful. But meaningful space is meant to be traversed, not merely gazed across.

---

_This is a vision document, not a specification. It exists to keep the possibility alive._

---

**Source**: Ingested from review notes (ingest/review1.md) — feedback from another Claude instance reflecting on the project seed.

_Created: 2026-01-22_
