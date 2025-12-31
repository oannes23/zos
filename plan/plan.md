# Zos Implementation Plan

This document breaks down the Zos project into implementation phases. Each phase is self-contained and delivers testable functionality. Phases build on each other sequentially.

---

## Phase 1: Project Foundation ✅ COMPLETE

**Goal:** Establish the project skeleton, configuration system, and development infrastructure.

### Features

1.1 **Repository Structure**
- Initialize Python project with `uv`
- Set up directory structure: `src/zos/`, `tests/`, `config/`, `layers/`
- Configure linting, formatting, type checking
- Create base `pyproject.toml`

1.2 **Configuration System**
- Define root `config.yml` schema (Pydantic models)
- Implement config loader with validation
- Support environment variable overrides for secrets
- Create example/default configuration

1.3 **Logging & Error Handling**
- Structured logging setup
- Error hierarchy for domain-specific exceptions
- Development vs production log levels

1.4 **Database Foundation**
- SQLite connection management
- Migration system (simple version-based)
- Base schema: metadata table, version tracking

### Deliverables
- Runnable project that loads config and initializes empty database
- `pytest` suite skeleton with fixtures
- CI-ready structure

### Manual Testing Checkpoint
Run these commands to verify Phase 1 is complete:
```bash
# 1. Run the test suite
uv run pytest

# 2. Run the application (should load config and initialize DB)
uv run python -m zos

# 3. Verify database was created
ls data/zos.db
```
**Expected behavior:**
- All tests pass
- Application starts, logs "Configuration loaded" and "Database initialized", then exits cleanly
- SQLite database file exists with metadata table

---

## Phase 2: Discord Ingestion ✅ COMPLETE

**Goal:** Connect to Discord and persist all observed messages and reactions to SQLite.

### Features

2.1 **Discord Client Setup**
- Bot connection using discord.py (or hikari/nextcord)
- Event subscription for configured guilds/channels
- Graceful connection handling and reconnection

2.2 **Message Storage Schema**
- Tables: `messages`, `reactions`
- Fields per spec: `message_id`, `guild_id`, `channel_id`, `thread_id`, `author_id`, `author_roles_snapshot`, `content`, `created_at`, `visibility_scope`
- Indexes for common query patterns

2.3 **Event Handlers**
- `on_message`: Store new messages
- `on_message_edit`: Update stored content (with edit history optional)
- `on_message_delete`: Mark as deleted (soft delete)
- `on_reaction_add/remove`: Maintain reaction state

2.4 **Backfill Capability**
- On startup, optionally backfill recent history for configured channels
- Configurable lookback window
- Idempotent insertion (handle duplicates)

### Deliverables
- Bot that joins server and silently logs all activity
- Query functions to retrieve messages by channel, user, time range
- Tests with mocked Discord events

### Manual Testing Checkpoint
```bash
# 1. Run tests
uv run pytest tests/test_discord.py

# 2. Start the bot (requires DISCORD_TOKEN in .env)
uv run python -m zos

# 3. Send some messages in your test Discord server, then check DB
uv run python -c "from zos.db import get_db; print(get_db().execute('SELECT COUNT(*) FROM messages').fetchone())"
```
**Expected behavior:**
- Bot comes online in Discord server
- Messages appear in SQLite within seconds of being sent
- Reactions are tracked when added/removed
- Bot reconnects automatically if connection drops

---

## Phase 3: Topic System & Salience ✅ COMPLETE

**Goal:** Implement the TopicKey system and salience ledger for attention allocation.

### Features

3.1 **TopicKey Implementation**
- Canonical key formats: `user:<id>`, `channel:<id>`, `user_in_channel:<ch>:<user>`, `dyad:<a>:<b>`, `dyad_in_channel:<ch>:<a>:<b>`
- Parser and serializer utilities
- TopicKey extraction from messages

3.2 **Salience Ledger Schema**
- Tables: `salience_earned`, `salience_spent`
- Fields: `topic_key`, `timestamp`, `amount`, `reason` (earned) / `run_id`, `layer`, `node` (spent)

3.3 **Salience Earning Rules**
- Message activity: base points per message
- Reactions: points per reaction given/received
- Mentions: bonus points for mentions
- Configurable weights per activity type

3.4 **Salience Query Interface**
- Get current balance for topic (earned - spent)
- Get top-N topics by category
- Time-windowed queries (salience since date)

### Deliverables
- Automatic salience accumulation as messages arrive
- CLI/API to inspect salience balances
- Unit tests for ledger math

