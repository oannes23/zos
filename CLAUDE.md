# Zos

Reflective Discord agent that observes conversations and generates insights.

## Commands

```bash
uv run pytest              # Run tests
uv run ruff check src      # Lint
uv run mypy src/zos        # Type check
uv run python -m zos       # Run bot (needs DISCORD_TOKEN)
```

## Structure

```
src/zos/           # Main application
  config.py        # Pydantic config models
  db.py            # SQLite + migrations
  discord/         # Discord client, repository, backfill
tests/             # pytest tests
config/            # config.example.yml
plan/              # Architecture docs
  project.md       # Full spec
  plan.md          # Implementation phases
layers/            # Reflection layer definitions (future)
```

## Key Files

- `config/config.example.yml` - All config options
- `plan/project.md` - Architecture and design spec
- `plan/plan.md` - Phased implementation plan
