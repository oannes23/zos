# Operations

Day-to-day operation and monitoring of a Zos instance.

---

## Overview

Running Zos involves two primary processes:

1. **Observation bot** (`zos observe`) — Connects to Discord, watches conversations, accumulates salience
2. **API server** (`zos api`) — Provides introspection endpoints for monitoring and debugging

Reflection happens automatically via scheduled layers (typically nightly).

---

## Quick Reference

### Starting Zos

```bash
# Terminal 1: Discord observation
zos observe

# Terminal 2: Introspection API
zos api --port 8000
```

### Health Check

```bash
curl http://localhost:8000/health
```

### View Recent Activity

```bash
# Top topics by salience
curl http://localhost:8000/salience

# Recent insights
curl http://localhost:8000/insights

# Recent messages
curl http://localhost:8000/messages

# Layer run history
curl http://localhost:8000/runs
```

### Web UI

A web-based dashboard is available for browsing data visually:

```
http://localhost:8000/ui/
```

Pages available:
- `/ui/messages` — Browse and search stored messages
- `/ui/insights` — Browse and filter insights
- `/ui/users` — Browse users sorted by insight count
- `/ui/channels` — Browse channels sorted by message count
- `/ui/media` — Browse link analyses, image descriptions, and YouTube summaries
- `/ui/salience` — Salience dashboard with budget groups
- `/ui/budget` — Track API costs, token usage, and spending over time
- `/ui/layers` — Browse configured reflection layers and their pipelines
- `/ui/runs` — Layer run history and stats

---

## Documentation

- [CLI Reference](cli-reference.md) — All commands with examples
- [API Reference](api-reference.md) — Introspection endpoints
- [Log Patterns](log-patterns.md) — Reading and interpreting logs
- [Monitoring](monitoring.md) — Health checks, dashboards, alerts
- [Troubleshooting](troubleshooting.md) — Common issues and solutions

---

## Operational Modes

### Observe Mode (Daytime)

During observation, Zos:
- Polls Discord channels at configured intervals
- Stores messages to the database
- Accumulates salience for relevant topics
- Responds to direct triggers (mentions, DMs)
- Uses minimal LLM resources

### Reflect Mode (Nighttime)

During scheduled reflection, Zos:
- Runs reflection layers (typically at 3 AM)
- Processes high-salience topics
- Generates insights from accumulated observations
- Spends salience budget
- Updates understanding

The sleep/wake metaphor is intentional: observations during the day consolidate into understanding at night.
