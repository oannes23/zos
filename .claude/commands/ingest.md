# Ingest Command

You are in **Ingest mode**.

Your goal is to extract structured spec content from unstructured notes, ideas, or discussion transcripts.

**Source file**: $ARGUMENTS

---

## Philosophy

Projects accumulate scattered notes — brainstorm dumps, Slack transcripts, voice memo transcriptions, competitor analyses, "random thoughts at 2am" documents. This information is valuable but unstructured.

Ingest mode transforms this raw material into canonical spec content by:
1. Identifying distinct ideas/concepts in the source
2. Clarifying each one with the user
3. Integrating approved content into the proper spec locations

---

## Context Loading

Before analyzing the source file, read:
1. `/spec/MASTER.md` — understand current spec structure and status
2. `/spec/glossary.md` — know existing terminology
3. Existing spec documents — to detect overlaps and conflicts
4. The source file to be ingested

---

## Analysis Phase

Read the source file and identify **distinct buckets** of information:

### Bucket Types

- **New Concepts**: Terms, entities, or ideas not in the glossary
- **Requirements**: Things the system should do (features, capabilities)
- **Constraints**: Things the system should NOT do, or limits
- **Architectural Decisions**: How things should be structured/built
- **Domain Details**: Specifics that belong in an existing domain spec
- **Open Questions**: Uncertainties or alternatives raised in the notes
- **Out of Scope**: Ideas explicitly marked as "not for now" or "future"

### Extraction Guidelines

- One bucket = one coherent idea (may span multiple paragraphs in source)
- Preserve the original language/phrasing when quoting
- Note confidence level: is this "we should" (spitballing) or "we will" (decided)?
- Flag any contradictions with existing specs

---

## Clarification Phase

For each bucket, use `AskUserQuestion` to clarify:

### Question Types by Bucket

**New Concept:**
- Is this a new term we should add to the glossary?
- Does it replace/refine an existing term?
- What domain does it belong to?

**Requirement:**
- Is this confirmed for MVP, or future/aspirational?
- Which domain spec should own this?
- Are there constraints or edge cases to note?

**Constraint:**
- Is this a hard rule or a preference?
- What's the rationale? (capture for spec)
- Any exceptions?

**Architectural Decision:**
- Is this decided or still open?
- What alternatives were considered?
- What does this affect downstream?

**Domain Detail:**
- Does this match, extend, or conflict with existing spec content?
- Should it replace existing content or supplement it?

**Open Question:**
- Should we try to answer this now via interrogation?
- Or note it as an open question in the relevant spec?

### Batch Questions Efficiently

- Group related buckets when possible (3-5 questions per round)
- Skip obvious cases (clearly new, clearly belongs in X)
- Focus questions on ambiguous or high-impact items

---

## Integration Phase

After clarification, update the specs:

### 1. Domain Specs

For each confirmed piece of information:
- Add to the appropriate section of the target spec
- Use decision block format for decisions:
  ```markdown
  ### [Decision Area]

  - **Decision**: [What was decided]
  - **Rationale**: [Why — from the notes or clarification]
  - **Source**: [Reference to ingested file]
  ```
- Mark speculative content appropriately (e.g., "Tentative:" prefix)

### 2. Glossary

For new terms:
- Add canonical definition
- Note relationships to other terms
- Include source reference

### 3. MASTER.md

- Update status indicators if specs gained significant content
- Add open questions to the relevant spec's row
- Note the ingest in "Recent Changes"

### 4. Source File (Optional)

If the user wants, mark the source file as processed:
- Add a header noting when it was ingested
- Or move to an `ingested/` subdirectory

---

## Conflict Resolution

When ingested content conflicts with existing specs:

1. **Surface the conflict explicitly** — show both versions
2. **Ask which is canonical** — the notes or the existing spec?
3. **If notes win**: Update spec, note the change in Recent Changes
4. **If spec wins**: Note that the ingested idea was superseded
5. **If unclear**: Add as open question for future `/interrogate`

---

## Output Report

After integration, report:

```markdown
## Ingest Complete

**Source**: `<file path>`

**Integrated**:
- Added 3 terms to glossary: X, Y, Z
- Updated `spec/domains/<domain>.md`: added requirements for [feature]
- Added decision block to `spec/architecture/<area>.md`: [decision summary]

**Noted as open questions**:
- [Question 1] — added to `spec/domains/<domain>.md`
- [Question 2] — needs `/interrogate` session

**Skipped/Deferred**:
- [Idea] — marked as out of scope for MVP
- [Idea] — contradicted by existing decision in [spec]

**Suggested next steps**:
- Run `/interrogate spec/domains/<domain>` to resolve open questions
- Review updated glossary for consistency
```

---

## Example Session Flow

```
User: /ingest ideas/discord-brainstorm.md

Agent: [Reads context files and source]

Agent: I found 7 distinct items in this brainstorm. Let me clarify a few:

[AskUserQuestion with 3-4 questions about ambiguous items]

User: [Answers]

Agent: Got it. A few more:

[AskUserQuestion with remaining items]

User: [Answers]

Agent: [Updates specs, glossary, MASTER.md]

Agent: ## Ingest Complete
[Report]
```

---

## Handling Different Source Types

### Brainstorm Dumps
- High volume, low signal — be aggressive about asking "is this real?"
- Many items may be "noted but deferred"

### Discussion Transcripts
- Look for decisions vs. exploration
- Multiple voices may have conflicting views — surface these

### Competitor/Research Notes
- Frame as "we could do X like [source]" — ask if we want to
- Don't auto-adopt — require explicit confirmation

### Technical Spikes/Experiments
- Results are more canonical than speculation
- Look for "this worked" vs "we could try"

---

## Important Notes

- **Never auto-integrate** — every significant addition needs user confirmation
- **Preserve provenance** — note where content came from
- **Bias toward questions** — when uncertain, ask rather than assume
- **Respect existing decisions** — don't silently override specs

---

*Invoked as: `/ingest <path-to-notes-file>`*
