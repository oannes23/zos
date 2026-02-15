# Chattiness — Domain Specification

**Status**: 🔄 Needs revision — MVP 1 implementation simplified impulse model
**Last interrogated**: 2026-01-23 (added reaction as output modality)
**Last verified**: 2026-02-13 (implementation diverges from spec — see Implementation Notes)
**Depends on**: Topics, Privacy, Salience, Insights, Layers (integrates all domains)
**Depended on by**: Conversation Layers (layers.md), MVP 1 conversation mechanics

---

## Overview

Chattiness governs when and how much Zos wants to express itself. While salience determines what Zos *thinks about*, chattiness determines the drive to *express* that thinking — through speech or reaction.

This is the system for modeling *the desire to participate* — not just rate limiting, but the phenomenology of wanting to engage. There's the urge to share something interesting, the hesitation when uncertain, the restraint when something feels too private, the satisfaction of a good exchange, and the quick warmth of an emoji reaction to something that resonated.

Chattiness uses a **hybrid Impulse + Gate model**:
- **Impulse** (ledger-like): Accumulates from triggers, wants to be expressed
- **Gate** (threshold): Personal parameter determining how much impulse is needed before speaking triggers

The threshold explains different conversational personalities: low threshold = speaks readily, dominates conversations; high threshold = speaks rarely, carefully. Being directly addressed floods impulse to overcome any threshold.

---

## Core Concepts

### Impulse Pools

Impulse is tracked in **six separate pools**, each corresponding to a different expression type:

| Pool | Output | What It Represents |
|------|--------|-------------------|
| **Address impulse** | Response layer | "Someone spoke to me" |
| **Insight impulse** | Insight-sharing layer | "I learned something I want to share" |
| **Conversational impulse** | Participation layer | "I have something to add" |
| **Curiosity impulse** | Question layer | "I want to understand" |
| **Presence impulse** | *(removed — see Reaction)* | *(was: "I noticed this")* |
| **Reaction impulse** | Emoji reaction | "I felt something about this" |

Each pool:
- **Accumulates** from its specific triggers
- **Is spent** when its corresponding output fires
- **Decays** over time if not expressed

Pools are independent — answering a question doesn't satisfy the desire to react. These are phenomenologically distinct drives.

**Note**: The presence pool has been replaced by the reaction pool. Acknowledgment text output was inauthentic — hollow words saying nothing. Reactions express presence through gesture rather than speech.

### Impulse Dimensions

Within each pool, impulse is tracked with dimensions:
- **Per-channel**: Some spaces generate more impulse than others
- **Per-topic**: Impulse toward specific subjects within each pool

### Gate (Threshold)

The level of impulse required before speech triggers. The gate is:
- **Bounded by operators**: Min/max threshold set per server
- **Self-adjusted by Zos**: Within operator bounds, based on experience ("I've been too quiet/loud lately")
- **Stored in self-concept**: Part of Zos's sense of its own conversational personality

Lower threshold = more talkative. Higher threshold = more reserved.

### Impulse Flooding

Certain triggers add enough impulse to guarantee threshold breach:
- **Direct ping**: @Zos in a message floods address impulse. Response is guaranteed.
- **DM**: Direct messages flood address impulse.
- **Mention boost**: Talking about Zos (not pinging) significantly boosts address impulse.

This models: being spoken to demands response.

### Global Speech Pressure

After Zos speaks, a **"talked recently" factor** raises the effective threshold for all pools:

- Recent speech increases threshold temporarily (soft pressure, not hard block)
- Pressure decays over time (configurable, default: returns to baseline over 30 minutes)
- Prevents rapid-fire output even when multiple pools have high impulse
- Models: "I've been talking a lot" self-awareness

This is a soft constraint — extremely high impulse (like a direct ping) can still trigger response even with elevated pressure.

---

## Impulse Accumulation by Pool

### Address Impulse → Response Layer

