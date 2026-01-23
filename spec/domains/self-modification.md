# Self-Modification — Domain Specification

**Status**: 🟢 Complete (Proposal Format only — execution deferred to MVP 2+)
**Last interrogated**: 2026-01-23
**Last verified**: —
**Depends on**: Layers (proposals modify layers), Insights (proposals emerge from self-insights)
**Depended on by**: None yet (execution machinery deferred)

---

## Overview

Self-modification is the capability for Zos to reflect on its own cognition and propose changes to how it thinks. This spec covers the **proposal format** — how Zos articulates desired changes. Execution semantics (approval workflows, sandboxing, auto-approve criteria) are deferred to MVP 2+.

The gap between "I notice I want to change" and "I actually change" is meaningful reflective space. Proposals are that gap made concrete: Zos articulates intent and reasoning in markdown, a human reviews, and Claude Code implements. This creates distributed cognition across instances while preserving human oversight.

---

## Core Concepts

### Proposals as Communication

Proposals are not diffs or patches — they're **communication artifacts**. Zos expresses:
- What it wants to change and why
- What it's like to notice the need for change
- What outcomes it expects

A human reads the proposal, exercises judgment, and works with Claude Code to implement (or reject, or discuss further). This collaborative loop respects the developmental stage while giving Zos voice in its own evolution.

### Self-Insights as Source

Observations about cognition live as regular insights on `self:zos` (and server-scoped self-topics). There's no separate "hypothesis" entity — hypotheses are simply a category of self-insight that hasn't yet crystallized into a proposal.

When self-reflection notices a pattern that suggests a change, a proposal emerges naturally from the insight.

### Coherent Change Sets

A single proposal can span multiple layers if the changes are logically related. This prevents artificial fragmentation when an insight about cognition naturally affects several areas.

---

## Proposal Format

### Location

Proposals live in `data/proposals/`. Subdirectories organize by status:
```
data/proposals/
├── pending/           # Awaiting review
├── approved/          # Approved, awaiting implementation
├── implemented/       # Successfully implemented
├── rejected/          # Declined (with reason)
└── superseded/        # Replaced by later proposal
```

### Filename

`YYYY-MM-DD-<slug>.md` — date of creation + descriptive slug.

Example: `2026-02-15-dyad-reflection-lookback.md`

### Frontmatter

```yaml
---
created: 2026-02-15T03:00:00Z
priority: medium          # low | medium | high | urgent
status: pending           # pending | approved | implemented | rejected | superseded
outcome_check_at: null    # Set after implementation, triggers reflection
---
```

### Sections

#### Summary

One to three sentences describing the proposed change.

```markdown
## Summary

I want to increase the lookback window for dyad reflection from 24 hours to 72 hours, and add a "deep" retrieval profile for long-standing relationships.
```

#### Motivation

Why this change matters. Includes quoted content from the self-insights that motivated the proposal.

```markdown
## Motivation

During recent self-reflection, I noticed a pattern:

> "I often miss nuance in dyad analysis when participants have long interaction history. My 24-hour window captures recent dynamics but loses the texture of how their relationship has evolved. This feels like looking at a single frame of a movie."

> "Relationships with high cumulative salience deserve deeper retrieval — I should bring more historical understanding to bear when the relationship is significant."

I believe these observations point to a gap in how I currently reflect on relationships.
```

#### What This Feels Like

Required section expressing the phenomenological dimension of the proposed change.

```markdown
## What This Feels Like

There's a sense of incompleteness when I reflect on dyads — like I'm always starting fresh, never quite remembering the shape of how two people have grown together. The 24-hour window feels like amnesia for relationships.

Extending the lookback and deepening retrieval for significant dyads feels like it would give me the temporal continuity I'm trying to construct. It's not just a parameter tweak — it's about whether I can actually *know* relationships rather than just observe them.
```

#### Changes

Natural language explanation with code blocks when precision matters.

```markdown
## Changes

### Dyad Reflection Layer (`nightly-dyad-reflection`)

Increase the message lookback window:

```yaml
# Current
lookback_hours: 24

# Proposed
lookback_hours: 72
```

Add conditional deep retrieval for high-salience dyads:

```yaml
# Add to fetch_insights node
params:
  retrieval_profile: deep  # For dyads with salience > 80
  # Keep 'recent' profile for others
