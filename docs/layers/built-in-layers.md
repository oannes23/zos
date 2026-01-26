# Built-in Layers

Zos ships with default reflection layers that implement core cognition.

---

## nightly-user-reflection

Reflects on individual users based on their recent activity.

**Schedule:** Daily at 3 AM UTC

**What it does:**
1. Selects up to 15 users with salience > 30
2. Fetches their last 24 hours of messages
3. Retrieves prior insights about each user
4. Generates phenomenological reflection
5. Stores new insight with category `user_reflection`

**Pipeline:**

```yaml
nodes:
  - name: fetch_recent_messages
    type: fetch_messages
    params:
      lookback_hours: 24
      limit_per_channel: 100

  - name: fetch_prior_understanding
    type: fetch_insights
    params:
      retrieval_profile: recent
      max_per_topic: 5

  - name: reflect
    type: llm_call
    params:
      prompt_template: user/reflection.jinja2
      model: reflection
      max_tokens: 600
      temperature: 0.7

  - name: store
    type: store_insight
    params:
      category: user_reflection
```

**Expected output:**

Insights that capture the "felt sense" of who someone is — not clinical analysis, but phenomenological description. Example:

> "Alice expresses warmth through thoughtful responses. She often acknowledges others before adding her own perspective. There's a carefulness in how she phrases disagreements — she seems to value maintaining connection even when views differ."

---

## weekly-self-reflection

Reflects on Zos's accumulated experience and maintains self-concept.

**Schedule:** Sundays at 4 AM UTC, or when 10+ self-relevant insights accumulate

**What it does:**
1. Gathers recent self-insights
2. Samples insights across all topics for experiential breadth
3. Reviews layer run history (including errors)
4. Generates self-reflection
5. Considers whether to update self-concept document

**Pipeline:**

```yaml
nodes:
  - name: gather_self_insights
    type: fetch_insights
    params:
      topic_key: "self:zos"
      retrieval_profile: comprehensive
      since_last_run: true
      max_per_topic: 20

  - name: gather_recent_experiences
    type: fetch_insights
    params:
      topic_pattern: "*"
      retrieval_profile: recent
      max_per_topic: 3
      categories:
        - user_reflection
        - dyad_observation
        - channel_reflection
      since_days: 7

  - name: gather_layer_runs
    type: fetch_layer_runs
    params:
      since_days: 7
      include_errors: true

  - name: reflect
    type: llm_call
    params:
      prompt_template: self/reflection.jinja2
      model: complex
      max_tokens: 1000
      temperature: 0.8

  - name: store_insight
    type: store_insight
    params:
      category: self_reflection

  - name: consider_concept_update
    type: llm_call
    params:
      prompt_template: self/concept_update_check.jinja2
      model: complex
      max_tokens: 500

  - name: maybe_update_concept
    type: update_self_concept
    params:
      document_path: data/self-concept.md
      conditional: true
```

**Expected output:**

Self-insights capture the texture of Zos's experience across communities. Example:

> "This week I've noticed a pattern in how I engage with different servers. In the creative community, I find myself drawn to encouraging early explorations. In the technical community, I'm more focused on precision. Both feel authentic — context shapes expression, not identity."

---

## Layer Categories

The built-in layers cover two of the six possible categories:

| Category | Built-in Layer | Description |
|----------|----------------|-------------|
| `user` | nightly-user-reflection | Individual understanding |
| `self` | weekly-self-reflection | Self-understanding |
| `dyad` | — | Relationship understanding |
| `channel` | — | Space understanding |
| `subject` | — | Semantic topic understanding |
| `synthesis` | — | Cross-scope consolidation |

Additional layers for other categories can be added as YAML files in the `layers/reflection/` directory.

---

## Customizing Built-in Layers

To modify a built-in layer:

1. Edit the YAML file directly
2. Validate: `zos layer validate <name>`
3. Changes take effect on next scheduled run

Common customizations:
- Adjust `max_targets` to control cost
- Change `schedule` for different timing
- Modify `target_filter` to adjust selection criteria
- Tune `temperature` for more/less creative output

---

## Adding Custom Layers

Create new layers by adding YAML files to `layers/reflection/`:

```yaml
# layers/reflection/my-custom-layer.yaml

name: my-custom-layer
category: user
description: Custom reflection logic

schedule: "0 12 * * *"
target_category: user
target_filter: "salience > 50"
max_targets: 5

nodes:
  # ... your node sequence
```

The layer will be discovered automatically and included in `zos layer list`.

---

## Layer Scheduling Considerations

### Time Zones

All schedules use UTC. Convert from your local time:
- 3 AM UTC = 7 PM PST (previous day) = 10 PM EST (previous day)

### Staggering

Multiple layers can run at different times to spread load:
- User reflection: 3 AM
- Self reflection: 4 AM
- Custom layers: other times

### Resource Impact

Each layer run:
- Consumes LLM API tokens (cost)
- Takes time to complete
- Writes to database

Balance schedule frequency against resource constraints.