### Manual Testing Checkpoint
```bash
# 1. Run tests
uv run pytest tests/test_salience.py

# 2. After bot has been running, check salience balances
uv run python -m zos.cli salience top --category user --limit 10
uv run python -m zos.cli salience top --category channel --limit 5
```
**Expected behavior:**
- Users and channels with more activity have higher salience
- Salience values are deterministic and auditable
- TopicKeys are correctly formatted

---

## Phase 4: Budget Allocation System ✅ COMPLETE

**Goal:** Implement the budget allocation logic that distributes reflection resources based on salience.

### Features

4.1 **Budget Configuration**
- Total budget per reflection run (in tokens)
- Category weights from config (user, channel, user_in_channel, dyad, dyad_in_channel)
- Per-topic caps

4.2 **Budget Allocator**
- Divide total budget across categories by weight
- Within each category, allocate to topics proportionally by salience
- Enforce per-topic maximums
- Return allocation plan: `{topic_key: allocated_tokens}`

4.3 **Cost Tracking**
- Pre-call estimation interface
- Post-call actual recording
- Run-level cost aggregation

4.4 **Budget Enforcement**
- Check available budget before LLM calls
- Deduct from allocation on spend
- Skip/truncate when budget exhausted

### Deliverables
- Budget allocator with deterministic output
- Cost tracking utilities
- Comprehensive tests for allocation edge cases

### Manual Testing Checkpoint
```bash
# 1. Run tests
uv run pytest tests/test_budget.py

# 2. Preview budget allocation for a hypothetical run
uv run python -m zos.cli budget preview --total-tokens 100000
```
**Expected behavior:**
- Allocation respects category weights from config
- High-salience topics get proportionally more budget
- Per-topic caps are enforced
- Output is deterministic (same input = same allocation)

---

## Phase 5: LLM Abstraction Layer

**Goal:** Create a unified interface for LLM calls that supports multiple providers and tracks costs.

### Features

5.1 **Provider Interface**
- Abstract base: `complete(messages, model, max_tokens) -> Response`
- Response includes: `content`, `tokens_used`, `cost_estimate`

5.2 **Provider Implementations**
- OpenAI-compatible (works with OpenAI, local endpoints)
- Anthropic
- Ollama (local)
- Generic HTTP endpoint

5.3 **Model Selection Hierarchy**
- Global default model
- Layer default (override)
- Node override (highest priority)
- Resolution utility function

5.4 **Prompt Management**
- Load prompts from files (Jinja2 templating)
- Variable substitution
- Prompt versioning support

### Deliverables
- Working LLM calls through abstraction
- Easy provider switching via config
- Mocked provider for testing

### Manual Testing Checkpoint
```bash
# 1. Run tests (uses mocked provider)
uv run pytest tests/test_llm.py

# 2. Test real provider connection (requires API key in .env)
uv run python -m zos.cli llm test --provider openai --prompt "Say hello"
uv run python -m zos.cli llm test --provider anthropic --prompt "Say hello"
```
**Expected behavior:**
- Mocked tests pass without API keys
- Real provider test returns response and logs token usage
- Provider switching works via config change
- Errors are handled gracefully with clear messages

---

## Phase 6: Layer Execution Engine

**Goal:** Build the core engine that executes YAML-defined reflection layers.

### Features

6.1 **Layer Schema Definition**
- YAML schema for layers (Pydantic validation)
- Fields: `name`, `schedule`, `targets`, `salience_rules`, `pipeline`, `model_defaults`

6.2 **Pipeline Nodes**
- `fetch_messages`: Retrieve messages for topic/time range
- `fetch_insights`: Retrieve existing insights for topic
- `llm_call`: Execute LLM with persona and context
- `reduce`: Combine multiple outputs
- `store_insight`: Persist new insight
- `output`: Send to Discord or other sink

6.3 **Pipeline Executor**
- Linear execution with context passing
- `for_each` expansion over targets
- Error handling and partial completion
- Budget checking at each LLM node

6.4 **Context Assembly**
- Build context blocks for LLM calls
- Include relevant messages, insights, metadata
- Enforce privacy scope (no raw DM text in public outputs)

### Deliverables
- Execute a simple layer from YAML definition
- Full pipeline trace in logs
- Integration tests with mocked LLM

