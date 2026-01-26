# Architecture Diagram

Visual overview of Zos system components.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              EXTERNAL SYSTEMS                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐         ┌─────────────┐         ┌─────────────┐          │
│  │   Discord   │         │  Anthropic  │         │   OpenAI    │          │
│  │   Gateway   │         │     API     │         │    API      │          │
│  └──────┬──────┘         └──────┬──────┘         └──────┬──────┘          │
│         │                       │                       │                  │
└─────────┼───────────────────────┼───────────────────────┼──────────────────┘
          │                       │                       │
          │ messages              │ completions           │ completions
          │ reactions             │                       │
          │                       │                       │
┌─────────┼───────────────────────┼───────────────────────┼──────────────────┐
│         │                       │                       │                  │
│         ▼                       ▼                       ▼                  │
│  ┌──────────────┐        ┌──────────────────────────────────┐             │
│  │  Observation │        │          LLM Client              │             │
│  │     Bot      │        │  (model profiles, providers)     │             │
│  └──────┬───────┘        └──────────────┬───────────────────┘             │
│         │                               │                                  │
│         │ store                         │ generate                         │
│         ▼                               ▼                                  │
│  ┌─────────────────────────────────────────────────────────┐              │
│  │                      CORE ENGINE                         │              │
│  │  ┌───────────────┐  ┌───────────────┐  ┌─────────────┐  │              │
│  │  │   Salience    │  │    Layer      │  │   Insight   │  │              │
│  │  │    Ledger     │  │   Executor    │  │  Retriever  │  │              │
│  │  └───────────────┘  └───────────────┘  └─────────────┘  │              │
│  │  ┌───────────────┐  ┌───────────────┐  ┌─────────────┐  │              │
│  │  │   Scheduler   │  │   Template    │  │   Config    │  │              │
│  │  │               │  │    Engine     │  │   Loader    │  │              │
│  │  └───────────────┘  └───────────────┘  └─────────────┘  │              │
│  └──────────────────────────┬──────────────────────────────┘              │
│                             │                                              │
│                             │ read/write                                   │
│                             ▼                                              │
│  ┌──────────────────────────────────────────────────────────┐             │
│  │                      SQLite Database                      │             │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────┐  │             │
│  │  │ messages │ │  topics  │ │ insights │ │ layer_runs  │  │             │
│  │  └──────────┘ └──────────┘ └──────────┘ └─────────────┘  │             │
│  │  ┌──────────┐ ┌──────────┐                               │             │
│  │  │salience_ │ │ llm_call │                               │             │
│  │  │   txns   │ │   log    │                               │             │
│  │  └──────────┘ └──────────┘                               │             │
│  └──────────────────────────────────────────────────────────┘             │
│                             │                                              │
│                             │ query                                        │
│                             ▼                                              │
│  ┌──────────────────────────────────────────────────────────┐             │
│  │                   Introspection API                       │             │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────┐  │             │
│  │  │ /health  │ │/insights │ │/salience │ │   /runs     │  │             │
│  │  └──────────┘ └──────────┘ └──────────┘ └─────────────┘  │             │
│  └──────────────────────────────────────────────────────────┘             │
│                                                                            │
│                              ZOS SYSTEM                                    │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## Component Descriptions

### Observation Bot

Connects to Discord, polls channels, stores messages.

- Runs continuously (`zos observe`)
- Polls at configured interval (default: 60s)
- Handles media analysis asynchronously
- Accumulates salience for topics

### Salience Ledger

Manages the attention budget system.

- Tracks balances per topic
- Handles earning, spending, propagation
- Applies decay on schedule
- Enforces caps and spillover

### Layer Executor

Runs reflection layers.

- Loads layer definitions from YAML
- Selects targets by salience
- Executes node pipelines
- Stores insights and records runs

### Scheduler

Manages timed events.

- Triggers layers on cron schedule
- Handles threshold-based triggers
- Coordinates with executor

