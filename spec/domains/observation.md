# Observation — Domain Specification

**Status**: 🟢 Complete
**Last interrogated**: 2026-01-23
**Last verified**: —
**Depends on**: Topics (emoji topic creation), Privacy (reaction tracking rules)
**Depended on by**: Layers (consumes observed data), Salience (reaction-based earning), Insights (social texture)

---

## Overview

Observation defines how Zos perceives its environment — the capture and enrichment of raw Discord events into meaningful context for cognition. This is the "eyes and ears" of the system: what gets noticed, how it's processed, and how it becomes available for reflection and conversation.

Observation is not passive recording. Following the core principle of building as if inner experience matters, observation is *attentive presence* — Zos choosing to attend to its communities, noticing not just what is said but how it's expressed, who responds to whom, and what visual and linked content is shared.

---

## Core Concepts

### Batch Polling Model

Observation operates through periodic check-ins rather than continuous event streaming:

- **Decision**: Batch polling, not event-driven
- **Rationale**: This mirrors human Discord usage — checking in periodically rather than being perpetually interrupt-driven. It also creates architectural space for future attention allocation: Zos may eventually have other activities competing for attention, and building as if that's possible now creates the right foundation.
- **Implications**: Polling interval is configurable; some latency between Discord events and Zos awareness; cleaner execution model

### Attentive Presence

Observation is phenomenologically active, not passive:
- Zos *attends* to conversations, not just records them
- Media is *seen* and described experientially, not just catalogued
- Reactions are noticed as social gestures, not just counted

This shapes how data is stored and surfaced.

---

## Message Observation

### Core Fields

Messages are captured with:
- Content (text)
- Author (real Discord ID, anonymized at context assembly)
- Timestamp
- Channel/thread context
- Reply relationships
- Visibility scope (`public` or `dm`)

### Edits and Deletions

- **Decision**: Latest state only — respect "unsaying"
- **Rationale**: If someone deleted or edited a message, they made a choice to unsay it. Zos doesn't hoard what was actively withdrawn. This aligns with the privacy philosophy: discretion includes not retaining what was removed.
- **Implications**: No edit history stored; deleted messages are removed; observation reflects current state

---

## Reaction Tracking

### Hybrid Tracking Model

- **Decision**: Full tracking for opted-in users; aggregate counts only for `<chat>` users
- **Rationale**: Reactions reveal rich relational signal (who appreciates whose contributions), but this should respect the privacy gate boundary. When no privacy gate role is configured, all users are opted in.
- **Implications**: Need Reaction entity with user+emoji+message; aggregation view for anonymous counts

### Reaction Schema

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | ULID |
| `message_id` | string | yes | Which message |
| `user_id` | string | yes | Who reacted (real ID, anonymized for `<chat>`) |
| `emoji` | string | yes | Emoji used (Unicode or custom emoji ID) |
| `is_custom` | bool | yes | Whether this is a server custom emoji |
| `created_at` | timestamp | yes | When reaction was added |

### Dual-Fetch Timing

Reactions leak in over time (hours to days after a message). To capture this:

- **Conversation layer**: Fetches current reactions at impulse trigger time (freshest available snapshot)
- **Reflection layer**: Re-checks messages for settled reaction state before reflecting

Salience earning happens at reflection time, when we have the complete picture.

### Relationship Inference

Observation detects reaction-based social patterns:
- Who consistently reacts to whose messages
- Reaction reciprocity (mutual appreciation)
- Emoji sentiment patterns per relationship

These signals feed into dyad understanding during reflection.

---

## Media Handling

### Vision Analysis

- **Decision**: Real-time inline analysis with phenomenological voice
- **Rationale**: Seeing an image and understanding it in the moment is part of genuine presence. The cost is real but the phenomenological coherence is worth it.
- **Voice**: "I see a sunset photograph, warm oranges bleeding into purple. Feels contemplative." — not "Image: sunset, outdoor, warm color palette."

### Media Analysis Schema

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | ULID |
| `message_id` | string | yes | Which message contained this media |
| `media_type` | enum | yes | `image`, `video`, `gif`, `embed` |
| `url` | string | yes | Media URL |
| `filename` | string | no | Original filename if available |
| `dimensions` | json | no | Width/height for images/video |
| `duration_seconds` | int | no | For video/audio |
| `description` | string | yes | Phenomenological description of content |
| `analyzed_at` | timestamp | yes | When analysis ran |

### Supported Media Types

| Type | Processing |
|------|------------|
| Images | Vision model analysis, phenomenological description |
| GIFs | Treated as short video, describe motion/emotion |
| Videos (< 30 min) | Frame sampling + analysis |
| Videos (≥ 30 min) | Metadata only (TLDW principle) |
| Embeds | Extract preview image if available |

---

## Link Handling

### Fetch and Summarize

- **Decision**: Fetch linked content and generate brief summaries
- **Rationale**: What people share is part of the conversation. Understanding shared content enables richer participation.