### Manual Testing Checkpoint
```bash
# 1. Run tests
uv run pytest tests/test_layer_engine.py

# 2. Validate a layer definition
uv run python -m zos.cli layer validate layers/channel_digest/

# 3. Dry-run a layer (no actual LLM calls or DB writes)
uv run python -m zos.cli layer dry-run channel_digest --topic "channel:123456"
```
**Expected behavior:**
- Layer YAML validation catches schema errors
- Dry-run shows pipeline execution trace
- Context assembly output is visible
- Node sequence executes in order

---

## Phase 7: Scheduling & Run Management

**Goal:** Implement scheduled execution of layers and comprehensive run tracking.

### Features

7.1 **Scheduler Integration**
- APScheduler setup with cron-like schedules
- Layer registration based on config
- Manual trigger capability

7.2 **Run Lifecycle**
- Run ID generation
- State tracking: pending, running, completed, failed
- "Since last successful run" window calculation
- Max lookback enforcement

7.3 **Run Artifacts Schema**
- Table: `runs`
- Fields: `run_id`, `layer_name`, `schedule`, `started_at`, `completed_at`, `status`, `targets_processed`, `targets_skipped`, `salience_spent`, `tokens_used`, `cost`

7.4 **Run Logging**
- Per-run detailed log (LLM calls, decisions, errors)
- Queryable run history

### Deliverables
- Layers execute on schedule automatically
- Full audit trail per run
- Graceful handling of overlapping/delayed runs

### Manual Testing Checkpoint
```bash
# 1. Run tests
uv run pytest tests/test_scheduler.py

# 2. Manually trigger a layer run
uv run python -m zos.cli layer run channel_digest

# 3. View run history
uv run python -m zos.cli runs list --limit 5
uv run python -m zos.cli runs show <run_id>
```
**Expected behavior:**
- Manual trigger creates a run with unique ID
- Run status progresses: pending → running → completed/failed
- Run artifacts show targets processed, tokens used, cost
- Scheduler fires layers at configured times (test by setting near-future schedule)

---

## Phase 8: Insights Storage

**Goal:** Implement the persistent insight system that stores reflection outputs.

### Features

8.1 **Insights Schema**
- Table: `insights`
- Fields: `insight_id`, `topic_key`, `created_at`, `summary` (text), `payload` (JSON), `source_refs`, `sources_scope_max`, `run_id`

8.2 **Insight CRUD**
- Create insight from layer output
- Query insights by topic, time range, scope
- Update/supersede insights (optional versioning)

8.3 **Source Reference Tracking**
- Link insights to source messages
- Track derivation chain (insight from insight)
- Privacy scope propagation

8.4 **Insight Retrieval for Context**
- Get relevant insights for topic
- Recency and relevance weighting
- Scope filtering for context assembly

### Deliverables
- Insights persisted from layer runs
- Query API for insight retrieval
- Privacy scope enforcement

### Manual Testing Checkpoint
```bash
# 1. Run tests
uv run pytest tests/test_insights.py

# 2. Query insights after a layer run
uv run python -m zos.cli insights list --topic "channel:123456"
uv run python -m zos.cli insights show <insight_id>
```
**Expected behavior:**
- Insights are created with proper topic keys
- Source references link back to messages
- Privacy scope is correctly tagged
- Insights can be queried by topic, time, scope

---

## Phase 9: First Reflection Layer (Channel Digest)

**Goal:** Implement and validate a complete nightly reflection layer.

### Features

9.1 **Layer Definition**
- YAML config for "channel_digest" layer
- Target: channels with sufficient salience
- Schedule: nightly

9.2 **Pipeline Implementation**
- Fetch messages since last run
- Summarize activity and notable exchanges
- Identify emerging topics/themes
- Store channel insight

9.3 **Prompts**
- System prompt defining analyst persona
- Summarization prompt template
- Output formatting instructions

9.4 **Validation & Tuning**
- Test with real or synthetic data
- Adjust prompts for quality
- Verify budget consumption

### Deliverables
- Working nightly channel digest
- Generated insights visible in database
- Documented layer as reference implementation

### Manual Testing Checkpoint
```bash
# 1. Run the layer manually with real LLM
uv run python -m zos.cli layer run channel_digest

# 2. Review generated insights
uv run python -m zos.cli insights list --run-id <run_id>

# 3. Check quality of summaries
uv run python -m zos.cli insights show <insight_id> --full
```
**Expected behavior:**
- Layer completes without errors
- Insights contain meaningful channel summaries
- Budget was respected (check run cost vs. allocation)
- Prompts produce consistent, useful output

**This is a major milestone - the core reflection pipeline works end-to-end.**

---

