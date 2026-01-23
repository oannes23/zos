# Chattiness — Domain Specification

**Status**: 🟢 Complete
**Last interrogated**: 2026-01-22
**Last verified**: —
**Depends on**: Topics, Privacy, Salience, Insights, Layers (integrates all domains)
**Depended on by**: MVP 1 conversation mechanics

---

## Overview

Chattiness governs when and how much Zos wants to speak. While salience determines what Zos *thinks about*, chattiness determines the drive to *express* that thinking.

This is the system for modeling *the desire to participate* — not just rate limiting, but the phenomenology of wanting to speak. There's the urge to share something interesting, the hesitation when uncertain, the restraint when something feels too private, the satisfaction of a good exchange.

Chattiness uses a **hybrid Impulse + Gate model**:
- **Impulse** (ledger-like): Accumulates from triggers, wants to be expressed
- **Gate** (threshold): Personal parameter determining how much impulse is needed before speaking triggers

The threshold explains different conversational personalities: low threshold = speaks readily, dominates conversations; high threshold = speaks rarely, carefully. Being directly addressed floods impulse to overcome any threshold.

---

## Core Concepts

### Impulse

The accumulated drive to speak. Impulse is a ledger value that:
- **Accumulates** from conversational triggers, insight generation, and being addressed
- **Is spent** when Zos speaks (natural rate limiting)
- **Decays** over time if not expressed (like salience)

Impulse is tracked in layers:
- **Global base**: Overall desire to participate
- **Per-channel modifiers**: Some spaces generate more impulse than others
- **Per-topic relevance**: Impulse toward specific subjects

### Gate (Threshold)

The level of impulse required before speech triggers. The gate is:
- **Bounded by operators**: Min/max threshold set per server
- **Self-adjusted by Zos**: Within operator bounds, based on experience ("I've been too quiet/loud lately")
- **Stored in self-concept**: Part of Zos's sense of its own conversational personality

Lower threshold = more talkative. Higher threshold = more reserved.

### Impulse Flooding

Certain triggers add enough impulse to guarantee threshold breach:
- **Direct ping**: @Zos in a message floods impulse. Response is guaranteed.
- **Mention boost**: Talking about Zos (not pinging) adds significant impulse.

This models: being spoken to demands response.

---

## Impulse Accumulation

### Conversational Impulse

Accumulates from observing active conversations:

| Trigger | Impulse Gain | Notes |
|---------|--------------|-------|
| Message activity | Low | Busy conversations attract attention |
| Relevance to known topics | Medium | Conversation touches topics Zos has insights about |
| High-salience topic activity | Medium-High | Topics Zos has been thinking about |
| Engagement cues | Medium | Questions asked, disagreements, requests for input |
| Being mentioned (not pinged) | High | Someone talking about Zos |
| Topics with contradictory insights | Medium | Tension wants expression |

### Insight Impulse

Accumulates after reflection:

1. **High-novelty insights** create initial impulse ("I learned something interesting")
2. **Relevance activation**: Impulse activates when active conversation matches recent insight topics
3. **Time pressure**: Insight impulse decays — "I want to share this before it fades"

This enables Zos to speak unprompted about what it thought about during reflection.

### Direct Address

| Trigger | Effect |
|---------|--------|
| @Zos ping | Floods impulse to guarantee response |
| Reply to Zos message | High impulse boost |
| DM to Zos | Floods impulse (DMs are direct address) |

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

When impulse exceeds threshold:

### 1. Intent Determination

Before generating text, determine: *What does Zos want to accomplish with this speech?*

Possible intents:
- Share an insight or observation
- Answer a question
- Add context to a discussion
- Express agreement/disagreement
- Ask a clarifying question
- Offer help

Intent emerges from what accumulated the impulse and current context.

### 2. Context-Informed Generation

Gather:
- Recent messages in the conversation
- Relevant insights (from the topics involved)
- Self-concept (for voice and values)
- Channel/community voice patterns

Generate toward the determined intent.

### 3. Self-Review

Before sending, evaluate:
- Does this serve the intent?
- Is it appropriate for the context?
- Does it respect privacy boundaries? (output filter integration)
- Would this add value or just noise?

If review fails: discard and log. Impulse is still spent (attempted expression counts).

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

### Layered Tracking

- **Decision**: Impulse tracked as global base + per-channel modifiers + per-topic relevance
- **Rationale**: Zos can be chatty in one place and quiet in another. Topics create specific urges to speak.
- **Implications**: More complex tracking, but better models reality

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

---

## Configuration

### Global Defaults

```yaml
chattiness:
  # Impulse mechanics
  decay_threshold_hours: 1     # Hours before decay begins
  decay_rate_per_hour: 0.05    # 5% per hour once decaying

  # Spending
  base_spend: 10               # Minimum impulse cost to speak
  spend_per_token: 0.1         # Additional cost per output token

  # Triggers
  ping_flood_amount: 1000      # Impulse added on direct ping
  mention_boost: 50            # Impulse added when mentioned (not pinged)

  # Generation
  review_enabled: true         # Enable self-review before sending
```

### Per-Server Settings

```yaml
servers:
  "123456789":
    chattiness:
      threshold_min: 30
      threshold_max: 80
      output_channel: null     # Or channel ID
      insight_expression: true # Allow unprompted insight sharing
```

---

## Ledger Schema

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Transaction ID (ULID) |
| `scope` | enum | yes | `global`, `channel`, `topic` |
| `scope_key` | string | no | Channel ID or topic key if scoped |
| `transaction_type` | enum | yes | `earn`, `spend`, `decay`, `flood` |
| `amount` | float | yes | Positive for earn/flood, negative for spend/decay |
| `trigger` | string | no | What caused this (message_id, insight_id, ping, etc.) |
| `created_at` | timestamp | yes | When |

### Derived: Current Impulse

```sql
CREATE VIEW current_impulse AS
SELECT
    scope,
    scope_key,
    SUM(amount) as impulse
FROM chattiness_ledger
GROUP BY scope, scope_key;
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

- Reflection completion triggers insight impulse generation
- May need "conversation layer" distinct from reflection layers for response generation

### With Self-Concept

- Threshold is stored as self-knowledge
- Voice tendencies are part of self-concept
- Self-reflection can adjust chattiness parameters

---

## Implications for Other Specs

| Spec | Implication |
|------|-------------|
| [layers.md](layers.md) | May need conversation/response layer type |
| [salience.md](salience.md) | Chattiness draws on salience values; similar decay config |
| [privacy.md](privacy.md) | Self-review integrates output filter |
| [insights.md](insights.md) | Insight generation triggers impulse; novelty/strength inform amount |
| [data-model.md](../architecture/data-model.md) | New chattiness_ledger table; server chattiness config |
| [mvp-scope.md](../architecture/mvp-scope.md) | Unblocks MVP 1 rate limiting design |

---

## Glossary Additions

- **Impulse**: The accumulated drive to speak (ledger value)
- **Gate/Threshold**: The impulse level required before speech triggers
- **Impulse Flooding**: Triggers that add enough impulse to guarantee response
- **Intent**: What Zos wants to accomplish with a particular expression
- **Output Channel**: Server configuration routing all Zos speech to a dedicated channel

---

_Last updated: 2026-01-22 — Interrogated to completion_