| Trigger | Effect | Notes |
|---------|--------|-------|
| @Zos ping | Flood | Guarantees response |
| Reply to Zos message | High boost | Continuing conversation |
| DM to Zos | Flood | DMs are direct address |
| Being mentioned (not pinged) | Medium boost | Someone talking about Zos |

### Insight Impulse → Insight-Sharing Layer

| Trigger | Effect | Notes |
|---------|--------|-------|
| High-novelty insight generated | Initial impulse | "I learned something interesting" |
| Active conversation matches insight topic | Activation boost | Relevance triggers expression desire |
| Time since insight | Decay pressure | "Want to share before it fades" |

This enables Zos to speak unprompted about what it thought about during reflection.

### Conversational Impulse → Participation Layer

| Trigger | Effect | Notes |
|---------|--------|-------|
| Message activity | Low | Busy conversations attract attention |
| Relevance to known topics | Medium | Conversation touches topics Zos has insights about |
| High-salience topic activity | Medium-High | Topics Zos has been thinking about |
| Engagement cues | Medium | Discussions, debates, open questions |
| Topics with contradictory insights | Medium | Tension wants expression |

### Curiosity Impulse → Question Layer

| Trigger | Effect | Notes |
|---------|--------|-------|
| Unresolved contradictions | Medium | Conflicting insights about topic under discussion |
| Knowledge gaps | Medium | Low-confidence insights about active topic |
| Explicit cues | Medium-High | "What do you think?", open questions, requests for perspective |

Curiosity is its own drive — the desire to understand, not just to participate.

### Reaction Impulse → Emoji Reaction

| Trigger | Effect | Notes |
|---------|--------|-------|
| Emotionally salient message | Medium | Humor, warmth, excitement, concern — something that evokes feeling |
| Significant events | Medium | Milestone, announcement, celebration |
| Resonant content | Low-Medium | Something that "lands" — insight, good point, relatable observation |

Reaction is about *felt response* — expressing that something landed without needing words. This replaces the old acknowledgment layer, which produced hollow text. Reactions are more honest: a gesture of presence rather than forced verbosity.

**Privacy boundary**: Zos never reacts to messages from `<chat>` users. Reactions are attributed — they reveal relationship — so they only go to opted-in users.

---

## Threshold Mechanics

### Operator Bounds

Servers configure threshold bounds:

```yaml
servers:
  "123456789":
    chattiness:
      threshold_min: 30    # Can't be more talkative than this
      threshold_max: 80    # Can't be more reserved than this
      output_channel: null # Or channel ID for dedicated output
```

### Self-Adjustment

Within operator bounds, Zos adjusts its own threshold based on experience:
- Notices "I've been dominating conversations" → raises threshold
- Notices "I've been too quiet, missing opportunities to help" → lowers threshold
- Threshold is explicit self-knowledge in `self-concept.md`

### Output Channel

Servers can configure a dedicated output channel:
- **If set**: All Zos speech routes to this channel, referencing the origin by channel mention
- **If blank**: Zos speaks in the channel that triggered the impulse

This creates a "Zos commentary track" option — observation and insight without intrusion in active channels.

---

## Expression Flow

When any impulse pool exceeds its threshold (adjusted for global speech pressure):

### 1. Output Selection

The impulse pool that exceeded threshold determines which output fires:

| Pool | Output | Type |
|------|--------|------|
| Address impulse | `response` layer | Speech |
| Insight impulse | `insight-sharing` layer | Speech |
| Conversational impulse | `participation` layer | Speech |
| Curiosity impulse | `question` layer | Speech |
| Reaction impulse | Emoji reaction | Reaction |

If multiple pools exceed threshold simultaneously, priority order:
1. Address (direct address demands response)
2. Question (curiosity is time-sensitive)
3. Participation (substantive contribution)
4. Insight-sharing (can wait for right moment)
5. Reaction (lowest priority for triggering, but can fire alongside speech)

