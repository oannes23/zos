# Environment Variables

Secrets and runtime overrides for Zos.

---

## Required

### DISCORD_TOKEN

Your Discord bot token from the Developer Portal.

```bash
export DISCORD_TOKEN=MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.XXXXXX.XXXXXXXXXXXXXXXXXXXXXXXX
```

**Where to find it:**
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Select your application → Bot
3. Click "Copy" under Token

**Security:**
- Never commit this token to version control
- Rotate immediately if exposed
- Use secrets management in production

### ANTHROPIC_API_KEY

Your Anthropic API key for Claude models.

```bash
export ANTHROPIC_API_KEY=sk-ant-api03-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

**Where to find it:**
1. Go to [Anthropic Console](https://console.anthropic.com/)
2. Navigate to API Keys
3. Create or copy an existing key

---

## Optional Overrides

These override corresponding config.yaml settings.

### ZOS_DATA_DIR

Override the data directory.

```bash
export ZOS_DATA_DIR=/var/lib/zos/data
```

Overrides: `data_dir` in config.yaml

### ZOS_LOG_LEVEL

Override the log level.

```bash
export ZOS_LOG_LEVEL=DEBUG
```

Values: `DEBUG`, `INFO`, `WARNING`, `ERROR`

Overrides: `log_level` in config.yaml

### ZOS_LOG_JSON

Override JSON logging.

```bash
export ZOS_LOG_JSON=false
```

Values: `true`, `false`

Overrides: `log_json` in config.yaml

---

## Additional Provider Keys

If using other LLM providers:

### OPENAI_API_KEY

For OpenAI models (if configured).

```bash
export OPENAI_API_KEY=sk-XXXXXXXXXXXXXXXXXXXXXXXX
```

The environment variable name is configurable per provider in `config.yaml`:

```yaml
models:
  providers:
    openai:
      api_key_env: OPENAI_API_KEY    # Can be customized
```

---

## Setting Variables

### Shell (temporary)

```bash
export DISCORD_TOKEN=your_token
export ANTHROPIC_API_KEY=your_key
zos observe
```

### Shell Profile (persistent)

Add to `~/.bashrc`, `~/.zshrc`, or equivalent:

```bash
export DISCORD_TOKEN=your_token
export ANTHROPIC_API_KEY=your_key
```

### .env File (development)

Create a `.env` file (add to `.gitignore`):

```
DISCORD_TOKEN=your_token
ANTHROPIC_API_KEY=your_key
```

Load with your preferred method (direnv, dotenv, etc.).

### Systemd Service

In your service file:

```ini
[Service]
Environment="DISCORD_TOKEN=your_token"
Environment="ANTHROPIC_API_KEY=your_key"
```

Or use an environment file:

```ini
[Service]
EnvironmentFile=/etc/zos/secrets
```

### Docker

```bash
docker run -e DISCORD_TOKEN=your_token -e ANTHROPIC_API_KEY=your_key zos

# Or with env file
docker run --env-file .env zos
```

---

## Security Best Practices

1. **Never commit secrets** — Use `.gitignore` for any files containing tokens
2. **Use secrets managers** — In production, use Vault, AWS Secrets Manager, etc.
3. **Rotate regularly** — Change tokens periodically
4. **Limit scope** — Use API keys with minimal required permissions
5. **Audit access** — Monitor who has access to secrets

---

## Verification

Check that variables are set:

```bash
# Should output something (don't share this!)
echo $DISCORD_TOKEN | head -c 10

# Verify Zos can see them
zos config check
```

If tokens aren't loading:
- Check spelling (case-sensitive)
- Ensure no quotes around values in shell
- Restart shell after changing profile
- Check systemd/Docker environment configuration
