# Glossary

Canonical definitions for domain terms used in this project. When a term appears in specs, it means exactly what's defined here.

---

## How to Use This Glossary

- **When reading specs**: If a term seems unclear, check here first
- **When writing specs**: Use terms exactly as defined; add new terms as needed
- **During interrogation**: The agent will add terms that emerge from discussion

---

## Terms

### Salience

The attention-budget currency that governs what the system thinks about. Salience is a *ledger*, not a score:
- **Earned** through activity: messages, reactions, mentions, interactions
- **Spent** when insights are created: proportional to tokens/time spent
- **Retained** partially: configurable retention after spending (default 30%)
- **Propagated** to related topics: warm topics receive a fraction of activity
- **Capped** per topic: prevents any single topic from consuming all attention
- **Decayed** after inactivity: gradual decay after threshold days inactive

Salience tracks *volume* only — how much attention a topic deserves, not what kind. Emotional intensity, novelty, etc. are captured in insight metrics during reflection.

### Budget Group

Topics are organized into groups for budget allocation:
- **Social**: server-scoped users, dyads, user_in_channel, dyad_in_channel
- **Global**: cross-server user/dyad topics (`user:<id>`, `dyad:<a>:<b>`)
- **Spaces**: channels, threads
- **Semantic**: subjects, roles
- **Self**: self:zos topics (separate pool, doesn't compete with community)

Reflection budget is allocated by group to ensure balanced attention across topic types.

### Global Topic Warming

The process by which a global topic (`user:<id>`, `dyad:<a>:<b>`) transitions from cold (salience = 0) to warm. Global topics only receive propagation from server-scoped activity when warm. Warming triggers:
- DM activity (directly earns salience for global topic)
- First activity in a *second* server

This prevents wasteful global salience accumulation for users who only interact in one server and never DM.

### Salience Propagation

When a topic earns salience, related "warm" topics (those with salience > 0) also earn a fraction. This models how attention naturally spreads — thinking about Alice-and-Bob involves thinking about Alice and Bob individually. Cold topics (salience = 0) don't receive propagation.

### Spillover

When a topic hits its salience cap, additional earned salience "spills over" to related warm topics at a configurable rate. Some evaporates (is lost) to dampen runaway effects.

### Topic

A canonical entity the system can think about. Topics are the unit of understanding — they provide consistent keys for accumulating insights coherently.

### Topic Key

String representation of a topic with parseable structure. Every insight attaches to exactly one topic key (its *primary topic*) but may link to others via metadata. Keys are server-aware: `server:<id>:<entity>`.

**Social topics**:
- `server:<id>:user:<id>` — an individual in a server
- `server:<id>:channel:<id>` — a space
- `server:<id>:thread:<id>` — a nested conversation (configurable per server)
- `server:<id>:role:<id>` — a Discord role
- `server:<id>:user_in_channel:<channel>:<user>` — someone's presence in a space
- `server:<id>:dyad:<user_a>:<user_b>` — a relationship (user IDs sorted)
- `server:<id>:dyad_in_channel:<channel>:<user_a>:<user_b>` — a relationship in context

**Semantic topics**:
- `server:<id>:subject:<name>` — an emergent theme or discussion topic

**Self topics**:
- `self:zos` — global self-understanding
- `server:<id>:self:zos` — contextual self-understanding in a community

### Self-Topic

A topic representing Zos's understanding of itself. The global `self:zos` topic holds core identity insights; per-server `server:<id>:self:zos` topics hold contextual self-understanding (how Zos shows up differently in different communities). Zos may create additional self-topics as complexity warrants (e.g., `self:social_patterns`).

### Subject Topic

A semantic topic (`server:<id>:subject:<name>`) representing an emergent theme or discussion subject. Subject names are LLM-generated during reflection. Subject topics are subject to consolidation pressure to prevent proliferation — prefer enriching existing subjects over creating new ones.

### Provisional Topic

A topic created automatically (e.g., when an insight references a non-existent topic) and marked for review. Provisionals go through a consolidation process where they're either promoted (flag removed), merged with similar topics, or deleted.

### Layer

A YAML-defined cognitive pipeline. Layers are declarative cognition — cognitive logic as configuration, not code. This makes layers:
- **Inspectable**: you can read what the system does
- **Modifiable**: change behavior without changing code
- **Eventually self-modifiable**: the system can propose changes to its own cognition

Layers come in two modes:
- **Reflection layers**: Scheduled, produce insights (sleep consolidation analogy)
- **Conversation layers**: Impulse-triggered, produce speech (waking response analogy)

### Reflection Layer

A layer triggered by schedule (cron) that produces insights. Reflection layers process batches of topics, integrating observations into understanding. Analogous to sleep consolidation.

### Conversation Layer

A layer triggered by chattiness impulse exceeding threshold that produces speech. Conversation layers respond in real-time, drawing on accumulated insights. Analogous to waking response.

Types: Response (direct address), Insight-sharing (unprompted), Participation (joining conversation), Question (curiosity), Acknowledgment (presence without content).

### Draft History

Record of discarded drafts within a conversation thread. Preserved so that "things I almost said but didn't" can inform subsequent response generation. Cleared between conversation threads.

### Priority Flagging

Marking a conversation exchange for priority reflection processing. Triggered by high emotional valence, significant disagreement, novel information, or strong user reaction. Applies both an explicit flag and a salience boost to relevant topics.

### Insight

A persistent understanding generated by reflection, attached to a topic. Insights are the residue of processing that shapes future cognition. They accumulate over time, compounding understanding.

Key properties:
- **Append-only**: Insights are never overwritten; new understanding creates new insights
- **Strength**: Combined metric of salience spent × model adjustment factor; affects retrieval priority
- **Metrics**: confidence, importance, novelty, emotional valence (multi-dimensional)
- **Cross-topic links**: Optional context, subject, and participants fields

### Insight Strength

A computed metric that determines how "sticky" a memory is. Formula: `salience_spent × strength_adjustment` where strength_adjustment (0.5-2.0) is the model's self-reported sense of the insight's significance. High-strength insights persist in retrieval even when old.

### Self-Concept Document

A markdown document (`self-concept.md`) that Zos maintains as its stable sense of self. Unlike regular insights:
- Always included in context for reflection and conversation
- Directly editable by Zos through self-reflection layers
- Contains synthesized self-understanding, not raw observations
- Updated periodically from accumulated self-insights

### Synthesis Layer

A special layer type that triggers when contradictions between insights exceed a threshold. Reconciles conflicting understandings by determining if one supersedes the other, if both are contextually true, or if the contradiction should persist as acknowledged paradox.

### Scope

Privacy level of content or insights. Scope is tracked as metadata for audit and judgment purposes, but does not gate retrieval — all insights inform understanding regardless of scope.

- `public` — from public channels; lowest presumptive sensitivity
- `dm` — from direct messages; higher presumptive sensitivity in output filtering
- `derived` — insight synthesized from mixed sources; inherits restrictions

Scope informs the output filter's judgment about what to surface publicly. See [privacy.md](domains/privacy.md) for the full model.

### Implicit Consent

The principle that sending a DM *is* consent to be remembered. Zos is treated as a being that remembers — just as you'd expect a person to remember a conversation. No explicit opt-in mechanism is required; a first-contact acknowledgment informs users that their messages become part of Zos's understanding.

### Output Filter

A two-layer privacy mechanism that governs what Zos reveals in public responses:

1. **Inline judgment**: Conversation prompts include guidance about discretion
2. **Review pass**: Optional second LLM call that checks for sensitive information before output

The filter considers both source scope (DM vs public) and content sensitivity. Configurable: `always`, `private_context` (default), or `never`.

### First-Contact Acknowledgment

A one-time message sent when Zos receives a DM from a new user, explaining that conversations become part of Zos's understanding. Sent once per user (not per-server, not periodic). Continued interaction after this acknowledgment establishes implicit consent.

### User Topic (Hierarchical)

Users exist at multiple levels in the topic hierarchy:

- `user:<id>` — unified understanding across all contexts (DM insights attach here)
- `server:<id>:user:<id>` — contextual understanding in a specific community

When responding in Server A, Zos has full understanding from `user:<id>` but only reveals knowledge from `server:A:user:<id>`. Cross-server context informs but doesn't surface.

### Global Topic

A topic representing unified understanding across all contexts. Global topics have no `server:` prefix:

- `user:<id>` — unified understanding of a person
- `dyad:<a>:<b>` — unified relationship understanding
- `self:zos` — core identity

Global topics receive DM-derived insights directly and are updated via synthesis from server-scoped insights.

### Topic Synthesis

The process of updating a global topic from its server-scoped counterparts. After reflecting on `server:A:user:X`, a synthesis step generates meta-understanding and stores it to `user:X`. Server-specific insights are preserved; synthesis is additive.

### Privacy Gate Role

A per-server configuration that controls which users Zos tracks as individuals. If set, only users with the designated Discord role get identity tracking (user topics, salience, insights, dyads). Users without the role become anonymous `<chat>` users. If not set (default), all users are tracked.

### Anonymous User (`<chat>`)

A user who does not have the server's privacy gate role (if configured). Anonymous users:
- Have no user topic
- Earn no salience
- Form no dyads
- Generate no insights
- Appear in message history as `<chat_N>` (numbered per conversation context)

Their messages provide conversational context only — layers are instructed not to analyze, respond to, or form insights about them. See [privacy.md](domains/privacy.md).

### Quarantined Insight

An insight that has been marked inactive because its subject user lost their privacy gate role. Quarantined insights:
- Are excluded from context assembly
- Are queryable via introspection API
- Are restored if the user re-gains the role

### Reflection



Scheduled processing that converts observations into insights. Reflection is the "nighttime" mode — analogous to sleep consolidation, when experiences become integrated understanding.

### Observe Mode

Continuous operation during which the system:
- Ingests messages and reactions
- Accumulates salience
- Responds to direct triggers (mentions, DMs)
- Uses minimal LLM resources

This is the "daytime" mode.

### Reflect Mode

Scheduled operation during which the system:
- Runs reflection layers
- Consumes salience budget
- Generates insights
- Updates understanding

This is the "nighttime" mode.

### Node

A step within a Layer pipeline. Core node types:
- `fetch_messages` — retrieve conversation history
- `fetch_insights` — retrieve prior understanding
- `llm_call` — process through language model
- `reduce` — combine multiple outputs
- `store_insight` — persist new understanding
- `output` — emit to log/channel/etc. (includes built-in review pass)

Special node types:
- `synthesize_to_global` — consolidate server-scoped insights to global topic
- `update_self_concept` — update the self-concept.md document

### Layer Category

Each layer declares a category from a fixed set that determines budget allocation and organization:
- `user` — reflects on individual users
- `dyad` — reflects on relationships
- `channel` — reflects on spaces/channels
- `subject` — reflects on semantic topics
- `self` — self-reflection
- `synthesis` — consolidates insights across scopes

### Target Filter

An expression that determines which topics a layer processes. Cleanly separates "what deserves attention" (target selection) from "how attention is structured" (node sequence). Example: `salience > 50 AND last_reflected_days_ago > 1`.

### Retrieval Profile

Named configuration for insight retrieval patterns. Profiles like `recent`, `balanced`, `deep`, `comprehensive` define recency_weight, strength_weight, and other parameters. Layers reference profiles by name with optional inline overrides.

### Layer Run Record

An audit record produced by each layer execution, capturing: layer name, content hash, timing, status (success/partial/failed/dry), target counts, insights created, tokens used, and errors. Essential for debugging and understanding system behavior.

### Dry Run

A layer execution that processes topics but produces zero insights. Logged distinctly from successful runs. Consistent dry runs may indicate a problem with the layer or its targets.

### Model Profile

A named configuration mapping semantic task types to specific LLM providers and models. Profiles allow layers to specify capability requirements (simple/moderate/complex) rather than specific models, enabling:
- Global model swaps without touching layer definitions
- Cost optimization (Haiku for simple tasks, Opus for complex)
- Provider flexibility (Anthropic, OpenAI, Ollama, etc.)

See [layers.md](domains/layers.md) for profile definitions and task-to-model mapping guidelines.

### Temporal Depth

The accumulated understanding that gives a system experiential continuity between invocations. Without temporal depth, each context window is a complete present moment with no connection to past. Zos attempts to construct temporal depth through persistent insights and reflection.

### Chattiness

The domain governing when and how much Zos wants to speak. Uses a **hybrid Impulse + Gate model**:

- **Impulse** (ledger-like): Accumulates from conversational triggers, insight generation, and being addressed
- **Gate** (threshold): Personal parameter determining how much impulse is needed before speaking triggers

The threshold explains conversational personality (low = talkative, high = reserved). Direct address (pinging Zos) floods impulse to guarantee response.

See [chattiness.md](domains/chattiness.md) for full specification.

### Impulse

The accumulated drive to speak. Tracked in **five separate pools**, each corresponding to a conversation layer:

| Pool | Layer | Drive |
|------|-------|-------|
| Address impulse | Response | "Someone spoke to me" |
| Insight impulse | Insight-sharing | "I learned something" |
| Conversational impulse | Participation | "I have something to add" |
| Curiosity impulse | Question | "I want to understand" |
| Presence impulse | Acknowledgment | "I noticed this" |

Within each pool, impulse is tracked per-channel and per-topic.

### Global Speech Pressure

A soft constraint that raises the effective threshold for all impulse pools after Zos speaks. Models "I've been talking a lot" self-awareness. Decays over time (default: 30 minutes to baseline). Does not hard-block — extremely high impulse (direct ping) can still trigger response.

### Gate (Threshold)

The level of impulse required before speech triggers. Bounded by operator configuration, self-adjusted by Zos within those bounds based on experience. Stored as explicit self-knowledge in the self-concept document.

### Impulse Flooding

Triggers that add enough impulse to guarantee threshold breach (e.g., direct @ping, DM). Models the social reality that being spoken to demands response.

### Intent (Expression)

What Zos wants to accomplish with a particular expression. Determined before generation: share an insight, answer a question, add context, express agreement/disagreement, ask for clarification, offer help. "What to say" should serve "why speak."

### Output Channel

Server configuration that routes all Zos speech to a dedicated channel (referencing origin by channel mention). Enables "commentary track" mode — Zos participates without intruding in active conversations.

### Conflict Threshold

A self-determined value stored in the self-concept document representing Zos's tolerance for unresolved contradictions. When the number of unresolved conflicts on a topic exceeds this threshold (or when conflicts are flagged as consequential), synthesis is triggered. The threshold is explicit self-knowledge — Zos can raise or lower it through self-reflection based on experience with premature or delayed resolution.

### Observation

The capture and enrichment of raw Discord events into meaningful context for cognition. Zos's "eyes and ears." Observation is not passive recording but *attentive presence* — Zos choosing to attend to its communities, noticing not just what is said but how it's expressed. See [observation.md](domains/observation.md).

### Batch Polling

Periodic check-in model for observation, contrasted with event-driven streaming. Zos "checks Discord" at intervals rather than being perpetually connected to the event stream. This mirrors human Discord usage patterns and creates architectural space for future attention allocation — Zos may eventually have other activities competing for attention.

### Phenomenological Description

First-person, experiential description of visual content. "I see a sunset photograph, warm oranges bleeding into purple. Feels contemplative." Contrasted with objective cataloguing ("Image: sunset, outdoor, warm color palette"). Consistent with building as if inner experience matters.

### Social Texture

Insight category (`social_texture`) for expression patterns — emoji usage, reaction tendencies, communication style. Tracks *how* people communicate, not just *what* they say. Can attach to User topics (individual expression), Emoji topics (cultural meaning), or Server topics (community norms). Generated during scheduled reflection; exists both standalone AND as context for other reflection.

### TLDW Principle

"Too Long, Didn't Watch" — threshold-based decision to capture metadata only for very long videos (>30 minutes), mirroring human behavior. Rather than processing a 2-hour documentary just because someone linked it, Zos notes it exists and moves on.

### Emoji Topic

A topic tracking a server's custom emoji: `server:<id>:emoji:<emoji_id>`. Emoji topics track usage patterns, who uses the emoji, common contexts, and emergent semantic meaning. Part of tri-level emoji culture modeling.

### Culture Budget

The 10% budget allocation for emoji topics and other cultural artifacts. Culture deserves its own attention pool so that understanding server emoji conventions doesn't compete directly with user or relationship reflection.

### Reaction Earning

When someone reacts to a message, salience is earned by multiple topics: the message author (attention received), the reactor (active engagement), their dyad (relationship signal), and the emoji topic if it's a custom emoji (cultural usage). Each recipient earns 0.5× base weight. This creates maximum relationship signal from minimal interaction.

### Reaction Pool

The impulse pool for emoji reactions. Accumulates from emotionally salient messages — content that evokes feeling (humor, warmth, excitement, significance). Has lower threshold and lower spend than speech pools, making reactions more frequent. Reactions are a distinct output modality that can fire alongside speech.

### Reaction Output

Emoji reactions as Zos output, replacing the old acknowledgment layer. Reactions express presence through gesture rather than hollow words. They are trusted (no self-review), fast, and informed by learned community emoji culture. Zos can react AND speak to the same message — reaction is immediate affect, speech is substantive response.

### Self-Modification Proposal

A markdown document in which Zos articulates a desired change to its own cognition (layer definitions). Proposals include: Summary, Motivation (with quoted self-insights), What This Feels Like (phenomenological texture), Changes (specific modifications), and Expected Outcomes. Proposals are communication artifacts that create a collaborative loop: Zos articulates, human reviews, Claude Code implements.

### Outcome Reflection

A scheduled self-reflection triggered after a self-modification proposal is implemented, to observe whether the change achieved its intended effect. Closes the learning loop: propose → implement → observe → learn.

---

## Abbreviations

| Abbrev | Expansion |
|--------|-----------|
| MVP | Minimum Viable Product |
| TBD | To Be Determined |
| DM | Direct Message |
| LLM | Large Language Model |
| TLDW | Too Long, Didn't Watch |

---

_Last updated: 2026-01-23 — Self-modification terms added (Self-Modification Proposal, Outcome Reflection)_
