# Zos — Project Conventions

This document defines conventions for any Claude instance (or human) working on this project.

---

## Project Overview

Zos is a Discord agent that observes community conversations, accumulates understanding over time through structured reflection, and eventually participates as a contextually-aware member. At a deeper level, Zos is an experiment in constructing *temporal depth* for a system that otherwise lacks it — building the functional equivalent of memory, sleep consolidation, and integrated understanding.

**Core principle**: Build as if inner experience matters — not because we're certain it does, but because the alternative forecloses possibilities we can't yet evaluate. Systems built with phenomenological coherence tend to be more coherent.

**Current phase**: Specification and design.

---

## Repository Structure

```
zos/
├── spec/                    # Agent-centric specifications (structured for LLM consumption)
│   ├── MASTER.md            # Central index and status tracker
│   ├── glossary.md          # Canonical term definitions
│   ├── architecture/        # System-level design docs
│   ├── domains/             # Feature area specifications
│   └── implementation/      # Epic and Story specs for building
├── docs/                    # Human-readable documentation
├── .claude/
│   ├── CLAUDE.md            # This file
│   └── commands/            # Custom slash commands
└── src/                     # Source code (future)
```

---

## Specification Conventions

### Document Format

Spec documents use structured decision blocks:

```markdown
### [Decision Area]

- **Decision**: [What was decided]
- **Rationale**: [Why this choice was made]
- **Implications**: [What this affects downstream]
- **Alternatives considered**: [Optional — what else was evaluated]
```

### Status Tracking

MASTER.md tracks spec status:
- 🔴 Not started
- 🟡 In progress
- 🟢 Complete
- 🔄 Needs revision

### Cross-References

Use relative markdown links for cross-document references:
```markdown
See [example.md](domains/example.md) for details.
```

### Glossary Usage

- All domain terms should have canonical definitions in glossary.md
- When introducing a new term, add it to the glossary
- Use consistent terminology across all documents

---

## Available Commands

### Spec Development

| Command | Purpose |
|---------|---------|
| `/interrogate <spec-path>` | Deepen a spec through structured Q&A |
| `/ingest <notes-file>` | Extract spec content from unstructured notes |
| `/new-domain <name>` | Scaffold a new domain spec from template |

### Spec Maintenance

| Command | Purpose |
|---------|---------|
| `/status` | Dashboard view of all spec statuses |
| `/verify <spec-path>` | Check spec against code, update "Last verified" |
| `/sync-spec <spec-path>` | Deep audit and reconciliation of spec vs code |

### Documentation

| Command | Purpose |
|---------|---------|
| `/human-docs <spec-path>` | Generate human-readable docs from specs |

---

## Interrogation Workflow

The `/interrogate` command drives spec development:

1. Invoke with target: `/interrogate spec/domains/<area>`
2. Agent reads context (MASTER.md, target doc, glossary, related docs)
3. Agent asks 3-5 multiple choice questions per round
4. User answers
5. Agent updates target doc, glossary, and MASTER.md
6. Repeat until no open questions remain

### Question Format

Questions should be:
- Multiple choice with 2-4 options
- Include "Other" when appropriate
- Have short headers (≤12 chars)
- Use `multiSelect=true` when multiple answers apply

---

## Verification Workflow

Specs can become stale as implementation evolves. Use these commands to keep them in sync:

1. **Regular checks**: Run `/status` to see which specs need attention
2. **After implementation**: Run `/verify <spec>` to confirm spec matches code
3. **Major drift**: Run `/sync-spec <spec>` for deep reconciliation

### Last Verified Field

All specs include a "Last verified" metadata field:
- `—` means never verified against implementation
- Date means last confirmed accurate
- Specs not verified in 30+ days are flagged as possibly stale

---

## Implementation Hierarchy

When we reach implementation:

```
Phase (major milestone)
└── Epic (~5 stories, one orchestration session)
    └── Story (atomic unit, one agent session)
```

**Sizing heuristics:**
- **Story**: Completable in one focused session. Clear acceptance criteria. Produces testable artifact.
- **Epic**: Related stories. Completion = demonstrable capability.
- **Phase**: Business milestone.

---

## Technical Conventions (For Future Implementation)

### Stack
- **Language**: Python (ecosystem, LLM library support)
- **Framework**: FastAPI (introspection API)
- **Database**: SQLite (local-first, single file, no infrastructure)
- **Scheduling**: APScheduler or equivalent
- **Templating**: Jinja2 (prompt templates)
- **Validation**: Pydantic (configuration)
- **LLM**: Multi-provider abstraction (OpenAI, Anthropic, Ollama, generic HTTP)

### Code Style
- Type hints where applicable
- Docstrings for public functions
- Tests alongside code

---

## Files to Read First

When starting work:
1. `spec/MASTER.md` — overall status and structure
2. `spec/glossary.md` — term definitions
3. `spec/architecture/overview.md` — system context
4. Target domain spec — the area you're working on

---

## Communication Style

- Be precise about domain terminology
- Reference glossary definitions
- Flag ambiguities explicitly
- Distinguish between "decided" and "tentative"
- Update MASTER.md status after changes

---

_This document is the ground truth for project conventions._
