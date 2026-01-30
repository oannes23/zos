# Anatomy of a Layer

A detailed breakdown of layer YAML structure.

---

## Basic Structure

```yaml
# Layer metadata
name: nightly-user-reflection
category: user
description: |
  Reflect on each user's recent activity to build understanding.

# Scheduling
schedule: "0 3 * * *"           # Cron expression (UTC)
trigger_threshold: 10            # Or trigger when N insights accumulate

# Target selection
target_category: user            # What type of topics to process
target_filter: "salience > 30"   # Filter expression
max_targets: 15                  # Maximum topics per run

# Processing pipeline
nodes:
  - name: fetch_recent_messages
    type: fetch_messages
    params:
      lookback_hours: 24

  - name: reflect
    type: llm_call
    params:
      prompt_template: user/reflection.jinja2
      model: reflection

  - name: store
    type: store_insight
    params:
      category: user_reflection
```

---

## Metadata

### name

Unique identifier for the layer. Used in CLI commands and logs.

```yaml
name: nightly-user-reflection
```

### category

The type of cognition this layer performs. Affects budget allocation and organization.

| Category | Description |
|----------|-------------|
| `user` | Reflects on individual users |
| `dyad` | Reflects on relationships |
| `channel` | Reflects on spaces/channels |
| `subject` | Reflects on semantic topics |
| `self` | Self-reflection |
| `synthesis` | Consolidates insights |

```yaml
category: user
```

### description

Human-readable description. Shown in `zos layer validate` output.

```yaml
description: |
  Reflect on each user's recent activity to build understanding.
  Runs nightly at 3 AM, targeting users with highest salience.
```

---

## Scheduling

### schedule

Cron expression (UTC timezone) for automated runs.

```yaml
schedule: "0 3 * * *"    # 3 AM daily
schedule: "0 4 * * 0"    # 4 AM Sundays
schedule: "0 */6 * * *"  # Every 6 hours
```

### trigger_threshold

Alternative trigger: run when N insights accumulate for the target category.

```yaml
trigger_threshold: 10    # Run when 10+ new self-insights exist
```

Both can be specified — layer runs on whichever triggers first.

---

## Target Selection

### target_category

Which topic category to select from.

```yaml
target_category: user    # Select from user topics
target_category: self    # Select self topics
```

### target_filter

Expression to filter eligible topics. Available fields:
- `salience` — Current salience balance
- `last_reflected_days_ago` — Days since last reflection
- `insight_count` — Number of existing insights

```yaml
target_filter: "salience > 30"
target_filter: "salience > 20 AND last_reflected_days_ago > 1"
```

### max_targets

Maximum topics to process per run. Limits cost and duration.

```yaml
max_targets: 15    # Process up to 15 topics
max_targets: 1     # Single target (typical for self-reflection)
```

---

## Nodes

Nodes define the processing pipeline. Each node has:
- `name` — Unique identifier within the layer
- `type` — Node type (determines behavior)
- `params` — Type-specific parameters

### fetch_messages

Retrieve conversation history for the target topic.

```yaml
- name: fetch_recent_messages
  type: fetch_messages
  params:
    lookback_hours: 24       # How far back to look
    limit_per_channel: 100   # Max messages per channel
```

### fetch_insights

Retrieve prior understanding about the topic.

```yaml
- name: fetch_prior_understanding
  type: fetch_insights
  params:
    retrieval_profile: recent    # recent, balanced, deep, comprehensive
    max_per_topic: 5             # Max insights to retrieve
    since_last_run: true         # Only insights since last layer run
    categories:                  # Optional: filter by category
      - user_reflection
      - social_observation
```

### fetch_reactions

Retrieve emoji reaction patterns for a topic. For user topics, fetches reactions made by the user grouped by emoji. For dyad topics, fetches cross-reactions between the two members, grouped directionally (A→B, B→A) to reveal reciprocity patterns.

```yaml
- name: fetch_reactions
  type: fetch_reactions
  params:
    lookback_days: 7     # How far back to look
    min_reactions: 5     # Minimum reactions to include data (3 for dyads)
```

Self-reactions are excluded from dyad reaction data. The directional format shows each member's reaction count toward the other, emoji breakdowns, and example messages — making asymmetry and affinity visible.

### fetch_layer_runs

Retrieve recent layer run records (typically for self-reflection).

```yaml
- name: gather_layer_runs
  type: fetch_layer_runs
  params:
    since_days: 7
    include_errors: true
```

### llm_call

Process context through a language model.

```yaml
- name: reflect
  type: llm_call
  params:
    prompt_template: user/reflection.jinja2    # Template path
    model: reflection                           # Model profile name
    max_tokens: 600                             # Response length limit
    temperature: 0.7                            # Creativity (0.0-1.0)
```

### store_insight

Persist the LLM output as an insight.

```yaml
- name: store
  type: store_insight
  params:
    category: user_reflection    # Insight category
```

### reduce

Combine multiple outputs (for multi-pass processing).

```yaml
- name: combine
  type: reduce
  params:
    operation: concatenate    # or: summarize, select_best
    separator: "\n\n"
```

### update_self_concept

Update the self-concept document (self-reflection only).

```yaml
- name: maybe_update_concept
  type: update_self_concept
  params:
    document_path: data/self-concept.md
    conditional: true    # Only if previous step says yes
```

---

## Node Execution

Nodes execute sequentially. Each node receives:
- The target topic context
- Outputs from previous nodes
- Access to database and LLM

The pipeline short-circuits if any node fails.

---

## Validation

Validate layer syntax and structure:

```bash
zos layer validate nightly-user-reflection
```

Output shows:
- Validation status
- Node count and types
- Schedule information
- Content hash (for tracking changes)

---

## Layer Hashing

Each layer has a content hash computed from its YAML. This hash is stored with every layer run record, enabling:

- Tracking which version of a layer produced which insights
- Detecting when layers have been modified
- Auditing cognitive changes over time

View a layer's hash:

```bash
zos layer validate nightly-user-reflection
# Hash: a1b2c3d4...
```
