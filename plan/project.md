# Zos — Reflective Discord Agent Architecture (Project Summary)

## Overview

**Zos** is a Discord chat bot designed to behave like a normal server member while maintaining a rich internal reflective process. During the day, Zos observes conversations and may occasionally participate. On configurable schedules (nightly, weekly, monthly), it runs structured self-analysis routines that synthesize observations into persistent internal memory (“Insights”), gradually evolving its personality, social understanding, and behavior.

The system prioritizes:
- **Clarity over cleverness**
- **Deterministic, auditable behavior**
- **Local-first execution** (SQLite + local models)
- **Configurable, extensible architecture** (no hard-coded layers)

---

## Core Design Principles

- **Observer / Reflector split**
  - Daytime: ingest events, accumulate salience, minimal LLM usage.
  - Reflection windows: bounded, scheduled, deterministic LLM pipelines.

- **Linear, defined flows**
  - Reflection logic is explicit and reproducible.
  - No unbounded trigger chains or recursive execution.

- **ECS-inspired internal model**
  - Entities = Topics (users, channels, combinations).
  - Components = stored state / models attached to topics.
  - Events = observed Discord events + internal derived events.
  - Systems = Layers that operate on topics and components.

- **Salience-driven budgeting**
  - Attention and compute are allocated based on accumulated salience.
  - Prevents runaway analysis and prioritizes what “matters.”

---

## Technology Stack

- **Language:** Python
- **Environment / deps:** `uv`
- **Discord:** Popular open-source Discord bot library (non-official)
- **Web API:** FastAPI
- **Storage:** SQLite (single local file)
- **Scheduling:** APScheduler or equivalent
- **LLMs:**
  - Abstracted provider interface
  - Supports:
    - Cloud APIs (OpenAI, Anthropic, etc.)
    - Local HTTP endpoints (Ollama, llama.cpp, vLLM, custom)
  - Model selection hierarchy:
    - Global default
    - Layer default
    - Node override

---

## Data Model (High Level)

### Message & Reaction Logging
- Messages:
  - `message_id`, `guild_id`, `channel_id`, `thread_id`
  - `author_id`, `author_roles_snapshot`
  - `content`, `created_at`
  - `visibility_scope` (public / DM)
- Reactions:
  - `message_id`, `emoji`, `user_id`, `created_at`

### TopicKeys (Canonical)
Used for salience, insights, and targeting.

- `user:<user_id>`
- `channel:<channel_id>`
- `user_in_channel:<channel_id>:<user_id>`
- `dyad:<user_a>:<user_b>` (sorted)
- `dyad_in_channel:<channel_id>:<user_a>:<user_b>`

Each Insight has exactly **one** TopicKey.

---

## Salience System

### Salience Ledger
Salience is **earned and spent**, not just a score.

- Earned via (configurable weights):
  - Messages: 1.0 points per message
  - Reactions given: 0.5 points
  - Reactions received: 0.3 points
  - Mentions/replies: 0.5 bonus points (added to dyad keys)
- Stored as:
  - `salience_earned(topic_key, category, timestamp, amount, reason, message_id)`
  - `salience_spent(topic_key, category, run_id, layer, node, amount)`

### Budget Allocation
- Total reflection budget per run (tokens).
- Budget divided by **Topic Category Weights** (default values):
  - User: 40
  - Channel: 40
  - User in Channel: 15
  - Dyad: 5
  - Dyad in Channel: 0
- Each category allocates budget internally to its highest-salience topics.
- Per-topic caps enforced.

### Cost Model
- Primary cost unit: **tokens**
- Estimated pre-call, actual recorded post-call.
- Local models allowed fixed or estimated token pricing.

---

## Layers

### Concept
A **Layer** is a configurable reflection or action system defined entirely in YAML.

- No hard-coded layers in code.
- Each Layer defines:
  - Schedule
  - Target topic categories
  - Salience spending rules
  - Linear pipeline of nodes
  - Model defaults
  - Optional outputs

