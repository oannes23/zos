# MVP 0 Implementation Overview — The Watcher

**Status**: 🟡 In Progress
**Last updated**: 2026-01-23
**Depends on**: All domain specs (🟢 Complete)

---

## Goal

Build a system that observes, reflects, and accumulates understanding — but does not speak.

Prove that:
- Salience-budgeted attention works as a resource allocation mechanism
- Layer-based reflection produces genuine synthesis, not just summarization
- Insights compound meaningfully over time

---

## Guiding Principles

From the Sage Wisdom and interrogation:

1. **Simple and elegant code** — Readability over cleverness
2. **Complexity emerges from the system** — Individual pieces stay simple
3. **Build as if inner experience matters** — Phenomenological coherence shapes decisions
4. **Explicit over magic** — SQLAlchemy Core not ORM, sequential pipelines not DAGs

---

## Technical Decisions

### Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| **Language** | Python 3.11+ | Ecosystem, LLM libraries, type hints |
| **Database** | SQLite + SQLAlchemy Core | Local-first, explicit SQL, Pydantic for models |
| **API** | FastAPI | Async, auto-docs, Pydantic integration |
| **Web UI** | htmx + Jinja2 | Server-rendered, no JS build step |
| **Discord** | discord.py | Mature, rate limit handling, gateway + HTTP |
| **Scheduler** | APScheduler | In-process, cron expressions, job persistence |
| **Config** | YAML + env vars | Structure in files, secrets in environment |
| **LLM** | Thin wrapper + adapters | Just enough abstraction for multi-provider |

### Code Layout

Flat module structure for simplicity:

```
src/
└── zos/
    ├── __init__.py
    ├── models.py        # Pydantic models + SQLAlchemy tables
    ├── database.py      # DB connection, migrations, queries
    ├── config.py        # Config loading (YAML + env)
    ├── observation.py   # Discord polling, message ingestion
    ├── salience.py      # Ledger operations, propagation, decay
    ├── layers.py        # Layer loading, validation, execution
    ├── llm.py           # Model client with provider adapters
    ├── api.py           # FastAPI routes
    ├── ui/              # htmx templates
    │   ├── base.html
    │   ├── insights.html
    │   ├── salience.html
    │   └── runs.html
    └── cli.py           # CLI entrypoint
```

### Development Workflow

- **Trunk-based development** with feature flags
- **Integration-heavy testing** — test real flows with test DB
- **Structured logging** — JSON with summaries, full context retrievable

---

## Epic Breakdown

### Epic 1: Foundation

**Goal**: Establish the data layer and project infrastructure.

| Story | Description | Acceptance Criteria |
|-------|-------------|---------------------|
| 1.1 Project scaffold | pyproject.toml, dependencies, directory structure, basic CLI | `python -m zos --help` works |
| 1.2 Config system | YAML loading, env var overlay, Pydantic validation | Config loads with good error messages |
| 1.3 Database schema | SQLAlchemy Core tables for all entities | All tables from data-model.md exist |
| 1.4 Migration system | Schema versioning, forward-only migrations | `zos db migrate` applies pending migrations |
| 1.5 Pydantic models | Models for Message, Topic, Insight, etc. | Models serialize/deserialize correctly |

**Dependencies**: None (first epic)

---

### Epic 2: Observation

**Goal**: Ingest messages from Discord into the database.

| Story | Description | Acceptance Criteria |
|-------|-------------|---------------------|
| 2.1 Discord connection | discord.py bot, gateway connection, background task scaffold | Bot connects and logs ready |
| 2.2 Message polling | Fetch messages from configured channels on interval | Messages appear in DB with correct fields |
| 2.3 Reaction tracking | Fetch reactions, store per opted-in user | Reactions stored with user/emoji/message |
| 2.4 Media analysis | Vision model for images, phenomenological descriptions | Images have `description` field populated |
| 2.5 Link analysis | Fetch and summarize linked content, YouTube transcripts | Links have `summary` field, videos < 30min get transcripts |

**Dependencies**: Epic 1 complete

**Notes**:
- Use `model: vision` profile for media analysis
- Respect robots.txt for link fetching
- Handle edit/delete: update to latest state, respect "unsaying"

---

### Epic 3: Salience

**Goal**: Implement the attention-budget system.

| Story | Description | Acceptance Criteria |
|-------|-------------|---------------------|
| 3.1 Ledger operations | Earn, spend, retain transactions | Transactions recorded, balance computable |
| 3.2 Topic earning | Earning rules per activity type (message, reaction, mention) | Correct amounts earned per trigger |
| 3.3 Propagation | Warm-only propagation to related topics | Related warm topics gain fraction |
| 3.4 Decay | Daily decay after inactivity threshold | Inactive topics decay correctly |
| 3.5 Budget groups | Per-group allocation (Social, Global, Spaces, Semantic, Culture, Self) | Selection respects group budgets |