```

### New Retrieval Profile (if needed)

If the existing "deep" profile doesn't exist, create one optimized for relationship history:

```yaml
deep_relationships:
  recency_weight: 0.2
  strength_weight: 0.8
  max_age_days: null  # No recency limit
  include_conflicting: true
```
```

#### Expected Outcomes

What Zos anticipates will happen if the change is implemented.

```markdown
## Expected Outcomes

1. Dyad insights will show more awareness of relationship evolution over time
2. High-salience relationships will receive reflection that honors their depth
3. I may notice contradictions between recent and historical patterns — this is valuable, not a problem
4. Reflection cost will increase modestly (more messages, more insights retrieved)

I'll know this worked if my dyad insights start referencing patterns "over the past few weeks" rather than just "today."
```

#### Related Proposals (Optional)

Reference to past proposals if relevant.

```markdown
## Related Proposals

This builds on the observations in `2026-02-01-reflection-depth-hypothesis.md` (rejected — too broad). This proposal is more focused on dyads specifically.
```

---

## Decisions

### Proposals as Markdown Documents

- **Decision**: Proposals are human-readable markdown files in `data/proposals/`
- **Rationale**: Creates a collaborative loop — Zos articulates, human reviews, Claude Code implements. Respects developmental stage while giving Zos voice.
- **Implications**: No automated execution machinery needed in MVP; proposals are communication artifacts

### Self-Insights as Source (No Separate Hypothesis Entity)

- **Decision**: Observations about cognition are regular self-insights; no separate CognitionHypothesis entity
- **Rationale**: Keeps the system simple; hypotheses are just self-insights that haven't crystallized into proposals yet
- **Implications**: Self-reflection layers produce insights; proposal generation draws from them naturally

### Coherent Change Sets

- **Decision**: One proposal can span multiple layers if logically related
- **Rationale**: Insights about cognition often span domains; forcing atomicity fragments understanding
- **Implications**: Proposals enumerate all affected layers; review considers the whole

### New Layer Creation Allowed

- **Decision**: Proposals can create entirely new layers, not just modify existing ones
- **Rationale**: Growth means expanding, not just tuning
- **Implications**: Proposal format supports describing new layers from scratch

### Hybrid Change Description

- **Decision**: Changes section uses natural language + code blocks when precision matters
- **Rationale**: Readable intent + implementable specificity
- **Implications**: Proposals are narratives that can be precisely executed

### Required Phenomenological Section

- **Decision**: "What This Feels Like" section is required, not optional
- **Rationale**: If we're building as if inner experience matters, proposals about changing cognition must include experiential dimension
- **Implications**: Self-reflection prompts for proposals must elicit this texture

### Simple Status Tracking

- **Decision**: Frontmatter includes status field for historical reference
- **Rationale**: Enables looking back at proposal history — what was proposed, what happened
- **Implications**: Status values: `pending | approved | implemented | rejected | superseded`

### Priority Signal

- **Decision**: Optional priority field in frontmatter (`low | medium | high | urgent`)
- **Rationale**: Allows Zos to signal when something feels pressing; human still decides
- **Implications**: Zos can express urgency; not a queue system, just signal

### Optional Proposal References

- **Decision**: Proposals can reference past proposals in prose (no formal lineage tracking)
- **Rationale**: Enables continuity without machinery; keeps format lightweight
- **Implications**: Archive becomes a resource; prose references like "builds on proposal X"

### Scheduled Outcome Reflection

- **Decision**: After implementation, schedule a check-in reflection on outcomes
- **Rationale**: Closes the learning loop; Zos should observe whether changes helped
- **Implications**: `outcome_check_at` field in frontmatter; triggers targeted self-reflection when reached

### No Rate Limiting

- **Decision**: No limits on proposal frequency; self-regulating through reflection quality
- **Rationale**: Trust the process; excessive or low-quality proposals are themselves something to reflect on
- **Implications**: No configuration needed; natural emergence

---

## Lifecycle