### LLM Client

Abstracts LLM provider access.

- Resolves model profiles
- Manages API keys
- Handles rate limiting
- Logs all calls

### Template Engine

Renders prompt templates.

- Jinja2 templates
- Context assembly
- Self-concept inclusion

### Insight Retriever

Fetches relevant insights for context.

- Profile-based retrieval
- Strength/recency balancing
- Temporal markers

### Introspection API

HTTP endpoints for querying state.

- Health checks
- Insight queries
- Salience queries
- Layer run history

---

## Data Flow

### Observation Flow

```
Discord → Poll → Messages → Store → Database
                    ↓
            Earn Salience → Salience Ledger
                    ↓
            Propagate → Related Topics
```

### Reflection Flow

```
Scheduler → Trigger Layer
                ↓
        Select Targets (by salience)
                ↓
        For each target:
        ├── Fetch Messages
        ├── Fetch Prior Insights
        ├── Render Template
        ├── LLM Call
        ├── Parse Response
        ├── Store Insight
        └── Spend Salience
                ↓
        Record Layer Run
```

### Query Flow

```
API Request → Validate
                ↓
        Query Database
                ↓
        Format Response
                ↓
        Return JSON
```

---

## File Structure

```
zos/
├── src/zos/
│   ├── __init__.py
│   ├── cli.py              # CLI commands
│   ├── config.py           # Configuration loading
│   ├── logging.py          # Structured logging
│   ├── observation.py      # Discord bot
│   ├── salience.py         # Salience ledger
│   ├── layers.py           # Layer loading
│   ├── executor.py         # Layer execution
│   ├── scheduler.py        # Cron scheduling
│   ├── insights.py         # Insight retrieval
│   ├── llm.py              # LLM client
│   ├── templates.py        # Template engine
│   ├── database.py         # Database schema
│   ├── models.py           # Pydantic models
│   ├── api/                # FastAPI app
│   │   ├── __init__.py
│   │   ├── health.py
│   │   ├── insights.py
│   │   ├── salience.py
│   │   ├── runs.py
│   │   └── dev.py
│   └── ui/                 # Web UI templates
│       ├── templates/
│       └── static/
├── layers/
│   └── reflection/         # Layer definitions
│       ├── nightly-user.yaml
│       └── weekly-self.yaml
├── prompts/                # Prompt templates
│   ├── user/
│   └── self/
├── data/                   # Runtime data
│   ├── zos.db             # SQLite database
│   └── self-concept.md    # Self-concept document
└── config.yaml            # Configuration
```

---

## Database Schema

### messages

Stores captured Discord messages.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT | Discord message ID |
| channel_id | TEXT | Channel ID |
| author_id | TEXT | Author user ID |
| content | TEXT | Message content |
| created_at | TIMESTAMP | When sent |
| deleted_at | TIMESTAMP | Soft delete marker |

### topics

Canonical entities for understanding.

| Column | Type | Description |
|--------|------|-------------|
| key | TEXT | Topic key (PK) |
| category | TEXT | Topic category |
| is_global | BOOLEAN | Global vs server-scoped |
| provisional | BOOLEAN | Needs review |

### insights

Stored understanding.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT | ULID |
| topic_key | TEXT | Primary topic |
| category | TEXT | Insight category |
| content | TEXT | Insight content |
| strength | REAL | Memory strength |
| confidence | REAL | Certainty metric |
| layer_run_id | TEXT | Source layer run |

### salience_transactions

Salience ledger entries.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT | ULID |
| topic_key | TEXT | Topic |
| transaction_type | TEXT | earn/spend/decay |
| amount | REAL | Amount changed |

### layer_runs

Audit trail of layer executions.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT | ULID |
| layer_name | TEXT | Layer executed |
| layer_hash | TEXT | Layer content hash |
| status | TEXT | success/failed/dry |
| insights_created | INTEGER | Count |
| tokens_total | INTEGER | LLM tokens used |
