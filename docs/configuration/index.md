# Configuration

Zos is configured through YAML files and environment variables.

---

## Configuration Sources

1. **config.yaml** — Primary configuration file
2. **Environment variables** — Secrets and overrides
3. **Layer files** — Cognitive pipeline definitions

---

## Quick Reference

```yaml
# config.yaml - minimal working configuration

data_dir: ./data
log_level: INFO

discord:
  polling_interval_seconds: 60
  operators:
    user_ids:
      - "YOUR_DISCORD_USER_ID"

models:
  profiles:
    simple:
      provider: anthropic
      model: claude-3-5-haiku-20241022
    moderate:
      provider: anthropic
      model: claude-sonnet-4-20250514
    complex:
      provider: anthropic
      model: claude-opus-4-20250514
    reflection: moderate
    conversation: moderate

  providers:
    anthropic:
      api_key_env: ANTHROPIC_API_KEY
```

```bash
# Required environment variables
export DISCORD_TOKEN=your_bot_token
export ANTHROPIC_API_KEY=your_api_key
```

---

## Documentation

- [Config Reference](config-reference.md) — Complete config.yaml documentation
- [Environment Variables](environment-variables.md) — Required and optional env vars
- [Model Profiles](model-profiles.md) — LLM provider and model setup

---

## Validation

Always validate configuration before running:

```bash
zos config check -c config.yaml
```

---

## Configuration Philosophy

Zos configuration follows these principles:

1. **Sensible defaults** — Most settings work out of the box
2. **Explicit overrides** — Change only what you need
3. **Secrets in environment** — Never commit tokens to files
4. **Server-specific tuning** — Override per Discord server

The goal is a configuration that starts simple and grows with your needs.
