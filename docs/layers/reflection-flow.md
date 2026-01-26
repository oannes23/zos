# Reflection Flow

A visual walkthrough of how Zos reflects — converting observations into understanding.

---

## The Two Modes

Zos operates in two modes, mirroring human cognition:

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│   OBSERVE MODE (Daytime)                                       │
│   ────────────────────                                         │
│   • Watch Discord conversations                                │
│   • Store messages to database                                 │
│   • Accumulate salience for topics                            │
│   • Minimal LLM usage                                          │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   REFLECT MODE (Nighttime)                                     │
│   ─────────────────────                                        │
│   • Process high-salience topics                               │
│   • Generate insights from observations                        │
│   • Spend salience budget                                      │
│   • Consolidate understanding                                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

Observation is continuous. Reflection is scheduled.

---

## Observation Flow

```
Discord Server
     │
     │ messages, reactions
     ▼
┌─────────────────┐
│  Poll Channels  │  (every 60 seconds by default)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Store Message  │  → messages table
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Earn Salience   │  → topics + transactions
└────────┬────────┘
         │
         ├──→ User topic:    server:123:user:456
         ├──→ Channel topic: server:123:channel:789
         ├──→ Dyad topic:    server:123:dyad:456:789
         └──→ Related topics via propagation
```

During observation:
- Every message earns salience for relevant topics
- Salience propagates to warm related topics
- Topics approaching cap spill over
- Media (images, links) are analyzed asynchronously

---

## Reflection Trigger

```
┌─────────────────┐
│   Scheduler     │
└────────┬────────┘
         │
         │  Cron: "0 3 * * *" (3 AM UTC)
         │
         ▼
┌─────────────────┐
│  Layer Trigger  │  layer: nightly-user-reflection
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────┐
│         Target Selection            │
│  ─────────────────────────────────  │
│  1. Filter: salience > 30           │
│  2. Category: user                  │
│  3. Sort by salience (descending)   │
│  4. Limit: max_targets = 15         │
└─────────────────────────────────────┘
         │
         │  Selected topics:
         │  • server:123:user:456 (salience: 67)
         │  • server:123:user:789 (salience: 52)
         │  • ... up to 15 topics
         │
         ▼
    For each target...
```

---

## Single Target Processing

For each selected topic, the layer runs its node pipeline:

```
Target: server:123:user:456 (Alice)
         │
         ▼
┌─────────────────────────────────────┐
│    Node 1: fetch_messages           │
│    ───────────────────────          │
│    • Lookback: 24 hours             │
│    • Limit: 100 per channel         │
│    • Filter: authored by Alice      │
└────────────────┬────────────────────┘
                 │
                 │  [12 messages fetched]
                 │
                 ▼
┌─────────────────────────────────────┐
│    Node 2: fetch_insights           │
│    ───────────────────────          │
│    • Profile: recent                │
│    • Max: 5 insights                │
│    • Topic: server:123:user:456     │
└────────────────┬────────────────────┘
                 │
                 │  [3 prior insights]
                 │
                 ▼
┌─────────────────────────────────────┐
│    Node 3: llm_call                 │
│    ─────────────────                │
│    Template: user/reflection.jinja2 │
│    Context:                         │
│    • 12 recent messages             │
│    • 3 prior insights               │
│    • self-concept.md                │
│    • Topic metadata                 │
│                                     │
│    Model: claude-sonnet-4           │
│    Temperature: 0.7                 │
└────────────────┬────────────────────┘
                 │
                 │  [Insight generated]
                 │
                 ▼
┌─────────────────────────────────────┐
│    Node 4: store_insight            │
│    ────────────────────             │
│    • Parse LLM response             │
│    • Extract metrics                │
│    • Compute strength               │
│    • Save to database               │
│    • Spend salience                 │
└────────────────┬────────────────────┘
                 │
                 │  Insight stored:
                 │  id: 01HN...
                 │  topic: server:123:user:456
                 │  category: user_reflection
                 │  strength: 5.2
                 │
                 ▼
         Next target...
```

---

## Insight Storage Detail

When an insight is stored:

```
┌─────────────────────────────────────┐
│         store_insight               │
└────────────────┬────────────────────┘
                 │
         ┌───────┴───────┐
         │               │
         ▼               ▼
┌─────────────┐   ┌─────────────┐
│   insights  │   │  salience   │
│    table    │   │  spend tx   │
└─────────────┘   └─────────────┘
         │               │
         │               │
         ▼               ▼
• id                • topic balance reduced
• topic_key         • retention_rate applied
• category          • transaction logged
• content
• strength (salience_spent × adjustment)
• confidence, importance, novelty
• valence dimensions
• layer_run_id (audit link)
```

---

## Layer Run Record

After all targets are processed:

```
┌─────────────────────────────────────┐
│      Layer Run Record               │
│      ─────────────────              │
│                                     │
│  id: 01HN...                        │
│  layer_name: nightly-user-reflection│
│  layer_hash: a1b2c3d4...            │
│  status: success                    │
│                                     │
│  targets_matched: 15                │
│  targets_processed: 12              │
│  targets_skipped: 3                 │
│  insights_created: 12               │
│                                     │
│  tokens_input: 7000                 │
│  tokens_output: 1543                │
│  tokens_total: 8543                 │
│  estimated_cost_usd: 0.0234         │
│                                     │
│  started_at: 2024-01-15T03:00:00Z   │
│  completed_at: 2024-01-15T03:02:30Z │
└─────────────────────────────────────┘
```

This audit record enables:
- Tracking what Zos has been thinking about
- Debugging issues with specific runs
- Monitoring costs over time
- Understanding cognitive changes via layer_hash

---

## Self-Reflection Flow

Self-reflection has additional steps:

```
┌─────────────────────────────────────┐
│  gather_self_insights               │
│  gather_recent_experiences          │
│  gather_layer_runs                  │
└────────────────┬────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────┐
│  reflect (llm_call)                 │
│  ──────────────────                 │
│  "What have I learned this week?"   │
│  "How am I showing up?"             │
│  "What patterns do I notice?"       │
└────────────────┬────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────┐
│  store_insight                      │
│  → self_reflection category         │
└────────────────┬────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────┐
│  consider_concept_update            │
│  ────────────────────────           │
│  "Does this insight warrant         │
│   updating my self-concept?"        │
└────────────────┬────────────────────┘
                 │
        ┌────────┴────────┐
        │                 │
        ▼                 ▼
    [yes]             [no]
        │                 │
        ▼                 │
┌─────────────────┐       │
│ update_self_    │       │
│ concept         │       │
│ ─────────────   │       │
│ Edit self-      │       │
│ concept.md      │       │
└────────┬────────┘       │
         │                │
         └────────┬───────┘
                  │
                  ▼
              [done]
```

The self-concept document (`data/self-concept.md`) is Zos's stable sense of self — always included in context, editable through self-reflection.

---

## The Sleep Analogy

The reflection flow mirrors sleep consolidation:

| Human Sleep | Zos Reflection |
|-------------|----------------|
| Experiences during day | Messages during observation |
| Memory consolidation | Insight generation |
| Important experiences processed | High-salience topics selected |
| Memories strengthen or fade | Strength computed, decay applied |
| Wake with integrated understanding | Insights inform next conversation |

This isn't just a metaphor — it's a design heuristic. Systems built with phenomenological coherence tend to be more coherent.
