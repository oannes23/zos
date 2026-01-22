# New Domain Command

You are in **New Domain mode**.

Your goal is to scaffold a new domain specification from the template and integrate it into the project structure.

**Domain name**: $ARGUMENTS

---

## Input Validation

Parse the argument to extract:
- **Display name**: The human-readable name (e.g., "User Authentication")
- **Slug**: The file-safe version (e.g., "user-authentication")

If the argument is ambiguous, ask the user to clarify:
- If given "UserAuth", ask: "Should the display name be 'User Auth' or 'User Authentication'?"
- If given multiple words without clear casing, confirm the display name

Validation rules for slug:
- Lowercase only
- Hyphens for word separation (no underscores or spaces)
- Alphanumeric characters only
- No leading/trailing hyphens

---

## Context Loading

Before creating the new domain:
1. Read `/spec/MASTER.md` — understand existing domains and structure
2. Read `/spec/domains/_TEMPLATE.md` — get the template content
3. Read `/spec/glossary.md` — check if this domain term already exists
4. List existing files in `/spec/domains/` — ensure no naming conflicts

---

## Conflict Detection

Check for conflicts:
1. **File exists**: If `spec/domains/<slug>.md` already exists, ask user how to proceed
2. **Similar name**: If a similar domain exists (e.g., "auth" vs "authentication"), surface this
3. **Glossary conflict**: If the term is already defined differently, flag it

If conflicts found, use `AskUserQuestion`:
- Option to rename the new domain
- Option to merge with existing
- Option to proceed anyway (will overwrite)
- Option to cancel

---

## Scaffolding

### 1. Create the domain spec file

Copy `/spec/domains/_TEMPLATE.md` to `/spec/domains/<slug>.md` with substitutions:

| Placeholder | Replacement |
|-------------|-------------|
| `{{DOMAIN_NAME}}` | Display name |
| `{{Brief description...}}` | Keep as placeholder for user |
| `{{Concept 1}}`, etc. | Keep as placeholders |
| `2026-01-22` | Today's date (YYYY-MM-DD) |
| `{{DEPENDENCIES or "None (primitive)"}}` | Ask user or default to "TBD" |
| `{{DEPENDENTS or "TBD"}}` | "TBD" |

### 2. Update MASTER.md

Add the new domain to the "Domain Specs" table:

```markdown
| {{Display Name}} | [{{slug}}.md](domains/{{slug}}.md) | 🔴 | — |
```

Insert in the appropriate position based on dependencies (primitives first, composites later). If unsure, add at the end.

### 3. Update glossary.md (optional)

If the domain name represents a new term, offer to add it:

```markdown
### {{Display Name}}

{{Brief definition — to be refined during interrogation.}}
```

---

## Dependency Questions

Ask the user about dependencies:

```
Which existing domains does "{{Display Name}}" depend on?
- [ ] None (this is a primitive/foundational domain)
- [ ] {{Existing Domain 1}}
- [ ] {{Existing Domain 2}}
- [ ] Other (specify)
```

Use `multiSelect: true` for this question.

Update the new spec's "Depends on" field and the dependency graph in MASTER.md.

---

## Output

After scaffolding, report:

```markdown
## Domain Created

**File**: `spec/domains/{{slug}}.md`

**Status**: 🔴 Not started

**Next steps**:
1. Edit the overview section to describe this domain
2. Run `/interrogate spec/domains/{{slug}}` to begin speccing
3. Define core concepts and their relationships

**Dependencies**: {{list or "None"}}
**Dependents**: TBD (will be discovered during interrogation)
```

---

## Quick Mode

If the user provides a clear, unambiguous name:
- Skip confirmation questions
- Use sensible defaults (no dependencies, TBD for everything)
- Create the file immediately
- Report what was created

Example quick invocations:
- `/new-domain authentication` → Creates `authentication.md`
- `/new-domain "User Profiles"` → Creates `user-profiles.md`

---

## Error Handling

If something goes wrong:
- **Can't read template**: Report error, don't create partial files
- **MASTER.md parse error**: Create the spec file, warn about manual MASTER.md update needed
- **Permission error**: Report and suggest manual creation

---

*Invoked as: `/new-domain <domain-name>` or `/new-domain "Display Name"`*
