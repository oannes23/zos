# User Profile Layer

Builds and maintains understanding of individual community members based on their public messages.

## Overview

The User Profile layer analyzes messages from active users to build persistent profiles that track:
- Communication patterns and style
- Interests and frequently discussed topics
- Self-disclosed personal information (names, pronouns, occupation)

This layer runs daily after the channel_digest layer and provides context for other layers like social_dynamics.

## Configuration

### Schedule

Runs daily at 4 AM (after channel_digest completes at 3 AM).

```yaml
schedule: "0 4 * * *"
```

### Targets

Targets individual users who have accumulated sufficient activity.

| Setting | Value | Description |
|---------|-------|-------------|
| categories | `user` | Targets user topics |
| min_salience | 15.0 | Higher threshold for active users |
| max_targets | 30 | Process up to 30 users per run |

### Pipeline

| Step | Node Type | Description |
|------|-----------|-------------|
| 1 | fetch_messages | Get user's messages from past week |
| 2 | fetch_insights | Get previous profile for this user |
| 3 | fetch_insights | Get channel context for broader understanding |
| 4 | llm_call | Analyze messages and update profile |
| 5 | store_insight | Save profile with structured payload |
| 6 | output | Log the result |

## Prompts

### system.j2

Defines Zos's role as a perceptive observer of community members. Emphasizes:
- Privacy-respecting observation
- Conservative claims about personal information
- Distinguishing facts from observations
- Confidence levels for uncertain data

### analyze.j2

Template for profile analysis that includes:
- Recent messages from the user
- Previous profile data (if exists)
- Channel context for broader understanding

Requests structured output with profile summary, communication style, interests, and JSON payload for persistent data.

## Usage

### Manual Execution

```bash
# Run the layer manually
uv run python -m zos.cli layer run user_profile

# Dry-run to see what would be processed
uv run python -m zos.cli layer dry-run user_profile

# Validate the layer definition
uv run python -m zos.cli layer validate user_profile
```

### Viewing Results

```bash
# List recent user profile insights
uv run python -m zos.cli insights list --layer user_profile

# Show a specific insight with payload
uv run python -m zos.cli insights show <insight_id> --full
```

## Output Example

```
## Profile Summary

Alice is an active software developer who frequently contributes technical discussions
about Python and machine learning. She communicates in a helpful, detailed manner and
often assists other community members with coding questions.

## Communication Style

Casual but technically precise. Uses code examples frequently. Tends toward longer,
explanatory messages when helping others.

## Interests

- Python programming
- Machine learning
- Open source development
- Code review best practices

## Profile Updates

- Names: Alice, alice_dev (from Discord username)
- Pronouns: she/her (stated in introduction message)
- Occupation: Software engineer (mentioned in career discussion)

## Notable Changes

Increased activity in the ML channel this week, suggesting growing interest in
machine learning topics.
```

## Budget

| Metric | Value |
|--------|-------|
| Salience per target | 1.5 |
| Temperature | 0.6 (lower for consistency) |
| Max tokens | 1500 |
| Lookback | 168 hours (1 week) |

## Structured Payload

The layer stores profiles with `include_payload: true`, enabling structured data queries:

```json
{
  "profile": {
    "known_names": ["Alice", "alice_dev"],
    "pronouns": "she/her",
    "occupation": "software engineer",
    "interests": ["Python", "machine learning", "open source"],
    "communication_style": "helpful and detailed"
  },
  "confidence": {
    "names": 0.9,
    "pronouns": 0.8,
    "occupation": 0.7
  }
}
```

## Cross-Layer Integration

This layer:
- **Consumes**: channel_digest insights for context
- **Produces**: User profiles used by social_dynamics and emoji_semantics layers