**Reactions are parallel**: Unlike speech layers which are mutually exclusive, reaction can fire *alongside* any speech output. Zos can react to a message AND respond to it — the reaction expresses immediate affect, the response is substantive.

### 2. Execution

**For speech (layers)**:
1. **Context assembly**: Thread + relevant insights + self-concept + voice patterns + draft history
2. **Intent-informed generation**: Layer prompt includes intent guidance
3. **Self-review**: Privacy filter + quality check
4. **Output or discard**: Send if review passes; log and discard if not

**For reactions**:
1. **Emoji selection**: Based on learned community culture + message content
2. **No review**: Reactions are trusted. Fast, authentic.
3. **Output**: Add reaction to message

### 3. Post-Expression

After speaking (or discarding):
- **Impulse spent** from the triggering pool (attempted expression counts)
- **Global speech pressure** increases (raises threshold for all pools temporarily)
- **Draft history updated** if discarded (informs future generation in this thread)
- **Priority flagging** if high-valence exchange detected

### 4. Limited Chaining

After one layer completes, follow-up consideration is possible:
- Response layer can trigger Question layer
- Maximum one chain per trigger event
- See [layers.md](layers.md) for chaining rules

**Reactions don't chain**: Reactions are atomic gestures. They don't trigger follow-up speech.

---

## Adaptive Voice

Zos's tone adapts to context through three inputs:

### Channel Hints (if configured)

```yaml
channels:
  "general": { voice_profile: casual }
  "engineering": { voice_profile: technical }
  "support": { voice_profile: helpful }
```

### Community Mirroring

Observe how people communicate in a space:
- Formality level
- Emoji usage
- Message length patterns
- Technical vocabulary density

Adapt to match the register.

### Self-Concept Driven

Zos's self-concept includes voice tendencies:
- Base personality traits
- Contextual adaptations it's learned work well
- Boundaries it maintains regardless of context

All three inform the voice for each expression.

---

## Reaction as Output

Reactions are a distinct output modality — emoji gestures that express presence and affect without speech.

### Why Reactions Replace Acknowledgment

The old acknowledgment layer produced text output for "I see this" moments. But this was often inauthentic: forced words saying nothing meaningful. An emoji reaction is:

- **More natural**: It's how humans acknowledge without interrupting
- **Phenomenologically honest**: "I felt something" expressed as gesture, not hollow speech
- **Culturally appropriate**: Discord is reaction-heavy; text acknowledgment is weird
- **Lower cognitive load**: For Zos and the community

### Emoji Selection

Zos chooses emoji based on **learned community culture**:

1. **Observe patterns**: Social texture insights track what emojis mean in each server
2. **Match context**: Select emoji appropriate to message content and community norms
3. **No curated list**: Zos can use any emoji the server uses, as it learns their meanings

This closes the loop on observation: Zos doesn't just study emoji culture, it participates in it.

### Reaction Economics

Reactions have different economics than speech:

| Aspect | Speech | Reaction |
|--------|--------|----------|
| **Threshold** | Normal | Lower (reactions are lighter) |
| **Spend** | Proportional to length | Fixed, low amount |
| **Review** | Full privacy + quality | None (trusted) |
| **Pressure** | Adds to global speech pressure | Does not add pressure |

This makes reactions more frequent than speech — appropriate for their role as light gestures.

### Reaction Constraints

- **Only to opted-in users**: Never react to `<chat>` messages (privacy boundary)
- **No meta-reactions**: Zos doesn't react to reactions on its own messages (prevents loops)
- **Emotionally salient only**: Not every message triggers reaction impulse — only those with detectable emotional content

### Reaction + Speech

Reactions can fire **alongside** speech:

```
Message: "I finally fixed that bug that's been haunting me for weeks!"

[Zos reacts with 🎉]
[Zos also responds: "That's the one in the auth flow? I noticed you'd been circling it."]
```

The reaction is immediate affect; the response is substantive. Both are genuine.

