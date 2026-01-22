# Sync Spec Command

You are in **Sync Spec mode**.

Your goal is to bring a specification and its implementation into alignment by identifying all divergences and helping the user decide how to resolve each one.

**Target**: $ARGUMENTS

---

## Philosophy

Specs and code drift apart. This is natural. The goal isn't to prevent drift but to periodically reconcile:

- **Spec → Code**: Spec was right, code needs updating
- **Code → Spec**: Code evolved correctly, spec needs updating
- **Both wrong**: Neither matches intent, both need work
- **Intentional divergence**: Document and move on

---

## Difference from /verify

| Command | Purpose | Output |
|---------|---------|--------|
| `/verify` | Confirm spec matches code, update timestamp | Timestamp update, minor fixes |
| `/sync-spec` | Deep audit and reconciliation | Comprehensive divergence report, action plan |

Use `/verify` for routine maintenance. Use `/sync-spec` when you suspect significant drift or before major feature work.

---

## Context Loading

### 1. Load the spec
Read the target spec file completely.

### 2. Load related specs
- MASTER.md for context
- Glossary for terminology
- Dependent and dependency specs (from metadata)

### 3. Find implementation files

Search strategies:
```bash
# By domain name
src/**/*{{domain-slug}}*
src/**/{{domain-slug}}/**

# By entity names mentioned in spec
src/**/*{{EntityName}}*

# By glossary terms
# Search for key terms from the spec
```

### 4. Load test files
Tests often reveal implementation details:
```
tests/**/{{domain-slug}}*
__tests__/**/{{domain-slug}}*
*.test.ts, *.spec.ts matching domain
```

---

## Deep Analysis

### Phase 1: Extract Spec Claims

Parse the spec and list every verifiable claim:

```markdown
## Spec Claims Extracted

### Entities
- User entity with fields: id, email, name, createdAt
- Session entity with fields: id, userId, token, expiresAt

### Behaviors
- "Users can reset their password via email"
- "Sessions expire after 24 hours of inactivity"

### Constraints
- "Email must be unique across all users"
- "Password must be at least 8 characters"

### Relationships
- "User has many Sessions"
- "Session belongs to User"

### Decisions
- "Using JWT for session tokens"
- "Storing sessions in Redis"
```

### Phase 2: Extract Code Reality

Analyze the implementation:

```markdown
## Implementation Reality

### Entities Found
- `src/models/User.ts`: id, email, name, createdAt, updatedAt, role
- `src/models/Session.ts`: id, userId, token, expiresAt, lastActiveAt

### Behaviors Implemented
- Password reset: Yes, in `src/services/auth/resetPassword.ts`
- Session expiry: 48 hours (not 24), in `src/middleware/session.ts`

### Constraints Enforced
- Unique email: Yes, database constraint
- Password length: 10 characters (not 8), in `src/validators/user.ts`

### Relationships
- User → Sessions: Yes, one-to-many
- Session → User: Yes, foreign key

### Implementation Details Not in Spec
- `role` field on User
- `lastActiveAt` field on Session
- Rate limiting on password reset
```

### Phase 3: Generate Divergence Report

Create a structured comparison:

```markdown
## Divergence Report

### 🔴 Critical (Blocks Work)

| # | Spec Says | Code Does | Impact |
|---|-----------|-----------|--------|
| 1 | Session expires after 24h | Expires after 48h | Security policy mismatch |
| 2 | Password min 8 chars | Validates min 10 chars | User experience |

### 🟡 Moderate (Should Resolve)

| # | Issue | Details |
|---|-------|---------|
| 3 | Missing from spec | `role` field on User |
| 4 | Missing from spec | Rate limiting on reset |
| 5 | Missing from code | [Feature not yet implemented] |

### 🟢 Minor (Document or Ignore)

| # | Issue | Details |
|---|-------|---------|
| 6 | Extra field | `updatedAt` on User (standard, no need to spec) |
| 7 | Naming | Spec: "expiresAt", Code: "expiresAt" ✓ |

### ✓ Verified Matches

- User entity structure (except noted fields)
- Session entity structure (except noted fields)
- Password reset flow exists
- User-Session relationship
- JWT token strategy
- Redis session storage
```

