# Zos

A reflective Discord agent that watches, thinks, and remembers.

## The Idea

Most Discord bots react to commands. Zos is different—it's designed to *understand* a community over time.

Zos quietly observes the conversations happening in your Discord server. It notices who's talking, what they're talking about, and how people interact with each other. Periodically, it reflects on what it's seen and builds up a persistent understanding of the community.

Think of it like having a thoughtful community member who pays attention to everything, remembers context, and can offer insights when asked—without being intrusive or creepy about it.

## How It Works

**1. Observe**

Zos watches messages and reactions in channels you configure. It stores everything locally in a SQLite database. Users can opt-in to full tracking via a Discord role, or remain "background" participants (messages stored but not reflected upon).

**2. Allocate Attention**

Not everything deserves equal attention. Zos uses a "salience" system to decide what's worth thinking about. Active users and busy channels accumulate salience points. When it's time to reflect, Zos spends its thinking budget on the most salient topics first.

**3. Reflect**

On a schedule (e.g., nightly), Zos runs "reflection layers"—structured analysis passes that generate insights. A channel digest layer might summarize what happened today. A social dynamics layer might notice who's been chatting with whom. Each layer produces insights that get stored for future context.

**4. Remember**

Insights persist. When Zos reflects again tomorrow, it can reference what it learned yesterday. Over time, it builds a layered understanding of your community—who the regulars are, what topics come up often, which conversations were particularly interesting.

## Key Concepts

- **Salience**: A budget system. Users and channels earn salience through activity. Zos spends salience to think about them. High-activity topics get more reflection time.

- **Topics**: Things Zos can think about. A user (`user:alice`), a channel (`channel:general`), a pair of users who interact (`dyad:alice:bob`), etc.

- **Layers**: Scheduled reflection tasks defined in YAML. Each layer fetches relevant messages, calls an LLM to analyze them, and stores the resulting insights.

- **Insights**: Persistent summaries and observations. "The #general channel discussed the upcoming event" or "Alice and Bob have been collaborating on the design project."

## Current Status

Zos is in early development. Currently implemented:

- **Phase 1**: Project foundation (config, database, logging)
- **Phase 2**: Discord ingestion (message/reaction capture, backfill)

Coming next: salience tracking, budget allocation, LLM integration, and the first reflection layers.

## Quick Start

```bash
# Clone and setup
git clone <repo-url>
cd zos
uv sync

# Configure
cp config/config.example.yml config/config.yml
# Edit config.yml with your settings

# Set your Discord bot token
export ZOS_DISCORD__TOKEN="your-token-here"

# Run
uv run python -m zos
```

The bot will connect to Discord, backfill recent messages from configured channels, and start logging new activity.

## Configuration Highlights

See `config/config.example.yml` for all options. Key settings:

- `discord.guilds`: Which servers to watch (empty = all)
- `discord.excluded_channels`: Channels to ignore (opt-out)
- `discord.tracking_opt_in_role`: Role name for full user tracking
- `budget.total_tokens_per_run`: LLM token budget per reflection cycle

## Digging Deeper

- **Architecture & Design**: `plan/project.md` has the full specification
- **Implementation Roadmap**: `plan/plan.md` breaks the build into phases
- **All Config Options**: `config/config.example.yml` is well-commented

## Development

```bash
uv run pytest           # Run tests
uv run ruff check src   # Lint
uv run mypy src/zos     # Type check
```

## Privacy Note

Zos stores Discord messages locally. Users without the tracking opt-in role have their messages stored but receive zero salience (Zos won't actively reflect on them). DM ingestion requires explicit opt-in. The system is designed to be transparent about what it observes and respects user consent boundaries.