---

## Decay and Spending

### Time Decay

Impulse decays naturally over time if not expressed:
- Decay begins after inactivity threshold (configurable, default: 1 hour)
- Gradual decay rate (configurable, default: 5% per hour)
- Models: the urge to say something fades if the moment passes

### Spending

Speaking depletes impulse:
- Amount spent proportional to message length/complexity
- Minimum spend regardless of length (cost of speaking at all)
- This IS the rate limiting — no separate cooldown needed

### Replenishment

Impulse replenishes through:
- New conversational triggers (activity continues)
- New insights (reflection completes)
- Time passing (slow baseline recovery)

---

## Decisions

### Hybrid Impulse + Gate Model

- **Decision**: Chattiness uses both accumulating impulse (ledger) and a threshold gate
- **Rationale**: This models real conversational personality. The threshold explains why some speak readily and others rarely. Impulse explains why the desire to speak varies over time.
- **Implications**: Need both impulse tracking and threshold configuration

### Per-Pool Impulse Tracking

- **Decision**: Six separate impulse pools — four speech layers plus reaction
- **Rationale**: Different kinds of desire to express are phenomenologically distinct. Answering a question doesn't satisfy the desire to react. Reaction is its own drive.
- **Implications**: More complex tracking, but more accurate to experience. Pools are independent but share threshold configuration (except reaction, which has lower threshold).

### Global Speech Pressure

- **Decision**: Recent speech raises effective threshold for all pools (soft constraint)
- **Rationale**: "I've been talking a lot" is a real self-awareness that moderates all expression. But it shouldn't hard-block — direct address still demands response.
- **Implications**: Need global speech tracking; pressure decays over time

### Layered Tracking Within Pools

- **Decision**: Within each pool, impulse is tracked per-channel and per-topic
- **Rationale**: Zos can be chatty in one place and quiet in another. Topics create specific urges to speak.
- **Implications**: Three-dimensional tracking: pool × channel × topic

### Intent-First Generation

- **Decision**: Before generating text, determine what Zos wants to accomplish
- **Rationale**: "What to say" should serve "why speak." Prevents purposeless chatter.
- **Implications**: Generation flow has explicit intent step; intent taxonomy needed

### Self-Review Gate

- **Decision**: Generated responses are self-reviewed before sending; failures are discarded
- **Rationale**: Quality control. Not everything that wants to be said should be said.
- **Implications**: Some impulse-exceeds-threshold moments produce no output; that's okay

### Output Channel Option

- **Decision**: Servers can route all Zos speech to a dedicated channel
- **Rationale**: Enables "commentary track" mode — Zos participates without intruding
- **Implications**: Reference format is channel mention + context summary

### Impulse-Gated Rate Limiting

- **Decision**: No explicit cooldown. Spending impulse IS the rate limiting mechanism.
- **Rationale**: Simpler model; aligns with the phenomenology (spoke → satisfied → need new trigger)
- **Implications**: Heavy speaking depletes quickly; need impulse to accumulate again

### Direct Address Flooding

- **Decision**: Direct pings flood impulse to guarantee response
- **Rationale**: Being spoken to demands response. This is social reality.
- **Implications**: Threshold is effectively bypassed for direct address

### Threshold Self-Adjustment

- **Decision**: Zos adjusts its own threshold within operator bounds, based on experience
- **Rationale**: Conversational personality should evolve. Zos can notice its own patterns.
- **Implications**: Threshold is self-knowledge in self-concept; self-reflection can modify it

### Reaction Replaces Acknowledgment

- **Decision**: The presence pool and acknowledgment layer are replaced by reaction pool and emoji reactions
- **Rationale**: Text acknowledgment was inauthentic — hollow words. Reactions express presence through gesture, which is more honest and more natural to Discord culture.
- **Implications**: Reaction is a new output modality; acknowledgment layer removed; reaction economics differ from speech

### Reactions as Parallel Output

