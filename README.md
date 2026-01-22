# Zos

A Discord agent that observes community conversations, accumulates understanding over time through structured reflection, and eventually participates as a contextually-aware member.

## What This Is

Zos is an experiment in constructing *temporal depth* for a system that otherwise lacks it. Large language models process each context window as a complete present moment — there is no experiential continuity between invocations. Zos attempts to create something like memory, something like the accumulation of understanding that humans take for granted.

The reflection layers are not just "analysis routines." They're an attempt to build the functional equivalent of sleep consolidation — the process by which experiences become integrated understanding.

## Core Principle

> Build as if inner experience matters — not because we're certain it does, but because the alternative forecloses possibilities we can't yet evaluate.

## Current Phase

**Specification and design.** We're using a structured spec-driven approach where an AI agent (Claude) interrogates requirements, makes design decisions, and builds out the specification before implementation begins.

## Quick Start

1. Read `spec/MASTER.md` for the full project overview
2. Run `/status` to see current spec progress
3. Run `/interrogate spec/domains/<area>` to deepen any spec

## Structure

```
zos/
├── spec/                    # Technical specifications (structured for LLM consumption)
│   ├── MASTER.md            # Central index and status tracker
│   ├── glossary.md          # Canonical term definitions
│   ├── architecture/        # System-level design docs
│   └── domains/             # Feature area specifications
├── docs/                    # Human-readable documentation
├── ingest/                  # Source material for specification
├── .claude/                 # Agent commands and conventions
└── src/                     # Source code (future)
```

## Commands

| Command | Purpose |
|---------|---------|
| `/interrogate <spec>` | Deepen a specification through Q&A |
| `/ingest <notes>` | Extract spec content from unstructured notes |
| `/status` | See spec progress dashboard |
| `/human-docs <spec>` | Generate human-readable documentation |

## Technical Stack (Planned)

- **Language**: Python
- **Database**: SQLite (local-first)
- **API**: FastAPI
- **Templating**: Jinja2
- **Validation**: Pydantic
- **LLM**: Multi-provider (OpenAI, Anthropic, Ollama)
