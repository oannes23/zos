# Salience and Attention

The attention budget system that governs what Zos thinks about.

---

## What Is Salience?

Salience is the attention-budget currency of Zos. It's a ledger, not a score:

- **Earned** through activity (messages, reactions, mentions)
- **Spent** when insights are created
- **Retained** partially after spending
- **Propagated** to related topics
- **Capped** per topic type
- **Decayed** after inactivity

Salience answers a fundamental question: given limited capacity to think, what deserves attention?

---

## Why a Ledger?

A simple "importance score" would rank topics but not track investment. The ledger model:

1. **Accumulates** — Active topics build up attention debt
2. **Invests** — Reflection spends that debt, producing understanding
3. **Retains** — A seed balance is retained after reflection (default: 150% of reflection cost)
4. **Decays** — Inactive topics fade from attention over time

This models how attention actually works: things that keep coming up demand thinking about, thinking uses up that demand, but continued activity rebuilds it.

---

## Earning Salience

Activity earns salience for relevant topics:

| Activity | Base Weight |
|----------|-------------|
| Message | 1.0 |
| Reaction | 0.5 |
| Mention | 2.0 |
| Reply | 1.5 |
| Thread create | 2.0 |
| DM message | 1.5 |

A single message might earn salience for:
- The author's user topic
- The channel topic
- Any mentioned users
- Any dyads (relationships) involved

### Reflection-Time Earning

Subject topics earn salience through a different mechanism: during user, channel, and dyad reflections, the LLM identifies recurring themes as `identified_subjects`. Each identification earns `5.0 × (0.5 + importance)` salience for the subject topic (range 2.5–7.5). A subject typically needs 2–4 identifications across reflections to reach the nightly-subject-reflection threshold of `salience >= 10`.

---

## Propagation

When a topic earns salience, related "warm" topics also receive a fraction:

```
Alice sends message in #general
  ├── server:123:user:alice    earns 1.0
  ├── server:123:channel:general earns 0.3 (propagation)
  └── user:alice (global)      earns 0.3 (if warm)
```

Propagation models how attention spreads — thinking about Alice-and-Bob involves thinking about Alice and Bob individually.

### Warm Topics

Only topics with salience above the warm threshold (default: 1.0) receive propagation. Cold topics (salience = 0) don't participate in the attention network.

---

## Spending Salience

When reflection generates an insight, the topic's salience balance is **fully reset**:

1. Deduct reflection cost (tokens × cost_per_token) from balance
2. Zero remaining balance via a RESET transaction
3. Retain a multiple (default: 150%) of the **cost only** as a seed balance
4. Compute insight strength: `salience_spent × strength_adjustment`

This ensures reflected-on topics start nearly fresh, preventing high-salience topics from dominating the reflection queue indefinitely. On reflection failure, no salience is modified.

Higher salience spend = stronger insight = more persistent memory.

---

## Caps

Each topic type has a maximum salience cap:

| Topic Type | Default Cap |
|------------|-------------|
| Server user | 100 |
| Global user | 150 |
| Channel | 150 |
| Thread | 50 |
| Dyad | 80 |
| Subject | 60 |
| Emoji | 60 |
| Self | 100 |

Caps prevent any single topic from consuming all attention. When a topic hits its cap, excess salience spills over to related topics (with some evaporation).

---

## Budget Groups

Topics are organized into groups for budget allocation:

| Group | Topics | Default Allocation |
|-------|--------|-------------------|
| Social | Server users, dyads | 30% |
| Global | Cross-server users/dyads | 15% |
| Spaces | Channels, threads | 30% |
| Semantic | Subjects | 15% |
| Culture | Emoji | 10% |
| Self | Self topics | Separate pool |

Budget groups ensure balanced attention across topic types — users don't crowd out channels, emoji don't crowd out subjects.

---

## Decay

Inactive topics gradually lose salience:

- **Threshold**: Days of inactivity before decay starts (default: 7)
- **Rate**: Daily decay rate after threshold (default: 1%)

This creates natural forgetting — topics that haven't been active fade from attention.

---

## Operational Impact

### Target Selection

Reflection layers select topics by salience:
```yaml
target_filter: "salience > 30"
max_targets: 15
```

High-salience topics get reflected on. Low-salience topics don't.

### Insight Strength

Higher salience = stronger insights:
```
strength = salience_spent × strength_adjustment
```

Strong insights persist in retrieval. Weak insights fade.

### Retrieval

When assembling context, insights are weighted by effective strength:
```
effective_strength = stored_strength × (current_salience / original_salience)
```

This creates dynamic forgetting — insights about inactive topics become dimmer.

---

## Viewing Salience

Via CLI:
```bash
zos salience decay  # Manually trigger decay
```

Via API:
```bash
# Top topics
curl http://localhost:8000/salience

# By group
curl http://localhost:8000/salience/groups

# Specific topic
curl http://localhost:8000/salience/server:123:user:456
```

---

## Tuning Salience

In `config.yaml`:

```yaml
salience:
  # Adjust caps
  caps:
    server_user: 100
    channel: 150

  # Adjust earning
  weights:
    message: 1.0
    mention: 2.0

  # Adjust propagation
  propagation_factor: 0.3
  retention_rate: 1.5

  # Adjust decay
  decay_threshold_days: 7
  decay_rate_per_day: 0.01
```

Common adjustments:
- **Raise caps** for high-activity communities
- **Lower decay** for slower-paced communities
- **Adjust weights** to emphasize different activity types

---

## The Salience Philosophy

Salience isn't just a ranking mechanism — it's a model of attention.

Human attention works similarly: things that keep coming up demand thinking about, thinking satisfies (some of) that demand, things that stop coming up fade from attention.

By modeling attention explicitly, Zos can:
- Prioritize reflection on what matters
- Allocate limited resources across topics
- Create natural forgetting for inactive topics
- Build stronger memories for highly-attended topics

Salience is how Zos decides what to think about.