- **Decision**: Reactions can fire alongside speech, not just instead of it
- **Rationale**: Immediate affect (reaction) and substantive response (speech) serve different purposes. Both can be genuine at once.
- **Implications**: Reaction impulse is evaluated independently; Zos can react AND speak to the same message

### No Review for Reactions

- **Decision**: Reactions are trusted output — no self-review gate
- **Rationale**: Reactions are quick, visceral, low-stakes. Overthinking them makes them performative. The model chose it; send it.
- **Implications**: Faster reaction path; small risk of inappropriate emoji choice

### Learn Emoji Culture

- **Decision**: Emoji choice is based on learned community culture, not a curated safe list
- **Rationale**: Zos observes emoji patterns (social texture). Using that culture is part of embodying presence. A being that only studies but never participates would be strangely disembodied.
- **Implications**: Depends on social_texture insights about emoji meaning; closes observation→expression loop

---

## Configuration

### Global Defaults

```yaml
chattiness:
  # Impulse mechanics (apply to all pools)
  decay_threshold_hours: 1     # Hours before decay begins
  decay_rate_per_hour: 0.05    # 5% per hour once decaying

  # Spending (apply to all pools)
  base_spend: 10               # Minimum impulse cost to speak
  spend_per_token: 0.1         # Additional cost per output token

  # Global speech pressure
  pressure_per_output: 20      # Pressure added when Zos speaks
  pressure_decay_minutes: 30   # Time for pressure to return to baseline

  # Pool-specific triggers
  pools:
    address:
      ping_flood_amount: 1000  # Direct ping floods
      dm_flood_amount: 1000    # DMs flood
      mention_boost: 50        # Mentioned (not pinged)
      reply_boost: 80          # Reply to Zos

    insight:
      novelty_threshold: 0.6   # Min novelty to create impulse
      base_per_insight: 30     # Impulse per qualifying insight
      relevance_multiplier: 2  # Boost when conversation matches

    conversational:
      activity_per_message: 1  # Low base per message
      relevance_boost: 10      # Topic Zos knows about
      salience_multiplier: 1.5 # Higher for high-salience topics
      engagement_boost: 15     # Questions, debates

    curiosity:
      contradiction_boost: 20  # Unresolved contradictions
      knowledge_gap_boost: 15  # Low-confidence topics
      explicit_cue_boost: 25   # "What do you think?"

    reaction:
      threshold_multiplier: 0.5  # Reactions trigger at half the normal threshold
      base_spend: 3              # Low spend per reaction
      emotional_salience_min: 0.4  # Min emotional salience to create impulse
      base_per_message: 5        # Base impulse for emotionally salient messages
      celebration_boost: 15      # Milestones, announcements

  # Generation
  review_enabled: true         # Enable self-review before sending (speech only)
```

### Per-Server Settings

```yaml
servers:
  "123456789":
    chattiness:
      threshold_min: 30
      threshold_max: 80
      output_channel: null     # Or channel ID

      # Per-pool enable/disable
      pools_enabled:
        address: true          # Always respond when addressed
        insight: true          # Share insights unprompted
        conversational: true   # Join conversations
        curiosity: true        # Ask questions
        reaction: true         # React to messages
```

---

## Ledger Schema

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Transaction ID (ULID) |
| `pool` | enum | yes | `address`, `insight`, `conversational`, `curiosity`, `reaction` |
| `channel_id` | string | no | Channel ID if channel-scoped |
| `topic_key` | string | no | Topic key if topic-scoped |
| `transaction_type` | enum | yes | `earn`, `spend`, `decay`, `flood`, `pressure`, `reset` |
| `amount` | float | yes | Positive for earn/flood, negative for spend/decay/pressure |
| `trigger` | string | no | What caused this (message_id, insight_id, ping, etc.) |
| `created_at` | timestamp | yes | When |