## Phase 10: Web API & Introspection

**Goal:** Expose system state and audit data via FastAPI endpoints.

### Features

10.1 **FastAPI Setup**
- Application factory
- CORS configuration
- Error handling middleware

10.2 **Read-Only Endpoints**
- `GET /health` - System health check
- `GET /config` - Current configuration (secrets redacted)
- `GET /layers` - Registered layers and schedules
- `GET /runs` - Run history with pagination
- `GET /runs/{id}` - Detailed run info
- `GET /insights` - Insight query with filters
- `GET /salience` - Salience balances by topic
- `GET /audit` - Audit log entries

10.3 **Response Formatting**
- JSON output
- Optional YAML output (Accept header)
- Consistent pagination structure

### Deliverables
- Running API server
- All specified endpoints functional
- OpenAPI documentation auto-generated

### Manual Testing Checkpoint
```bash
# 1. Run tests
uv run pytest tests/test_api.py

# 2. Start the API server
uv run python -m zos.api &

# 3. Test endpoints
curl http://localhost:8000/health
curl http://localhost:8000/config
curl http://localhost:8000/runs
curl http://localhost:8000/insights?topic=channel:123456
curl http://localhost:8000/salience?category=user&limit=10

# 4. View OpenAPI docs
open http://localhost:8000/docs
```
**Expected behavior:**
- All endpoints return valid JSON
- Secrets are redacted in /config
- Pagination works correctly
- OpenAPI docs are accurate and complete

---

## Phase 11: Conversational Layer

**Goal:** Enable Zos to participate in conversations based on context and triggers.

### Features

11.1 **Trigger Detection**
- Direct mention detection
- Reply to Zos detection
- Salience spike monitoring
- Keyword/pattern triggers (configurable)

11.2 **Response Decision**
- Should-respond evaluation (lightweight LLM or rules)
- Rate limiting per channel
- Budget allocation for responses

11.3 **Response Generation**
- Context assembly for conversation
- Persona-appropriate response generation
- Message length limits

11.4 **Message Sending**
- Send to configured output channels only
- Reply threading
- DM response handling

### Deliverables
- Zos responds to mentions
- Rate-limited spontaneous participation
- Response quality baseline

### Manual Testing Checkpoint
```bash
# 1. Run tests
uv run pytest tests/test_conversation.py

# 2. Start bot and test in Discord
uv run python -m zos
```
**In Discord, test:**
- @mention Zos → should reply
- Reply to Zos's message → should continue conversation
- Rapid mentions → should be rate-limited
- Message in non-output channel → should not respond

**Expected behavior:**
- Responses are contextually appropriate
- Rate limiting prevents spam
- Only responds in configured output channels
- Response latency is acceptable (<5s typically)

**This is a major milestone - Zos is now interactive.**

---

## Phase 12: DM Handling & Privacy

**Goal:** Implement private DM conversations with appropriate privacy controls.

### Features

12.1 **DM Ingestion**
- Capture DM messages (opted-in users only)
- Store with `visibility_scope = 'dm'`
- Role-based opt-in verification

12.2 **DM Conversations**
- Private conversation context
- Response generation for DMs
- Conversation continuity

12.3 **Privacy Enforcement**
- DM text exclusion from public outputs
- Scope tagging on all derived insights
- Context assembly filtering

12.4 **User Opt-In Management**
- Check user roles for DM permission
- Graceful handling of non-opted users
- Clear user communication

### Deliverables
- Working DM conversations
- Privacy guarantees enforced
- Audit trail for DM-derived insights

### Manual Testing Checkpoint
```bash
# 1. Run tests
uv run pytest tests/test_dm.py tests/test_privacy.py

# 2. Start bot
uv run python -m zos
```
**In Discord, test:**
- DM Zos (with opted-in user) → should respond
- DM Zos (without role) → should politely decline
- Run reflection layer, check insights don't leak DM content

```bash
# 3. Verify privacy enforcement
uv run python -m zos.cli insights list --scope public
# Should not contain any raw DM text
```
**Expected behavior:**
- DM conversations work for opted-in users
- DM-derived insights are tagged with correct scope
- Public outputs never contain raw DM text
- Audit log shows DM access

---

## Phase 13: Additional Reflection Layers

**Goal:** Implement remaining planned reflection layers.

### Features

13.1 **Social Dynamics Layer**
- User interaction analysis
- Dyad relationship tracking
- Social graph insights

13.2 **User Profile Layer**
- Individual user understanding
- Communication style analysis
- Interest tracking

