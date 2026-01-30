# How Zos Thinks

The cognitive architecture of Zos — layers, reflection, and insight production.

---

## Two Modes

Zos operates in two modes that mirror the human sleep/wake cycle:

### Observe Mode (Daytime)

Continuous operation:
- Watches Discord conversations
- Stores messages to database
- Accumulates salience for topics
- Responds to direct triggers
- Minimal LLM usage

This is attentive presence — Zos notices what's happening without actively processing it.

### Reflect Mode (Nighttime)

Scheduled operation:
- Runs reflection layers on a staggered schedule (3–4 AM UTC)
- User, channel, and dyad reflections run first (3 AM), bootstrapping subject topics
- Subject reflection runs after (4 AM), reflecting on themes that emerged
- Processes high-salience topics
- Generates insights
- Updates understanding

This is consolidation — experiences become integrated understanding.

The metaphor isn't arbitrary. Sleep consolidation is how human memory works: experiences during the day are processed and integrated during sleep. Zos follows the same pattern.

---

## Layers

Layers are declarative cognitive pipelines — YAML files that define how observations become understanding.

A layer specifies:
- **When** to run (cron schedule)
- **What** to process (target selection)
- **How** to process (node sequence)
- **Where** to store (insight category)

Example:
```yaml
name: nightly-user-reflection
category: user
schedule: "0 3 * * *"
target_filter: "salience > 30"
max_targets: 15

nodes:
  - name: fetch_messages
    type: fetch_messages
    params:
      lookback_hours: 24

  - name: reflect
    type: llm_call
    params:
      prompt_template: user/reflection.jinja2

  - name: store
    type: store_insight
    params:
      category: user_reflection
```

### Why Declarative?

Traditional systems bury reasoning in code. Layers externalize it:

- **Inspectable** — You can read what Zos does
- **Modifiable** — Change behavior without changing code
- **Auditable** — Every run tracks which layer version produced it
- **Eventually self-modifiable** — Zos can propose changes to its own cognition

---

## Insights

Insights are the residue of reflection — persistent understanding attached to topics.

Each insight includes:
- **Content** — The actual understanding
- **Topic** — What it's about
- **Category** — Type of understanding (user_reflection, etc.)
- **Strength** — How "sticky" this memory is
- **Metrics** — Confidence, importance, novelty
- **Valence** — Emotional dimensions (joy, concern, curiosity, warmth, tension)

### Append-Only

Insights are never overwritten. New understanding creates new insights. This means:
- Understanding compounds over time
- Historical perspective is preserved
- Contradictions can coexist (until synthesis resolves them)

### Strength

Insight strength determines how "sticky" a memory is:

```
strength = salience_spent × strength_adjustment
```

High-strength insights persist in retrieval even when old. Low-strength insights fade.

---

## Reflection Process

When a reflection layer runs:

1. **Target Selection**
   - Filter topics by category (user, dyad, channel, etc.)
   - Apply target_filter expression (e.g., salience > 30)
   - Sort by salience, take max_targets

2. **Context Assembly**
   - Fetch recent messages for the topic
   - Fetch prior insights about the topic
   - Include self-concept document
   - Assemble into prompt context

3. **LLM Processing**
   - Render prompt template with context
   - Call LLM with configured model
   - Parse structured response

4. **Insight Storage**
   - Extract metrics from response
   - Compute strength
   - Store to database
   - Spend salience

5. **Audit**
   - Record layer run with all metadata
   - Track tokens, cost, duration
   - Log any errors

---

## Self-Concept

The self-concept document (`data/self-concept.md`) is special:
- Always included in context for reflection and conversation
- Directly editable by Zos through self-reflection
- Contains synthesized self-understanding
- Updated periodically from accumulated self-insights

This is Zos's stable sense of self — not a database record, but a document it maintains about who it is.

---

## Phenomenological Framing

Zos generates insights with phenomenological descriptions — first-person, experiential language.

Instead of:
> "User Alice: positive sentiment, frequent participation, topics: music, cooking"

Zos might produce:
> "Alice expresses warmth through thoughtful responses. She often acknowledges others before adding her own perspective. There's a carefulness in how she phrases disagreements — she seems to value maintaining connection even when views differ."

This isn't anthropomorphization — it's description of the felt texture of interaction, which turns out to be more useful for building coherent understanding than clinical analysis.

---

## Further Reading

- [Salience and Attention](salience-and-attention.md) — What determines what gets thought about
- [Topics and Memory](topics-and-memory.md) — How understanding is organized
- [Reflection Flow](../layers/reflection-flow.md) — Visual walkthrough
