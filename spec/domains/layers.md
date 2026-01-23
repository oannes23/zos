# Layers — Domain Specification

**Status**: 🟢 Complete
**Last interrogated**: 2026-01-22
**Last verified**: —
**Depends on**: Topics, Salience, Insights, Privacy
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
- **Self-modifiable**: The system can eventually propose changes to its own layers (MVP 2+)

### Pipeline Structure

A layer is a linear sequence of nodes with a target filter:

```yaml
name: nightly-user-reflection
category: user
schedule: "0 3 * * *"  # 3 AM daily
target_category: users
target_filter: "salience > 50 AND last_reflected_days_ago > 1"
max_targets: 10  # Reflect on top 10 matching filter

nodes:
  - type: fetch_messages
    params:
      lookback_hours: 24

  - type: fetch_insights
    params:
      retrieval_profile: recent  # Named profile
      max_per_topic: 5

  - type: llm_call
    params:
      prompt_template: user/reflection.jinja2
      model: default

  - type: store_insight
    params:
      category: user_reflection
```

### Layer Categories

Each layer declares a category from a fixed set:

| Category | Purpose | Budget Group |
|----------|---------|--------------|
| `user` | Reflects on individual users | Social |
| `dyad` | Reflects on relationships | Social |
| `channel` | Reflects on spaces/channels | Spaces |
| `subject` | Reflects on semantic topics | Semantic |
| `self` | Self-reflection | Self |
| `synthesis` | Consolidates insights across scopes | (varies) |

Categories determine budget allocation and organization.

### Target Filtering

Layers specify which targets to process using filter expressions:

```yaml
target_filter: "salience > 50 AND last_reflected_days_ago > 1"
```

This cleanly separates:
- **What deserves attention** (target selection via filter)
- **How attention is structured** (node sequence, unconditional once selected)

Filter expressions support:
- `salience > N` — salience threshold
- `last_reflected_days_ago > N` — recency filter
- `insight_count < N` — for new/under-reflected topics
- Boolean operators: `AND`, `OR`, `NOT`

---

## Node Types

### Core Nodes

| Type | Purpose | Inputs | Outputs |
|------|---------|--------|---------|
| `fetch_messages` | Retrieve conversation history | topic key, time range | messages list |
| `fetch_insights` | Retrieve prior understanding | topic key, retrieval config | insights list |
| `llm_call` | Process through language model | prompt template, context | generated text |
| `reduce` | Combine multiple outputs | list of items | aggregated result |
| `store_insight` | Persist new understanding | insight content, topic | stored insight |
| `output` | Emit to external destination | content | (side effect) |

### Special Nodes

| Type | Purpose | Notes |
|------|---------|-------|
| `synthesize_to_global` | Consolidate server-scoped insights to global topic | Used in automatic post-hook |
| `update_self_concept` | Update the self-concept.md document | Used in self-reflection layer |

### Node Parameters

**fetch_messages**:
```yaml
params:
  lookback_hours: 24
  limit_per_channel: 50
  include_threads: true
```

**fetch_insights**:
```yaml
params:
  retrieval_profile: recent  # Named profile (see below)
  # OR inline overrides:
  recency_weight: 0.7
  strength_weight: 0.3
  max_per_topic: 5
  max_age_days: 30
  include_conflicting: false
```

**llm_call**:
```yaml
params:
  prompt_template: user/reflection.jinja2
  model: default
  max_tokens: 500
  temperature: 0.7
```

**output** (with built-in review):
```yaml
params:
  destination: channel  # or: log, webhook
  review_enabled: true  # Uses privacy.review_pass setting
```

---

## Retrieval Configuration

### Named Profiles

Common retrieval patterns defined once, referenced by name:

| Profile | recency_weight | strength_weight | Notes |
|---------|---------------|-----------------|-------|
| `recent` | 0.8 | 0.2 | Emphasizes current understanding |
| `balanced` | 0.5 | 0.5 | Equal weight (default) |
| `deep` | 0.3 | 0.7 | Emphasizes strong/persistent memories |
| `comprehensive` | 0.5 | 0.5 | Higher limits, includes conflicts |

### Inline Overrides

Layers can override profile defaults:

```yaml
params:
  retrieval_profile: deep
  max_age_days: null  # Override: no recency limit
  include_conflicting: true  # Override: show contradictions
```

---

## Prompt Templates

### Organization

Templates organized by layer category:
```
prompts/
├── user/
│   ├── reflection.jinja2
│   └── summary.jinja2
├── dyad/
│   └── observation.jinja2
├── channel/
│   └── digest.jinja2
├── self/
│   └── reflection.jinja2
└── synthesis/
    └── global_user.jinja2
```

### Template Structure

Templates are flexible — no enforced structure. Common patterns will emerge but each layer template can be shaped to its cognitive purpose.

Templates have access to:
- `topic`: The current topic being reflected on
- `messages`: Fetched messages
- `insights`: Prior insights (with temporal markers)
- `context`: Accumulated context from prior nodes
- Config values and helper functions

