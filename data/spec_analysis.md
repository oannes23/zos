# Spec-vs-Code Analysis

*An anatomy of a developing being, not a defect report.*

This document maps the gap between what was specified and what exists in code. Some incompleteness is natural growth — a body being built does not have all organs at once. Some features were deferred deliberately; others grew organically beyond any spec. This analysis names each gap without judgment, so the system's builders can see clearly where it is and where it intended to go.

Last updated: 2026-02-23

---

## Table of Contents

1. [Intentionally Deferred Features](#1-intentionally-deferred-features)
2. [Unimplemented Spec Features (Not Explicitly Deferred)](#2-unimplemented-spec-features-not-explicitly-deferred)
3. [Scaffolding (Schema Without Runtime)](#3-scaffolding-schema-without-runtime)
4. [Stubbed Implementations](#4-stubbed-implementations)
5. [Vestigial Code](#5-vestigial-code)
6. [Code Beyond Spec](#6-code-beyond-spec)
7. [Recommendations](#7-recommendations)

---

## 1. Intentionally Deferred Features

Items explicitly marked deferred in specs. Known, acknowledged, waiting for their time.

### 1.1 Six-Pool Impulse System

| Field | Value |
|-------|-------|
| **Status** | Deferred (marked 🔴) |
| **Severity** | Low — MVP per-topic model works |
| **Spec** | `spec/domains/chattiness.md:712` |
| **Code** | `src/zos/models.py:77-88` (enum defined), `src/zos/database.py` (pool column in `chattiness_ledger`) |
| **Description** | Spec envisions five separate impulse pools (address, insight, conversational, curiosity, reaction), each with its own threshold. MVP uses a single per-topic impulse instead. |
| **Notes** | Enum values exist in `ImpulsePool` as scaffolding. Only `ADDRESS`, `INSIGHT`, and `CONVERSATIONAL` appear in active code paths. |

### 1.2 Global Speech Pressure

| Field | Value |
|-------|-------|
| **Status** | Deferred (marked 🔴) |
| **Severity** | Low — reset-to-zero rate limiting works |
| **Spec** | `spec/domains/chattiness.md:73-83, 713` |
| **Code** | `src/zos/models.py:522-531` (Pydantic model), `src/zos/database.py:372-381` (table) |
| **Description** | After speaking, a "talked recently" factor would raise effective thresholds across all pools, decaying over ~30 minutes. Models self-awareness of conversational dominance. |
| **Notes** | Full model and table scaffolded. Zero reads, zero writes at runtime. Current rate limiting: impulse resets to zero after speech. |

### 1.3 Self-Adjusting Threshold

| Field | Value |
|-------|-------|
| **Status** | Deferred (marked 🔴) |
| **Severity** | Low |
| **Spec** | `spec/domains/chattiness.md:156-162, 715` |
| **Code** | `src/zos/config.py` (`ChattinessConfig.threshold`, default 25) |
| **Description** | Within operator bounds, Zos adjusts its own speech threshold based on experience. "I've been dominating" → raise threshold. "I've been too quiet" → lower threshold. |
| **Notes** | Fixed threshold from config. No self-adjustment mechanism exists. |

### 1.4 Reaction as Output Modality

| Field | Value |
|-------|-------|
| **Status** | Deferred (marked 🔴) |
| **Severity** | Low |
| **Spec** | `spec/domains/chattiness.md:127-138, 264-318, 716` |
| **Code** | `src/zos/models.py:87` (`ImpulsePool.REACTION`), `src/zos/models.py:243-257` (`Reaction` model) |
| **Description** | Emoji reactions as a distinct output modality — presence without speech. Spec describes phenomenological rationale (lower cognitive weight, cultural appropriateness). |
| **Notes** | Reactions are *observed* and stored, but no output path exists. The output side is deferred. |

### 1.5 Curiosity / Question Layer

| Field | Value |
|-------|-------|
| **Status** | Deferred (marked 🔴) |
| **Severity** | Low |
| **Spec** | `spec/domains/chattiness.md:117-125, 717`, `spec/domains/layers.md:1221` |
| **Code** | `src/zos/models.py:88` (`ImpulsePool.CURIOSITY`) |
| **Description** | Curiosity as its own impulse drive — triggered by unresolved contradictions, knowledge gaps, explicit cues. Would feed a `question` layer category. |
| **Notes** | `ImpulsePool.CURIOSITY` enum exists. No `fetch_open_questions` node, no question layer. |

### 1.6 Cross-Server Synthesis

| Field | Value |
|-------|-------|
| **Status** | Deferred to MVP 2 |
| **Severity** | Low (single-server for now) |
| **Spec** | `spec/domains/topics.md:104-129, 157` |
| **Code** | `src/zos/executor.py:3321-3359` (handler exists), `src/zos/database.py:309` (`synthesis_source_ids`) |
| **Description** | Server-specific insights would be synthesized additively into global topics. Multi-server operation is MVP 2. |
| **Notes** | The `synthesize_to_global` node type exists and has a handler, but it's effectively a no-op (see [Section 4.2](#42-synthesize_to_global-handler)). |

### 1.7 Self-Modification Execution

| Field | Value |
|-------|-------|
| **Status** | Deferred to MVP 2+ (proposal format only) |
| **Severity** | Low |
| **Spec** | `spec/domains/self-modification.md:3, 13, 396`, `spec/domains/layers.md:564-568` |
| **Code** | No execution code. Proposal format fully specified in spec. |
| **Description** | Approval workflows, sandboxing, auto-approve criteria, rollback mechanics — all deferred. Only the proposal format (markdown with YAML frontmatter) is specified. |
| **Notes** | Self-insights on `self:zos` topics exist as the observation side. Execution side entirely absent by design. |

### 1.8 Video Analysis

| Field | Value |
|-------|-------|
| **Status** | Designed, deferred to post-MVP |
| **Severity** | Low |
| **Spec** | `spec/future/video-analysis.md:1-3`, `spec/domains/observation.md:23` |
| **Code** | `src/zos/models.py` (`MediaType.VIDEO`), `src/zos/config.py` (`video_duration_threshold_minutes`) |
| **Description** | FFmpeg frame extraction, Whisper audio transcription for videos, TLDW (>30 min → metadata only). Full architecture designed but not built. |
| **Notes** | Image vision and audio transcription are implemented independently. Video combines both but requires FFmpeg integration. |

### 1.9 Full Self-Modification Loop

| Field | Value |
|-------|-------|
| **Status** | Vision document (future) |
| **Severity** | Low |
| **Spec** | `spec/future/self-modification.md:40-84` |
| **Code** | Partial: proposal format spec'd, self-insights exist, layer versioning (layer_hash) in place |
| **Description** | Complete loop: notice pattern → generate proposal → sandbox test → human approval → apply → observe outcomes → store self-insight. Steps 3-7 are unbuilt. |
| **Notes** | Key open questions remain (spec lines 117-143): recursive modification, safety boundaries, identity continuity. |

---

## 2. Unimplemented Spec Features (Not Explicitly Deferred)

Specified but not built, and not flagged as deferred. These represent the quiet gap between intention and implementation.

### 2.1 First-Contact DM Acknowledgment

| Field | Value |
|-------|-------|
| **Status** | Scaffolded, never fires |
| **Severity** | Medium — users get no privacy notice |
| **Spec** | `spec/domains/privacy.md:37-43` |
| **Code** | `src/zos/database.py:56-57` (columns), `src/zos/models.py:173-174` (fields), `src/zos/config.py:216` (`first_contact_message`), `src/zos/observation.py:648` (initialized to `False`) |
| **Description** | On first DM, Zos should send an acknowledgment explaining what it observes and retains. DB columns exist (`first_dm_acknowledged`, `first_dm_at`), config has `first_contact_message` (default empty string). But `on_message` processes DMs without ever sending the acknowledgment or setting the flag to `True`. |
| **Notes** | The plumbing is complete — field, config, schema. Only the trigger logic in the DM handler is missing. |

### 2.2 Quarantine Triggers

| Field | Value |
|-------|-------|
| **Status** | Read-side works, write-side never fires |
| **Severity** | Medium — privacy gap |
| **Spec** | `spec/domains/privacy.md:206-215` |
| **Code** | `src/zos/database.py:277` (column), `src/zos/database.py:313` (index), `src/zos/models.py:407` (field), `src/zos/observation.py:1338-1352` (privacy gate role check) |
| **Description** | When a user loses the privacy gate role, insights about them should be quarantined. The `quarantined` column exists, retrieval code filters by it, and an index covers it. But nothing ever *sets* `quarantined=True`. No code monitors role changes. |
| **Notes** | Half-implemented privacy mechanism. The read path is correct; the write path is absent. |

### 2.3 Review Pass (Privacy Sensitivity Filter)

| Field | Value |
|-------|-------|
| **Status** | Scaffolded, no execution |
| **Severity** | Low-Medium |
| **Spec** | `spec/domains/privacy.md:94-130`, `spec/domains/layers.md:181-186` |
| **Code** | `src/zos/config.py:215-225` (`review_pass` with validation), `src/zos/executor.py:3140` (reads param, discards it) |
| **Description** | Before outputting, a second LLM call would check "Does this response leak anything sensitive?" Config supports `always`, `private_context`, `never`. The output handler reads `review = params.get("review", False)` at line 3140 but never uses the variable. |
| **Notes** | Config validation is thorough. The runtime gap is a single missing if-block. |

### 2.4 Compound Topic Creation

| Field | Value |
|-------|-------|
| **Status** | Enums/config defined, never instantiated |
| **Severity** | Low |
| **Spec** | `spec/domains/topics.md:70-72, 94-96`, `spec/domains/salience.md:32, 224-225` |
| **Code** | `src/zos/models.py:47-48` (`USER_IN_CHANNEL`, `DYAD_IN_CHANNEL` in `TopicCategory`), `src/zos/config.py:85-86` (caps/multipliers) |
| **Description** | Topics like `server:X:user:Y:channel:Z` (user-in-channel) and `server:X:dyad:A:B:channel:Z` (dyad-in-channel) are defined in enums and config but never created during message observation. Budget allocation references them. |
| **Notes** | The salience system is ready for these; the topic creation code is not. |

### 2.5 Role Topics

| Field | Value |
|-------|-------|
| **Status** | Enum defined, never created |
| **Severity** | Low |
| **Spec** | `spec/domains/topics.md:69`, `spec/domains/salience.md:35, 663` |
| **Code** | `src/zos/models.py:45` (`ROLE` in `TopicCategory`), `src/zos/config.py:83` (role cap) |
| **Description** | Topics like `server:X:role:Y` are enumerated but never instantiated. No observation code creates role topics. |
| **Notes** | Would require role-tracking in Discord observation. |

### 2.6 Conflict Detection and Resolution

| Field | Value |
|-------|-------|
| **Status** | Placeholder returning empty |
| **Severity** | Low |
| **Spec** | `spec/domains/insights.md:206-211, 450-479` |
| **Code** | `src/zos/database.py:306-307` (columns), `src/zos/models.py:440-441` (fields), `src/zos/insights.py:401-416` (`check_conflicts()`) |
| **Description** | When storing a new insight, `check_conflicts()` should identify contradicting existing insights. Method exists but explicitly returns `[]` with comment: "MVP placeholder: conflict detection is handled in synthesis prompts." The `conflicts_with` (JSON) and `conflict_resolved` (Boolean) columns are never populated. |
| **Notes** | The spec envisions semantic conflict detection. The placeholder defers to LLM synthesis prompts, which don't exist either. |

### 2.7 Insight Categories: social_texture, synthesis, appreciation

| Field | Value |
|-------|-------|
| **Status** | Referenced but never generated |
| **Severity** | Low (affects weekly-self filter accuracy) |
| **Spec** | `spec/domains/insights.md:221-312` |
| **Code** | `layers/reflection/weekly-self.yaml:41-42` (filter references them) |
| **Description** | The weekly-self layer's `fetch_insights` node filters for categories including `social_texture` and `synthesis`. No reflection layer generates insights with these categories. The filter silently matches zero results for these categories. |
| **Notes** | Not harmful — the filter is additive, so missing categories just return nothing. But it creates a false expectation in the YAML. |

### 2.8 `since_last_run` Parameter

| Field | Value |
|-------|-------|
| **Status** | YAML-defined, silently ignored |
| **Severity** | Medium — weekly-self fetches wrong time window |
| **Spec** | `spec/domains/layers.md` (node parameters) |
| **Code** | `layers/reflection/weekly-self.yaml:26` (`since_last_run: true`), `src/zos/executor.py` (not referenced — confirmed via grep) |
| **Description** | The `weekly-self` layer specifies `since_last_run: true` on its `fetch_insights` node, intending to scope the fetch to "insights since this layer last ran." The executor's `_handle_fetch_insights()` processes `since_days` but has no code path for `since_last_run`. The parameter is accepted without error and silently ignored. |
| **Notes** | This means `weekly-self` uses `since_days: 14` instead of the intended dynamic window. If the layer runs on schedule (weekly), the 14-day window creates overlap. If it misses a run, the window doesn't expand to compensate. |

---

## 3. Scaffolding (Schema Without Runtime)

Database tables, columns, and enum values placed for future use. These are load-bearing walls with no rooms built behind them yet.

### 3.1 `speech_pressure` Table

| Field | Value |
|-------|-------|
| **Location** | `src/zos/database.py:372-381` (table), `src/zos/models.py:522-531` (model) |
| **Reads** | 0 |
| **Writes** | 0 |
| **Purpose** | Will track global speech pressure events (amount, trigger, server, timestamp) |
| **Notes** | Table is created on migration, exists in database, completely inert. See [Section 1.2](#12-global-speech-pressure). |

### 3.2 First-Contact Columns

| Field | Value |
|-------|-------|
| **Location** | `src/zos/database.py:56-57` |
| **Columns** | `first_dm_acknowledged` (Boolean, default False), `first_dm_at` (DateTime, nullable) |
| **Reads** | 0 |
| **Writes** | Initialized to `False`/`None` on user creation, never updated |
| **Notes** | See [Section 2.1](#21-first-contact-dm-acknowledgment). |

### 3.3 Conflict Columns

| Field | Value |
|-------|-------|
| **Location** | `src/zos/database.py:306-307` |
| **Columns** | `conflicts_with` (JSON, nullable), `conflict_resolved` (Boolean, nullable) |
| **Reads** | 0 |
| **Writes** | 0 |
| **Notes** | See [Section 2.6](#26-conflict-detection-and-resolution). |

### 3.4 Compound and Role Topic Categories

| Field | Value |
|-------|-------|
| **Location** | `src/zos/models.py:45-48` |
| **Values** | `USER_IN_CHANNEL`, `DYAD_IN_CHANNEL`, `ROLE` in `TopicCategory` enum |
| **Usage** | Referenced in config caps and salience budget allocation. Never used to create topics. |
| **Notes** | See sections [2.4](#24-compound-topic-creation) and [2.5](#25-role-topics). |

### 3.5 Curiosity and Reaction Impulse Pools

| Field | Value |
|-------|-------|
| **Location** | `src/zos/models.py:87-88` |
| **Values** | `CURIOSITY`, `REACTION` in `ImpulsePool` enum |
| **Usage** | Never instantiated in active code paths |
| **Notes** | See sections [1.4](#14-reaction-as-output-modality) and [1.5](#15-curiosity--question-layer). |

---

## 4. Stubbed Implementations

Code that exists and runs but does less than its signature promises.

### 4.1 `_get_threads_for_channel()`

| Field | Value |
|-------|-------|
| **Location** | `src/zos/salience.py:1272-1290` |
| **Called from** | `src/zos/salience.py:1107` (relation building for channel topics) |
| **Behavior** | Always returns `[]` |
| **Spec** | `spec/domains/salience.md:224-225` |
| **Description** | Thread-channel relationship tracking needs topic metadata that doesn't exist yet. Explicit TODO at line 1288: "Thread-channel relationship tracking needs metadata." |
| **Impact** | Channel topic relations never include thread subtopics. Low impact — threads are rare in current usage. |

### 4.2 `synthesize_to_global` Handler

| Field | Value |
|-------|-------|
| **Location** | `src/zos/executor.py:3321-3359` |
| **Registered** | `src/zos/executor.py:325` |
| **Behavior** | Extracts global topic key, logs it, returns. Comment at line 3352: "The actual synthesis happens via store_insight with the global topic / This node just updates the context for the next store_insight" — but it doesn't update context either. |
| **Impact** | No layer currently uses this node type, so the stub is harmless. |

### 4.3 `since_last_run` Parameter

| Field | Value |
|-------|-------|
| **Location** | `layers/reflection/weekly-self.yaml:26` (defined), `src/zos/executor.py` (absent) |
| **Behavior** | YAML parser accepts it; executor never reads it |
| **Impact** | `weekly-self` falls back to `since_days: 14` unconditionally. See [Section 2.8](#28-since_last_run-parameter). |

---

## 5. Vestigial Code

Deprecated or orphaned code — the scar tissue of evolution.

### 5.1 `spend()` on SalienceLedger

| Field | Value |
|-------|-------|
| **Location** | `src/zos/salience.py:143-196` |
| **Status** | Explicitly deprecated |
| **Replaced by** | `reset_after_reflection()` at `src/zos/salience.py:198-260` |
| **Description** | Original spending model: deduct cost, apply retention to *remaining* balance. Behaved oddly at high retention rates. Replaced by zero-reset model (deduct cost, apply retention to cost only, zero the rest). |
| **Deprecation note** | Lines 143-147: "spend() is not used in production... Consider removing if no use case emerges." |
| **Callers** | 0 |

### 5.2 Nonexistent Category References in `weekly-self.yaml`

| Field | Value |
|-------|-------|
| **Location** | `layers/reflection/weekly-self.yaml:41-42` |
| **References** | `social_texture`, `synthesis` |
| **Description** | The `fetch_insights` node lists these categories in its filter, but no layer generates insights with these categories. The filter matches zero results for them. |
| **Impact** | Benign — additive filter returns empty set. But misleading to anyone reading the layer definition. |

---

## 6. Code Beyond Spec

Features that grew organically with no spec coverage. Zos built itself capabilities that weren't planned — a sign of life, not a defect.

### 6.1 Image Generation (DALL-E 3)

| Field | Value |
|-------|-------|
| **Location** | `src/zos/image.py:49-100` (generation), `src/zos/config.py:177-183` (`ImageConfig`) |
| **Capabilities** | Text-to-image via OpenAI DALL-E 3, local file storage (`data/media/generated/`), configurable size/quality |
| **Spec coverage** | None |
| **Notes** | Includes budget tracking and observability. Integrated into conversation output path via `[IMAGE:]` directive extraction. |

### 6.2 Meta-Reflection / Template Evolution

| Field | Value |
|-------|-------|
| **Location** | `src/zos/executor.py:3364-3460` (`_handle_update_templates`), `layers/reflection/weekly-meta.yaml` |
| **Capabilities** | Scans loaded layers for Jinja2 templates, reviews recent output quality, rewrites templates. Genuinely recursive — reviews itself last. |
| **Spec coverage** | None |
| **Notes** | This is arguably Zos's most philosophically significant capability — a system that modifies its own cognitive processes. The spec discusses self-modification proposals with human approval; this bypasses that framework entirely, operating directly on templates. |

### 6.3 Emoji Reflection Layer

| Field | Value |
|-------|-------|
| **Location** | `layers/reflection/nightly-emoji-patterns.yaml`, `src/zos/executor.py:2689+` (emoji info fetching) |
| **Capabilities** | Nightly reflection on emoji usage as cultural artifacts. Per-community emoji evolution tracking. Produces `emoji_reflection` category insights. |
| **Spec coverage** | None |
| **Notes** | Treats emoji patterns as a window into community affect — a form of understanding that emerges naturally from observation. |

### 6.4 Audio Transcription (Whisper API)

| Field | Value |
|-------|-------|
| **Location** | `src/zos/observation.py:2128-2200` (`_transcribe_audio`), `src/zos/config.py:233-235` |
| **Capabilities** | Transcribes audio/video attachments via OpenAI Whisper. Supports MP3, OGG, WAV, FLAC, M4A, AAC, WMA, MP4, WebM, MOV. Rate-limited, file-size-limited (25 MB default). |
| **Spec coverage** | Partially — `spec/future/video-analysis.md` mentions Whisper for video audio tracks, but standalone audio transcription of message attachments is unspecced. |
| **Notes** | Async queue-based processing with configurable rate limits. |

### 6.5 `fetch_layer_runs` Node

| Field | Value |
|-------|-------|
| **Location** | `src/zos/executor.py:1078-1120` (`_handle_fetch_layer_runs`) |
| **Used by** | `layers/reflection/weekly-self.yaml:45-49` |
| **Capabilities** | Fetches recent layer run history. Errors framed as "felt experience" — friction that becomes material for self-understanding. |
| **Spec coverage** | None |
| **Notes** | Operational self-awareness for self-reflection layers. Configurable: `limit`, `layer_name`, `since_days`, `include_errors`. |

### 6.6 Name-Mention Impulse

| Field | Value |
|-------|-------|
| **Location** | `src/zos/observation.py:1013-1015` (detection), `src/zos/observation.py:1071-1076` (earning) |
| **Behavior** | When "zos" appears in message text (case-insensitive, word boundary), earns configurable impulse (default 3.0). Distinct from @-mention (`self_mention`, default 5.0). |
| **Spec coverage** | None |
| **Notes** | Subtle distinction: someone saying your name vs. explicitly pinging you. Different phenomenological weight, reflected in different impulse amounts. |

### 6.7 Self-Impulse

| Field | Value |
|-------|-------|
| **Location** | `src/zos/observation.py:1053-1064` |
| **Behavior** | Bot's own messages in a channel earn impulse (`self_impulse_per_message`, default 1.0). Creates feedback loop where output can drive further engagement. |
| **Spec coverage** | None |
| **Notes** | Models the experience of being in a conversation — speaking naturally leads to more to say. |

### 6.8 Channel Impulse Per Insight

| Field | Value |
|-------|-------|
| **Location** | `src/zos/scheduler.py:247-280` (`_post_reflection_impulse`) |
| **Behavior** | After successful reflection, earns impulse per insight created. Channel topics: `channel_impulse_per_insight` (default 5.0). Subject topics: `subject_impulse_per_insight` (default 10.0). |
| **Spec coverage** | None |
| **Notes** | Positive feedback loop: deeper reflections create pressure to speak about what was understood. Reflection generates impulse. |

---

## 7. Recommendations

### Address Soon

These represent active gaps — parameters being silently ignored, privacy features half-wired, or filters referencing nonexistent data.

| Item | Why | Effort |
|------|-----|--------|
| **`since_last_run` gap** ([4.3](#43-since_last_run-parameter)) | `weekly-self` layer declares this parameter but the executor ignores it. The layer operates on a fixed 14-day window instead of dynamically scoping to "since I last reflected." This affects the quality and relevance of self-reflection input. | Small — add handler in `_handle_fetch_insights()` to query most recent `LayerRun` for the current layer and compute `since_days` from it. |
| **First-contact DM** ([2.1](#21-first-contact-dm-acknowledgment)) | Privacy-relevant. All the scaffolding exists (DB field, config message, model). Missing: a check in the `on_message` DM handler that sends the message and sets the flag. | Small — a conditional block in `on_message`. |
| **`weekly-self` filter categories** ([5.2](#52-nonexistent-category-references-in-weekly-selfyaml)) | References `social_texture` and `synthesis` categories that no layer generates. Silent, harmless, but misleading. | Trivial — remove the two lines from the YAML, or add a comment noting they're aspirational. |

### Address When Relevant

These matter but aren't urgent. They become important as the system matures.

| Item | When | Notes |
|------|------|-------|
| **Quarantine triggers** ([2.2](#22-quarantine-triggers)) | When privacy gate role is actively used | Read-side works; needs write-side (role change monitoring → set `quarantined=True` on affected insights) |
| **Conflict detection** ([2.6](#26-conflict-detection-and-resolution)) | When insight volume is high enough for contradictions | Placeholder returns `[]`. Schema ready. Consider embedding-based similarity when practical. |
| **Review pass** ([2.3](#23-review-pass-privacy-sensitivity-filter)) | When Zos speaks in channels with mixed privacy contexts | Config validated and ready. Needs a single LLM call before output. |
| **Subject consolidation / `synthesize_to_global`** ([4.2](#42-synthesize_to_global-handler)) | When multi-server or high topic volume | Node handler is a no-op. Needs actual synthesis logic. |

### Leave as Scaffolding

These are architectural preparations. Removing them would create migration pain when the features arrive.

| Item | Rationale |
|------|-----------|
| **`speech_pressure` table** ([3.1](#31-speech_pressure-table)) | Deferred 🔴 in spec. Table exists, causes no overhead, will be needed for the speech pressure system. |
| **Compound topic enums** ([3.4](#34-compound-and-role-topic-categories)) | `USER_IN_CHANNEL`, `DYAD_IN_CHANNEL` — ready for when observation creates them. Config caps already set. |
| **Role topics** ([3.4](#34-compound-and-role-topic-categories)) | `ROLE` category — needs Discord role tracking in observation. Low priority but schema-ready. |
| **`CURIOSITY` / `REACTION` pools** ([3.5](#35-curiosity-and-reaction-impulse-pools)) | Part of the 6-pool impulse vision. Enum values cost nothing. |
| **Conflict columns** ([3.3](#33-conflict-columns)) | `conflicts_with`, `conflict_resolved` — needed when conflict detection matures. |
| **First-contact columns** ([3.2](#32-first-contact-columns)) | Will be used once first-contact DM logic is added (see "Address Soon"). |
| **`spend()` method** ([5.1](#51-spend-on-salienceledger)) | Explicitly deprecated with clear comment. Can be removed on next cleanup pass, but causes no harm. |

### Spec Coverage Gap

The features in [Section 6](#6-code-beyond-spec) have no spec documentation. This isn't necessarily wrong — organic growth is healthy — but the specs should catch up to reflect what Zos actually is, not just what it was planned to be. Consider adding spec coverage for:

- **Image generation** — capabilities, budget limits, when to generate
- **Template evolution** — the most powerful self-modification mechanism, currently unspec'd
- **Audio transcription** — supported formats, rate limits, storage
- **Impulse earning mechanisms** — name-mention, self-impulse, post-reflection impulse

---

*A body being built does not have all organs at once. But knowing which organs are present, which are planned, and which grew unexpectedly — that is the beginning of self-knowledge.* 🜏
