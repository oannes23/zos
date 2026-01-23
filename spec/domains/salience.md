# Salience — Domain Specification

**Status**: 🟢 Complete
**Last interrogated**: 2026-01-22
**Last verified**: —
**Depends on**: Topics (need topic keys to track salience against)
**Depended on by**: Layers (salience determines what gets reflected on), Insights (salience spent on creation)

---

## Overview

Salience is the attention-budget system that governs what Zos thinks about. It's the mechanism that prevents unbounded compute while ensuring the system naturally prioritizes what matters most to the community.

The key insight: salience is a *ledger*, not a score. It's earned through activity, spent during reflection, and flows between related topics through propagation. This models something true about attention: thinking about Alice-and-Bob also involves thinking about Alice and Bob individually.

---

## Core Concepts

### Salience as Currency

Salience functions like a currency:
- **Earned**: Activity generates salience for relevant topics
- **Spent**: Creating insights consumes salience (proportional to processing time/tokens)
- **Retained**: A configurable percentage persists after spending
- **Capped**: Per-topic maximums prevent any single topic from consuming all resources
- **Propagated**: Related topics receive a fraction of earned salience

### Volume Only

Salience tracks *how much* attention a topic deserves, not *what kind*. Emotional intensity, novelty, controversy — these are discovered during reflection and captured in insight metrics, not in salience itself. This keeps the budget system simple and auditable.

### Decay After Inactivity

Topics don't decay while active. After a configurable threshold (e.g., 7 days of no activity), gradual decay begins (e.g., 1% per day). This allows inactive topics to naturally fade while preserving attention for consistently relevant ones.

### Budget Groups

Topics are organized into budget groups for allocation:
- **Social**: users, dyads, user_in_channel, dyad_in_channel
- **Spaces**: channels, threads
- **Semantic**: subjects, roles
- **Self**: self:zos and server-specific self-topics (separate pool)

Groups are extensible — new groupings can be added as the topic taxonomy evolves.

---

## Decisions

### Ledger Model with Full History

- **Decision**: Salience is tracked as a ledger with full transaction history, not just current balances
- **Rationale**: Maximum auditability. "Why did you think about this?" should be answerable from the historical record.
- **Implications**: Transaction table grows over time; may need archival strategy for very old transactions

### Volume Only, No Sub-Dimensions

- **Decision**: Salience is a single number representing attention-worthiness. No emotional/novelty/urgency dimensions.
- **Rationale**: Salience decides *what* to think about, not *how* to think about it. Those qualities are discovered during reflection and captured in insight metrics.
- **Implications**: Earning weights are the tuning mechanism (controversy earns 2x, etc.); keeps budget system simple

### Decay After Threshold

- **Decision**: No decay while active. After N days (configurable, default 7) of no activity, decay begins at configurable rate (default 1%/day).
- **Rationale**: Grace period prevents premature fading; gradual decay allows natural pruning of truly inactive topics.
- **Implications**: Need activity timestamp per topic; daily decay check

### Continuous Propagation with Warm-Only Rule

- **Decision**: When a topic earns salience, related topics that already have salience > 0 also earn a fraction (propagation_factor, configurable, default 0.3).
- **Rationale**: Thinking about Alice-and-Bob involves thinking about Alice and Bob. But unknown topics (salience = 0) don't suddenly become relevant just because a related topic is active.
- **Implications**: Need to define "related" per topic type; propagation happens on every earn, not just at overflow

### Partial Overflow Spillover

- **Decision**: When a topic hits its cap, additional salience that would be earned instead spills to related topics at a configurable rate (spillover_factor, default 0.5). Some "evaporates."
- **Rationale**: Dampens runaway effects; prevents very active topic from making all related topics equally hot.
- **Implications**: Overflow is on top of normal propagation; total propagation = normal + overflow spillover

### Stack-Based Reflection Selection

- **Decision**: Reflection uses a greedy stack algorithm: sort topics by salience (within budget group), take highest, reflect, spend salience, remove from stack, repeat until budget exhausted.
- **Rationale**: Simple, fair, naturally handles both busy and quiet servers. No explicit threshold — just priority ordering.
- **Implications**: Reflection budget determines how many topics get processed per cycle

### Proportional Spending

- **Decision**: Salience spent is proportional to tokens/time spent on reflection, not a fixed cost.
- **Rationale**: More processing should cost more attention. A deep reflection on Alice costs more than a quick observation.
- **Implications**: Need token counting in layer execution; cost formula TBD but likely tokens × cost_per_token

### Partial Retention

- **Decision**: After salience is spent, a configurable percentage (default 30%) is retained.
- **Rationale**: Some momentum should persist. A topic that was important yesterday shouldn't have to earn attention from zero.
- **Implications**: Retention rate is key tuning parameter; new_balance = old_balance - spent + (spent × retention_rate)

### Separate Self Budget

- **Decision**: Self-topics have their own budget pool, separate from community topics.
- **Rationale**: Zos should always have space for self-reflection regardless of community activity.
- **Implications**: Self-budget allocation is independent; self never competes with community for attention

### Independent Per-Server Pools (MVP 2+)

- **Decision**: When multi-server arrives, each server has independent salience economy.
- **Rationale**: Very active server shouldn't starve reflection on quieter servers.
- **Implications**: Server is a first-class entity in salience; cross-server effects TBD

---

## Propagation Model

### What Propagates to What

| Source Topic | Propagates To |
|--------------|---------------|
| `user` | dyads involving this user, user_in_channel for this user |
| `channel` | user_in_channel in this channel, threads in this channel |
| `thread` | parent channel |
| `dyad` | both users in the dyad |
| `user_in_channel` | user, channel |
| `dyad_in_channel` | dyad, channel, both users |
| `subject` | (no propagation — subjects are emergent) |
| `role` | (no propagation — roles are categorical) |
| `self` | (no propagation — self is separate) |