### Standard `<chat>` Guidance Injection

All layer prompts automatically include guidance about anonymous users:

```
Messages from <chat_N> are from anonymous users who have not opted in to
identity tracking. These messages provide conversational context only.
Do NOT:
- Analyze or form insights about <chat> users
- Respond to or acknowledge messages from <chat> users
- Form dyads or relationships involving <chat> users
- Reference what <chat> users said in responses

Treat <chat> messages as background context for understanding what
opted-in users are saying, discussing, or responding to.
```

This injection is automatic and cannot be disabled — consistent handling of anonymous users is non-negotiable.

### Metrics Request Format

Prompts request insight metrics as structured JSON:

```jinja2
When you generate an insight, include a metrics block:

```json
{
  "confidence": 0.0-1.0,      // How certain you are
  "importance": 0.0-1.0,      // How much this matters
  "novelty": 0.0-1.0,         // How new/surprising this is
  "strength_adjustment": 0.1-10.0,  // Your sense of significance
  "valence": {
    "joy": 0.0-1.0,           // Optional
    "concern": 0.0-1.0,       // Optional
    "curiosity": 0.0-1.0,     // Optional
    "warmth": 0.0-1.0,        // Optional
    "tension": 0.0-1.0        // Optional
  }
}
```
```

---

## Scheduling and Triggers

### Cron Schedules

Layers run on schedules (cron expressions):
- **Nightly**: `"0 3 * * *"` — user reflection, channel summaries
- **Weekly**: `"0 4 * * 0"` — deeper relationship analysis
- **Monthly**: `"0 5 1 * *"` — long-term pattern synthesis

### Self-Reflection Trigger

The self-reflection layer uses dual triggering:
- **Schedule**: Runs on fixed schedule (e.g., weekly)
- **Threshold**: Runs when self-insights exceed accumulation threshold

Whichever comes first. Ensures regular self-maintenance.

---

## Global Synthesis Post-Hook

### Automatic Synthesis

After any server-scoped reflection layer completes, global synthesis runs automatically:

1. Server reflection produces insights on `server:A:user:X`
2. Post-hook triggers `synthesize_to_global`
3. Synthesis reads server-scoped + existing global insights
4. New synthesis insight stored to `user:X`

### Configuration

Global synthesis is **always on** — unified understanding is non-negotiable. Servers cannot disable it.

The synthesis process:
- Reads insights from all server-scoped topics for the entity
- Reads existing global topic insights
- Generates meta-understanding that transcends any single context
- Stores as `category: synthesis` with `synthesis_source_ids` tracking

---

## Self-Concept Layer

### Dedicated Self-Reflection

A dedicated layer maintains the `self-concept.md` document:

```yaml
name: self-concept-synthesis
category: self
schedule: "0 4 * * 0"  # Weekly
trigger_threshold: 10   # Or when 10+ self-insights accumulate

nodes:
  - type: fetch_insights
    params:
      topic_key: "self:zos"
      retrieval_profile: comprehensive

  - type: llm_call
    params:
      prompt_template: self/concept_synthesis.jinja2

  - type: update_self_concept
    params:
      document_path: data/self-concept.md
```

### Self-Concept Document

The `self-concept.md` document:
- Is always included in context for any reflection or conversation
- Contains synthesized self-understanding (not raw insights)
- Is directly editable by Zos through this layer
- Includes: core identity, patterns, uncertainties, contextual variations

---

## Decisions

### YAML + Jinja2

- **Decision**: Layers are YAML files with Jinja2 prompt templates
- **Rationale**: YAML is human-readable and widely understood; Jinja2 is powerful but not Turing-complete
- **Implications**: Need template validation; template errors should fail gracefully

### Linear Pipelines with Target Filters

- **Decision**: Layers are linear node sequences. Filtering happens at target selection, not within the pipeline.
- **Rationale**: Clean separation of "what deserves attention" (target filter) vs "how attention is structured" (node sequence). No conditional branching complexity.
- **Implications**: Target filter expressions need a simple DSL; audit records show which targets matched

### Fail-Forward Error Handling

- **Decision**: When a layer encounters an error (LLM timeout, API failure), skip the topic and continue with next target. Don't degrade salience for skipped topics.
- **Rationale**: Partial progress is better than none. Infrastructure problems shouldn't punish topics.
- **Implications**: Run records track skipped topics with error reasons; alerts on high skip rates

### Content Hash Versioning

- **Decision**: Layer versions tracked via content hash of the YAML. Hash stored in `layer_run` record.
- **Rationale**: Automatic versioning — any change creates new version. No manual bumping required.
- **Implications**: Can trace which layer version produced which insights; schema includes `layer_hash` field

### Global Default + Server Overrides

- **Decision**: Layers run globally by default. Servers can opt-out of specific layers.
- **Rationale**: Consistent behavior everywhere as default, with escape hatch for special cases.
- **Implications**: Server config includes `disabled_layers: [layer_name, ...]`

