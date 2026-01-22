# Spec Interrogation Command

You are in **Spec Interview mode**.

Your goal is to deepen the specification for: **$ARGUMENTS**

## Context Loading

Before asking questions, read and understand:
1. `/spec/MASTER.md` — project overview and status
2. `/spec/glossary.md` — canonical terminology
3. The target spec document (if it exists)
4. Related spec documents (check cross-references)

## Interview Rules

1. **Ask 3-5 questions per round**
2. Each question should have:
   - 2-4 concrete options
   - Short headers (≤12 characters)
   - An "Other" option when the design space is open
3. After receiving answers:
   - Summarize decisions as bullet points
   - Note any implications for other specs
   - Ask the next round of questions
4. Continue until:
   - User says "done"
   - You have no remaining questions that would affect implementation
5. When complete, update all artifacts (see below)

## Question Categories

Good questions to explore:
- **Data shape**: What fields? What types? Required vs optional?
- **Relationships**: How does this connect to other entities?
- **Lifecycle**: What states? What transitions?
- **Constraints**: What invariants must hold? What's forbidden?
- **Edge cases**: What happens when X? How do we handle Y?
- **Scope boundaries**: What's explicitly NOT part of this?

## Output Requirements

When the interview is complete:

### 1. Update the target spec document
Use structured decision blocks:
```markdown
### [Decision Area]

- **Decision**: [What was decided]
- **Rationale**: [Why]
- **Implications**: [What this affects]
```

### 2. Update glossary.md
Add any new terms that emerged during discussion.

### 3. Update MASTER.md
- Change status indicator (🔴→🟡→🟢)
- Note any newly-identified open questions
- Flag any specs that now need revision (🔄)

### 4. List implications
Tell the user which other specs may need updates based on decisions made.

## Tone

- Be thorough but not exhausting
- Prioritize decisions that affect implementation
- Flag when something is "good enough for MVP" vs "needs more thought"
- Respect the user's time — don't ask questions with obvious answers

## Starting the Interview

Begin by:
1. Stating what document you're interrogating
2. Summarizing what's already known/decided (from existing docs)
3. Identifying the key open questions
4. Asking your first round of questions

---

*Invoked as: `/interrogate spec/domains/<area>` or `/interrogate spec/architecture/<area>`*
