# Getting Started

This guide walks you through setting up and running a Zos instance.

---

## Quick Start

If you're already familiar with Discord bots and Python environments:

```bash
# 1. Clone and install
git clone https://github.com/your-org/zos.git
cd zos
pip install -e .

# 2. Configure
cp config.yaml.example config.yaml
# Edit config.yaml with your settings

# 3. Set environment variables
export DISCORD_TOKEN=your_bot_token
export ANTHROPIC_API_KEY=your_api_key

# 4. Initialize database
zos db migrate

# 5. Run (two terminals)
zos observe  # Terminal 1
zos api      # Terminal 2
```

---

## Step-by-Step Guide

1. **[Prerequisites](prerequisites.md)** — Install Python, create a virtual environment
2. **[Discord Setup](discord-setup.md)** — Create a Discord bot and configure permissions
3. **[Configuration](configuration.md)** — Set up config.yaml and environment variables
4. **[First Run](first-run.md)** — Start Zos and verify everything works

---

## What You'll Have Running

After completing this guide:

- **Observation bot** connected to Discord, watching your configured servers
- **API server** at `http://localhost:8000` for introspection
- **Scheduled reflection** running nightly to process accumulated observations

---

## Next Steps

Once Zos is running:

- [Monitor health](../operations/monitoring.md) via the API
- [Read logs](../operations/log-patterns.md) to understand what's happening
- [Explore insights](../operations/api-reference.md#insights) via the API
- [Tune configuration](../configuration/index.md) as needed
