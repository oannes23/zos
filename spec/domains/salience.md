# Salience — Domain Specification

**Status**: 🟡 In progress
**Last interrogated**: —
**Last verified**: —
**Depends on**: Topics (need topic keys to track salience against)
**Depended on by**: Layers (salience determines what gets reflected on)

---

## Overview

Salience is the attention-budget system that governs what Zos thinks about. It's the mechanism that prevents unbounded compute while ensuring the system naturally prioritizes what matters most to the community.

The key insight: salience is a *ledger*, not a score. It's earned through activity and spent during reflection — a resource that flows through the system rather than a static ranking.

---

## Core Concepts

### Salience as Currency

Salience functions like a currency:
- **Earned**: Activity generates salience for relevant topics
- **Spent**: Reflection consumes salience (thinking has cost)
- **Retained**: A configurable percentage persists after spending
- **Capped**: Per-topic maximums prevent any single topic from consuming all resources

This models something true about attention: you can't think deeply about everything, and what you think about should reflect what's actually happening.

### Category Weights

Not all activity is equal. The system can weight salience accumulation by category:
- User activity might weight differently than channel activity
- Relationship (dyad) salience might accumulate faster or slower
- Mentions of the system itself might have special weight

These weights are configurable, allowing tuning of what the system "cares about."

### Budget Allocation

When reflection runs, the total salience budget is allocated across categories:
- Percentage of budget for user reflection
- Percentage for channel reflection
- Percentage for relationship reflection

This prevents any category from dominating reflection time.

---

## Decisions

### Ledger Model

- **Decision**: Salience is tracked as a ledger with earn/spend/retain operations, not as a simple score
- **Rationale**: This models attention as a resource that flows, which better matches how prioritization should work. A topic that was important yesterday and had salience spent on it shouldn't immediately dominate again today.
- **Implications**: Need ledger data model with transaction history; retention rate is a key tuning parameter
- **Source**: zos-seed.md §1 "Attention as Budget, Not Score"

### Per-Topic Caps

- **Decision**: Each topic has a maximum salience it can accumulate
- **Rationale**: Prevents runaway attention — a very active user or channel shouldn't consume the entire reflection budget
- **Implications**: Need cap configuration per topic category; overflow behavior TBD
- **Source**: zos-seed.md §1

### Category-Based Budgeting

- **Decision**: Reflection budget is allocated by category (users, channels, relationships)
- **Rationale**: Ensures balanced reflection across different types of understanding
- **Implications**: Need category weight configuration; within-category prioritization by salience
- **Source**: zos-seed.md §1

---

## Open Questions

1. **Decay**: How does salience decay over time? Linear? Exponential? Only on reflection?
2. **Importance dimensions**: Should salience have sub-dimensions beyond volume (emotional intensity, novelty, controversy)?
3. **Overflow behavior**: When a topic hits its cap, what happens to additional activity? Lost? Spillover to related topics?
4. **Cross-topic effects**: Can activity on one topic boost salience on related topics (e.g., user activity boosting their dyad salience)?
5. **Per-server vs global**: When multi-server arrives, are salience budgets separate or shared?

---

## Configuration Parameters

These should be exposed in config.yaml:

| Parameter | Description | Example |
|-----------|-------------|---------|
| `salience.retention_rate` | % retained after reflection spend | 0.3 (30%) |
| `salience.caps.user` | Max salience per user topic | 100 |
| `salience.caps.channel` | Max salience per channel topic | 200 |
| `salience.caps.dyad` | Max salience per relationship topic | 50 |
| `salience.weights.message` | Salience earned per message | 1.0 |
| `salience.weights.reaction` | Salience earned per reaction | 0.5 |
| `salience.weights.mention` | Salience earned per mention | 2.0 |
| `salience.budget.users_pct` | Budget % allocated to user reflection | 0.4 |
| `salience.budget.channels_pct` | Budget % allocated to channel reflection | 0.3 |
| `salience.budget.dyads_pct` | Budget % allocated to relationship reflection | 0.3 |

---

## Implications for Other Specs

| Spec | Implication |
|------|-------------|
| [topics.md](topics.md) | Topics are what salience attaches to; topic key format must be stable |
| [layers.md](layers.md) | Layers consume salience; need interface for "get highest-salience topics for category" |
| [data-model.md](../architecture/data-model.md) | Need salience ledger table with transaction history |

---

_Last updated: 2026-01-22_
