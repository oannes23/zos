# Verify Command

You are in **Verify mode**.

Your goal is to check whether a specification still accurately reflects the current implementation and update its "Last verified" timestamp.

**Target**: $ARGUMENTS

---

## When to Use This Command

- After completing implementation of a feature
- During regular maintenance (monthly spec reviews)
- Before starting new work that depends on an existing spec
- When `/status` flags a spec as possibly stale

---

## Context Loading

1. Read the target spec file
2. Read `/spec/MASTER.md` — understand overall project context
3. Read `/spec/glossary.md` — understand terminology
4. Identify corresponding source files:
   - Look for directories/files matching the domain slug in `src/`
   - Check for imports or references to the domain name
   - Review any test files related to this domain

---

## Verification Process

### Step 1: Locate Implementation

Find source code that corresponds to this spec:

```
spec/domains/authentication.md  →  src/auth/, src/services/auth.ts, etc.
spec/architecture/data-model.md →  src/models/, src/db/, schema files
```

If no implementation exists yet:
- Report: "No implementation found for this spec"
- Ask if user wants to mark as verified anyway (spec-only verification)
- Update timestamp if confirmed

### Step 2: Compare Spec to Code

For each major section of the spec, check against implementation:

| Spec Section | Verification Method |
|--------------|---------------------|
| Core Concepts | Do entities/classes exist? Names match? |
| Decisions | Are decisions reflected in code structure? |
| Data Model | Do types/schemas match spec? |
| Constraints | Are validations/guards in place? |
| Relationships | Are connections implemented correctly? |

### Step 3: Identify Divergences

Create a checklist of findings:

```markdown
## Verification Checklist

### Matches Spec ✓
- [ ] Entity `User` exists with specified fields
- [ ] Authentication flow follows described process
- [ ] Error handling matches spec

### Diverges from Spec ⚠️
- [ ] Spec says X, but code does Y
- [ ] Field `foo` in spec is named `bar` in code
- [ ] Missing implementation of [feature]

### In Spec, Not in Code (OK if not yet implemented)
- [ ] Feature X (marked as MVP 1, we're in MVP 0)

### In Code, Not in Spec (needs spec update)
- [ ] Additional field `baz` not documented
- [ ] Helper function `validateInput` not mentioned
```

---

## User Interaction

If divergences are found, ask the user:

```
I found some differences between the spec and implementation:

1. **Spec says**: Users have an `email` field (required)
   **Code has**: `emailAddress` field (optional)

   → Which is correct?
   - Update spec to match code
   - Flag for code fix (don't update spec)
   - Note as intentional divergence

2. **Code has**: `lastLoginAt` timestamp
   **Spec missing**: This field

   → Should I add this to the spec?
   - Yes, add to spec
   - No, it's an implementation detail
```

Use `AskUserQuestion` with appropriate options for each divergence.

---

## Updating the Spec

After verification and user decisions:

### 1. Update "Last verified" timestamp

Change:
```markdown
**Last verified**: —
```

To:
```markdown
**Last verified**: 2024-01-18
```

### 2. Apply user-approved changes

If user chose to update spec to match code:
- Update the relevant sections
- Add any missing fields/concepts
- Correct any outdated information

### 3. Mark divergences if intentional

If user noted intentional divergences, add a section:

```markdown
## Known Divergences

| Spec | Implementation | Reason |
|------|----------------|--------|
| `email` required | `email` optional | Legacy data migration |
```

### 4. Update status if needed

- If major updates were made: Consider changing to 🔄 (needs revision) for deeper review
- If spec was significantly out of date: Flag in MASTER.md

---

## Output Report

```markdown
## Verification Complete

**Spec**: `spec/domains/{{domain}}.md`
**Last verified**: {{today's date}}

### Summary
- **Matches**: 12 items verified
- **Updated**: 3 items (spec updated to match code)
- **Flagged**: 1 item (code needs fix)
- **Intentional divergences**: 1 item (documented)

### Changes Made
- Added `lastLoginAt` field to User entity
- Updated `validatePassword` description to match implementation
- Documented intentional divergence for email optionality

### Action Items
- [ ] Code fix needed: `UserService.create()` should validate email format (spec requirement)

### Next Steps
- Run `/interrogate spec/domains/{{domain}}` if significant gaps found
- Review flagged code fixes with team
```

---

## Quick Verification Mode

If the argument includes `--quick` or the spec is simple:
- Skip detailed comparison
- Just update the timestamp
- Report: "Quick verification — timestamp updated. Run full verification for detailed check."

Example: `/verify spec/domains/auth.md --quick`

---

## Verification for Architecture Specs

Architecture specs verify differently:

| Spec | What to Check |
|------|---------------|
| overview.md | Project structure, main entry points, stated constraints |
| data-model.md | Schema files, ORM models, database structure |
| mvp-scope.md | Feature flags, implemented vs planned features |

---

## Important Notes

- **Don't auto-fix code** — only update specs or flag issues
- **Preserve decisions** — rationale in specs is valuable even if implementation diverged
- **Be conservative** — when uncertain, ask rather than assume
- **Document everything** — future readers need to understand why things diverged

---

*Invoked as: `/verify spec/domains/<area>` or `/verify spec/architecture/<area>` or `/verify --quick <path>`*
