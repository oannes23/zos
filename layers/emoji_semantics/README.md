# Emoji Semantics Layer

Analyzes emoji and reaction usage patterns to understand their meanings and social functions within the community.

## Overview

The Emoji Semantics layer examines how emojis and reactions are used, identifying:
- Custom emoji meanings inferred from context
- Reaction semantics (approval, humor, disagreement, etc.)
- Community-specific emoji culture
- User patterns in emoji usage
- Trends in reaction behavior over time

This layer runs weekly and helps understand the non-verbal communication patterns in the community.

## Configuration

### Schedule

Runs weekly on Sundays at 6 AM (after social_dynamics layer completes at 5 AM).

```yaml
schedule: "0 6 * * 0"
```

### Targets

Targets channel topics with high activity levels.

| Setting | Value | Description |
|---------|-------|-------------|
| categories | `channel` | Targets channel topics |
| min_salience | 20.0 | Higher threshold for active channels |
| max_targets | 15 | Process up to 15 channels per run |

### Pipeline

| Step | Node Type | Description |
|------|-----------|-------------|
| 1 | fetch_messages | Get messages with reaction data |
| 2 | fetch_insights | Get previous emoji analysis |
| 3 | fetch_insights | Get user profiles for context |
| 4 | fetch_insights | Get channel digest for context |
| 5 | llm_call | Analyze emoji patterns and meanings |
| 6 | store_insight | Save analysis with structured payload |
| 7 | output | Log the result |

## Prompts

### system.j2

Defines Zos's role as an analyst of emoji patterns. Emphasizes:
- Understanding both standard and custom emoji meanings
- Recognizing context-dependent interpretations
- Identifying ironic or sarcastic usage
- Using confidence levels for uncertain meanings

### analyze.j2

Template for emoji analysis that includes:
- Messages with their reaction data
- Reaction statistics summary
- Previous emoji analysis (if exists)
- User and channel context

Requests structured output with emoji dictionary, top reactions, and cultural observations.

## Usage

### Manual Execution

```bash
# Run the layer manually
uv run python -m zos.cli layer run emoji_semantics

# Dry-run to see what would be processed
uv run python -m zos.cli layer dry-run emoji_semantics

# Validate the layer definition
uv run python -m zos.cli layer validate emoji_semantics
```

### Viewing Results

```bash
# List recent emoji semantics insights
uv run python -m zos.cli insights list --layer emoji_semantics

# Show a specific insight with payload
uv run python -m zos.cli insights show <insight_id> --full
```

## Output Example

```
## Emoji Overview

This channel has an active reaction culture with heavy use of custom server emojis.
Users frequently react to messages to show appreciation, agreement, or humor.
The community has developed several custom emojis with specific meanings.

## Custom Emoji Meanings

- :pepethink: - Used when considering complex technical problems or philosophical questions
- :shipIt: - Approval for code that's ready to deploy, originated from a squirrel meme
- :yikes: - Reaction to concerning news or problematic code
- :bigbrain: - Praising clever solutions or smart observations

## Reaction Semantics

Reactions in this channel primarily serve three functions:
1. **Approval**: thumbsup, shipIt, 100 - indicating agreement or support
2. **Humor**: joy, pepethink, yikes - responding to funny or relatable content
3. **Engagement**: eyes, thinking_face - showing interest without commenting

## Popular Reactions

1. thumbsup (156 uses) - General approval and acknowledgment
2. :shipIt: (89 uses) - Code/solution approval
3. joy (67 uses) - Responding to humor
4. :pepethink: (52 uses) - Thoughtful consideration

## User Patterns

- Alice frequently uses :bigbrain: when praising others' solutions
- Bob tends to use the classic thumbsup for quick acknowledgments

## Trends

Custom emoji usage has increased 20% since last analysis, suggesting growing
community identity and shared vocabulary.
```

## Budget

| Metric | Value |
|--------|-------|
| Salience per target | 2.0 |
| Temperature | 0.7 |
| Max tokens | 2000 |
| Lookback | 336 hours (2 weeks) |

## Structured Payload

The layer stores emoji analysis with `include_payload: true`, enabling structured data queries:

```json
{
  "emoji_dictionary": {
    ":pepethink:": {
      "meaning": "thoughtful consideration of complex problems",
      "usage": "custom",
      "confidence": 0.85
    },
    ":shipIt:": {
      "meaning": "approval for deployment-ready code",
      "usage": "approval",
      "confidence": 0.9
    }
  },
  "top_reactions": [
    {
      "emoji": "thumbsup",
      "count": 156,
      "primary_use": "general approval"
    },
    {
      "emoji": ":shipIt:",
      "count": 89,
      "primary_use": "code approval"
    }
  ],
  "channel_emoji_culture": "Active reaction culture with custom emojis for code review"
}
```

## Cross-Layer Integration

This layer:
- **Consumes**: user_profile insights for user context, channel_digest for channel context
- **Produces**: Emoji dictionary and reaction patterns for understanding non-verbal communication

## Reaction Data

This layer uses `include_reactions: true` in the fetch_messages node, which:
- Attaches reaction data to each message
- Provides a `reaction_summary` in the context with aggregate counts
- Enables analysis of which messages receive which reactions