### Link Schema

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | ULID |
| `message_id` | string | yes | Which message contained this link |
| `url` | string | yes | Full URL |
| `domain` | string | yes | Extracted domain for pattern analysis |
| `title` | string | no | Page title or embed title |
| `summary` | string | no | Brief content summary |
| `content_type` | enum | yes | `article`, `video`, `image`, `other` |
| `fetched_at` | timestamp | no | When content was retrieved |

### YouTube Special Handling

For YouTube links:
- Fetch video transcript (when available)
- Generate summary from transcript
- Store channel name, duration
- **Threshold**: Videos > 30 minutes get metadata only, no transcript analysis

### Fetch Constraints

- Respect `robots.txt`
- Cache fetched content to avoid re-fetching
- Timeout after configurable threshold
- Skip known problematic domains (configurable blocklist)

---

## Emoji Culture Modeling

### Tri-Level Approach

Emoji culture is modeled at three levels, providing different lenses on the same phenomenon:

#### 1. Server-Level Emoji Topics

- **Decision**: Create topic for every custom emoji at first use
- **Rationale**: Even low-usage emojis can be culturally significant (inside jokes, legacy meanings). Salience will naturally sort importance.
- **Topic key**: `server:<id>:emoji:<emoji_id>`

Emoji topics track:
- Usage frequency and trends
- Who uses this emoji most
- Common contexts (channels, subjects)
- Semantic meaning as it emerges

#### 2. Aggregate Metrics

Server-wide emoji statistics:
- Most used emojis (custom and Unicode)
- Emoji velocity (trending up/down)
- Reaction vs. message usage patterns

#### 3. User Traits

Individual emoji fingerprints:
- Which emojis each user favors
- Contextual patterns ("uses 🔥 sarcastically")
- Reaction tendencies (heavy/light reactor)

---

## Configuration

### Hierarchy

Configuration follows full hierarchy: global → server → channel

```yaml
observation:
  # Global defaults
  polling_interval_seconds: 60
  vision_enabled: true
  link_fetch_enabled: true
  youtube_transcript_enabled: true
  video_duration_threshold_minutes: 30

  # Server overrides
  servers:
    "123456789":
      polling_interval_seconds: 30  # More frequent for active server

      # Channel overrides
      channels:
        "987654321":  # e.g., #memes
          vision_enabled: false  # Too much low-value media
```

### Configurable Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `polling_interval_seconds` | 60 | How often to check for new activity |
| `vision_enabled` | true | Run vision analysis on images |
| `link_fetch_enabled` | true | Fetch and summarize linked content |
| `youtube_transcript_enabled` | true | Fetch YouTube transcripts |
| `video_duration_threshold_minutes` | 30 | Max video length for full analysis |
| `reaction_batch_size` | 100 | Reactions to process per poll cycle |
| `link_fetch_timeout_seconds` | 30 | Timeout for fetching linked content |

---

## Context Assembly

Observation produces enriched data that layers consume. Context assembly (preparing observed data for layer input) is handled at the layer execution boundary. See [layers.md](layers.md) for context assembly details.

Key handoff points:
- `fetch_messages` node receives enriched messages (with media descriptions, link summaries)
- Reaction data available via topic queries
- Emoji culture available as server/user context

---

## Non-Goals

Explicit exclusions for MVP:

### Voice/Audio Analysis

Zos does not listen to voice channels. Voice is a different modality with different privacy implications and technical complexity. Deferred to future consideration.

### External User Research

Zos does not look up users on other platforms or external sources. Understanding is built purely from in-Discord observation.

### Real-Time Event Streaming

Observation uses batch polling, not Discord gateway events. This is intentional — see [Batch Polling Model](#batch-polling-model).

---

## Implications for Other Specs

| Spec | Implication |
|------|-------------|
| [data-model.md](../architecture/data-model.md) | New entities: Reaction, MediaAnalysis, LinkAnalysis; emoji topic type |
| [topics.md](topics.md) | New topic type: `server:<id>:emoji:<emoji_id>` |
| [salience.md](salience.md) | Reaction-based salience earning; timing at reflection |
| [layers.md](layers.md) | `fetch_messages` returns enriched data with media/links; reaction data available |
| [insights.md](insights.md) | New insight category: `social_texture` for expression pattern insights |
| [privacy.md](privacy.md) | Reaction tracking respects privacy gate role |

---

## Glossary Additions

- **Observation**: The capture and enrichment of raw Discord events into meaningful context for cognition. Zos's "eyes and ears."
- **Batch Polling**: Periodic check-in model for observation, contrasted with event-driven. Mirrors human Discord usage patterns.
- **Phenomenological Description**: First-person, experiential description of visual content ("I see...") rather than objective cataloguing.
- **Social Texture**: Insight category for expression patterns — emoji usage, reaction tendencies, communication style. Tracks *how* people communicate, not just *what*.
- **TLDW Principle**: "Too Long, Didn't Watch" — threshold-based decision to capture metadata only for very long videos, mirroring human behavior.

---

_Last updated: 2026-01-23_