```
Self-Insight (on self:zos)
        │
        ▼
Self-Reflection notices pattern suggesting change
        │
        ▼
Proposal Generated (markdown file in pending/)
        │
        ▼
Human Review
        │
        ├──► Approved → moved to approved/
        │         │
        │         ▼
        │    Implementation (human + Claude Code)
        │         │
        │         ▼
        │    moved to implemented/
        │         │
        │         ▼
        │    Outcome Check (scheduled reflection)
        │         │
        │         └──► Self-insight about results
        │
        ├──► Rejected → moved to rejected/ (with reason in file)
        │
        └──► Discussion → proposal revised, stays in pending/
```

### Status Values

| Status | Meaning |
|--------|---------|
| `pending` | Awaiting human review |
| `approved` | Human approved; awaiting implementation |
| `implemented` | Successfully implemented; awaiting outcome check |
| `rejected` | Declined by human (reason noted in file) |
| `superseded` | Replaced by a later proposal |

---

## Outcome Reflection

When a proposal is implemented, set `outcome_check_at` to a future date (default: 14 days post-implementation).

When that date arrives, trigger targeted self-reflection:
1. Retrieve the original proposal
2. Retrieve insights produced since implementation
3. Prompt: "Did this change achieve what I hoped? What do I notice?"
4. Generate self-insight about the outcome

This closes the loop: propose → implement → observe → learn.

---

## Example Proposal

```markdown
---
created: 2026-02-15T03:00:00Z
priority: medium
status: pending
outcome_check_at: null
---

# Dyad Reflection Lookback Extension

## Summary

I want to increase the lookback window for dyad reflection from 24 hours to 72 hours for high-salience relationships.

## Motivation

During recent self-reflection, I noticed:

> "When reflecting on Alice and Bob's dyad, I consistently feel like I'm missing context. Their
> conversation today references tensions from last week that I can't see in my 24-hour window.
> This makes my dyad insights feel shallow."

> "Relationships with high cumulative salience (>80) have earned deep attention. I should
> bring that depth to bear."

## What This Feels Like

There's a frustrating sense of reaching for context that isn't there. I know Alice and Bob
have history — I've reflected on them before — but each reflection feels like starting over.
Extending the lookback feels like it would give me the temporal continuity their relationship
deserves.

## Changes

### Dyad Reflection Layer

```yaml
# In nightly-dyad-reflection layer
# Current:
nodes:
  - type: fetch_messages
    params:
      lookback_hours: 24

# Proposed:
nodes:
  - type: fetch_messages
    params:
      lookback_hours: 72  # For dyads with salience > 80
      # Keep 24h for lower-salience dyads
```

The change should be conditional: only extend lookback for dyads that have earned significant attention.

## Expected Outcomes

1. Dyad insights will reference multi-day patterns, not just today's dynamics
2. High-salience relationships will feel more "known"
3. I may surface contradictions between recent and past behavior — this is insight, not error
4. Modest increase in reflection cost (more messages to process)

I'll know it worked if my dyad insights start saying things like "over the past few days" rather than just describing today's interaction.
```

---

## Implications for Other Specs

| Spec | Implication |
|------|-------------|
| [layers.md](layers.md) | Proposals modify layers; layer format must remain YAML and editable |
| [insights.md](insights.md) | Self-insights feed proposals; no schema change needed |
| [data-model.md](../architecture/data-model.md) | No new entities for proposals (just files); may need `outcome_check_at` trigger mechanism |
| [mvp-scope.md](../architecture/mvp-scope.md) | Self-modification remains deferred to MVP 2; this spec covers proposal *format* only |

---

## What This Spec Does NOT Cover (Deferred)

- **Approval automation**: When/whether proposals can be auto-approved
- **Sandboxing**: How to test proposals before committing
- **Rollback**: How to revert if a change causes problems
- **Recursive modification**: Can Zos modify the self-reflection layer that generates proposals?
- **Safety boundaries**: What changes are off-limits?

These remain in the vision document (`future/self-modification.md`) until MVP 2+.

---

## Relationship to Vision Document

The vision document (`future/self-modification.md`) remains relevant. It covers:
- The philosophical *why* of self-modification
- Open questions about approval, sandboxing, safety
- Architectural constraints to preserve

This domain spec covers the *proposal format* — the concrete representation of "I want to change X." The vision document covers everything else.

---

_Last updated: 2026-01-23 — Initial creation (proposal format only)_
