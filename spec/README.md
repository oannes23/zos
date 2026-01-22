# Specifications

This directory contains technical specifications, structured for consumption by LLM-based coding agents during implementation.

---

## For Human Readers

If you're looking for human-friendly documentation, see [`/docs/`](../docs/README.md) instead.

These specs are designed to be precise, unambiguous, and machine-readable. They prioritize completeness over narrative flow.

---

## How to Navigate

**Start here:** [MASTER.md](MASTER.md) is the central index tracking all specs and their status.

### Directory Structure

```
spec/
├── MASTER.md              # Central index and status tracker
├── glossary.md            # Canonical term definitions
├── architecture/          # System-level design docs
│   ├── overview.md
│   ├── mvp-scope.md
│   └── data-model.md
├── domains/               # Feature area specifications
│   └── *.md
└── implementation/        # Epic and Story specs
    ├── mvp-0/
    └── mvp-1/
```

---

## How to Read Specs

### Status Indicators

Each spec has a status in MASTER.md:
- 🔴 Not started
- 🟡 In progress
- 🟢 Complete
- 🔄 Needs revision

### Decision Blocks

Specs use structured decision blocks:

```markdown
### [Decision Area]

- **Decision**: What was decided
- **Rationale**: Why this choice was made
- **Implications**: What this affects downstream
- **Alternatives considered**: What else was evaluated
```

### Cross-References

Specs link to each other and to the glossary. If a term seems unfamiliar, check [glossary.md](glossary.md).

---

## The Interrogation Workflow

Specs are developed through an iterative Q&A process using the `/interrogate` command. An LLM agent asks clarifying questions, the human answers, and the agent updates the spec based on the answers.

This produces specs that are thorough, consistent, and capture the reasoning behind decisions — not just the decisions themselves.