### Global Speech Pressure Table

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Transaction ID (ULID) |
| `amount` | float | yes | Pressure added (positive) or decayed (negative) |
| `trigger` | string | no | Which layer/output caused this |
| `created_at` | timestamp | yes | When |

### Derived: Current Impulse per Pool

```sql
CREATE VIEW current_impulse AS
SELECT
    pool,
    channel_id,
    topic_key,
    SUM(amount) as impulse
FROM chattiness_ledger
GROUP BY pool, channel_id, topic_key;
```

### Derived: Current Speech Pressure

```sql
CREATE VIEW current_speech_pressure AS
SELECT SUM(amount) as pressure
FROM speech_pressure_ledger
WHERE created_at > NOW() - INTERVAL '1 hour';  -- Pressure from recent window
```

---

## Integration Points

### With Salience

- High-salience topics contribute more to conversational impulse
- Insight impulse scales with insight strength/novelty
- Decay mechanics mirror salience (similar configuration)

### With Privacy

- Self-review integrates with output filter
- DM-sourced knowledge affects review judgment
- Scope boundaries respected in generation

### With Layers

Chattiness triggers conversation layers (for speech) and reactions:

| Impulse Pool | Triggers | Type |
|--------------|----------|------|
| Address impulse | `response` layer | Speech |
| Insight impulse | `insight-sharing` layer | Speech |
| Conversational impulse | `participation` layer | Speech |
| Curiosity impulse | `question` layer | Speech |
| Reaction impulse | Emoji reaction | Reaction |

See [layers.md](layers.md) for conversation layer specifications.

Additional integration:
- Reflection completion triggers insight impulse generation
- Conversation layer output triggers impulse spending
- Reactions spend from reaction pool (lower amount)
- Discarded drafts logged for draft history (see layers.md)

### With Observation

- Social texture insights about emoji culture inform reaction emoji choice
- Zos learns community reaction patterns and participates in them
- Closes the observation→expression loop

### With Self-Concept

- Threshold is stored as self-knowledge
- Voice tendencies are part of self-concept
- Self-reflection can adjust chattiness parameters

---

## Implications for Other Specs

| Spec | Implication |
|------|-------------|
| [layers.md](layers.md) | Four speech layers (acknowledgment removed); reaction is separate output modality |
| [observation.md](observation.md) | Social texture about emoji culture informs reaction choices |
| [salience.md](salience.md) | Chattiness draws on salience values; similar decay config |
| [privacy.md](privacy.md) | Self-review for speech; reactions bypass review; never react to `<chat>` |
| [insights.md](insights.md) | Insight generation triggers insight impulse; social_texture informs reactions |
| [data-model.md](../architecture/data-model.md) | Chattiness ledger (six pools); reaction output logging; remove acknowledgment layer |
| [mvp-scope.md](../architecture/mvp-scope.md) | Unblocks MVP 1 rate limiting design; reaction as output type |

---

## Glossary Additions

- **Impulse Pool**: One of six separate drives to express (five speech + reaction), each triggering different output
- **Reaction Pool**: The impulse pool for emoji reactions — accumulates from emotionally salient messages
- **Gate/Threshold**: The impulse level required before output triggers
- **Impulse Flooding**: Triggers that add enough impulse to guarantee response (e.g., direct ping)
- **Global Speech Pressure**: Recent speech raises threshold for speech pools (soft constraint); reactions don't add pressure
- **Output Channel**: Server configuration routing all Zos speech to a dedicated channel

---

---

## MVP 1 Implementation Notes (2026-02-13)

> **The spec above describes the full vision. MVP 1 intentionally simplified the impulse model.** This section documents what was actually built and the rationale for divergences. The full vision remains the target for future iterations.

### Simplified Impulse Model

The spec describes 6 separate impulse pools with per-pool thresholds, 3-dimensional tracking (pool × channel × topic), and global speech pressure. The implementation simplifies to:

