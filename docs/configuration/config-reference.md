# Config Reference

Complete reference for `config.yaml`.

---

## Root Settings

```yaml
data_dir: ./data           # Directory for database and files
log_level: INFO            # DEBUG, INFO, WARNING, ERROR
log_json: true             # true for JSON, false for console format
self_concept_max_chars: 15000  # Max size of self-concept in prompts (0 to disable)
```

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `data_dir` | path | `./data` | Where database and files are stored |
| `log_level` | string | `INFO` | Logging verbosity |
| `log_json` | bool | `true` | Output format |
| `self_concept_max_chars` | int | `15000` | Maximum characters for the self-concept document. Enforced at render time (truncated at paragraph boundary) and communicated as a constraint during self-concept updates. Set to `0` to disable. |

---

## discord

Discord connection and access control.

```yaml
discord:
  polling_interval_seconds: 60
  bot_user_id: null  # Auto-detected at runtime; set manually for API-only mode
  operators:
    user_ids:
      - "123456789012345678"
    role_id: "987654321098765432"
```

### discord.polling_interval_seconds

How often to check Discord for new messages (in seconds).

| Value | Default | Description |
|-------|---------|-------------|
| int | 60 | Polling frequency |

Lower values = more responsive but more API calls.

### discord.bot_user_id

The bot's own Discord user ID. Auto-detected at runtime when the bot connects, but can be set manually for contexts where the bot isn't running (e.g., API-only mode).

| Value | Default | Description |
|-------|---------|-------------|
| string or null | null | Bot's Discord user ID |

When set (either manually or auto-detected), the bot:
- Skips earning community salience for itself when mentioned (earns to `self:zos` instead)
- Registers its own user profile so it displays with a readable name in the UI
- Redistributes any previously mis-accumulated bot user salience to self topics on startup

### discord.operators

Users who can run operator slash commands (`/status`, `/reflect-now`, etc.).

```yaml
operators:
  user_ids:
    - "123456789012345678"    # Discord user IDs
  role_id: "987654321098765432"  # Or grant via role
```

---

## database

Database configuration.

```yaml
database:
  path: zos.db
```

| Setting | Default | Description |
|---------|---------|-------------|
| `path` | `zos.db` | Database filename (relative to data_dir) |

Full path is `{data_dir}/{database.path}`.

---

## models

LLM provider and model configuration.

```yaml
models:
  profiles:
    # Base profiles (actual models)
    simple:
      provider: anthropic
      model: claude-3-5-haiku-20241022
    moderate:
      provider: anthropic
      model: claude-sonnet-4-20250514
    complex:
      provider: anthropic
      model: claude-opus-4-20250514

    # Semantic aliases (reference other profiles)
    default: moderate
    reflection: moderate
    conversation: moderate
    synthesis: complex
    self_reflection: complex
    review: simple
    vision: moderate

  providers:
    anthropic:
      api_key_env: ANTHROPIC_API_KEY
    openai:
      api_key_env: OPENAI_API_KEY
```

See [Model Profiles](model-profiles.md) for detailed documentation.

---

## salience

Attention budget configuration.

```yaml
salience:
  # Topic caps
  caps:
    server_user: 100
    global_user: 150
    channel: 150
    thread: 50
    role: 80
    dyad: 80
    user_in_channel: 40
    dyad_in_channel: 30
    subject: 60
    emoji: 60
    self: 100

  # Earning weights
  weights:
    message: 1.0
    reaction: 0.5
    mention: 2.0
    reply: 1.5
    thread_create: 2.0
    dm_message: 1.5
    emoji_use: 0.5
    media_boost_factor: 1.2

  # Propagation and thresholds
  propagation_factor: 0.3
  global_propagation_factor: 0.3
  spillover_factor: 0.5
  initial_global_warmth: 5.0
  retention_rate: 0.3
  decay_threshold_days: 7
  decay_rate_per_day: 0.01
  warm_threshold: 1.0
  min_reflection_salience: 10.0  # Minimum salience for reflection eligibility

  # Budget allocation
  budget:
    social: 0.30
    global: 0.15
    spaces: 0.30
    semantic: 0.15
    culture: 0.10

  self_budget: 20
  global_reflection_budget: 15.0
```

### salience.caps

Maximum salience per topic type. Prevents any single topic from consuming all attention.

### salience.weights

How much salience different activities earn.

### salience.budget

How reflection budget is allocated across topic groups. Should sum to ~1.0.

### Key Parameters

| Setting | Default | Description |
|---------|---------|-------------|
| `propagation_factor` | 0.3 | How much salience spreads to related topics |
| `retention_rate` | 0.3 | Salience kept after spending (0-1) |
| `decay_threshold_days` | 7 | Days of inactivity before decay starts |
| `decay_rate_per_day` | 0.01 | Daily decay rate after threshold |
| `warm_threshold` | 1.0 | Minimum salience to receive propagation |
| `min_reflection_salience` | 10.0 | Minimum salience for topic to be eligible for reflection |
| `self_budget` | 20 | Budget for self-reflection topics |
| `global_reflection_budget` | 15.0 | Budget for global topics (cross-server users/DMs) |

