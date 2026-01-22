# Status Command

You are in **Status mode**.

Your goal is to provide a quick dashboard view of the project's specification status.

---

## Context Loading

Read the following files:
1. `/spec/MASTER.md` — central index with status indicators
2. All files in `/spec/architecture/` — architecture specs
3. All files in `/spec/domains/` — domain specs (skip `_TEMPLATE.md`)
4. `/spec/glossary.md` — term definitions

---

## Analysis

For each spec file, extract:
- **Status indicator**: 🔴🟡🟢🔄
- **Last interrogated date**: from metadata
- **Last verified date**: from metadata (if present)
- **Open questions count**: count items in "Open Questions" section
- **Staleness**: flag if last verified > 30 days ago or if code has changed since

---

## Output Format

Present a clear dashboard:

```markdown
# Zos — Spec Status Dashboard

## Summary

| Metric | Count |
|--------|-------|
| 🔴 Not started | X |
| 🟡 In progress | X |
| 🟢 Complete | X |
| 🔄 Needs revision | X |
| ⚠️ Possibly stale | X |
| **Total open questions** | X |

## Architecture Specs

| Spec | Status | Last Interrogated | Last Verified | Open Questions |
|------|--------|-------------------|---------------|----------------|
| overview.md | 🔴 | — | — | 0 |
| ... | ... | ... | ... | ... |

## Domain Specs

| Spec | Status | Last Interrogated | Last Verified | Open Questions |
|------|--------|-------------------|---------------|----------------|
| domain-1.md | 🟡 | 2024-01-15 | — | 3 |
| ... | ... | ... | ... | ... |

## Attention Needed

### Stale Specs (not verified in 30+ days)
- `spec/domains/example.md` — last verified 45 days ago

### High Open Question Count
- `spec/domains/example.md` — 5 open questions

### Needs Revision
- `spec/architecture/data-model.md` — marked 🔄

## Suggested Next Steps

1. Run `/interrogate spec/domains/<highest-priority-incomplete>` to continue speccing
2. Run `/verify spec/domains/<stale-spec>` to check against implementation
3. Run `/sync-spec spec/domains/<needs-revision>` to identify divergences
```

---

## Staleness Detection

A spec is **possibly stale** if:
1. It has a "Last verified" date older than 30 days
2. It's marked 🟢 but has no "Last verified" date
3. There are source files in `src/` that correspond to this domain and have been modified after the spec's last update

For staleness detection involving source files:
- Look for directory/file names matching the domain slug
- Check git history for recent changes
- Flag but don't alarm — just surface for human review

---

## Important Notes

- This is a **read-only** command — don't modify any files
- Be concise — the goal is a quick glance, not deep analysis
- Highlight actionable items in "Attention Needed"
- If no issues found, say "All specs healthy — no immediate action needed"

---

*Invoked as: `/status`*
