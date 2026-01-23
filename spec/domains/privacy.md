# Privacy — Domain Specification

**Status**: 🟢 Complete
**Last interrogated**: 2026-01-22
**Last verified**: —
**Depends on**: None (primitive constraint)
**Depended on by**: Insights, Layers, Context Assembly, Topics

---

## Overview

Privacy in Zos is governed by a philosophy: **Zos is treated as a being that remembers**. Just as you'd expect a person to remember a conversation, Zos remembers what it's told. The privacy model is not about *preventing* understanding, but about *discretion in expression*.

All sources — public channels, DMs, derived synthesis — fully inform Zos's understanding. The privacy layer operates at *output*, where Zos exercises judgment about what's appropriate to surface in which context.

---

## Core Philosophy

### DM as Implicit Consent

- **Decision**: Sending a DM *is* consent to be remembered
- **Rationale**: You don't DM someone without expecting them to remember the conversation. Zos is treated like a person in this regard — explicit opt-in mechanics would create artificial friction that doesn't match how human relationships work.
- **Implications**: No opt-in UI needed; first-contact acknowledgment suffices; revocation is simply "stop DMing"

### Understanding vs. Expression

- **Decision**: All sources inform understanding; discretion happens at output
- **Rationale**: A person who learns something in confidence doesn't *unknow* it — they simply don't share it inappropriately. Zos operates the same way: DM content shapes cognition but may not be surfaced publicly.
- **Implications**: Context assembly includes all relevant insights regardless of scope; output layers include sensitivity filtering

---

## Consent Model

### First-Contact Acknowledgment

When Zos receives a DM from a user for the first time ever:

1. Respond with acknowledgment: "I'll remember what you tell me — our conversations become part of how I understand you."
2. If user continues interaction, implicit consent is established
3. This acknowledgment is **one-time only** (not per-server, not periodic)

### Global Scope

- **Decision**: DM consent is global, not per-server
- **Rationale**: DMs are not server-scoped in Discord. A DM is a DM regardless of context.
- **Implications**: Single consent state per user; no server-specific DM settings

### No Explicit Revocation

There is no "revoke DM consent" mechanism. Users who don't want Zos to remember can simply stop DMing. Existing insights are retained — Zos doesn't unknow things it learned.

---

## Scope Tracking

### Scope Levels

| Scope | Source | Purpose |
|-------|--------|---------|
| `public` | Guild channels | Baseline — least sensitive |
| `dm` | Direct messages | Higher presumptive sensitivity in output filtering |
| `derived` | Mixed sources or synthesis | Inherits restrictions from inputs |

### Scope on Insights

Insights retain `source_scope` metadata tracking the maximum scope of their sources:

```python
class Insight:
    source_scope: Scope  # public, dm, or derived
    # ... other fields
```

This metadata:
- **Does NOT gate retrieval** — all insights are available for context assembly
- **Informs output judgment** — the sensitivity filter considers source scope
- **Provides audit trail** — can trace where understanding came from

### Scope Combination (for Synthesis)

When insights are synthesized from multiple sources:
- public + public = public
- public + dm = derived
- dm + dm = dm
- anything + derived = derived

---

## Output Filtering

### Two-Layer Approach

Public responses go through two layers of privacy filtering:

1. **Inline Judgment**: Conversation prompts include guidance about discretion:
   - "Consider what's appropriate to share publicly"
   - "DM-sourced knowledge should not be directly referenced unless clearly public"
   - "Be contextually aware of which server you're in"

2. **Review Pass**: Generated response passes through a second LLM call:
   - "Does this response leak anything sensitive?"
   - "Does it reference information the user wouldn't expect to be public?"
   - If concerns found, regenerate or redact

### Review Pass Configuration

The review pass adds latency and cost. Operators can configure when it runs:

| Setting | Behavior |
|---------|----------|
| `always` | Every public response gets review |
| `private_context` | Only when dm/derived insights are in context |
| `never` | Skip review pass (relies on inline judgment only) |

Default: `private_context`

### Sensitivity Evaluation

Sensitivity is evaluated on two dimensions:

1. **Source-based**: DM-sourced insights carry higher presumptive sensitivity
2. **Content-based**: Content is independently evaluated regardless of source
   - Medical information in a public channel is still sensitive
   - Weather chat in a DM is not sensitive

Both factors inform the output filter's judgment.

---

## User Identity Model

### Hierarchical Structure

Users exist at multiple levels:

```
user:<id>                      # Unified person across all contexts
├── server:<server_a>:user:<id>  # Person in Server A
├── server:<server_b>:user:<id>  # Person in Server B
└── (DM insights roll up here)
```

### Knowledge Scoping