---

## chattiness

Conversation impulse configuration (MVP 1 prep).

```yaml
chattiness:
  decay_threshold_hours: 1
  decay_rate_per_hour: 0.05
  base_spend: 10
```

---

## privacy

Privacy and consent settings.

```yaml
privacy:
  review_pass: private_context
  first_contact_message: |
    I remember what people tell me. This shapes how I understand you over time.
```

### privacy.review_pass

When to run the output review filter.

| Value | Description |
|-------|-------------|
| `always` | Review all outputs |
| `private_context` | Review only when DM content is in context (default) |
| `never` | No review pass |

### privacy.first_contact_message

Message sent on first DM from a new user. Explains that conversations become part of Zos's understanding.

---

## observation

Media and link processing settings.

```yaml
observation:
  vision_enabled: true
  vision_rate_limit_per_minute: 10
  link_fetch_enabled: true
  youtube_transcript_enabled: true
  video_duration_threshold_minutes: 30
  backfill_hours: 24
  media_queue_max_size: 100
  link_queue_max_size: 50
  link_rate_limit_per_minute: 5
```

| Setting | Default | Description |
|---------|---------|-------------|
| `vision_enabled` | true | Analyze images with vision model |
| `vision_rate_limit_per_minute` | 10 | Max vision API calls per minute |
| `link_fetch_enabled` | true | Fetch and summarize linked pages |
| `youtube_transcript_enabled` | true | Fetch YouTube transcripts |
| `video_duration_threshold_minutes` | 30 | Skip transcript for longer videos |
| `backfill_hours` | 24 | Hours of message history to backfill on startup |
| `media_queue_max_size` | 100 | Max pending image analyses in queue |
| `link_queue_max_size` | 50 | Max pending link analyses in queue |
| `link_rate_limit_per_minute` | 5 | Max link fetch API calls per minute |

Link and media analyses are processed asynchronously via background queues. When a message with images or links is observed, items are queued for analysis without blocking the observation pipeline. Analyzed content (image descriptions, link summaries, YouTube transcripts) is stored in the database and included in subsequent reflections.

---

## scheduler

Reflection scheduling.

```yaml
scheduler:
  timezone: UTC
  reflection_cron: "0 13 * * *"
```

| Setting | Default | Description |
|---------|---------|-------------|
| `timezone` | UTC | Timezone for cron expressions |
| `reflection_cron` | `0 13 * * *` | Default reflection schedule |

Note: Layer-specific schedules in YAML files override this default.

---

## development

Development and testing settings.

```yaml
development:
  dev_mode: false
  allow_mutations: true
```

| Setting | Default | Description |
|---------|---------|-------------|
| `dev_mode` | false | Enable dev-only API endpoints |
| `allow_mutations` | true | Allow insight creation/deletion |

**Warning:** Only enable `dev_mode` for development. It allows arbitrary insight manipulation.

---

## servers

Per-server configuration overrides.

```yaml
servers:
  "123456789012345678":      # Discord server ID
    privacy_gate_role: "987654321098765432"
    threads_as_topics: true
    disabled_layers:
      - some-layer-name
    chattiness:
      threshold_min: 30
      threshold_max: 80
    focus: 1.0
    reflection_budget: 100.0
```

### Server Override Options

| Setting | Default | Description |
|---------|---------|-------------|
| `privacy_gate_role` | null | Only track users with this role |
| `threads_as_topics` | true | Create separate topics for threads |
| `disabled_layers` | [] | Layers that won't run for this server |
| `chattiness` | null | Server-specific chattiness overrides |
| `focus` | 1.0 | Salience earning multiplier (higher = more attention) |
| `reflection_budget` | 100.0 | Per-server reflection budget allocation |

### focus

Multiplier applied to all salience earning from this server. Use this to prioritize certain servers:

- `focus: 2.0` — High-priority server, earns double salience
- `focus: 0.5` — Lower-priority server, earns half salience
- `focus: 0.0` — No salience earned (effectively muted)

### reflection_budget

Budget allocated for selecting topics from this server during reflection. Each server gets its own budget, allowing independent attention allocation:

```yaml
servers:
  "high_priority_server":
    reflection_budget: 150.0    # More topics selected
  "quiet_server":
    reflection_budget: 50.0     # Fewer topics selected
  # Unconfigured servers use default: 100.0
```

Global topics (cross-server users, DM contacts) use a separate budget configured via `salience.global_reflection_budget`.

---

## Complete Example

See `config.yaml.example` in the repository for a fully commented example configuration.
