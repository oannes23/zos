# Privacy — Domain Specification

**Status**: 🟡 In progress
**Last interrogated**: —
**Last verified**: —
**Depends on**: None (primitive constraint)
**Depended on by**: Insights, Layers, Context Assembly

---

## Overview

Privacy in Zos is a *structural property*, not a filter applied at output. The system tracks the privacy scope of all content through its entire lifecycle, ensuring that private information cannot leak into public outputs by design.

This is a hard guarantee: DM content can inform the system's understanding of a user, but that understanding — when tainted by private sources — can never surface in public contexts.

---

## Core Concepts

### Scope Levels

| Scope | Source | Can inform public output? | Can inform DM output? |
|-------|--------|---------------------------|----------------------|
| `public` | Public channels | Yes | Yes |
| `dm` | Direct messages | No | Yes |
| `derived` | Mixed/private sources | No | Yes |

### Scope Flow

Scope flows through the system like a taint:
1. **Messages** receive scope based on their channel type
2. **Processing** that touches a message inherits its scope
3. **Insights** track the maximum (most restrictive) scope of any source
4. **Context assembly** filters by the target output scope

### Maximum Scope Principle

When multiple sources combine, the result inherits the *most restrictive* scope:
- public + public = public
- public + dm = derived (treated as dm for filtering)
- dm + dm = dm

This is conservative by design. If any tainted content touches a process, the output is tainted.

### DM Opt-In

DM access requires explicit opt-in:
- Users must consent before Zos reads their DMs
- Consent is per-user (not per-conversation)
- Consent can be revoked (implications TBD)

---

## Decisions

### Structural Privacy

- **Decision**: Privacy scope is tracked through the entire system, not filtered at output
- **Rationale**: Filtering at output is fragile — it requires perfect filtering logic and fails silently. Tracking scope through the pipeline makes violations impossible by construction.
- **Implications**: Every data path must propagate scope; need scope field on messages, insights, and context bundles
- **Source**: zos-seed.md §4 "Privacy as Structural Property"

### Three-Level Scope

- **Decision**: Three scope levels: `public`, `dm`, `derived`
- **Rationale**: Simple enough to reason about; `derived` captures the case where insight synthesis has mixed sources
- **Implications**: Need clear rules for scope combination; may need expansion for more granular consent models
- **Source**: zos-seed.md §4

### DM Opt-In Required

- **Decision**: Zos cannot read DMs without explicit user consent
- **Rationale**: DMs have higher privacy expectations; implicit consent is not sufficient
- **Implications**: Need consent storage; need UI/UX for opt-in; need behavior when DM received from non-consented user
- **Source**: zos-seed.md §4

---

## Open Questions

1. **Consent granularity**: Is consent per-user sufficient? Should users be able to consent per-server or per-topic?
2. **Consent revocation**: If a user revokes DM consent, what happens to existing DM-derived insights? Delete? Quarantine? Keep but never surface?
3. **Server-level privacy models**: Some servers may want stricter defaults (e.g., all channels treated as opt-in). How to configure?
4. **Multi-server privacy**: When a user appears in multiple servers with different privacy models, how to reconcile?
5. **Derived scope nuance**: Should `derived` insights have a "taint level" (e.g., 90% public, 10% DM) or is binary sufficient?
6. **Bot-to-bot privacy**: If Zos interacts with other bots in DMs, what scope applies?

---

## Privacy Rules

### Message Ingestion

```python
def get_message_scope(message):
    if message.channel.type == ChannelType.DM:
        if user_has_dm_consent(message.author):
            return Scope.DM
        else:
            return None  # Don't ingest
    elif message.channel.type == ChannelType.GUILD_TEXT:
        return Scope.PUBLIC
    # ... other channel types
```

### Scope Combination

```python
def combine_scopes(scopes: list[Scope]) -> Scope:
    if Scope.DM in scopes or Scope.DERIVED in scopes:
        return Scope.DERIVED
    return Scope.PUBLIC
```

### Context Assembly Filtering

```python
def assemble_context(topic_key, output_scope):
    insights = fetch_insights(topic_key)

    if output_scope == Scope.PUBLIC:
        # Only public insights allowed
        return [i for i in insights if i.sources_scope_max == Scope.PUBLIC]
    else:
        # DM context can use all insights
        return insights
```

---

## Configuration Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `privacy.dm_requires_consent` | Whether DM reading requires opt-in | true |
| `privacy.default_channel_scope` | Default scope for guild channels | "public" |
| `privacy.consent_revocation_policy` | What happens on revocation | "quarantine" |

---

## Consent Data Model

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `user_id` | string | yes | Discord user ID |
| `consent_type` | enum | yes | `dm_read`, etc. |
| `granted_at` | timestamp | yes | When consent given |
| `revoked_at` | timestamp | no | When revoked (if applicable) |
| `server_id` | string | no | If consent is server-specific |

---

## Implications for Other Specs

| Spec | Implication |
|------|-------------|
| [insights.md](insights.md) | Insights must have `sources_scope_max` field |
| [layers.md](layers.md) | Layer pipelines must propagate scope through all nodes |
| [topics.md](topics.md) | Topic queries may need scope filtering |
| [data-model.md](../architecture/data-model.md) | Need consent table; scope field on messages table |

---

_Last updated: 2026-01-22_