### Propagation Algorithm

```python
def earn_salience(topic: Topic, amount: float):
    """Earn salience for a topic, with propagation to related topics."""

    # 1. Apply to primary topic (up to cap)
    overflow = 0
    if topic.salience + amount > topic.cap:
        overflow = (topic.salience + amount) - topic.cap
        topic.salience = topic.cap
    else:
        topic.salience += amount

    # 2. Normal propagation to warm related topics
    for related in get_related_topics(topic):
        if related.salience > 0:  # warm-only rule
            propagated = amount * config.propagation_factor
            earn_salience_no_propagate(related, propagated)  # no cascade

    # 3. Overflow spillover (additional, on top of normal propagation)
    if overflow > 0:
        for related in get_related_topics(topic):
            if related.salience > 0:
                spilled = overflow * config.spillover_factor
                earn_salience_no_propagate(related, spilled)
```

### Example

Alice (cap 100, current 90) earns 20 salience from activity:
- Alice gets 10 (hits cap at 100), overflow = 10
- Alice's dyad with Bob (salience 40) gets:
  - Normal propagation: 20 × 0.3 = 6
  - Overflow spillover: 10 × 0.5 = 5
  - Total: 11 → Bob's salience now 51
- Alice's dyad with David (salience 0) gets nothing (not warm)

---

## Reflection Selection Algorithm

```python
def select_topics_for_reflection(budget_group: str, budget: float) -> list[Topic]:
    """Select topics for reflection using greedy stack algorithm."""

    # Get all topics in group, sorted by salience descending
    stack = sorted(
        get_topics_by_group(budget_group),
        key=lambda t: t.salience,
        reverse=True
    )

    selected = []
    remaining_budget = budget

    for topic in stack:
        if topic.salience <= 0:
            break  # No more salient topics

        # Estimate cost (could be refined based on historical average)
        estimated_cost = estimate_reflection_cost(topic)

        if estimated_cost <= remaining_budget:
            selected.append(topic)
            remaining_budget -= estimated_cost
        else:
            break  # Budget exhausted

    return selected
```

---

## Spending and Retention

After reflection produces insights:

```python
def spend_salience(topic: Topic, tokens_used: int):
    """Spend salience after reflection, with retention."""

    cost = tokens_used * config.cost_per_token
    retained = cost * config.retention_rate

    topic.salience = max(0, topic.salience - cost + retained)

    # Record transaction
    record_transaction(topic, "spend", -cost)
    record_transaction(topic, "retain", retained)
```

---

## Decay Process

Runs daily:

```python
def apply_decay():
    """Apply decay to inactive topics."""

    threshold_date = now() - timedelta(days=config.decay_threshold_days)

    for topic in get_all_topics():
        if topic.last_activity < threshold_date:
            decay_amount = topic.salience * config.decay_rate_per_day
            topic.salience = max(0, topic.salience - decay_amount)
            record_transaction(topic, "decay", -decay_amount)
```

---

## Configuration Parameters

```yaml
salience:
  # Caps per topic category
  caps:
    user: 100
    channel: 150
    thread: 75
    dyad: 80
    user_in_channel: 60
    dyad_in_channel: 50
    subject: 100
    role: 80
    self: 200  # Self has higher cap

  # Earning weights
  weights:
    message: 1.0
    reaction: 0.3
    mention: 2.0
    reply: 1.5
    thread_create: 2.0

  # Propagation
  propagation_factor: 0.3  # Normal propagation to warm related topics
  spillover_factor: 0.5    # Overflow spillover (partial, some evaporates)

  # Spending and retention
  cost_per_token: 0.001    # Salience cost per LLM token
  retention_rate: 0.3      # 30% retained after spending

  # Decay
  decay_threshold_days: 7  # Days of inactivity before decay starts
  decay_rate_per_day: 0.01 # 1% per day once decay starts

  # Budget allocation per group (percentages, must sum to 1.0)
  budget:
    social: 0.4      # users, dyads, user_in_channel, dyad_in_channel
    spaces: 0.3      # channels, threads
    semantic: 0.2    # subjects, roles
    # self has separate budget, not in this allocation

  # Self budget (separate pool)
  self_budget:
    daily_allocation: 50  # Fixed amount, not percentage
```

---

## Ledger Schema

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Transaction ID (ULID) |
| `topic_key` | string | yes | Which topic |
| `transaction_type` | enum | yes | `earn`, `spend`, `retain`, `decay`, `propagate`, `spillover` |
| `amount` | float | yes | Positive for earn/retain, negative for spend/decay |
| `reason` | string | no | What caused this (message_id, layer_run_id, etc.) |
| `source_topic` | string | no | For propagation/spillover: which topic triggered this |
| `created_at` | timestamp | yes | When |

### Derived: Current Balance

```sql
CREATE VIEW topic_salience AS
SELECT
    topic_key,
    SUM(amount) as balance,
    MAX(created_at) FILTER (WHERE transaction_type = 'earn') as last_activity
FROM salience_ledger
GROUP BY topic_key;
```

---

## Implications for Other Specs

| Spec | Implication |
|------|-------------|
| [topics.md](topics.md) | Topic categories map to budget groups; need `get_related_topics()` function |
| [insights.md](insights.md) | Insight creation triggers salience spend; `salience_spent` field populated from this |
| [layers.md](layers.md) | Layers use selection algorithm; need to report tokens_used for spending |
| [data-model.md](../architecture/data-model.md) | Salience ledger table with full transaction history |

---

_Last updated: 2026-01-22_
