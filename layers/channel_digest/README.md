# Channel Digest Layer

The **channel_digest** layer is a nightly reflection layer that summarizes channel activity and generates insights about community discussions.

## Overview

This layer runs on a daily schedule (3 AM by default) and:
1. Fetches recent messages from channels with sufficient salience
2. Retrieves prior insights for context
3. Generates a structured digest summarizing activity
4. Stores the insight for future reference

## Configuration

### Schedule

```yaml
schedule: "0 3 * * *"  # Daily at 3 AM
```

### Targets

Targets channels based on salience:
- Categories: `channel`
- Minimum salience: 10.0
- Maximum targets per run: 20

### Pipeline

```
fetch_messages -> fetch_insights -> llm_call -> store_insight -> output
```

| Node | Description |
|------|-------------|
| `get_recent_messages` | Fetches up to 100 public messages from past 24 hours |
| `get_prior_insights` | Retrieves up to 5 previous insights for context |
| `summarize` | Calls LLM with system and summarize prompts |
| `save_summary` | Stores the generated insight in the database |
| `log_output` | Logs the output (Discord output in Phase 11) |

## Prompts

### system.j2

Defines the Zos persona as an observant analyst of Discord conversations. Sets expectations for:
- Identifying themes and topics
- Noting notable exchanges
- Tracking patterns
- Maintaining objectivity

### summarize.j2

Structured prompt requesting:
1. **Activity Summary** - Overview of activity level and mood
2. **Key Topics** - 2-4 main subjects discussed
3. **Notable Moments** - Interesting exchanges or highlights
4. **Emerging Themes** - Patterns worth tracking

Target length: 300-500 words

## Usage

### Manual Execution

```bash
# Run the layer manually
uv run python -m zos.cli layer run channel_digest

# Dry-run (validate without execution)
uv run python -m zos.cli layer dry-run channel_digest --topic "channel:123456"
```

### Viewing Results

```bash
# List recent runs
uv run python -m zos.cli runs list --limit 5

# Show run details with trace
uv run python -m zos.cli runs show <run_id> --trace

# List insights from a run
uv run python -m zos.cli insights list --run-id <run_id>

# Show full insight
uv run python -m zos.cli insights show <insight_id> --full
```

## Output Example

```markdown
## Activity Summary
The channel had moderate activity with engaging discussions...

## Key Topics
1. **Python Learning** - Members discussing tutorials and async patterns
2. **Weekly Sync** - Coordination for upcoming meeting

## Notable Moments
- Alice and Bob had an exchange about asyncio
- Charlie reminded everyone about the weekly sync

## Emerging Themes
- Growing interest in async programming
- Good community coordination for events
```

## Budget

- Per-target salience spend: 1.0
- Model defaults: temperature 0.7, max_tokens 2048

## Reference

This layer serves as the **reference implementation** for Zos reflection layers.
See `plan/plan.md` Phase 9 for implementation details.