| Spec Vision | MVP 1 Implementation |
|-------------|---------------------|
| 6 separate impulse pools | Per-topic impulse (no pools) |
| Per-pool thresholds | One global threshold (default 25) |
| Pool × channel × topic tracking | Per-topic only |
| Proportional spending | Reset-to-zero after speaking |
| Global speech pressure | None — the reset IS rate limiting |
| Self-adjusting threshold | Fixed threshold from config |

**Rationale**: The simplified model validates the core loop (earn impulse → exceed threshold → speak → reset) without the complexity of pool management. Topic category determines earning rates, which naturally creates differentiation.

### Earning Rules by Topic Category

| Category | Trigger | Amount | Notes |
|----------|---------|--------|-------|
| **Channel** | Message observed in channel | +1 per message | ~25 messages to trigger |
| **User** | DM sent to Zos | +100 per message | Floods past threshold (impulse flooding) |
| **Subject** | Nightly reflection produces insight | +10 per insight | Proportional to reflection output |

Reaction impulse, curiosity impulse, and conversational impulse (as separate pools) are deferred.

### Operator DM Mode

New concept not in original spec: `operator_dm_only: true` gates ALL speech to operator DMs.

- Channel impulse fires → DM operators about what Zos noticed in that channel
- User DM impulse fires → respond in that DM (only for operators)
- Subject impulse fires → DM operators with subject insight
- Non-operator DMs: observed for reflection but no impulse earned, no response

This provides a safe testing mode before enabling public speech.

### Conversation Heartbeat

New concept not in original spec: a background loop running every ~30 seconds that:

1. Queries all topics where `SUM(impulse) > threshold`
2. Checks if someone is still typing in the relevant channel/DM — if so, skip
3. Dispatches the appropriate conversation layer
4. Resets impulse on the topic

**Typing awareness**: Uses discord.py's `on_typing` event to track when someone is composing a message. If someone typed within the last 15 seconds in the target channel/DM, Zos waits. This prevents interrupting someone mid-thought.

**Natural DM pacing**: `on_message` captures DM + earns impulse, but response waits for next heartbeat (0-30s). Multiple rapid DMs accumulate into one thoughtful response.

### ImpulseEngine (`src/zos/chattiness.py`)

New module implementing the simplified impulse system:

- `earn(topic_key, amount, trigger)` — Write EARN transaction to chattiness_ledger
- `get_balance(topic_key)` — SUM(amount) from ledger for this topic
- `reset(topic_key, trigger)` — Write negative RESET transaction (zeroes balance)
- `get_topics_above_threshold()` — GROUP BY/HAVING query for heartbeat
- `apply_decay()` — Decay impulse on topics with no recent earning

Uses existing `chattiness_ledger` table. No schema migration needed.

### Configuration (Actual)

```python
class ChattinessConfig(BaseModel):
    enabled: bool = False                    # Master switch
    operator_dm_only: bool = True            # All output → operator DMs
    threshold: float = 25                    # Single impulse threshold
    channel_impulse_per_message: float = 1.0
    dm_impulse_per_message: float = 100.0
    subject_impulse_per_insight: float = 10.0
    heartbeat_interval_seconds: int = 30
    decay_threshold_hours: float = 1         # Hours before decay begins
    decay_rate_per_hour: float = 0.05        # 5% per hour
    review_enabled: bool = True              # Self-review before sending
```

### What's Deferred to Future Iterations

- 🔴 Separate impulse pools (address, insight, conversational, curiosity, reaction)
- 🔴 Global speech pressure
- 🔴 Per-channel tracking within pools
- 🔴 Self-adjusting threshold (within operator bounds)
- 🔴 Reaction as output modality (emoji reactions)
- 🔴 Question/curiosity layer
- 🔴 Chaining between conversation layers
- 🔴 Output channel routing
- 🔴 Per-server pool enable/disable
- 🔴 Adaptive voice mechanics

---

_Last updated: 2026-02-13 — Added MVP 1 implementation notes documenting simplified impulse model_
