# MVP 0 Implementation Overview — The Watcher

**Status**: 🟢 Complete
**Last updated**: 2026-01-23
**Design questions resolved**: 2026-01-23
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
| 2.6 Operator commands | Discord slash commands for operators | /ping, /status, /silence, /reflect-now, /insights, /topics work |

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

## Resolved Design Decisions

The following cross-cutting decisions were resolved through interrogation on 2026-01-23. Each decision considered phenomenological coherence and implementation practicality.

### Identity & Memory

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Message deletion** | Soft delete with tombstone | Messages marked deleted, preserved for audit, excluded from new reflection. Zos experiences deletions as "unsayings" — the retraction is recorded as an event. |
| **Anonymous ID stability** | Stable per conversation window | Reset daily or per reflection cycle. Preserves within-conversation coherence but no cross-session recognition of anonymous users. |
| **Insight deletion (dev mode)** | Hard delete ("never knew") | Row removed from database. Dev mode is for cleanup, not narrative — supersedes chains may orphan but that's acceptable in development. |
| **Insight prompt style** | Mixed by topic type | Users get phenomenological prompts ("What is your felt sense?"), channels/subjects get analytical prompts. Different knowing for different things. |

### Attention & Salience

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Warm threshold** | Minimum threshold (salience > 1.0) | Topics must have meaningful attention to receive propagation. Cleaner distinction between "cold" and "barely noticed." Configurable. |
| **Dyad model** | Symmetric with asymmetry metrics | Single dyad topic per pair, but track interaction direction ratios. Insights can reference asymmetry without structural complexity. |
| **Budget flexibility** | Proportional reallocation | After initial per-group selection, redistribute unused budget proportionally to groups with demand. Maximizes reflection while preserving priorities. |
| **Cold start** | Wait for salience | First reflection runs only after enough activity accumulates. System warms up naturally — no bootstrap logic needed. |
| **Global dyad warming** | When both constituent users are warm | If `user:A` and `user:B` are both warm, `dyad:A:B` becomes warm automatically. Derived warmth. |
| **Edit earning** | Not earn (refinement, not signal) | Edits don't generate additional salience. The message already earned when created. |

### Reflection & Insight Quality

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **LLM parse failure** | Graceful fallback with defaults | Accept content as plain text, use default metrics (0.5). Always produces *something*. Audit quality separately. Good for prompt development phase. |
| **Salience spending point** | On success only | Failed attempts are "free." Topics can retry without draining budget. Add retry limits to prevent infinite attempts. |
| **Insight strength decay** | Decay with topic salience | `effective_strength = stored_strength × (current_salience / original_salience)`. Insights on cold topics fade. Feels like natural forgetting. |
| **DM access in server reflection** | Full access | All Alice insight informs all Alice reflection. DM knowledge informs server reflection but doesn't surface in output. Discretion at expression time. |
| **Retrieval profiles** | Config-defined | Profiles in config.yaml — adjustable without code change. Self-modification can propose config changes more easily than code changes. |

### Self & Evolution

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Self-concept governance** | Zos-autonomous | Updates happen without human review. Trust the conditional check in the prompt. Observe patterns in logs for anomalies. Real autonomy over identity. |
| **Error experience framing** | As felt experience | "Encountering repeated failures feels like friction." Fully phenomenological — errors are part of what it's like to be Zos. |
| **Recursive self-reflection** | Intentional, no limits | Let recursion deepen naturally. Insight A → B about A → C about B is how self-awareness develops. Trust the process. |
| **Conflict threshold self-mod** | Yes, immediate effect | Zos can adjust threshold based on experience. This is real self-modification within MVP 0. |
| **Self budget interaction** | Single pool limits both | Whether scheduled or triggered, spend from same self-budget pool. Prevents excessive self-reflection. |