### Schedules
- Cron-like schedules:
  - Nightly
  - Weekly
  - Monthly
- Execution window:
  - “Since last successful run”
  - Max lookback cap
- Multiple layers may run on the same schedule.

### Example Layers
- Social Layer (nightly):
  - Analyze channel and user interactions.
  - Infer social dynamics, emoji semantics.
- Conversational Layer (continuous/lightweight):
  - Decide whether Zos should speak.
  - Output only to configured channels.
- Self-Optimization Layer (future):
  - Reads codebase and layer definitions from filesystem.
  - Produces feature requests or PR drafts (human-reviewed).

---

## Layer Execution Model

### Pipeline Style
- **Linear pipeline** (internally represented as DAG-ready).
- Supports:
  - `for_each` target expansion
  - Multiple persona LLM calls
  - Reduction / summarization
  - Insight storage
  - Optional output

### Nodes (Conceptual)
- `fetch_messages`
- `fetch_insights`
- `llm_call` (persona-specific)
- `reduce`
- `store_insight`
- `output`

Each node:
- Has explicit inputs and outputs.
- May override model selection.
- Has a known estimated cost.

---

## LLM Personas & Dialogues

- Personas are configuration, not code.
- Multi-persona “dialogue” = orchestrated node sequence.
- Each persona node:
  - Receives scoped context blocks.
  - Produces text + metadata + source references.
- Dialogue stops by:
  - Fixed turns, or
  - Explicit termination token.

---

## Privacy & DM Policy

- Users with the required role explicitly opt in.
- DM messages **are stored**.
- DM **text is never directly included** in public outputs.
- Derived insights **may reference DM-derived understanding**.
- Every Insight carries:
  - `sources_scope_max`
- Context assembly enforces:
  - Public outputs cannot include raw private text.

---

## Conversational Behavior

- Zos observes all configured channels.
- Zos speaks only in allowed channels (default: one).
- Triggers:
  - Mentions / replies
  - Salience spikes
- Rate-limited and budgeted.
- DM conversations allowed.

---

## Configuration

### Root `config.yml`
- Discord connection
- Watched guilds/channels
- Role gating
- Model providers
- Global budgets
- Category weights
- Enabled layers

### Layers
- Each Layer in its own directory:
  - `layer.yml`
  - `prompts/`
  - `README.md`
- Layers included by reference from root config.

---

## Storage & Memory

- **SQLite only** (single file).
- Insights stored as:
  - Natural language summary
  - Structured JSON payload
  - TopicKey
  - Timestamp
  - Source references
- Schema designed so:
  - Vector embeddings can be added later without breaking data.

---

## Auditability & Introspection

### Run Artifacts
Every reflection run records:
- Run ID
- Layer name
- Schedule
- Targets considered
- Targets skipped + reasons
- Salience spent
- LLM calls:
  - model
  - tokens
  - cost
- Outputs generated

### Web API (FastAPI)
Simple, no-frills endpoints:
- `/health`
- `/config`
- `/layers`
- `/runs`
- `/runs/{id}`
- `/insights`
- `/salience`
- `/audit`

Outputs JSON/YAML only. No fancy UI.

---

## Testing Strategy

- Unit tests for:
  - SQLite queries
  - Salience ledger
  - Budget allocator
  - Context assembly
  - Layer YAML validation
- LLM calls fully mocked.
- Snapshot (“golden”) integration tests for full layer runs.

---

## Future-Proofing Hooks

- Filesystem context access for Layers (read-only initially).
- Git integration planned:
  - Layers can propose new Layers or changes.
  - PRs reviewed by humans.
- Embeddings / vector DB optional later.
- Additional salience heuristics pluggable.

---

## MVP Implementation Order

1. Repo skeleton + config loading
2. Discord ingest → SQLite
3. Salience ledger + allocator
4. Layer execution engine (linear pipeline)
5. LLM abstraction
6. First nightly layer (channel digest)
7. Audit endpoints
8. Conversational layer

---

**Status:** Phases 1-3 complete. Proceeding to Phase 4 (Budget Allocation).