13.3 **Emoji Semantics Layer**
- Server-specific emoji meaning inference
- Reaction pattern analysis

13.4 **Cross-Layer Integration**
- Layers referencing other layers' insights
- Insight synthesis across domains

### Deliverables
- Multiple working reflection layers
- Richer insight generation
- Demonstrated layer composability

### Manual Testing Checkpoint
```bash
# 1. Run all layer tests
uv run pytest tests/test_layers/

# 2. Run each new layer
uv run python -m zos.cli layer run social_dynamics
uv run python -m zos.cli layer run user_profile
uv run python -m zos.cli layer run emoji_semantics

# 3. Verify cross-layer insight references
uv run python -m zos.cli insights list --has-derived-from
```
**Expected behavior:**
- Each layer produces meaningful insights
- Layers can reference insights from other layers
- Social graph insights show relationships
- Emoji meanings are inferred from usage context

---

## Phase 14: Testing & Hardening

**Goal:** Comprehensive testing and production readiness.

### Features

14.1 **Unit Test Coverage**
- All core modules tested
- Edge cases covered
- Mocked external dependencies

14.2 **Integration Tests**
- Full layer execution tests
- Golden/snapshot tests for outputs
- Database migration tests

14.3 **Load Testing**
- High message volume simulation
- Concurrent layer execution
- Memory and connection management

14.4 **Error Recovery**
- Graceful degradation
- Retry logic for transient failures
- Data consistency guarantees

### Deliverables
- High test coverage
- Performance benchmarks
- Documented failure modes

### Manual Testing Checkpoint
```bash
# 1. Run full test suite with coverage
uv run pytest --cov=zos --cov-report=html
open htmlcov/index.html

# 2. Run load tests
uv run python -m zos.tests.load_test --messages 10000

# 3. Test error recovery
# (kill bot mid-run, restart, verify it recovers)
```
**Expected behavior:**
- Test coverage >80%
- System handles 1000+ messages/minute without issues
- Graceful recovery from crashes
- No data corruption after unexpected shutdown

---

## Phase 15: Documentation & Deployment

**Goal:** Production deployment capability and operational documentation.

### Features

15.1 **Deployment Configuration**
- Docker containerization
- Environment-based config
- Health checks and readiness probes

15.2 **Operational Documentation**
- Setup guide
- Configuration reference
- Troubleshooting guide

15.3 **Layer Development Guide**
- How to create new layers
- Prompt engineering guidelines
- Testing layer changes

15.4 **Monitoring & Alerting**
- Key metrics identification
- Log aggregation setup
- Alert thresholds

### Deliverables
- Deployable container image
- Complete documentation
- Monitoring recommendations

### Manual Testing Checkpoint
```bash
# 1. Build and run Docker container
docker build -t zos .
docker run -v $(pwd)/config:/app/config -v $(pwd)/data:/app/data zos

# 2. Verify health check
curl http://localhost:8000/health

# 3. Test with docker-compose (if applicable)
docker-compose up -d
docker-compose logs -f
```
**Expected behavior:**
- Container builds successfully
- Bot starts and connects to Discord
- API is accessible
- Data persists across container restarts
- Logs are properly formatted for aggregation

**Project is production-ready.**

---

## Dependency Graph

```
Phase 1 (Foundation)
    ↓
Phase 2 (Discord Ingestion)
    ↓
Phase 3 (Topics & Salience) ←──────────┐
    ↓                                   │
Phase 4 (Budget Allocation)             │
    ↓                                   │
Phase 5 (LLM Abstraction)               │
    ↓                                   │
Phase 6 (Layer Engine) ─────────────────┤
    ↓                                   │
Phase 7 (Scheduling)                    │
    ↓                                   │
Phase 8 (Insights) ─────────────────────┘
    ↓
Phase 9 (First Layer) ──→ Phase 13 (More Layers)
    ↓
Phase 10 (Web API)
    ↓
Phase 11 (Conversational)
    ↓
Phase 12 (DM/Privacy)
    ↓
Phase 14 (Testing)
    ↓
Phase 15 (Deployment)
```

---

## Notes

- **Parallelization:** Phases 10-12 can proceed in parallel after Phase 9
- **Iteration:** Phase 9 serves as validation; expect to revisit earlier phases based on learnings
- **Flexibility:** Layer implementations (Phases 9, 13) can be expanded incrementally
- **Testing:** Each phase should include relevant tests; Phase 14 is for comprehensive coverage
