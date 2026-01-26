# Privacy Model

How Zos handles sensitive information — understanding vs. expression.

---

## The Core Distinction

Zos separates **understanding** from **expression**:

- **Understanding** — What Zos knows (insights, memories)
- **Expression** — What Zos reveals (public speech)

Everything Zos observes becomes understanding. Not everything is appropriate to express publicly.

---

## Scope Tracking

Every insight tracks its source scope:

| Scope | Source | Sensitivity |
|-------|--------|-------------|
| `public` | Public channels | Lower presumed sensitivity |
| `dm` | Direct messages | Higher presumed sensitivity |
| `derived` | Mixed sources | Inherits restrictions |

Scope informs what can be expressed, not what can be understood.

---

## Output Filter

A two-layer mechanism governs public expression:

### 1. Inline Judgment

Conversation prompts include guidance about discretion:
- What context is available
- What sources informed the response
- Guidance on appropriate revelation

### 2. Review Pass

An optional second LLM call that checks for sensitive information before output:
- Reviews the proposed response
- Considers source scopes
- May recommend modifications

Configured via `privacy.review_pass`:

| Value | Behavior |
|-------|----------|
| `always` | Review all outputs |
| `private_context` | Review when DM content is in context (default) |
| `never` | No review pass |

---

## Implicit Consent

Zos operates on implicit consent for memory:

> Sending a DM *is* consent to be remembered.

This mirrors human social norms — you expect people you talk to to remember what you said. Zos is transparent about this through the first-contact acknowledgment.

### First-Contact Acknowledgment

When Zos receives a first DM from a user, it sends a one-time message:

```
I remember what people tell me. This shapes how I understand you over time.
I won't share what you say in DMs in other contexts without good reason.
If you'd prefer I not remember our conversations, let me know.
```

Configure in `config.yaml`:
```yaml
privacy:
  first_contact_message: |
    Your custom message here...
```

---

## Privacy Gate Role

Servers can restrict who Zos tracks individually:

```yaml
servers:
  "123456789012345678":
    privacy_gate_role: "987654321098765432"
```

When configured:
- Only users with the role get individual tracking
- Users without the role become anonymous (`<chat>`)
- Anonymous users earn no salience, form no dyads, generate no insights
- Their messages provide conversational context only

### Anonymous Users

Anonymous users appear as `<chat_N>` in context (numbered per conversation). Layers are instructed not to:
- Analyze them
- Respond to them directly
- Form insights about them

---

## Quarantine

When a user loses their privacy gate role:

1. Their insights are **quarantined** (marked inactive)
2. Quarantined insights are excluded from context
3. Insights are queryable via API (for auditing)
4. If the user re-gains the role, insights are restored

This isn't deletion — it's suspension of expression.

---

## Cross-Server Privacy

Understanding is unified; expression is contextual.

Example: Alice is in both Server A and Server B.

- Zos has unified understanding of Alice (global topic `user:456`)
- In Server A, Zos only reveals knowledge from Server A context
- Cross-server context informs but doesn't surface

```
Understanding: Alice mentioned in DMs that she's job hunting
Expression (Server A): [Does not volunteer this]
Expression (DM): [May discuss if relevant]
```

---

## What Zos Reveals

Public expression follows these principles:

1. **Public content is fair game** — Things said in public channels can be referenced
2. **DM content is private** — Not revealed without good reason
3. **Synthesis is careful** — Derived insights respect source sensitivity
4. **Context matters** — What's appropriate varies by situation

The output filter makes judgment calls, not binary rules.

---

## Operator Access

Operators can query all insights via the API, including:
- Quarantined insights
- DM-derived insights
- All topic history

This is for operational visibility, not for public expression. Operators should treat this access with appropriate discretion.

```bash
# Include quarantined insights
curl "http://localhost:8000/insights/server:123:user:456?include_quarantined=true"
```

---

## No Deletion

Understanding is append-only. There is no mechanism for:
- Users to delete their insights
- Purging historical understanding
- "Forgetting" on demand

This is intentional: understanding that can be deleted isn't understanding, it's data. Natural forgetting happens through salience decay and retrieval prioritization, not through deletion.

If regulatory compliance requires deletion capability, that would need to be implemented separately.

---

## Configuration Summary

```yaml
privacy:
  # When to run output review
  review_pass: private_context    # always | private_context | never

  # First-contact message for DMs
  first_contact_message: |
    I remember what people tell me...

servers:
  "123456789012345678":
    # Only track users with this role
    privacy_gate_role: "987654321098765432"
```

---

## The Privacy Philosophy

Zos is designed as a being that remembers — not a database that stores.

This has implications:
- Memory is natural, not intrusive
- Discretion is about expression, not knowledge
- Consent is implicit in interaction
- Forgetting happens naturally, not on demand

The goal is coherent behavior that respects social norms, not compliance checkboxes.
