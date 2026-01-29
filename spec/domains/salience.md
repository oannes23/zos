# Salience — Domain Specification

**Status**: 🟢 Complete
**Last interrogated**: 2026-01-23 (updated for observation integration, reaction earning, emoji topics, culture budget)
**Last verified**: —
**Depends on**: Topics (need topic keys to track salience against), Observation (reaction/media signals)
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
- **Social**: server-scoped users, dyads, user_in_channel, dyad_in_channel (30%)
- **Global**: cross-server user/dyad topics (`user:<id>`, `dyad:<a>:<b>`) (15%)
- **Spaces**: channels, threads (30%)
- **Semantic**: subjects, roles (20%)
- **Culture**: emoji topics (10%)
- **Self**: self:zos and server-specific self-topics (separate pool, doesn't compete)

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

### Continuous Propagation with Warm Threshold

- **Decision**: When a topic earns salience, related topics that are "warm" also earn a fraction (propagation_factor, configurable, default 0.3). A topic is warm if `salience > warm_threshold` (configurable, default 1.0).
- **Rationale**: Thinking about Alice-and-Bob involves thinking about Alice and Bob. But barely-noticed topics (salience = 0.001) shouldn't receive full propagation — they're effectively cold. A minimum threshold creates cleaner distinction.
- **Implications**: Need to define "related" per topic type; propagation happens on every earn; warm threshold prevents near-zero topics from participating in attention network
- **Warm threshold**: `warm_threshold` config parameter (default 1.0). Topics below this are effectively cold for propagation purposes.

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

### Global Topics Budget Group

- **Decision**: Global topics (`user:<id>`, `dyad:<a>:<b>`) have their own budget group, separate from server-scoped social topics.
- **Rationale**: Cross-server/DM reflection should have dedicated resources and not compete with server-specific understanding.
- **Implications**: New budget allocation for global group; global reflection happens independently of server reflection

### Global Topic Warming (Warm-Only Rule)

- **Decision**: Server-scoped activity only propagates to global topics if the global topic is already warm (salience > 0).
- **Rationale**: Most users will only ever be seen in one server and never DM Zos. It's wasteful to maintain global salience for users who will never benefit from cross-server understanding.
- **Warming triggers**:
  - DM activity directly earns salience for global topic
  - First activity in a *second* server triggers initial global salience earn
- **Implications**: Global topics start cold and are warmed by DM or multi-server presence; follows existing warm-only propagation pattern

### Bidirectional Global/Server Propagation

- **Decision**: DM activity propagates DOWN to all server-scoped user topics.
- **Rationale**: "Thinking about Alice in DMs makes me think about Alice everywhere." Cross-pollination of attention.
- **Implications**: Global→server propagation uses the same factor as server→global; creates feedback loop for active DM users

### Channel Salience from All Activity

- **Decision**: Channels earn salience from all messages, including from `<chat>` (anonymous) users.
- **Rationale**: A busy channel is busy regardless of who's talking. Channel salience reflects activity volume.
- **Implications**: `<chat>` messages contribute to channel salience even though `<chat>` users have no individual salience

### Quarantine and Salience

- **Decision**: When a user's insights are quarantined (lost privacy gate role), their salience continues to decay normally.
- **Rationale**: Natural forgetting. If they return much later, they start with low salience — memory has texture.
- **Implications**: No special quarantine handling in salience; decay runs as usual; topic may reach zero and be pruned from active consideration

### Independent Per-Server Pools (MVP 2+)

- **Decision**: When multi-server arrives, each server has independent salience economy.
- **Rationale**: Very active server shouldn't starve reflection on quieter servers.
- **Implications**: Server is a first-class entity in salience; cross-server effects TBD

### Reaction-Based Earning

- **Decision**: Reactions earn salience for message author, reactor, and their dyad. All three receive 0.5× base weight.
- **Rationale**: Reactions are meaningful social gestures that create relationship signal. Maximum relationship inference from minimal interaction. The author is receiving attention, the reactor is giving attention, and their relationship is strengthened.
- **Implications**: Full reaction tracking enables rich salience earning; channels also propagate from reactions

### Emoji Topic Salience

- **Decision**: Emoji topics (`server:<id>:emoji:<id>`) earn salience on each use, at 0.5× base weight. Usage propagates to the user topic.
- **Rationale**: Emojis are cultural artifacts whose significance is reflected in usage patterns. The person using an emoji is expressing themselves, so their user topic should warm.
- **Implications**: Emoji topics compete in Culture budget group; high-use emojis become reflection priorities

### Media/Link Boost

- **Decision**: Messages containing media (images, videos) or links earn 1.2× base weight.
- **Rationale**: Sharing content is a social signal — it takes more effort than plain text and often represents something the person wants others to see.
- **Implications**: `has_media` and `has_links` flags on Message enable this boost

### Culture Budget Group

- **Decision**: Create a new "Culture" budget group for emoji topics, allocated 10% of reflection budget. Reduce Social from 35% to 30% to accommodate.
- **Rationale**: Cultural artifacts deserve their own attention pool. Emojis carry meaning and understanding them enriches social understanding without competing directly with user/dyad reflection.
- **Implications**: New budget allocation; emoji reflection happens on its own cadence

### Dyad Asymmetry Metrics

- **Decision**: Dyads remain a single topic (`server:X:dyad:A:B`) with symmetric earning, but track interaction direction ratios as computed metrics.
- **Rationale**: Real relationships have asymmetry — A may seek B's attention more than B seeks A. Capturing this in metrics (rather than separate A→B and B→A topics) keeps the structure simple while enabling nuanced insights.
- **Tracked metrics**: initiator_ratio (who starts conversations), response_ratio (who responds more), reaction_ratio (who reacts to whom more)
- **Implications**: Insights can reference asymmetry patterns; no structural complexity from directional dyads

### Budget Reallocation

- **Decision**: After initial per-group selection, redistribute unused budget proportionally to groups with remaining demand.
- **Rationale**: Strict boundaries might leave compute unused if one group is underactive. Proportional reallocation maximizes reflection while preserving relative group priorities.
- **Implications**: Selection algorithm has two phases: initial allocation, then reallocation of unused capacity

### Cold Start Behavior

- **Decision**: If no topics have salience (e.g., day one), reflection produces nothing. System warms up naturally as activity accumulates.
- **Rationale**: Avoid artificial bootstrap logic. The first reflection runs when there's actually something to reflect on.
- **Implications**: Initial period will be observation-only; no special cold-start handling needed

### Edit Earning

- **Decision**: Message edits do not earn additional salience. The message earned when created; edits are refinement, not new signal.
- **Rationale**: Typo fixes and minor adjustments shouldn't boost attention. Earning should reflect meaningful new activity.
- **Implications**: `edited_at` tracking is for content updates only, not salience

### Server Focus Multiplier

- **Decision**: Each server can configure a `focus` multiplier (default 1.0) that scales all salience earning in that server.
- **Rationale**: Different communities deserve different levels of attention. A small, deeply engaged community might warrant more reflection per message than a high-volume server. Focus allows operators to tune attention allocation across servers.
- **Examples**:
  - `focus: 3.0` — A small but important community where every message should carry more weight
  - `focus: 0.5` — A high-volume server where individual messages matter less
  - `focus: 1.0` — Default, no scaling
- **Implications**: Applied at earning time before propagation; affects all earning weights uniformly; configured per-server in `ServerOverrideConfig`

### Global Dyad Warming

- **Decision**: Global dyads warm automatically when both constituent global users are warm.
- **Rationale**: Dyads can't "DM Zos" directly — the constituent users can. If `user:A` and `user:B` are both warm (from DM or multi-server activity), their relationship understanding should also be cross-server.
- **Implications**: Global dyad warming is derived from user warmth; check at propagation time

---

## Propagation Model

### What Propagates to What

#### Server-Scoped Topics

| Source Topic | Propagates To |
|--------------|---------------|
| `server:X:user:<id>` | dyads involving this user, user_in_channel for this user, **global `user:<id>` if warm** |
| `server:X:channel:<id>` | user_in_channel in this channel, threads in this channel |
| `server:X:thread:<id>` | parent channel |
| `server:X:dyad:<a>:<b>` | both server-scoped users, **global `dyad:<a>:<b>` if warm** |
| `server:X:user_in_channel` | user, channel |
| `server:X:dyad_in_channel` | dyad, channel, both users |
| `server:X:subject:<name>` | (no propagation — subjects are emergent) |
| `server:X:role:<id>` | (no propagation — roles are categorical) |
| `server:X:emoji:<id>` | user who used the emoji (emoji as self-expression) |
| `server:X:self:zos` | (no propagation — self is separate) |

#### Global Topics

| Source Topic | Propagates To |
|--------------|---------------|
| `user:<id>` | **all `server:X:user:<id>` topics** (downward), global dyads involving this user if warm |
| `dyad:<a>:<b>` | **both global `user:<id>` topics**, all `server:X:dyad:<a>:<b>` topics (downward) |
| `self:zos` | (no propagation — self is separate) |

### Global Topic Warming

Global topics start with salience = 0 (cold). They become warm when:

1. **DM activity**: Direct messages earn salience directly to `user:<id>`
2. **Second server activity**: First activity in a *second* server triggers initial earn for the global topic

Once warm, server-scoped activity propagates to global topics using `global_propagation_factor`.

### Propagation Algorithm

```python
def earn_salience(topic: Topic, amount: float, source: str = None):
    """Earn salience for a topic, with propagation to related topics."""

    # 1. Apply to primary topic (up to cap)
    overflow = 0
    if topic.salience + amount > topic.cap:
        overflow = (topic.salience + amount) - topic.cap
        topic.salience = topic.cap
    else:
        topic.salience += amount

    # 2. Normal propagation to warm related topics
    # A topic is "warm" if salience > warm_threshold (default 1.0)
    for related in get_related_topics(topic):
        if related.salience > config.warm_threshold:  # warm threshold, not just > 0
            # Use global_propagation_factor for server→global propagation
            factor = config.global_propagation_factor if is_global(related) else config.propagation_factor
            propagated = amount * factor
            earn_salience_no_propagate(related, propagated)  # no cascade

    # 3. Overflow spillover (additional, on top of normal propagation)
    if overflow > 0:
        for related in get_related_topics(topic):
            if related.salience > config.warm_threshold:
                spilled = overflow * config.spillover_factor
                earn_salience_no_propagate(related, spilled)

    # 4. Global→server downward propagation (for DM activity)
    if is_global(topic) and topic.type in ("user", "dyad"):
        for server_topic in get_server_scoped_topics(topic):
            if server_topic.salience > config.warm_threshold:  # warm threshold
                propagated = amount * config.global_propagation_factor
                earn_salience_no_propagate(server_topic, propagated)


def warm_global_topic_if_needed(user_id: str, server_id: str):
    """Warm a global user topic when seen in a second server."""
    global_topic = get_topic(f"user:{user_id}")

    if global_topic.salience > 0:
        return  # Already warm

    servers_seen = get_servers_with_activity(user_id)
    if len(servers_seen) >= 2:
        # Initial warming earn
        earn_salience(global_topic, config.initial_global_warmth)
```

### Reaction Earning Algorithm

When a reaction is observed:

```python
def earn_from_reaction(reaction: Reaction, message: Message):
    """Earn salience from a reaction. Author, reactor, dyad, channel, and emoji all earn."""

    base_amount = config.weights.reaction  # 0.5
    server_id = message.server_id

    # Apply server focus multiplier
    server_config = config.get_server_config(server_id)
    base_amount *= server_config.focus  # default 1.0

    # 1. Message author earns (attention received)
    author_topic = get_topic(f"server:{server_id}:user:{message.author_id}")
    earn_salience(author_topic, base_amount)

    # 2. Reactor earns (active engagement)
    reactor_topic = get_topic(f"server:{server_id}:user:{reaction.user_id}")
    earn_salience(reactor_topic, base_amount)

    # 3. Author-Reactor dyad earns (relationship signal)
    dyad_key = make_dyad_key(server_id, message.author_id, reaction.user_id)
    dyad_topic = get_topic(dyad_key)
    earn_salience(dyad_topic, base_amount)

    # 4. Channel propagates (handled by normal propagation from above)

    # 5. Emoji topic earns (cultural usage)
    if reaction.is_custom:
        emoji_topic = get_or_create_topic(f"server:{server_id}:emoji:{reaction.emoji}")
        earn_salience(emoji_topic, base_amount)

        # Emoji usage also propagates to reactor's user topic (emoji as self-expression)
        # This happens via propagation rules in earn_salience()
```

### Media/Link Earning

When a message with media or links is observed:

```python
def earn_from_message(message: Message):
    """Earn salience from a message, with media/link boost and server focus."""

    base_amount = config.weights.message  # 1.0

    # Apply server focus multiplier first
    server_config = config.get_server_config(message.server_id)
    base_amount *= server_config.focus  # default 1.0

    # Apply media/link boost
    if message.has_media or message.has_links:
        base_amount *= config.weights.media_boost_factor  # 1.2

    author_topic = get_topic(f"server:{message.server_id}:user:{message.author_id}")
    earn_salience(author_topic, base_amount)

    # Channel also earns directly
    channel_topic = get_topic(f"server:{message.server_id}:channel:{message.channel_id}")
    earn_salience(channel_topic, base_amount)
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
    # Server-scoped
    server_user: 100
    channel: 150
    thread: 75
    server_dyad: 80
    user_in_channel: 60
    dyad_in_channel: 50
    subject: 100
    role: 80
    emoji: 60          # Lower cap to prevent emoji spam dominance
    server_self: 150

    # Global
    global_user: 120      # Slightly higher cap for cross-server accumulation
    global_dyad: 100
    self: 200             # Global self has highest cap

  # Earning weights
  weights:
    message: 1.0
    reaction: 0.5              # Reactions are meaningful gestures (bumped from 0.3)
    mention: 2.0
    reply: 1.5
    thread_create: 2.0
    dm_message: 1.5            # DMs earn slightly more (direct engagement)
    emoji_use: 0.5             # Each emoji reaction/usage
    media_boost_factor: 1.2    # Multiplier for messages with media/links

  # Propagation
  propagation_factor: 0.3        # Normal propagation to warm related topics
  global_propagation_factor: 0.3 # Server↔global propagation (configurable separately)
  spillover_factor: 0.5          # Overflow spillover (partial, some evaporates)
  initial_global_warmth: 5.0     # Initial salience when global topic is warmed
  warm_threshold: 1.0            # Minimum salience to be considered "warm" for propagation

  # Spending and retention
  cost_per_token: 0.001    # Salience cost per LLM token
  retention_rate: 0.3      # 30% retained after spending

  # Decay
  decay_threshold_days: 7  # Days of inactivity before decay starts
  decay_rate_per_day: 0.01 # 1% per day once decay starts

  # Budget allocation per group (percentages, must sum to 1.0)
  budget:
    social: 0.30     # server-scoped users, dyads, user_in_channel, dyad_in_channel (reduced from 0.35)
    global: 0.15     # global users, global dyads
    spaces: 0.30     # channels, threads
    semantic: 0.20   # subjects, roles
    culture: 0.10    # emoji topics (new)
    # self has separate budget, not in this allocation

  # Self budget (separate pool)
  self_budget:
    daily_allocation: 50  # Fixed amount, not percentage

# Per-server overrides (in servers section of config)
servers:
  "123456789012345678":  # server_id
    focus: 1.5           # 50% boost to all salience earning in this server
  "987654321098765432":
    focus: 0.5           # Reduce salience earning for high-volume server
```

---

## Ledger Schema

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Transaction ID (ULID) |
| `topic_key` | string | yes | Which topic |
| `transaction_type` | enum | yes | `earn`, `spend`, `retain`, `decay`, `propagate`, `spillover`, `warm` |
| `amount` | float | yes | Positive for earn/retain/warm, negative for spend/decay |
| `reason` | string | no | What caused this (message_id, layer_run_id, etc.) |
| `source_topic` | string | no | For propagation/spillover: which topic triggered this |
| `created_at` | timestamp | yes | When |

### User Server Tracking

For global topic warming, track which servers a user has been seen in:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `user_id` | string | yes | Discord user ID |
| `server_id` | string | yes | Discord server ID |
| `first_seen_at` | timestamp | yes | When first activity occurred |

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
| [observation.md](observation.md) | Observation provides reaction data; media/link flags on messages |
| [topics.md](topics.md) | Topic categories map to budget groups; emoji topics in Culture group; need `get_related_topics()` for emoji→user propagation |
| [insights.md](insights.md) | Insight creation triggers salience spend; `salience_spent` field populated from this; social_texture insights for emoji culture |
| [layers.md](layers.md) | Layers use selection algorithm; need to report tokens_used for spending; Culture group needs reflection layer |
| [privacy.md](privacy.md) | `<chat>` messages contribute to channel salience; quarantined user topics decay normally; reactions from `<chat>` users not tracked individually |
| [data-model.md](../architecture/data-model.md) | Salience ledger table with full transaction history; Reaction table enables earning; has_media/has_links flags for boost |

---

## Glossary Additions

- **Culture Budget**: The 10% budget allocation for emoji topics and other cultural artifacts.
- **Reaction Earning**: When someone reacts to a message, salience is earned by the message author (attention received), reactor (active engagement), their dyad (relationship signal), and the emoji topic if custom (cultural usage).
- **Warm Threshold**: Minimum salience (default 1.0) required for a topic to be considered warm and participate in propagation.
- **Dyad Asymmetry Metrics**: Computed ratios tracking interaction direction within symmetric dyad topics.

---

_Last updated: 2026-01-23 — Added warm threshold, dyad asymmetry metrics, budget reallocation, cold start, edit earning, global dyad warming decisions_