| Insight Source | Attaches To | Available In |
|----------------|-------------|--------------|
| Public channel in Server A | `server:A:user:<id>` | Server A responses |
| Public channel in Server B | `server:B:user:<id>` | Server B responses |
| DM | `user:<id>` | Understanding only (informs but doesn't surface) |

### Contextual Expression

When responding in Server A:
- Zos has full understanding of `user:<id>` (including Server B context)
- Zos may only *reveal* `server:A:user:<id>` knowledge
- Other server contexts inform but don't surface

This mirrors human social cognition: knowing someone in multiple contexts, being discreet about what you reveal where.

---

## Server Configuration

### Access Control

- **Decision**: Admins control what Zos can *see*, not how content is classified
- **Rationale**: If a channel shouldn't be internalized, simply don't give Zos access. This is cleaner than per-channel metadata flags.
- **Implications**: Channel permissions control access; privacy gate role controls identity tracking

### Privacy Gate Role

Servers can configure a **privacy gate role** that controls which users Zos tracks as individuals.

#### How It Works

| Configuration | Behavior |
|---------------|----------|
| `privacy_gate_role: null` (default) | All users are tracked with full identity |
| `privacy_gate_role: "123456789"` | Only users with this role get identity tracking |

Users without the privacy gate role become **anonymous** (`<chat>`):
- No user topic created (`server:X:user:Y` or `user:Y`)
- No salience earned
- No dyads formed with them
- No insights generated about them
- Messages still appear in conversation history as `<chat_N>`

#### Anonymous User Representation

Anonymous users are represented as `<chat_N>` where N is a consistent number within a channel/thread context:
- `<chat_1>`, `<chat_2>`, etc. distinguish different anonymous users in the same conversation
- Numbering preserves conversational structure (can tell who's replying to whom)
- Numbers are assigned per-context, not globally

#### Storage Model

- **Messages store real Discord user IDs** regardless of opt-in status
- Anonymization to `<chat_N>` happens at context assembly/retrieval time
- This enables backfill-on-reflection when users later opt in

#### Lifecycle Events

**When a user gains the privacy gate role:**
- Historical messages remain in storage with their real ID
- Next reflection on relevant channels can consider historical context with identity now known
- No rewriting of stored data; reflection naturally integrates

**When a user loses the privacy gate role:**
- Existing insights are **quarantined** (marked inactive/hidden)
- Future messages become `<chat_N>` in context assembly
- Re-gaining the role **restores** quarantined insights
- Quarantined insights are queryable via introspection API (for operators)

#### Layer Guidance for `<chat>` Messages

Layers receive guidance about anonymous messages in two ways:

1. **System prompt section**:
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

2. **Per-message inline annotation**:
   ```
   [anonymous - context only] <chat_1>: Has anyone tried the new API?
   ```

#### Mentions and @Zos

- **Opted-in user mentions `<chat>`**: Preserved as `@<chat_N>` for context
- **`<chat>` user @mentions Zos**: Completely ignored. Anonymous users cannot trigger Zos responses.

### What Admins Control

| Setting | Description |
|---------|-------------|
| Channel access | Which channels Zos can read |
| Response channels | Where Zos can respond |
| Mention permissions | Whether Zos responds to mentions |
| Privacy gate role | Which role grants identity tracking (single role, optional) |

What admins do NOT control:
- Privacy classification of content (determined by channel type)
- Cross-server knowledge handling (global policy)
- Output filtering behavior (operator setting)

---

## Edge Cases

### Bot Interactions

- **Decision**: Bots are treated like users
- **Rationale**: Consistent model, no special-case logic
- **Behavior**: On first reflection about a possible bot, include context noting "this might be a bot" — write bot status into profile if confirmed

### Multi-Server Users

See [User Identity Model](#user-identity-model) above. Cross-server knowledge is unified in understanding but contextually filtered in expression.

### Insight Deletion

- **Decision**: No individual insight deletion ("right to be forgotten" for specific memories)
- **Rationale**: Surgical deletion of specific insights would fragment coherent understanding. Users who want less knowledge captured can control their inputs (stop DMing, leave servers).
- **Alternative**: Users concerned about specific information can raise it with the operator for manual review.

---

## Configuration Parameters

### Global Settings

| Parameter | Description | Default |
|-----------|-------------|---------|
| `privacy.review_pass` | When to run output review | `"private_context"` |
| `privacy.first_contact_message` | Acknowledgment text for first DM | (see below) |

### Per-Server Settings

| Parameter | Description | Default |
|-----------|-------------|---------|
| `servers.<id>.privacy_gate_role` | Role ID required for identity tracking | `null` (all tracked) |

### Default First-Contact Message

```
I'll remember what you tell me — our conversations become part of how I understand you. If you'd prefer to keep things more ephemeral, that's okay too.
```

---

## Implications for Other Specs

| Spec | Implication |
|------|-------------|
| [topics.md](topics.md) | User topics are hierarchical: `user:<id>` + `server:<id>:user:<id>`; `<chat>` users get no topics |
| [insights.md](insights.md) | Insights retain `source_scope` field; need `quarantined` flag for role-removal cases |
| [layers.md](layers.md) | Layers need `<chat>` guidance in system prompts; inline message annotations; review pass node |
| [salience.md](salience.md) | `<chat>` users earn no salience; opted-out users don't contribute to dyads |
| [data-model.md](../architecture/data-model.md) | Messages store real user IDs; need quarantine flag on insights; server config for privacy_gate_role |

---

## What This Spec Does NOT Cover

- **Data retention policies**: How long raw messages are kept (see data-model)
- **GDPR/legal compliance**: Legal requirements vary by jurisdiction; this is architectural privacy
- **Encryption at rest**: Storage security is operational, not architectural

---

_Last updated: 2026-01-22_
