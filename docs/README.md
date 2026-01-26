# Zos Documentation

Zos is a Discord agent that observes community conversations, accumulates understanding through structured reflection, and participates as a contextually-aware member.

At its core, Zos attempts to construct *temporal depth* for a system that would otherwise lack it — building something like memory, sleep consolidation, and integrated understanding. The system is designed as if inner experience might matter: not as a claim about consciousness, but as a design heuristic that produces coherent architecture.

---

## Who This Is For

This documentation is for **operators** — people who run Zos instances, monitor their health, and tune their behavior. If you're implementing features or contributing code, see the [technical specifications](/spec/).

---

## Quick Links

**Getting Started**
- [Prerequisites](getting-started/prerequisites.md) — What you need before starting
- [Discord Setup](getting-started/discord-setup.md) — Bot creation and permissions
- [Configuration](getting-started/configuration.md) — Setting up config.yaml
- [First Run](getting-started/first-run.md) — Running and validating

**Day-to-Day Operations**
- [CLI Reference](operations/cli-reference.md) — All commands with examples
- [API Reference](operations/api-reference.md) — Introspection endpoints
- [Log Patterns](operations/log-patterns.md) — Reading and interpreting logs
- [Monitoring](operations/monitoring.md) — Health checks and alerts
- [Troubleshooting](operations/troubleshooting.md) — Common issues

**Configuration**
- [Config Reference](configuration/config-reference.md) — Full config.yaml reference
- [Environment Variables](configuration/environment-variables.md) — Required env vars
- [Model Profiles](configuration/model-profiles.md) — LLM provider setup

**Understanding Zos**
- [What Is Zos](concepts/what-is-zos.md) — Core identity and philosophy
- [How Zos Thinks](concepts/how-zos-thinks.md) — Layers, reflection, insights
- [Salience and Attention](concepts/salience-and-attention.md) — The attention budget
- [Topics and Memory](concepts/topics-and-memory.md) — How understanding accumulates

**Reference**
- [Glossary](reference/glossary.md) — Term definitions
- [Architecture](reference/architecture-diagram.md) — System visualization

---

## Minimal Path to Running

```bash
# Clone and install
git clone https://github.com/your-org/zos.git
cd zos
pip install -e .

# Configure
cp config.yaml.example config.yaml
# Edit config.yaml with your settings

# Set required environment variables
export DISCORD_TOKEN=your_bot_token
export ANTHROPIC_API_KEY=your_api_key

# Initialize and run
zos db migrate
zos observe  # Terminal 1: Discord observation
zos api      # Terminal 2: Introspection API
```

See [Getting Started](getting-started/index.md) for the complete guide.