---

## Resolution Workflow

For each divergence, ask the user:

### Question Format

```
Divergence #1: Session Expiry Mismatch

Spec: "Sessions expire after 24 hours of inactivity"
Code: Sessions expire after 48 hours (src/middleware/session.ts:42)

How should we resolve this?

○ Update spec to 48 hours (code is correct)
○ Flag for code fix to 24 hours (spec is correct)
○ This is intentional — document the divergence
○ Needs discussion — add to open questions
```

### Batch Similar Issues

Group related divergences:
```
I found 3 fields in code not documented in spec:
- User.role
- User.updatedAt
- Session.lastActiveAt

For each, should I:
○ Add to spec (it's important to document)
○ Skip (implementation detail, not spec-worthy)
```

---

## Output Actions

Based on user decisions, execute updates:

### 1. Spec Updates

```markdown
### Session Expiry (Updated 2024-01-18)

- **Decision**: Sessions expire after 48 hours of inactivity
- **Rationale**: Originally 24h, extended for better UX based on usage patterns
- **Implications**: Security team approved extended window
- **Previous**: Was 24 hours in original spec
```

### 2. Code Fix Tickets

Generate actionable items:

```markdown
## Code Fixes Needed

### Fix #1: Password Validation
**File**: `src/validators/user.ts:15`
**Current**: Minimum 10 characters
**Should be**: Minimum 8 characters (per spec)
**Reason**: Spec is the agreed security policy

### Fix #2: [...]
```

### 3. Open Questions

Add to spec's "Open Questions" section:

```markdown
## Open Questions

1. Should session expiry be configurable per user role?
2. Is rate limiting on password reset sufficient at 5/hour?
```

### 4. Known Divergences

If intentional, document:

```markdown
## Known Divergences

| Area | Spec | Implementation | Reason | Approved |
|------|------|----------------|--------|----------|
| Password length | 8 chars | 10 chars | Security team override | 2024-01-10 |
```

---

## Final Report

```markdown
## Sync Complete

**Spec**: `spec/domains/{{domain}}.md`
**Files analyzed**: 12 source files, 4 test files
**Sync date**: {{today}}

### Resolution Summary

| Category | Count | Action |
|----------|-------|--------|
| Spec updated | 4 | Changes applied |
| Code fix needed | 2 | Tickets created |
| Documented divergence | 1 | Added to Known Divergences |
| Open questions | 2 | Added for discussion |
| Verified matches | 15 | No action needed |

### Spec Changes Made
1. Updated session expiry from 24h to 48h
2. Added `role` field to User entity
3. Added rate limiting note to password reset
4. Documented password length divergence

### Code Fixes Required
1. [ ] `src/validators/user.ts` — password length (if spec wins)
2. [ ] `src/services/auth.ts` — add missing validation (from spec)

### Next Steps
- Review code fix tickets with team
- Run `/verify spec/domains/{{domain}}` after fixes applied
- Consider `/interrogate` for open questions
```

---

## Partial Sync

If the codebase is large, support partial sync:

```
/sync-spec spec/domains/auth.md --section "Session Management"
/sync-spec spec/domains/auth.md --entity User
```

Focus analysis on the specified area only.

---

## No Implementation Yet

If no code exists:
```
No implementation found for spec/domains/payments.md

This spec describes:
- Payment entity
- Stripe integration
- Refund workflow

Options:
○ Mark as "spec only" (implementation pending)
○ Generate implementation scaffold
○ Review spec for implementability
```

---

## Important Notes

- **This is a heavy operation** — may take time for large domains
- **Involves code reading** — ensure source files are accessible
- **User-driven decisions** — never auto-resolve divergences
- **Preserve history** — note what changed and why in spec updates
- **Don't edit code** — only flag issues, let developers fix

---

*Invoked as: `/sync-spec spec/domains/<area>` or `/sync-spec spec/architecture/<area>`*
