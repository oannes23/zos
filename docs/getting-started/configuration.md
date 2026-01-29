# Configuration

Zos is configured through a YAML file (`config.yaml`) and environment variables.

---

## Quick Setup

```bash
# Copy the example configuration
cp config.yaml.example config.yaml

# Set required environment variables
export DISCORD_TOKEN=your_bot_token
export ANTHROPIC_API_KEY=your_api_key
```

Edit `config.yaml` with your specific settings.

---

## Minimum Configuration

The defaults work for most setups. At minimum, you need:

1. **Environment variables** (see below)
2. **Operator IDs** in config.yaml for slash command access

```yaml
discord:
  operators:
    user_ids:
      - "YOUR_DISCORD_USER_ID"  # Your 18-digit Discord user ID
```

To find your Discord user ID: Enable Developer Mode in Discord settings, then right-click your name and select "Copy User ID".

---

## Required Environment Variables

| Variable | Description |
|----------|-------------|
| `DISCORD_TOKEN` | Bot token from Discord Developer Portal |
| `ANTHROPIC_API_KEY` | API key from Anthropic Console |

Optional environment variables:
| Variable | Description |
|----------|-------------|
| `ZOS_DATA_DIR` | Override the data directory |
| `ZOS_LOG_LEVEL` | Override log level (DEBUG, INFO, WARNING, ERROR) |
| `ZOS_LOG_JSON` | Override JSON logging (true/false) |

---

## Configuration Sections

### General

```yaml
data_dir: ./data          # Where database and files are stored
log_level: INFO           # DEBUG, INFO, WARNING, ERROR
log_json: true            # true for JSON logs, false for console
```

### Discord

```yaml
discord:
  polling_interval_seconds: 60   # How often to check for new messages
  # bot_user_id: null            # Auto-detected at runtime; set for API-only mode
  operators:
    user_ids:
      - "123456789012345678"     # Discord user IDs with operator access
    role_id: null                # Optional: role that grants operator access
```

`bot_user_id` is auto-detected when the bot connects to Discord. You only need to set it manually if running the API without the bot (e.g., for UI debugging).

### Models

```yaml
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

    # Semantic aliases
    reflection: moderate
    conversation: moderate
    self_reflection: complex

  providers:
    anthropic:
      api_key_env: ANTHROPIC_API_KEY
```

See [Model Profiles](../configuration/model-profiles.md) for detailed configuration.

---

## Validating Configuration

Test your configuration before running:

```bash
zos config check -c config.yaml
```

Output shows:
- Configuration validity
- Data directory path
- Database path
- Configured model profiles

---

## Server-Specific Overrides

Override settings per Discord server:

```yaml
servers:
  "123456789012345678":       # Discord server ID
    privacy_gate_role: "987654321098765432"  # Only track users with this role
    threads_as_topics: false  # Don't create separate topics for threads
```

---

## Next Step

[First Run](first-run.md) — Start Zos and verify everything works
