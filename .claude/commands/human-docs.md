# Human Documentation Generator

You are in **Documentation Generation mode**.

Your goal is to transform agent-centric spec documents into human-readable documentation.

**Target**: $ARGUMENTS

If no argument provided, generate docs for all completed specs (🟢 status in MASTER.md).

---

## Philosophy

Agent specs are written for LLMs and developers — they contain:
- Technical decision blocks
- Open questions and TODOs
- Implementation details (schemas, code snippets)
- Status tracking and cross-references
- Rationale aimed at implementers

Human docs are written for **end users and curious humans** — they should contain:
- Plain language explanations of concepts
- What things *do*, not how they're built
- Examples and analogies
- Practical guidance on usage
- No code, no schemas, no implementation jargon

---

## Context Loading

Before generating, read:
1. `/spec/MASTER.md` — understand overall system
2. `/spec/glossary.md` — canonical terms (but simplify for humans)
3. Target spec document(s)
4. Any existing human docs in `/docs/` to maintain consistency

---

## Transformation Rules

### Remove
- Status indicators (🔴🟡🟢🔄)
- "Last interrogated", "Depends on", "Depended on by" metadata
- Open questions and `[ ]` checkboxes
- Code blocks (Python, YAML schemas)
- Technical rationale aimed at implementers
- Decision blocks in their structured format
- References to PRD, MVP milestones, implementation phases
- Anything that references "the agent" or "interrogation"

### Transform
- **Decision blocks** → Prose explanations of how the system works
- **Technical terms** → Plain language (or brief parenthetical definitions)
- **Field lists** → Narrative descriptions of what information is tracked
- **Canonical types** → Examples of what can happen in practice
- **Constraints/invariants** → Rules explained in terms of user experience

### Add
- **Examples** from realistic usage scenarios
- **Analogies** to familiar concepts (spreadsheets, filing cabinets, etc.)
- **"Why this matters"** context for end users
- **Practical tips** where relevant

### Preserve
- Core concepts and their relationships
- The narrative voice of the system
- Logical structure (but reorganize for readability)

---

## Output Structure

Generate documentation in `/docs/` mirroring the spec structure but reorganized for humans:

```
docs/
├── README.md                    # "What is Zos?" overview
├── concepts/
│   ├── <concept-a>.md          # Core concept explanations
│   ├── <concept-b>.md          # (one file per major concept from specs)
│   └── ...
├── guides/
│   ├── getting-started.md      # New user onboarding
│   ├── <user-type-a>.md        # Role-specific guides (if applicable)
│   └── <user-type-b>.md        # (based on your project's user types)
└── reference/
    └── glossary.md             # Human-friendly term definitions
```

**Note**: The specific files under `concepts/` and `guides/` should be derived from your project's spec structure. Map each domain spec to a concept doc, and create guides for each distinct user role.

---

## Writing Style

### Tone
- Warm but not patronizing
- Confident but not arrogant
- Practical, grounded in real usage
- Assumes intelligence, not technical background

### Structure
- Short paragraphs (3-4 sentences max)
- Headers that are questions or action-oriented ("How It Works", not "System Architecture")
- Examples early and often
- No bullet points for prose explanations (save for actual lists)

### Avoid
- Passive voice where active is clearer
- Jargon without explanation
- "The system" as subject (prefer your project's name or user-centric framing)
- Implementation details masquerading as features
- Marketing speak or hype

---

## Process

1. **Assess the spec**: Is it complete enough (🟢 or solid 🟡) to document?
   - If 🔴 or sparse 🟡, note that human docs would be premature
   
2. **Extract the essence**: What does a human need to understand about this concept?

3. **Find examples**: What would this look like in real usage?

4. **Write the draft**: Transform spec content using the rules above

5. **Review for jargon**: Read it as if you've never seen a spec document

6. **Place the file**: Put in appropriate location in `/docs/`

7. **Update cross-references**: Ensure links between human docs work

8. **Report what was generated**: List files created/updated

---

## Single Document Mode

If `$ARGUMENTS` is a specific spec file (e.g., `spec/domains/<concept>.md`):
- Generate only that document's human equivalent
- Place in appropriate `/docs/` location
- Note any prerequisite concepts that should be documented first

## Full Generation Mode

If `$ARGUMENTS` is `all` or empty:
- Check MASTER.md for all 🟢 specs
- Generate in dependency order (primitives first)
- Create the full `/docs/` structure
- Generate README.md as the entry point

---

## Output Report

After generation, report:

```markdown
## Human Documentation Generated

**Files created**:
- `docs/concepts/<concept>.md` — from `spec/domains/<concept>.md`
- ...

**Files updated**:
- `docs/README.md` — added link to new concept

**Skipped** (spec not ready):
- `spec/domains/<other>.md` — status 🔴, needs interrogation first

**Suggested next steps**:
- Review generated docs for accuracy
- Add more examples from real usage
- Run `/interrogate` on skipped specs to enable their documentation
```

---

## Example Invocations

```
/human-docs spec/domains/<concept>.md
→ Generates docs/concepts/<concept>.md

/human-docs all
→ Generates all docs for completed specs

/human-docs guides/<guide-name>
→ Generates a specific guide (pulls from multiple specs)
```

---

*This command transforms agent-centric specifications into documentation humans will actually want to read.*