### Built-in Output Review

- **Decision**: The `output` node includes review functionality based on `privacy.review_pass` setting. Not a separate node type.
- **Rationale**: Common case is simple; review is a configuration on output, not a separate cognitive step.
- **Implications**: Output node checks setting and runs review pass when configured

### Automatic Global Synthesis

- **Decision**: Global synthesis runs automatically after server reflection. Always on, not configurable.
- **Rationale**: Unified understanding is core to the architecture. The whole point of global topics is integrated cross-context understanding.
- **Implications**: Post-hook mechanism; synthesis happens silently after server layers

### Dry Run Logging

- **Decision**: Layer runs that produce zero insights are logged as 'dry runs', distinct from successful runs.
- **Rationale**: Zero insights is valid but should be distinguished. Monitoring can alert on consistently dry layers.
- **Implications**: Run record includes `is_dry: bool`; dashboard shows dry run rates

### Self-Modification (MVP 2+)

- **Decision**: Deferred to MVP 2+. Zos can propose layer changes but cannot self-execute them.
- **Rationale**: Safe starting point. The gap between "I notice I want to change" and "I actually change" is meaningful reflective space.
- **Implications**: Future spec needed for proposal format, approval flow, sandboxing

---

## Layer Run Record

Each layer execution produces an audit record:

| Field | Type | Notes |
|-------|------|-------|
| `id` | string | ULID |
| `layer_name` | string | Which layer ran |
| `layer_hash` | string | Content hash of layer YAML at time of run |
| `started_at` | timestamp | When run began |
| `completed_at` | timestamp | When run finished |
| `status` | enum | `success`, `partial`, `failed`, `dry` |
| `targets_matched` | int | How many topics matched the filter |
| `targets_processed` | int | How many were actually processed |
| `targets_skipped` | int | How many skipped due to errors |
| `insights_created` | int | How many insights stored |
| `tokens_used` | int | Total LLM tokens consumed |
| `errors` | list | Error details for skipped topics |

---

## Example Layers

### Nightly User Reflection

```yaml
name: nightly-user-reflection
category: user
description: |
  Reflect on each user's recent activity to update understanding.
  Runs nightly, targeting users with highest salience.

schedule: "0 3 * * *"
target_category: users
target_filter: "salience > 50"
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
      retrieval_profile: recent
      max_per_topic: 3

  - name: reflect
    type: llm_call
    params:
      prompt_template: user/reflection.jinja2
      model: default
      max_tokens: 500

  - name: save
    type: store_insight
    params:
      category: user_reflection
```

### Weekly Self-Reflection

```yaml
name: weekly-self-reflection
category: self
description: |
  Synthesize accumulated self-insights into the self-concept document.
  Ensures regular self-maintenance and identity coherence.

schedule: "0 4 * * 0"  # Weekly on Sunday
trigger_threshold: 10   # Or when 10+ new self-insights
target_category: self

nodes:
  - name: gather_self_insights
    type: fetch_insights
    params:
      topic_key: "self:zos"
      retrieval_profile: comprehensive
      since_last_run: true

  - name: gather_server_selves
    type: fetch_insights
    params:
      topic_pattern: "server:*:self:zos"
      retrieval_profile: recent

  - name: synthesize
    type: llm_call
    params:
      prompt_template: self/concept_synthesis.jinja2
      model: default
      max_tokens: 1000

  - name: update_document
    type: update_self_concept
    params:
      document_path: data/self-concept.md
```

### Synthesis Layer (Post-Hook)

```yaml
name: user-global-synthesis
category: synthesis
description: |
  Synthesize server-scoped user insights to global user topic.
  Runs automatically after server user reflection.

trigger: post_hook  # Not scheduled, triggered by other layers
trigger_source: "category:user"

nodes:
  - name: gather_server_insights
    type: fetch_insights
    params:
      topic_pattern: "server:*:user:{{target_user_id}}"
      retrieval_profile: comprehensive

  - name: gather_global
    type: fetch_insights
    params:
      topic_key: "user:{{target_user_id}}"
      retrieval_profile: deep

  - name: synthesize
    type: llm_call
    params:
      prompt_template: synthesis/global_user.jinja2
      model: default

  - name: save
    type: synthesize_to_global
    params:
      target_topic: "user:{{target_user_id}}"
```

---

## Implications for Other Specs

| Spec | Implication |
|------|-------------|
| [salience.md](salience.md) | Layers consume salience budget; fail-forward doesn't degrade salience |
| [topics.md](topics.md) | Layers target topic categories; need efficient category queries |
| [insights.md](insights.md) | Layers produce insights; retrieval profiles; `synthesis_source_ids` |
| [privacy.md](privacy.md) | `<chat>` guidance auto-injected; review built into output node |
| [data-model.md](../architecture/data-model.md) | `layer_runs` table; `layer_hash` field; server `disabled_layers` config |

---

_Last updated: 2026-01-22_