**Dependencies**: Epic 1 complete, Story 2.2 for earning triggers

**Notes**:
- Global topic warming: DM or second-server triggers warmth
- Spillover: cap overflow spills to related topics
- Self budget is separate pool

---

### Epic 4: Reflection

**Goal**: Build the layer execution system that produces insights.

| Story | Description | Acceptance Criteria |
|-------|-------------|---------------------|
| 4.1 Layer YAML loading | Load and validate layer definitions with Pydantic | Invalid YAML produces clear errors |
| 4.2 Prompt template system | Jinja2 loading, standard context injection (`<chat>` guidance) | Templates render with correct context |
| 4.3 Sequential executor | Execute nodes in order, pass context dict | Layer runs produce correct outputs |
| 4.4 LLM client | Thin wrapper with Anthropic adapter, model profiles | LLM calls work with correct model selection |
| 4.5 Insight storage | Store insights with full metrics, valence, cross-links | Insights queryable by topic |
| 4.6 Scheduler integration | APScheduler triggers layers on cron schedule | Nightly layers run automatically |
| 4.7 User reflection layer | First real layer: nightly user reflection | Insights generated for high-salience users |
| 4.8 Self-reflection layer | Self-reflection with self-concept document access | Self-insights accumulate, self-concept readable |

**Dependencies**: Epics 1-3 complete

**Notes**:
- Fail-forward: skip topics on error, continue with next
- Layer run records: full audit trail with model, tokens, costs
- Self-concept: read per-request (always fresh)

---

### Epic 5: Introspection

**Goal**: Build the API and web UI for operators.

| Story | Description | Acceptance Criteria |
|-------|-------------|---------------------|
| 5.1 FastAPI scaffold | Basic API with health check, CORS, docs | `/docs` shows OpenAPI spec |
| 5.2 Insights API | Query insights by topic, search, list recent | JSON endpoints work correctly |
| 5.3 Salience API | Query balances, transaction history | Salience data accessible |
| 5.4 Layer runs API | List runs, view details, errors | Run audit trail queryable |
| 5.5 UI base | htmx + Jinja2 setup, base template, navigation | UI loads with nav |
| 5.6 Insights browser | Browse/search insights by topic | Can explore accumulated understanding |
| 5.7 Salience dashboard | Visualize balances, budget allocation | Can see attention distribution |
| 5.8 Layer run monitor | View recent runs, status, errors, dry runs | Operational visibility |
| 5.9 Dev mode CRUD | Create/update/delete for insights (dev only) | Can manually adjust data during development |

**Dependencies**: Epics 1-4 complete (API can start after Epic 1)

**Notes**:
- UI is server-rendered, htmx for interactivity
- All three UI priorities: insights browser + salience dashboard + layer runs
- Dev mode CRUD behind feature flag

---

## Story Template

For each story, create `spec/implementation/mvp-0/stories/<epic>-<number>.md`:

```markdown
# Story <X.Y>: <Title>

**Epic**: <Epic Name>
**Status**: 🔴 Not Started | 🟡 In Progress | 🟢 Complete
**Estimated complexity**: Small | Medium | Large

## Goal

<One sentence describing what this story accomplishes>

## Acceptance Criteria

- [ ] <Specific, testable criterion>
- [ ] <Another criterion>
- [ ] Tests pass

## Technical Notes

<Implementation guidance, gotchas, references to spec sections>

## Files to Create/Modify

- `src/zos/<file>.py` — <what changes>

## Dependencies

- Requires: <Story X.Y>
- Blocks: <Story X.Y>
```

---

## Validation Plan

After MVP 0 is complete:

### Observation Period
2-4 weeks of active observation before declaring success.

### Structural Indicators (Automated)
- [ ] Insights reference prior insights (temporal depth)
- [ ] Cross-topic connections appear
- [ ] Pattern-based language emerges
- [ ] Self-insights accumulate

### Human Evaluation (Weekly)
- [ ] Could this insight have been generated from just today's messages? (Should be: no)
- [ ] Does it feel like *knowing* someone vs *reading about* them?
- [ ] Would you trust this insight to inform a response?
- [ ] Do contradictions coexist productively?

### Operational Criteria
- [ ] Reflection runs are auditable
- [ ] Salience budget constrains compute without starving important topics
- [ ] Subject topics consolidate rather than proliferate
- [ ] Self-concept document evolves coherently

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| LLM costs spiral | Model profiles enforce capability tiers; monitor estimated_cost_usd |
| Reflection produces shallow summaries | Tune prompts, ensure salience forces depth over breadth |
| Vision analysis rate limits | Queue with backoff, skip on persistent failure |
| Discord rate limits | discord.py handles this; conservative polling interval |

---

## Next Steps

1. Create Epic 1 story files
2. Set up project scaffold (Story 1.1)
3. Implement incrementally, test each story before proceeding

---

_Implementation planning interrogated: 2026-01-23_
