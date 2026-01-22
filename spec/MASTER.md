# Zos — Spec Master Index

## How This Document Works

This is the central index for all design specifications. Each area links to its detailed spec doc.

**Status indicators:**
- 🔴 Not started — needs initial interrogation
- 🟡 In progress — has content, needs deepening
- 🟢 Complete — no open questions remain
- 🔄 Needs revision — downstream decisions may have invalidated something

**Workflow:**
1. Run `/interrogate spec/domains/<area>` to deepen any spec
2. Answer questions until the agent has no more to ask
3. Agent updates the spec doc, glossary, and this index
4. Repeat for next area

---

## Core Principle

> **{{CORE_PRINCIPLE}}**

---

## Scope

### MVP 0
- {{MVP_0_GOAL}}

### MVP 1
- {{MVP_1_GOAL}}

See [mvp-scope.md](architecture/mvp-scope.md) for full details.

---

## Architecture Specs

| Area | Doc | Status | Notes |
|------|-----|--------|-------|
| System Overview | [overview.md](architecture/overview.md) | 🔴 | Philosophy, constraints, non-goals |
| Data Model | [data-model.md](architecture/data-model.md) | 🔴 | Entity relationships, storage approach |
| MVP Scope | [mvp-scope.md](architecture/mvp-scope.md) | 🔴 | MVP 0 vs MVP 1 boundaries |

---

## Domain Specs

<!-- Order by conceptual dependency: primitives first, composites later -->

| Area | Doc | Status | Key Open Questions |
|------|-----|--------|-------------------|
| {{DOMAIN_1}} | [{{domain_1_slug}}.md](domains/{{domain_1_slug}}.md) | 🔴 | — |
| {{DOMAIN_2}} | [{{domain_2_slug}}.md](domains/{{domain_2_slug}}.md) | 🔴 | — |
| {{DOMAIN_3}} | [{{domain_3_slug}}.md](domains/{{domain_3_slug}}.md) | 🔴 | — |

---

## Implementation Specs

### MVP 0

| Epic | Doc | Status | Blocked By |
|------|-----|--------|------------|
| Overview | [overview.md](implementation/mvp-0/overview.md) | 🔴 | Domain specs |

### MVP 1

| Epic | Doc | Status | Blocked By |
|------|-----|--------|------------|
| Overview | [overview.md](implementation/mvp-1/overview.md) | 🔴 | MVP 0 complete |

---

## Dependency Graph

```
<!-- Fill in as you discover dependencies -->
{{DOMAIN_1}} (primitive)
    ↓
{{DOMAIN_2}}
    ↓
{{DOMAIN_3}}
```

---

## Recent Changes

### 2026-01-22: Project Initialized

- Created initial spec structure
- Key decisions pending: all

---

## Glossary

See [glossary.md](glossary.md) for canonical definitions of all terms.

---

## Last Updated
_2026-01-22 — Initial setup._
