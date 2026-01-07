# Social Dynamics Layer

Analyzes interaction patterns between pairs of users to understand relationship dynamics within the community.

## Overview

The Social Dynamics layer examines how users interact with each other, identifying:
- Relationship types (collaborators, supporters, debate partners, etc.)
- Interaction patterns and frequency
- Shared interests and topics
- Evolution of relationships over time

This layer runs weekly and provides context for understanding the social fabric of the community.

## Configuration

### Schedule

Runs weekly on Sundays at 5 AM (after user_profile layer completes at 4 AM daily).

```yaml
schedule: "0 5 * * 0"
```

### Targets

Targets dyad topics (pairs of users) with accumulated interaction salience.

| Setting | Value | Description |
|---------|-------|-------------|
| categories | `dyad` | Targets user pair topics |
| min_salience | 5.0 | Lower threshold for relationship building |
| max_targets | 50 | Process up to 50 relationships per run |

### Pipeline

| Step | Node Type | Description |
|------|-----------|-------------|
| 1 | fetch_messages | Get interactions between the user pair |
| 2 | fetch_insights | Get previous dynamics for this pair |
| 3 | fetch_insights | Get user profiles for context |
| 4 | fetch_insights | Get channel context for broader understanding |
| 5 | llm_call | Analyze relationship dynamics |
| 6 | store_insight | Save analysis with structured payload |
| 7 | output | Log the result |

## Prompts

### system.j2

Defines Zos's role as an observer of social dynamics. Emphasizes:
- Focus on observable interaction patterns
- Respectful analysis of online relationships
- Distinguishing frequent interactions from meaningful connections
- Using confidence levels for uncertain assessments

### analyze.j2

Template for relationship analysis that includes:
- Recent interaction messages between the pair
- Previous dynamics analysis (if exists)
- User profiles for individual context
- Channel context for broader understanding

Requests structured output with relationship summary, interaction style, shared interests, strength assessment, and JSON payload.

## Usage

### Manual Execution

```bash
# Run the layer manually
uv run python -m zos.cli layer run social_dynamics

# Dry-run to see what would be processed
uv run python -m zos.cli layer dry-run social_dynamics

# Validate the layer definition
uv run python -m zos.cli layer validate social_dynamics
```

### Viewing Results

```bash
# List recent social dynamics insights
uv run python -m zos.cli insights list --layer social_dynamics

# Show a specific insight with payload
uv run python -m zos.cli insights show <insight_id> --full
```

## Output Example

```
## Relationship Summary

Alice and Bob have developed a collaborative relationship centered around Python
development. They frequently help each other with technical questions and share
resources in the programming channels.

## Interaction Style

Their interactions are friendly and technically focused. Alice often initiates
discussions with questions, while Bob provides detailed explanations and code
examples. Both express appreciation for each other's contributions.

## Shared Interests

- Python programming
- Machine learning projects
- Open source contributions
- Code review practices

## Relationship Strength

Strong - They interact multiple times per week across several channels and have
established a pattern of mutual support.

## Notable Patterns

- Bob consistently responds to Alice's questions within a few hours
- They have started collaborating on an open source project together
- Both reference each other's advice in conversations with others

## Changes

Since last analysis, their collaboration has intensified with the start of a
joint project. Interaction frequency has increased from occasional to frequent.
```

## Budget

| Metric | Value |
|--------|-------|
| Salience per target | 2.0 |
| Temperature | 0.7 |
| Max tokens | 1500 |
| Lookback | 336 hours (2 weeks) |

## Structured Payload

The layer stores relationships with `include_payload: true`, enabling structured data queries:

```json
{
  "relationship": {
    "type": "collaborators",
    "strength": "strong",
    "primary_context": "#programming",
    "shared_interests": ["Python", "machine learning", "open source"],
    "interaction_frequency": "frequent"
  },
  "confidence": {
    "type": 0.85,
    "strength": 0.8
  }
}
```

## Cross-Layer Integration

This layer:
- **Consumes**: user_profile insights for individual context, channel_digest for channel context
- **Produces**: Relationship dynamics used for understanding community social fabric
