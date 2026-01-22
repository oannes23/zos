# Layers — Domain Specification

**Status**: 🟡 In progress
**Last interrogated**: —
**Last verified**: —
**Depends on**: Topics, Salience, Insights
**Depended on by**: None (top of dependency chain for reflection)

---

## Overview

Layers are the heart of Zos's cognition. They define how the system reflects — how raw observations become integrated understanding.

A Layer is a YAML-defined pipeline: a sequence of nodes that fetch data, process it through LLMs, and store insights. This makes reflection logic *configuration*, not code — inspectable, modifiable, and eventually self-modifiable.

---

## Core Concepts

### Declarative Cognition

Layers embody a principle: if you can't read what the system does, you can't understand or improve it.

By defining reflection as YAML:
- **Inspectable**: Anyone can read a layer file and understand the processing
- **Modifiable**: Change reflection behavior by editing config, not code
- **Auditable**: Every run can log exactly what pipeline executed
- **Self-modifiable**: The system can eventually propose changes to its own layers

### Pipeline Structure

A layer is a linear sequence of nodes:

```yaml
name: nightly-user-reflection
schedule: "0 3 * * *"  # 3 AM daily
target_category: users
max_targets: 10  # Reflect on top 10 by salience

nodes:
  - type: fetch_messages
    params:
      lookback_hours: 24

  - type: fetch_insights
    params:
      categories: [user]
      max_per_topic: 5

  - type: llm_call
    params:
      prompt_template: user_reflection.jinja2
      model: default

  - type: store_insight
    params:
      category: user_reflection
      ttl_days: 30
```

### Node Types

| Type | Purpose | Inputs | Outputs |
|------|---------|--------|---------|
| `fetch_messages` | Retrieve conversation history | topic key, time range | messages list |
| `fetch_insights` | Retrieve prior understanding | topic key, filters | insights list |
| `llm_call` | Process through language model | prompt template, context | generated text |
| `reduce` | Combine multiple outputs | list of items | aggregated result |
| `store_insight` | Persist new understanding | insight content, topic | stored insight |
| `output` | Emit to external destination | content | (side effect) |

### Prompt Templates

LLM calls use Jinja2 templates that have access to:
- `topic`: The current topic being reflected on
- `messages`: Fetched messages
- `insights`: Prior insights
- `context`: Accumulated context from prior nodes
- Config values and helper functions

### Scheduling

Layers run on schedules (cron-like expressions):
- Nightly: user reflection, channel summaries
- Weekly: deeper relationship analysis, trend detection
- Monthly: long-term pattern synthesis

---

## Decisions

### YAML + Jinja2

- **Decision**: Layers are YAML files with Jinja2 prompt templates
- **Rationale**: YAML is human-readable and widely understood; Jinja2 is powerful but not Turing-complete, reducing risk of runaway templates
- **Implications**: Need template validation; template errors should fail gracefully
- **Source**: zos-seed.md §3 "Layers as Declarative Cognition"

### Linear Pipelines

- **Decision**: Layers are strictly linear node sequences (for MVP)
- **Rationale**: Simpler to reason about, implement, and audit; DAG complexity can come later if needed
- **Implications**: No conditional branching within layers; conditionals happen at layer selection level
- **Alternatives considered**: DAG pipelines (deferred to post-MVP)
- **Source**: zos-seed.md §3 (noted as open for reconsideration)

### Cross-Layer Synthesis

- **Decision**: Layers can reference insights produced by other layers
- **Rationale**: Enables layered cognition — quick nightly reflections feed into deeper weekly synthesis
- **Implications**: Need insight categorization; layer dependencies should be explicit
- **Source**: zos-seed.md §3

### Auditable Execution

- **Decision**: Every layer run produces an audit record (inputs, outputs, token counts, sources)
- **Rationale**: Essential for debugging, understanding system behavior, and building toward self-modification
- **Implications**: Need run_record table; token counting integration with LLM providers
- **Source**: zos-seed.md §3

---

## Open Questions

1. **DAG pipelines**: Should layers support directed acyclic graphs for parallel processing? When would this be needed?
2. **Conditional execution**: Should nodes support conditionals (e.g., "only run if salience > threshold")? Or handle at layer level?
3. **Error handling**: What happens when an LLM call fails? Retry? Skip topic? Abort layer?
4. **Self-modification**: How does the system propose layer changes? PR to repo? Config update? Operator approval flow?
5. **Layer versioning**: When a layer definition changes, how do we track which version produced which insights?
6. **Per-server layers**: Should different servers be able to enable/disable specific layers?

---

## Example Layer: Nightly User Reflection

```yaml
name: nightly-user-reflection
description: |
  Reflect on each user's recent activity to update understanding.
  Runs nightly, targeting users with highest salience.

schedule: "0 3 * * *"
target_category: users
budget_category: users  # Draws from user salience budget
max_targets: 10

nodes:
  - name: get_messages
    type: fetch_messages
    params:
      lookback_hours: 24
      limit_per_channel: 50

  - name: get_prior
    type: fetch_insights
    params:
      categories: [user_reflection, user_summary]
      max_per_topic: 3
      max_age_days: 30

  - name: reflect
    type: llm_call
    params:
      prompt_template: layers/user_reflection.jinja2
      model: default
      max_tokens: 500
      temperature: 0.7

  - name: save
    type: store_insight
    params:
      category: user_reflection
      ttl_days: 14
      scope: derived  # Inherits from source messages
```

---

## Implications for Other Specs

| Spec | Implication |
|------|-------------|
| [salience.md](salience.md) | Layers consume salience budget; need "deduct salience for topic" operation |
| [topics.md](topics.md) | Layers target topic categories; need efficient category queries |
| [insights.md](insights.md) | Layers produce insights; need store/fetch interface |
| [privacy.md](privacy.md) | Insights inherit scope from source messages; need scope tracking through pipeline |
| [data-model.md](../architecture/data-model.md) | Need layer_runs table for audit trail |

---

_Last updated: 2026-01-22_
