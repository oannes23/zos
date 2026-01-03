# Zos

Reflective Discord agent that observes conversations and generates insights.

**Note:** Files in `plan/archived/` are historical documents. Ignore them unless explicitly asked to review archived content.

## Commands

```bash
uv run pytest              # Run tests
uv run ruff check src      # Lint
uv run mypy src/zos        # Type check
uv run python -m zos       # Run bot (needs DISCORD_TOKEN)
uv run python -m zos.cli salience top --category user  # View salience
uv run python -m zos.cli budget preview                # Preview budget allocation
uv run python -m zos.cli llm list                      # List configured LLM providers
uv run python -m zos.cli llm test --provider openai    # Test LLM provider connection
uv run python -m zos.cli layer list                    # List available layers
uv run python -m zos.cli layer validate channel_digest # Validate a layer definition
uv run python -m zos.cli layer dry-run channel_digest  # Dry-run a layer
uv run python -m zos.cli layer run channel_digest      # Run a layer manually
uv run python -m zos.cli runs list                     # List recent runs
uv run python -m zos.cli runs show <run_id>            # Show run details
uv run python -m zos.cli runs show <run_id> --trace    # Show run with execution trace
uv run python -m zos.cli insights list                 # List recent insights
uv run python -m zos.cli insights list --topic channel:123  # Filter by topic
uv run python -m zos.cli insights show <insight_id>    # Show insight details
uv run python -m zos.cli insights show <insight_id> --full  # Show with payload and sources
```

## Behavior
- After you make a change, make sure to update any relevant markdown files if the change needs to be reflected in that documentation

## Structure

```
src/zos/           # Main application
  config.py        # Pydantic config models
  db.py            # SQLite + migrations
  discord/         # Discord client, repository, backfill
  topics/          # TopicKey system (canonical key formats)
  salience/        # Salience ledger (earn/spend tracking)
  budget/          # Budget allocation (token distribution by salience)
  llm/             # LLM abstraction (providers, retry, prompts)
  layer/           # Layer execution engine (schema, executor, nodes)
  scheduler/       # Run scheduling (APScheduler, run management)
  insights/        # Insights storage (reflection outputs with source tracking)
  cli/             # CLI tools (salience, budget, llm, layer, runs, insights)
tests/             # pytest tests
config/            # config.example.yml
plan/              # Architecture docs
  project.md       # Full spec
  plan.md          # Implementation phases
layers/            # Reflection layer definitions (YAML + prompts)
  channel_digest/  # Example layer for channel summaries
```

## Key Files

- `config/config.example.yml` - All config options
- `plan/project.md` - Architecture and design spec
- `plan/plan.md` - Phased implementation plan
