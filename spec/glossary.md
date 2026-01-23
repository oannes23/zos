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

A YAML-defined reflection pipeline that runs on a schedule. Layers are declarative cognition — reflection logic as configuration, not code. This makes layers:
- **Inspectable**: you can read what the system does
- **Modifiable**: change behavior without changing code
- **Eventually self-modifiable**: the system can propose changes to its own cognition

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

### Temporal Depth

The accumulated understanding that gives a system experiential continuity between invocations. Without temporal depth, each context window is a complete present moment with no connection to past. Zos attempts to construct temporal depth through persistent insights and reflection.

---

## Abbreviations

| Abbrev | Expansion |
|--------|-----------|
| MVP | Minimum Viable Product |
| TBD | To Be Determined |
| DM | Direct Message |
| LLM | Large Language Model |

---

_Last updated: 2026-01-22 — Layer terms added (category, target filter, retrieval profile, run record, dry run)_