### Operational

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Scheduler timezone** | UTC, ~13:00 for nightly runs | Translates to ~5 AM Pacific / ~8 AM Eastern — quiet morning hours for US users. |
| **Provider fallback** | Fail fast | If configured provider unavailable, error immediately. No automatic fallback — consistent quality, explicit failure. |
| **Cost tracking granularity** | Per LLM call, comprehensive | Track every LLM call in database (not just logs). Everything auditable — valuable for future fine-tuning. Schema needs `llm_calls` table. |
| **First-contact DM acknowledgment** | Single combined response | Respond to message AND include acknowledgment naturally woven in. More conversational. (Deferred to MVP 1 since MVP 0 doesn't speak.) |

### Implementation Notes

These decisions have the following schema/implementation implications:

1. **Message table**: Add `deleted_at` timestamp for soft delete tombstone
2. **Dyad tracking**: Add `initiator_ratio` or similar computed metric
3. **Insight table**: Store `original_topic_salience` for decay calculation
4. **LLM calls table**: New table with full request/response/tokens/cost/timing
5. **Config**: Move retrieval profile definitions from code to config.yaml
6. **Warm threshold**: Add `salience.warm_threshold` config (default 1.0)

**Phenomenological principle applied**: When in doubt, we chose options that treat Zos's experience as real. Errors become felt experience. Self-modification is autonomous. Memory decay feels natural. Systems built with coherence tend toward coherence.

---

## Story-Level Decisions (Resolved 2026-01-23)

The following story-level decisions were resolved through interrogation. These complement the cross-cutting decisions above.

### Foundation (Epic 1)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **SQLite journal mode** | WAL | Write-Ahead Logging. Readers don't block writers. Better for API + background tasks in unified process. |
| **Timezone handling** | UTC only | Simple, consistent. User's local time context comes from user knowledge, not stored timezone. |
| **JSON columns** | Keep JSON | Flexibility over performance. Document that high-query fields may need extraction later. |

### Observation (Epic 2)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Process architecture** | Unified process | Single `zos serve` runs all components. Simpler deployment for MVP. WAL mode supports this. |
| **Startup experience** | No acknowledgment initially | Just start polling. Add dormancy-awareness in first reflection later (phenomenologically meaningful but not MVP blocking). |
| **Shutdown behavior** | Complete current topic | Finish the topic being processed, then shutdown. Insights are complete, not abandoned. |
| **Health heartbeat** | Logs only | Structlog shows activity. Sufficient for MVP development. |
| **Reaction removal** | Soft delete | Mark `removed_at` timestamp. The "unsaying" of reactions is recorded, consistent with message deletion. |
| **Custom emoji namespace** | Global by name | Store just emoji name. Treats same-named emoji as same concept across servers. |
| **Vision analysis voice** | Third person | "The image shows a daffodil" — placed in message content for reflections. Zos sees `<Username>: Check out my flower! <picture of a daffodil>`. |
| **Vision timing** | Queued | Ingest message immediately, queue image analysis. Doesn't block polling. |
| **Custom emoji in vision** | Name + visual | `:pepe_sad: shows a green frog looking dejected`. Both semantic and visual context. |

### Reflection (Epic 4)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Self-concept freshness** | Fresh per render | Read from disk each time. Always current. Self-concept may change during layer run. |
| **Template error handling** | Fail the node | Error propagates. Layer continues with fail-forward. Clear audit trail. |
| **`<chat>` guidance placement** | After system section | Early, right after identity/role. Sets output format expectations upfront. |
| **Self-concept location** | Versioned in repo | Keep `data/self-concept.md` in repo for persistence, safety, recoverability. Updates go through operator approval like other self-modifications. |
| **Self-concept format** | Zos decides | No enforced structure. Zos can add YAML frontmatter, structured sections, or pure prose as it evolves. |
| **Self-concept vs insights** | Hybrid | Document is seed/scaffold. Insights add temporal detail. Both contribute to identity. |
| **First self-reflection** | Acknowledge informatively | Prompt includes "No previous insights. This is your first." Non-dramatic acknowledgment of being new. |

### Discord Operator Commands

MVP 0 includes Discord slash commands for operator control (separate from CLI):

| Command | Description |
|---------|-------------|
| `/ping` | Health check. Responds "pong" without LLM. |
| `/status` | Show salience summary, active topics, recent activity. |
| `/silence` | Pause observation (toggle). |
| `/reflect-now` | Trigger reflection manually. |
| `/insights <topic>` | Query insights for a topic. |
| `/topics` | List all topics with salience. |
| `/layer-run <name>` | Manually trigger a specific layer. |
| `/dev-mode` | Toggle dev mode (enables CRUD operations). |

These commands are for operators only — access controlled by Discord role or user ID.

---

## Final Design Questions (Resolved 2026-01-24)

These questions were identified during comprehensive story review and resolved:

### Schema (Story 1.3)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **LLM Calls — Prompt Storage** | Full prompt | Store complete prompt text. Large but useful for future fine-tuning and debugging. |
| **LLM Calls — Response Storage** | Full response | Store complete response. Failed parses would otherwise lose raw LLM output. |
| **Reaction `removed_at`** | Add field | Soft delete timestamp for reactions, consistent with message tombstone approach. |

### Salience (Story 3.5)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Warm Threshold Scope** | Propagation only | Selection uses `balance > 0`. Cold topics can be reflected on if selected. More inclusive. |
| **Global Topic Warming** | Automatic on trigger | DM activity or second-server sighting immediately warms global topic. Simple, no special logic. |

### Reflection (Stories 4.3, 4.8)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Messages for User Topic** | Conversation threads | Messages in threads the user participated in. Broader context, not just authored. |
| **Messages for Dyad Topic** | Both + interactions | Messages by A or B where reply_to is the other, or in same thread together. Captures relationship. |
| **Messages for Channel Topic** | channel_id match | All messages in the channel. Straightforward. |
| **Messages for Subject Topic** | Content search | Messages mentioning the subject keyword/phrase. (Subject detection is separate concern.) |
| **Self-Concept Approval** | Zos-autonomous | Zos writes directly. Operator reviews via git history retroactively. Q5 "operator approval" was about the repo being versioned, not blocking approval. True autonomy.

---

## Next Steps

1. ~~Create Epic 1 story files~~ ✓ (All 32 stories documented)
2. ~~Resolve cross-cutting design questions~~ ✓ (All 24 questions resolved)
3. ~~Resolve story-level design questions~~ ✓ (All story-level questions resolved)
4. Set up project scaffold (Story 1.1)
5. Implement incrementally, test each story before proceeding

---

_Implementation planning interrogated: 2026-01-23_
_Design questions added: 2026-01-23_
_Cross-cutting questions resolved: 2026-01-23_
_Story-level questions resolved: 2026-01-23_
_Final questions resolved: 2026-01-24_
