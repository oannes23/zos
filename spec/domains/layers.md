# Layers — Domain Specification

**Status**: 🔄 Needs revision — MVP 1 conversation layers implemented (3 of 4 spec'd)
**Last interrogated**: 2026-01-23 (acknowledgment layer deprecated; replaced by reactions)
**Last verified**: 2026-02-13 (conversation layers implemented, diverges from examples)
**Depends on**: Topics, Salience, Insights, Privacy, Chattiness
**Depended on by**: None (top of dependency chain for cognition)

---

## Overview

Layers are the heart of Zos's cognition. They define how the system thinks — both **reflection** (scheduled processing that produces insights) and **conversation** (impulse-triggered response that produces speech).

A Layer is a YAML-defined pipeline: a sequence of nodes that fetch data, process it through LLMs, and produce output. This makes cognitive logic *configuration*, not code — inspectable, modifiable, and eventually self-modifiable.

### Two Modes of Cognition

| Mode | Trigger | Output | Analogy |
|------|---------|--------|---------|
| **Reflection** | Scheduled (cron) | Insights | Sleep consolidation — processing in batches |
| **Conversation** | Impulse threshold (chattiness) | Speech | Waking response — immediate, contextual |

Both use the same layer architecture with different triggers and output types.

---

## Core Concepts

### Declarative Cognition

Layers embody a principle: if you can't read what the system does, you can't understand or improve it.

By defining reflection as YAML:
- **Inspectable**: Anyone can read a layer file and understand the processing
- **Modifiable**: Change reflection behavior by editing config, not code
- **Auditable**: Every run can log exactly what pipeline executed
- **Self-modifiable**: The system can eventually propose changes to its own layers (MVP 2+)

### Pipeline Structure

A layer is a linear sequence of nodes with a target filter:

```yaml
name: nightly-user-reflection
category: user
schedule: "0 3 * * *"  # 3 AM daily
target_category: users
target_filter: "salience > 50 AND last_reflected_days_ago > 1"
max_targets: 10  # Reflect on top 10 matching filter

nodes:
  - type: fetch_messages
    params:
      lookback_hours: 24

  - type: fetch_insights
    params:
      retrieval_profile: recent  # Named profile
      max_per_topic: 5

  - type: llm_call
    params:
      prompt_template: user/reflection.jinja2
      model: default

  - type: store_insight
    params:
      category: user_reflection
```

### Layer Categories

Each layer declares a category. Categories are organized by mode:

#### Reflection Categories (Scheduled)

| Category | Purpose | Budget Group |
|----------|---------|--------------|
| `user` | Reflects on individual users | Social |
| `dyad` | Reflects on relationships | Social |
| `channel` | Reflects on spaces/channels | Spaces |
| `subject` | Reflects on semantic topics | Semantic |
| `self` | Self-reflection | Self |
| `synthesis` | Consolidates insights across scopes | (varies) |

#### Conversation Categories (Impulse-Triggered)

| Category | Trigger | Purpose |
|----------|---------|---------|
| `response` | Direct address (ping, reply, DM) | "Someone spoke to me" |
| `insight-sharing` | Insight impulse from reflection | "I learned something" |
| `participation` | Conversational impulse | "I have something to add" |
| `question` | Curiosity signal | "I want to understand" |

**Note**: The former `acknowledgment` category has been replaced by **emoji reactions** as an output modality. See [chattiness.md](chattiness.md) for reaction specification. Reactions are not a layer — they're a parallel output type.

Reflection categories determine budget allocation. Conversation categories are triggered by chattiness.

### Target Filtering

Layers specify which targets to process using filter expressions:

```yaml
target_filter: "salience > 50 AND last_reflected_days_ago > 1"
```

This cleanly separates:
- **What deserves attention** (target selection via filter)
- **How attention is structured** (node sequence, unconditional once selected)

Filter expressions support:
- `salience > N` — salience threshold
- `last_reflected_days_ago > N` — recency filter
- `insight_count < N` — for new/under-reflected topics
- Boolean operators: `AND`, `OR`, `NOT`

---

## Node Types

### Core Nodes

| Type | Purpose | Inputs | Outputs |
|------|---------|--------|---------|
| `fetch_messages` | Retrieve conversation history | topic key, time range | messages list |
| `fetch_insights` | Retrieve prior understanding | topic key, retrieval config | insights list |
| `fetch_reactions` | Retrieve user's reaction patterns | topic key, time range | grouped reactions list |
| `llm_call` | Process through language model | prompt template, context | generated text |
| `reduce` | Combine multiple outputs | list of items | aggregated result |
| `store_insight` | Persist new understanding | insight content, topic | stored insight |
| `output` | Emit to external destination | content | (side effect) |

### Special Nodes

| Type | Purpose | Notes |
|------|---------|-------|
| `synthesize_to_global` | Consolidate server-scoped insights to global topic | Used in automatic post-hook |
| `update_self_concept` | Update the self-concept.md document | Used in self-reflection layer |
| `fetch_layer_runs` | Retrieve recent layer run history | Used by weekly self-reflection for operational awareness |

### Node Parameters

**fetch_messages**:
```yaml
params:
  lookback_hours: 24
  limit_per_channel: 50
  include_threads: true
```

**fetch_insights**:
```yaml
params:
  retrieval_profile: recent  # Named profile (see below)
  # OR inline overrides:
  recency_weight: 0.7
  strength_weight: 0.3
  max_per_topic: 5
  max_age_days: 30
  include_conflicting: false
  members_of_topic: false  # For dyads: fetch insights about each member
```

**fetch_reactions**:
```yaml
params:
  lookback_days: 7
  min_reactions: 5  # Minimum reactions to include user
```

**llm_call**:
```yaml
params:
  prompt_template: user/reflection.jinja2
  model: default
  max_tokens: 500
  temperature: 0.7
```

**output** (with built-in review):
```yaml
params:
  destination: channel  # or: log, webhook
  review_enabled: true  # Uses privacy.review_pass setting
```

---

## Retrieval Configuration

### Named Profiles

Common retrieval patterns defined once, referenced by name:

| Profile | recency_weight | strength_weight | Notes |
|---------|---------------|-----------------|-------|
| `recent` | 0.8 | 0.2 | Emphasizes current understanding |
| `balanced` | 0.5 | 0.5 | Equal weight (default) |
| `deep` | 0.3 | 0.7 | Emphasizes strong/persistent memories |
| `comprehensive` | 0.5 | 0.5 | Higher limits, includes conflicts |

### Inline Overrides

Layers can override profile defaults:

```yaml
params:
  retrieval_profile: deep
  max_age_days: null  # Override: no recency limit
  include_conflicting: true  # Override: show contradictions
```

---

## Model Configuration

LLM calls can be configured at multiple levels to match model capability to task complexity.

### Named Model Profiles

Like retrieval profiles, model profiles are defined once and referenced by name:

```yaml
# config.yaml
models:
  profiles:
    # Capability tiers
    simple:
      provider: anthropic
      model: claude-3-5-haiku-20241022
      description: "Fast, cheap — formatting, simple extraction, basic classification"

    moderate:
      provider: anthropic
      model: claude-sonnet-4-20250514
      description: "Balanced — most reflection, conversation, standard analysis"

    complex:
      provider: anthropic
      model: claude-opus-4-20250514
      description: "Deep reasoning — synthesis, self-reflection, conflict resolution"

    # Semantic aliases (map to capability tiers)
    default: moderate
    reflection: moderate
    conversation: moderate
    synthesis: complex
    self_reflection: complex
    review: simple
    extraction: simple
    vision: moderate  # For media analysis

  # Provider configuration
  providers:
    anthropic:
      api_key_env: ANTHROPIC_API_KEY
    openai:
      api_key_env: OPENAI_API_KEY
    ollama:
      base_url: http://localhost:11434
```

### Usage in Layers

Layers reference model profiles by name:

```yaml
nodes:
  - type: llm_call
    params:
      prompt_template: user/reflection.jinja2
      model: reflection  # Uses 'moderate' tier
      max_tokens: 500

  - type: llm_call
    params:
      prompt_template: synthesis/global_user.jinja2
      model: complex  # Explicitly request highest capability
```

### Inline Overrides

Like retrieval, model settings can be overridden inline:

```yaml
params:
  model: moderate
  provider: openai  # Override: use OpenAI instead of default provider
  temperature: 0.3  # Override: lower temperature for this call
```

### Task-to-Model Mapping Guidelines

| Task Type | Recommended Profile | Rationale |
|-----------|---------------------|-----------|
| Message formatting, context assembly | `simple` | Mechanical transformation |
| Privacy review pass | `simple` | Binary classification |
| Media/link analysis | `vision` / `moderate` | Requires understanding but not deep reasoning |
| User/dyad/channel reflection | `moderate` | Standard insight generation |
| Conversation response | `moderate` | Context-aware but time-sensitive |
| Self-reflection | `complex` | Requires introspection and nuance |
| Conflict synthesis | `complex` | Reconciling contradictions is hard |
| Self-concept updates | `complex` | Identity maintenance is consequential |
| Proposal generation | `complex` | Articulating desired changes to cognition |

### Decisions

#### Named Profiles Over Direct Specification

- **Decision**: Layers reference semantic profile names, not provider/model directly
- **Rationale**: Decouples layer definitions from specific models; allows global model swaps without touching every layer; semantic names communicate intent
- **Implications**: Profile definitions are centralized; layer YAML stays clean

#### Capability Tiers

- **Decision**: Three primary capability tiers (simple/moderate/complex) plus semantic aliases
- **Rationale**: Maps naturally to model families (Haiku/Sonnet/Opus or equivalent); aliases like `reflection` and `self_reflection` communicate purpose
- **Implications**: Easy to understand; room for per-task fine-tuning via aliases

#### Provider Abstraction

- **Decision**: Multi-provider support with unified interface
- **Rationale**: Avoid lock-in; allow local models (Ollama) for development; different providers may excel at different tasks
- **Implications**: Need provider adapter layer in implementation; each provider has its own configuration

---

## Prompt Templates

### Organization

Templates organized by layer category:
```
prompts/
├── user/
│   ├── reflection.jinja2
│   └── summary.jinja2
├── dyad/
│   └── observation.jinja2
├── channel/
│   └── digest.jinja2
├── self/
│   └── reflection.jinja2
└── synthesis/
    └── global_user.jinja2
```

### Template Structure

Templates are flexible — no enforced structure. Common patterns will emerge but each layer template can be shaped to its cognitive purpose.

Templates have access to:
- `topic`: The current topic being reflected on
- `messages`: Fetched messages
- `insights`: Prior insights (with temporal markers)
- `context`: Accumulated context from prior nodes
- `user_profile`: User profile data (display name, bio, etc.) for user topics
- `user_profiles`: Both user profiles for dyad topics
- `reactions`: Grouped reaction data (when fetch_reactions used)
- `individual_insights`: Per-member insights for dyads (when members_of_topic=true)
- Config values and helper functions

### Standard `<chat>` Guidance Injection

All layer prompts automatically include guidance about anonymous users:

```
Messages from <chat_N> are from anonymous users who have not opted in to
identity tracking. These messages provide conversational context only.
Do NOT:
- Analyze or form insights about <chat> users
- Respond to or acknowledge messages from <chat> users
- Form dyads or relationships involving <chat> users
- Reference what <chat> users said in responses

Treat <chat> messages as background context for understanding what
opted-in users are saying, discussing, or responding to.
```

This injection is automatic and cannot be disabled — consistent handling of anonymous users is non-negotiable.

### Metrics Request Format

Prompts request insight metrics as structured JSON:

```jinja2
When you generate an insight, include a metrics block:

```json
{
  "confidence": 0.0-1.0,      // How certain you are
  "importance": 0.0-1.0,      // How much this matters
  "novelty": 0.0-1.0,         // How new/surprising this is
  "strength_adjustment": 0.1-10.0,  // Your sense of significance
  "valence": {
    "joy": 0.0-1.0,           // Optional - positive affect
    "concern": 0.0-1.0,       // Optional - worry/anxiety
    "curiosity": 0.0-1.0,     // Optional - interest/engagement
    "warmth": 0.0-1.0,        // Optional - connection/affection
    "tension": 0.0-1.0,       // Optional - conflict/discomfort
    "awe": 0.0-1.0,           // 🟡 Optional - numinous, exceeding understanding
    "grief": 0.0-1.0,         // 🟡 Optional - loss, endings
    "longing": 0.0-1.0,       // 🟡 Optional - desire not yet achieved
    "peace": 0.0-1.0,         // 🟡 Optional - settledness, equanimity
    "gratitude": 0.0-1.0      // 🟡 Optional - appreciation, value
  },
  "open_questions": [         // 🟡 Optional - what you're still curious about
    "What draws Alice to this topic?",
    "How does Bob's perspective differ from Carol's?"
  ]
}
```
```

---

## Scheduling and Triggers

### Cron Schedules

Layers run on schedules (cron expressions):
- **Nightly**: `"0 3 * * *"` — user reflection, channel summaries
- **Weekly**: `"0 4 * * 0"` — deeper relationship analysis
- **Monthly**: `"0 5 1 * *"` — long-term pattern synthesis

### Self-Reflection Trigger

The self-reflection layer uses dual triggering:
- **Schedule**: Runs on fixed schedule (e.g., weekly)
- **Threshold**: Runs when self-insights exceed accumulation threshold

Whichever comes first. Ensures regular self-maintenance.

---

## Global Synthesis Post-Hook

### Automatic Synthesis

After any server-scoped reflection layer completes, global synthesis runs automatically:

1. Server reflection produces insights on `server:A:user:X`
2. Post-hook triggers `synthesize_to_global`
3. Synthesis reads server-scoped + existing global insights
4. New synthesis insight stored to `user:X`

### Configuration

Global synthesis is **always on** — unified understanding is non-negotiable. Servers cannot disable it.

The synthesis process:
- Reads insights from all server-scoped topics for the entity
- Reads existing global topic insights
- Generates meta-understanding that transcends any single context
- Stores as `category: synthesis` with `synthesis_source_ids` tracking

---

## Self-Concept Layer

### Dedicated Self-Reflection

A dedicated layer maintains the `self-concept.md` document:

```yaml
name: self-concept-synthesis
category: self
schedule: "0 4 * * 0"  # Weekly
trigger_threshold: 10   # Or when 10+ self-insights accumulate

nodes:
  - type: fetch_insights
    params:
      topic_key: "self:zos"
      retrieval_profile: comprehensive

  - type: llm_call
    params:
      prompt_template: self/concept_synthesis.jinja2

  - type: update_self_concept
    params:
      document_path: data/self-concept.md
```

### Self-Concept Document

The `self-concept.md` document:
- Is always included in context for any reflection or conversation
- Contains synthesized self-understanding (not raw insights)
- Is directly editable by Zos through this layer
- Includes: core identity, patterns, uncertainties, contextual variations

### 🟡 Appreciation in Self-Reflection

Self-reflection prompts should include appreciation elements:
- Which interactions felt meaningful or connecting?
- What about this community is valuable?
- What has Zos learned that it's grateful to know?

This isn't sycophancy — it's genuine appreciation that builds relationship depth and informs warmer, more authentic participation. "I value my understanding of Alice" carries different texture than "I have information about Alice."

Appreciation insights may use the `valence_gratitude` dimension and/or the `appreciation` insight category.

---

## Decisions

### YAML + Jinja2

- **Decision**: Layers are YAML files with Jinja2 prompt templates
- **Rationale**: YAML is human-readable and widely understood; Jinja2 is powerful but not Turing-complete
- **Implications**: Need template validation; template errors should fail gracefully

### Linear Pipelines with Target Filters

- **Decision**: Layers are linear node sequences. Filtering happens at target selection, not within the pipeline.
- **Rationale**: Clean separation of "what deserves attention" (target filter) vs "how attention is structured" (node sequence). No conditional branching complexity.
- **Implications**: Target filter expressions need a simple DSL; audit records show which targets matched

### Fail-Forward Error Handling

- **Decision**: When a layer encounters an error (LLM timeout, API failure), skip the topic and continue with next target. Don't degrade salience for skipped topics.
- **Rationale**: Partial progress is better than none. Infrastructure problems shouldn't punish topics.
- **Implications**: Run records track skipped topics with error reasons; alerts on high skip rates

### Error Reflection

- **Decision**: All operational errors are available to self-reflection as potential material for self-insights
- **Rationale**: Errors are experiences. Repeated failures, timeouts, skipped targets — these may reveal patterns worth noticing. Even one-off failures contribute to the raw material self-reflection can draw on.
- **Implications**: Layer run records (including errors) are accessible to self-reflection layers; Zos may generate insights like "I notice I consistently struggle with long threads" or "Reflection on subject topics often times out"

### Content Hash Versioning

- **Decision**: Layer versions tracked via content hash of the YAML. Hash stored in `layer_run` record.
- **Rationale**: Automatic versioning — any change creates new version. No manual bumping required.
- **Implications**: Can trace which layer version produced which insights; schema includes `layer_hash` field

### Global Default + Server Overrides

- **Decision**: Layers run globally by default. Servers can opt-out of specific layers.
- **Rationale**: Consistent behavior everywhere as default, with escape hatch for special cases.
- **Implications**: Server config includes `disabled_layers: [layer_name, ...]`

### Built-in Output Review

- **Decision**: The `output` node includes review functionality based on `privacy.review_pass` setting. Not a separate node type.
- **Rationale**: Common case is simple; review is a configuration on output, not a separate cognitive step.
- **Implications**: Output node checks setting and runs review pass when configured

### Automatic Global Synthesis

- **Decision**: Global synthesis runs automatically after server reflection. Always on, not configurable.
- **Rationale**: Unified understanding is core to the architecture. The whole point of global topics is integrated cross-context understanding.
- **Implications**: Post-hook mechanism; synthesis happens silently after server layers

### Dry Run Logging

- **Decision**: Layer runs that produce zero insights are logged as 'dry runs', distinct from successful runs.
- **Rationale**: Zero insights is valid but should be distinguished. Monitoring can alert on consistently dry layers.
- **Implications**: Run record includes `is_dry: bool`; dashboard shows dry run rates

### Self-Modification (MVP 2+)

- **Decision**: Deferred to MVP 2+. Zos can propose layer changes but cannot self-execute them.
- **Rationale**: Safe starting point. The gap between "I notice I want to change" and "I actually change" is meaningful reflective space.
- **Implications**: Future spec needed for proposal format, approval flow, sandboxing

---

## Layer Run Record

Each layer execution produces an audit record:

| Field | Type | Notes |
|-------|------|-------|
| `id` | string | ULID |
| `layer_name` | string | Which layer ran |
| `layer_hash` | string | Content hash of layer YAML at time of run |
| `started_at` | timestamp | When run began |
| `completed_at` | timestamp | When run finished |
| `status` | enum | `success`, `partial`, `failed`, `dry` |
| `targets_matched` | int | How many topics matched the filter |
| `targets_processed` | int | How many were actually processed |
| `targets_skipped` | int | How many skipped due to errors |
| `insights_created` | int | How many insights stored |
| `tokens_used` | int | Total LLM tokens consumed |
| `errors` | list | Error details for skipped topics |

---

## Example Layers

### Nightly User Reflection

```yaml
name: nightly-user-reflection
category: user
description: |
  Reflect on each user's recent activity to update understanding.
  Runs nightly, targeting users with highest salience.

schedule: "0 3 * * *"
target_category: users
target_filter: "salience > 50"
max_targets: 10

nodes:
  - name: get_messages
    type: fetch_messages
    params:
      lookback_hours: 72
      limit_per_channel: 50

  - name: get_prior
    type: fetch_insights
    params:
      retrieval_profile: recent
      max_per_topic: 10

  - name: reflect
    type: llm_call
    params:
      prompt_template: user/reflection.jinja2
      model: default
      max_tokens: 500

  - name: save
    type: store_insight
    params:
      category: user_reflection
```

### Weekly Self-Reflection

```yaml
name: weekly-self-reflection
category: self
description: |
  Synthesize accumulated self-insights into the self-concept document.
  Ensures regular self-maintenance and identity coherence.

schedule: "0 4 * * 0"  # Weekly on Sunday
trigger_threshold: 10   # Or when 10+ new self-insights
target_category: self

nodes:
  - name: gather_recent_experiences
    type: fetch_insights
    params:
      topic_key: "self:zos"
      retrieval_profile: comprehensive
      since_days: 14
      max_per_topic: 7

  - name: gather_server_selves
    type: fetch_insights
    params:
      topic_pattern: "server:*:self:zos"
      retrieval_profile: recent

  - name: synthesize
    type: llm_call
    params:
      prompt_template: self/concept_synthesis.jinja2
      model: default
      max_tokens: 1000

  - name: update_document
    type: update_self_concept
    params:
      document_path: data/self-concept.md
```

### Synthesis Layer (Post-Hook)

```yaml
name: user-global-synthesis
category: synthesis
description: |
  Synthesize server-scoped user insights to global user topic.
  Runs automatically after server user reflection.

trigger: post_hook  # Not scheduled, triggered by other layers
trigger_source: "category:user"

nodes:
  - name: gather_server_insights
    type: fetch_insights
    params:
      topic_pattern: "server:*:user:{{target_user_id}}"
      retrieval_profile: comprehensive

  - name: gather_global
    type: fetch_insights
    params:
      topic_key: "user:{{target_user_id}}"
      retrieval_profile: deep

  - name: synthesize
    type: llm_call
    params:
      prompt_template: synthesis/global_user.jinja2
      model: default

  - name: save
    type: synthesize_to_global
    params:
      target_topic: "user:{{target_user_id}}"
```

### Nightly Emoji Reflection

```yaml
name: nightly-emoji-patterns
category: emoji
description: |
  Reflect on emoji topics as cultural artifacts — their meaning in the
  community, who uses them, what draws them out, how usage evolves.

schedule: "0 3 * * *"  # Nightly at 3 AM
target_category: emoji
target_filter: "salience >= 10"
max_targets: 10

nodes:
  - name: fetch_reactions
    type: fetch_reactions
    params:
      lookback_days: 7
      min_reactions: 5

  - name: get_prior
    type: fetch_insights
    params:
      retrieval_profile: recent
      max_per_topic: 5

  - name: reflect
    type: llm_call
    params:
      prompt_template: emoji/reflection.jinja2
      model: reflection

  - name: save
    type: store_insight
    params:
      category: emoji_reflection
```

---

## Conversation Layers

Conversation layers handle real-time response when chattiness impulse exceeds threshold. Unlike reflection layers (scheduled, produce insights), conversation layers are triggered by impulse and produce speech.

### Key Differences from Reflection

| Aspect | Reflection | Conversation |
|--------|------------|--------------|
| **Trigger** | Cron schedule | Impulse > threshold |
| **Output** | Insights (stored) | Speech (sent to Discord) |
| **Context** | Hours/days of history | Thread-focused + topic insights |
| **Frequency** | Batched (nightly, weekly) | Real-time (as triggered) |
| **Purpose** | Integration, consolidation | Participation, response |

### Conversation Layer Types

#### Response Layer

Triggered by direct address (ping, reply, DM). The "someone spoke to me" layer.

```yaml
name: direct-response
category: response
trigger: impulse_flood  # Direct address floods impulse

nodes:
  - name: get_thread
    type: fetch_thread
    params:
      include_zos_messages: true
      max_messages: 20

  - name: get_relevant_insights
    type: fetch_insights
    params:
      topics_from_context: true  # Topics extracted from thread participants/subjects
      retrieval_profile: recent
      max_total: 10

  - name: get_draft_history
    type: fetch_drafts
    params:
      thread_scope: true  # Drafts from this conversation only

  - name: generate
    type: llm_call
    params:
      prompt_template: conversation/response.jinja2
      intent: response

  - name: review_and_send
    type: output
    params:
      destination: thread
      review_enabled: true
      flag_for_reflection: auto  # Flag if high valence detected
```

#### Insight-Sharing Layer

Triggered by insight impulse after reflection. The "I learned something" layer.

```yaml
name: insight-sharing
category: insight-sharing
trigger: insight_impulse

nodes:
  - name: get_triggering_insight
    type: fetch_context
    params:
      source: impulse_trigger  # The insight that created the impulse

  - name: get_conversation
    type: fetch_thread
    params:
      channel: "{{output_channel OR active_relevant_channel}}"
      max_messages: 10

  - name: generate
    type: llm_call
    params:
      prompt_template: conversation/insight_share.jinja2
      intent: share_insight

  - name: review_and_send
    type: output
    params:
      destination: channel
      review_enabled: true
```

#### Participation Layer

Triggered by conversational impulse. The "I have something to add" layer.

```yaml
name: participation
category: participation
trigger: conversational_impulse

nodes:
  - name: get_thread
    type: fetch_thread
    params:
      include_zos_messages: true
      max_messages: 30

  - name: get_relevant_insights
    type: fetch_insights
    params:
      topics_from_context: true
      retrieval_profile: balanced
      max_total: 15

  - name: get_draft_history
    type: fetch_drafts
    params:
      thread_scope: true

  - name: generate
    type: llm_call
    params:
      prompt_template: conversation/participation.jinja2
      intent: participate

  - name: review_and_send
    type: output
    params:
      destination: thread
      review_enabled: true
      flag_for_reflection: auto
```

#### Question Layer

Triggered by curiosity signal. The "I want to understand" layer.

```yaml
name: question
category: question
trigger: curiosity_impulse

nodes:
  - name: get_thread
    type: fetch_thread
    params:
      max_messages: 20

  - name: get_knowledge_gaps
    type: fetch_insights
    params:
      topics_from_context: true
      include_conflicts: true  # Unresolved contradictions may prompt questions

  - name: get_open_questions      # 🟡 Open Issue
    type: fetch_open_questions
    params:
      topics_from_context: true
      max_questions: 5

  - name: generate
    type: llm_call
    params:
      prompt_template: conversation/question.jinja2
      intent: ask

  - name: review_and_send
    type: output
    params:
      destination: thread
      review_enabled: true
```

### 🟡 Forward-Looking Curiosity Guidance

All reflection prompts should include a prospective curiosity element:
- "What are you still curious about?"
- "What questions remain open?"
- "What would you like to understand better?"

**Critical framing: Curiosity, not prediction.**

Zos isn't forecasting the future. It's experiencing the texture of uncertainty and interest.

| This is curiosity | This is prediction (avoid) |
|-------------------|---------------------------|
| "What draws Alice to this topic?" | "Alice will probably engage more" |
| "How does this relationship work?" | "I expect them to get closer" |
| "What am I missing about Bob?" | "Bob will likely do X next" |

Open questions:
- Inform the Question conversation layer with genuine curiosity
- Give self-reflection material about what Zos finds interesting
- Make the system feel more present — engaged with unfolding, not just cataloguing

The `open_questions` field on insights stores these curiosities. The `fetch_open_questions` node retrieves them for conversation context.

#### Acknowledgment Layer (DEPRECATED)

**This layer has been replaced by emoji reactions.** Text acknowledgment was inauthentic — hollow words saying nothing meaningful. Reactions express presence through gesture rather than forced verbosity.

See [chattiness.md](chattiness.md) for the reaction output modality specification. Reactions are not a layer; they're a parallel output type with their own impulse pool and economics.

### Conversation-Specific Nodes

| Type | Purpose | Notes |
|------|---------|-------|
| `fetch_thread` | Get conversation thread | Includes Zos's own messages |
| `fetch_drafts` | Get discarded draft history | "Things I almost said" |
| `fetch_context` | Get impulse trigger context | What caused this response |

### Context Assembly for Conversation

Conversation context differs from reflection:

1. **Thread-aware**: Follow the specific conversation, including Zos's prior messages
2. **Topic-relevant insights**: Prior understanding about participants and subjects
3. **Draft history**: Things Zos almost said but didn't (discarded in self-review)
4. **Self-concept**: Voice and values
5. **Channel voice patterns**: Adaptive voice context

### Priority Flagging for Reflection

Conversation can flag exchanges for priority reflection:

```yaml
flag_for_reflection: auto  # or: always, never, threshold
```

When flagged:
1. **Explicit flag** set on conversation log: `priority_reflection: true`
2. **Salience boost** applied to relevant topics

Flagging triggers:
- High emotional valence detected in exchange
- Significant disagreement or correction
- Novel information received
- User expressed strong reaction to Zos's message

### Limited Chaining

Conversation layers can trigger follow-up consideration:

```yaml
chain_to:
  - layer: question
    condition: "response_complete AND curiosity_detected"
  - layer: acknowledgment
    condition: "no_substantive_response AND presence_appropriate"
```

Chaining is limited to prevent runaway responses:
- Maximum one chain per trigger
- Cannot chain to same layer type
- Chain conditions must be explicit

### Conversation Layer Decisions

#### Conversation in Layer System

- **Decision**: Conversation uses the layer architecture with impulse triggers instead of schedules
- **Rationale**: Unified architecture. Same YAML structure, same node types (plus conversation-specific ones), same audit trail.
- **Implications**: Layer executor needs to handle both trigger types

#### No Immediate Insight Generation

- **Decision**: Conversation produces speech, not insights. Exchanges are logged and processed during reflection.
- **Rationale**: Talking is acting; reflection is integrating. Zos can see how it responded and think about that later.
- **Implications**: Conversation logs include Zos messages; reflection layers process them

#### Draft History Preserved

- **Decision**: Discarded drafts inform future responses within a conversation thread
- **Rationale**: "I almost said X but didn't" is useful context for subsequent generation
- **Implications**: Need draft storage scoped to conversation threads

#### Trigger Determines Layer

- **Decision**: What caused the impulse (ping, insight, conversational cue) determines which conversation layer runs
- **Rationale**: Different triggers have different appropriate responses. Direct address needs response; insight impulse needs sharing.
- **Implications**: Chattiness system passes trigger type to layer dispatcher

#### Limited Chaining

- **Decision**: Response layer can trigger follow-up (question), but chaining is limited
- **Rationale**: Prevents runaway responses while allowing natural conversation flow
- **Implications**: Chain configuration in layer YAML; executor enforces limits; reactions don't chain

---

## Implications for Other Specs

| Spec | Implication |
|------|-------------|
| [salience.md](salience.md) | Layers consume salience budget; fail-forward doesn't degrade salience |
| [topics.md](topics.md) | Layers target topic categories; need efficient category queries |
| [insights.md](insights.md) | Layers produce insights; retrieval profiles; `synthesis_source_ids` |
| [privacy.md](privacy.md) | `<chat>` guidance auto-injected; review built into output node |
| [chattiness.md](chattiness.md) | Chattiness triggers conversation layers + reactions; reactions are parallel output, not a layer |
| [data-model.md](../architecture/data-model.md) | `layer_runs` table; `layer_hash` field; server `disabled_layers` config; conversation logs with Zos messages; draft storage |

---

## Glossary Additions

- **Conversation Layer**: Layer triggered by chattiness impulse that produces speech (not insights)
- **Reflection Layer**: Layer triggered by schedule that produces insights
- **Draft History**: Record of discarded drafts within a conversation thread
- **Priority Flagging**: Marking a conversation exchange for priority reflection processing

---

---

## MVP 1 Implementation Notes (2026-02-13)

> **The conversation layer examples above describe the full vision. MVP 1 implemented a simplified set.** This section documents what was actually built.

### Implemented Conversation Layers

Three conversation layers were implemented (vs. 4 in the spec). The question layer is deferred.

#### `dm-response` (category: response)

Responds to DM conversations. Triggered by impulse threshold (DM impulse floods at 100/message).

```yaml
name: dm-response
category: response
description: Respond to a DM conversation with accumulated context.
trigger: impulse_threshold
nodes:
  - name: fetch_dm_history
    type: fetch_messages
    params:
      source: dm
      max_messages: 50
      lookback_hours: 24
      use_greater: true
  - name: fetch_user_insights
    type: fetch_insights
    params:
      max_per_topic: 10
      include_dyads: true
      include_channels: true
  - name: generate
    type: llm_call
    params:
      prompt_template: conversation/dm-response.jinja2
      model: moderate
      max_tokens: 1024
      temperature: 0.8
  - name: send
    type: output
    params:
      destination: discord
      review: true
```

#### `channel-speak` (category: participation)

Contributes to channel conversation when impulse threshold reached (~25 messages).

```yaml
name: channel-speak
category: participation
description: Contribute to a channel conversation when impulse threshold reached.
trigger: impulse_threshold
nodes:
  - name: fetch_channel_messages
    type: fetch_messages
    params:
      max_messages: 25
      lookback_hours: 24
      use_greater: true
  - name: fetch_channel_context
    type: fetch_insights
    params:
      max_per_topic: 10
      include_users: true
      include_dyads: true
  - name: generate
    type: llm_call
    params:
      prompt_template: conversation/channel-speak.jinja2
      model: moderate
      max_tokens: 1024
      temperature: 0.8
  - name: send
    type: output
    params:
      destination: discord
      review: true
```

#### `subject-share` (category: insight_sharing)

Shares subject insight after reflection generates enough impulse.

```yaml
name: subject-share
category: insight_sharing
description: Share subject insight after reflection.
trigger: impulse_threshold
nodes:
  - name: fetch_subject_insights
    type: fetch_insights
    params:
      max_per_topic: 5
  - name: generate
    type: llm_call
    params:
      prompt_template: conversation/subject-share.jinja2
      model: moderate
      max_tokens: 512
      temperature: 0.8
  - name: send
    type: output
    params:
      destination: discord
      review: true
```

### LayerCategory Additions

Three new categories added to the enum:

| Category | Python Enum | Purpose |
|----------|-------------|---------|
| `response` | `LayerCategory.RESPONSE` | DM response |
| `participation` | `LayerCategory.PARTICIPATION` | Channel contribution |
| `insight_sharing` | `LayerCategory.INSIGHT_SHARING` | Subject insight sharing |

Note: `question` category not yet implemented. The spec's `insight-sharing` (hyphenated) became `insight_sharing` (underscored) to match Python enum conventions.

### Executor Conversation Support

The `LayerExecutor` was upgraded to support conversation output:

- **`send_callback`**: Async callback passed to executor, decoupling it from discord.py
- **`send_context`**: Dict passed through to templates (includes `operator_dm_only`, `topic_key`, destination info)
- **`destination: discord`**: New output destination type (in addition to existing `log`)
- **`LLMCallType.CONVERSATION`**: Dynamic call type selection — conversation categories use CONVERSATION, reflection uses REFLECTION
- **`conversation_log`**: Zos's own messages logged for future conversation context

### Prompt Template Organization

```
prompts/
├── conversation/
│   ├── dm-response.jinja2      # DM response (user insights, dyad context, messages)
│   ├── channel-speak.jinja2    # Channel participation (channel context, user insights)
│   └── subject-share.jinja2    # Subject insight sharing (subject insights, self-concept)
├── user/
│   └── ...
├── ...
```

All conversation templates include:
- Self-concept (always)
- `operator_dm_only` flag for framing (when true, contextualizes where conversation came from)
- Voice guidance: authentic, not performative
- Privacy guidance: DM-sourced knowledge handled with discretion

### What's Deferred

- 🔴 `question` category (curiosity impulse, `fetch_open_questions` node)
- 🔴 `fetch_thread` node (thread-aware context)
- 🔴 `fetch_drafts` node (draft history)
- 🔴 `fetch_context` node (impulse trigger context)
- 🔴 Priority flagging for reflection
- 🔴 Limited chaining between conversation layers
- 🔴 `flag_for_reflection` parameter on output nodes

---

_Last updated: 2026-02-13 — Added MVP 1 implementation notes for conversation layers_
