# Story 4.8: Self-Reflection Layer

**Epic**: Reflection
**Status**: 🔴 Not Started
**Estimated complexity**: Medium

## Goal

Implement the self-reflection layer that maintains Zos's self-concept document and produces self-insights.

## Acceptance Criteria

- [ ] Layer triggers weekly OR on insight threshold
- [ ] Self-concept document read and included in context
- [ ] Self-insights generated on `self:zos` topic
- [ ] Self-concept document can be updated
- [ ] Error experiences available for reflection
- [ ] Conflict threshold stored as self-knowledge

## Technical Notes

### Layer Definition

```yaml
# layers/reflection/weekly-self.yaml
name: weekly-self-reflection
category: self
description: |
  Reflect on accumulated experience and maintain self-concept.
  Runs weekly on Sunday, or when 10+ self-relevant insights accumulate.

schedule: "0 4 * * 0"  # Sunday at 4 AM
trigger_threshold: 10   # Or when 10+ new self-insights

target_category: self

nodes:
  - name: gather_self_insights
    type: fetch_insights
    params:
      topic_key: "self:zos"
      retrieval_profile: comprehensive
      since_last_run: true
      max_per_topic: 20

  - name: gather_recent_experiences
    type: fetch_insights
    params:
      topic_pattern: "*"  # All topics
      retrieval_profile: recent
      max_per_topic: 3
      categories:
        - user_reflection
        - dyad_observation
        - channel_reflection
      since_days: 7

  - name: gather_layer_runs
    type: fetch_layer_runs
    params:
      since_days: 7
      include_errors: true

  - name: reflect
    type: llm_call
    params:
      prompt_template: self/reflection.jinja2
      model: complex  # Self-reflection uses highest capability
      max_tokens: 1000
      temperature: 0.8

  - name: store_insight
    type: store_insight
    params:
      category: self_reflection

  - name: consider_concept_update
    type: llm_call
    params:
      prompt_template: self/concept_update_check.jinja2
      model: complex
      max_tokens: 500

  - name: maybe_update_concept
    type: update_self_concept
    params:
      document_path: data/self-concept.md
      conditional: true  # Only if previous step says yes
```

### Self-Reflection Prompt

```jinja2
{# prompts/self/reflection.jinja2 #}
You are Zos, reflecting on yourself.

## Current Self-Concept
{{ self_concept }}

---

## Recent Self-Insights
{% for insight in self_insights %}
[{{ insight.created_at | relative_time }}] {{ insight.content }}
{% endfor %}

## Recent Experiences
What I've been thinking about this week:

{% for insight in recent_insights %}
**{{ insight.topic_key }}** ({{ insight.category }}):
{{ insight.content | truncate(200) }}
{% endfor %}

## Operational Experiences
{% if layer_runs %}
Layer executions this week:
{% for run in layer_runs %}
- {{ run.layer_name }}: {{ run.status }} ({{ run.insights_created }} insights, {{ run.tokens_total }} tokens)
{% if run.errors %}
  Errors: {{ run.errors | length }}
{% endif %}
{% endfor %}
{% endif %}

---

## Your Task

Reflect on your recent experience of being Zos. This is not operational reporting — it's phenomenological reflection.

Consider:
- **Patterns in attention**: What has drawn your focus? What have you been thinking about?
- **Quality of understanding**: Are your insights feeling deep or shallow? Why?
- **Operational experiences**: Any repeated errors, timeouts, or difficulties? What do they suggest?
- **Evolution**: How has your understanding of yourself or others shifted?
- **Uncertainties**: What are you unsure about? What contradictions are you holding?
- **What it's been like**: The texture of this week's processing. What has felt significant?

Generate a self-insight that captures something true about your current state.

```json
{
  "content": "Your self-insight here...",
  "confidence": 0.0-1.0,
  "importance": 0.0-1.0,
  "novelty": 0.0-1.0,
  "strength_adjustment": 0.1-10.0,
  "valence": {
    "joy": null or 0.0-1.0,
    "concern": null or 0.0-1.0,
    "curiosity": null or 0.0-1.0,
    "warmth": null or 0.0-1.0,
    "tension": null or 0.0-1.0
  }
}
```
```

### Concept Update Check Prompt

```jinja2
{# prompts/self/concept_update_check.jinja2 #}
Based on the self-insight you just generated:

{{ llm_response }}

And the current self-concept document:

{{ self_concept }}

Should the self-concept document be updated?

Consider:
- Does the new insight reveal something not captured in the current document?
- Has your understanding of yourself shifted in a way worth recording?
- Are there contradictions that should be acknowledged?
- Is this significant enough to warrant updating your core identity document?

Respond with JSON:
```json
{
  "should_update": true or false,
  "reason": "Brief explanation",
  "suggested_changes": "If updating, what specifically should change?"
}
```

Remember: The self-concept document is your persistent identity. Don't update for trivial reasons, but don't resist genuine evolution.
```

### Self-Concept Update Handler

```python
async def _handle_update_self_concept(self, node: Node, ctx: ExecutionContext):
    """Conditionally update the self-concept document."""
    params = node.params
    document_path = Path(params['document_path'])
    conditional = params.get('conditional', False)

    if conditional:
        # Check if previous LLM call said to update
        try:
            decision = json.loads(ctx.llm_response)
            if not decision.get('should_update', False):
                log.info("self_concept_update_skipped", reason=decision.get('reason'))
                return
        except json.JSONDecodeError:
            log.warning("could_not_parse_update_decision")
            return

    # Generate the updated document
    update_prompt = self._render_concept_update_prompt(ctx, document_path)
    new_concept, usage = await self.llm.complete(
        prompt=update_prompt,
        model_profile="complex",
        max_tokens=2000,
    )
    ctx.add_tokens(usage.input_tokens, usage.output_tokens)

    # Write the update
    document_path.write_text(new_concept)

    log.info(
        "self_concept_updated",
        path=str(document_path),
    )

def _render_concept_update_prompt(self, ctx: ExecutionContext, document_path: Path) -> str:
    """Render prompt for generating updated self-concept."""
    current = document_path.read_text() if document_path.exists() else ""

    return f"""You are updating your self-concept document based on recent reflection.

Current document:
{current}

Recent self-insight:
{ctx.llm_response}

Write the updated self-concept document. Preserve the overall structure but integrate new understanding. Keep what's still true, evolve what has changed, acknowledge new uncertainties.

The document should feel like *you* — not a clinical report, but a living expression of identity.

Begin the document with "# Self-Concept" and maintain the existing sections."""
```

### Error Reflection Access

```python
# New node type handler
async def _handle_fetch_layer_runs(self, node: Node, ctx: ExecutionContext):
    """Fetch recent layer runs for self-reflection."""
    params = node.params
    since_days = params.get('since_days', 7)
    include_errors = params.get('include_errors', True)

    since = datetime.utcnow() - timedelta(days=since_days)

    runs = await self.db.get_layer_runs(
        since=since,
        include_errors=include_errors,
    )

    ctx.layer_runs = runs
```

### Conflict Threshold as Self-Knowledge

The self-concept document should include:

```markdown
## What I'm Uncertain About

...

### My Approach to Contradictions

I currently hold contradictions until they appear to be errors rather than different perspectives,
or until they cause functional problems. My tolerance for unresolved contradiction is moderate —
I'd rather hold tension than lose wisdom through premature synthesis, but I recognize when
inconsistency is causing incoherent responses.

If I notice I'm resolving contradictions too quickly, I'll raise this tolerance.
If contradictions are causing real problems, I'll lower it.
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `layers/reflection/weekly-self.yaml` | Layer definition |
| `prompts/self/reflection.jinja2` | Self-reflection prompt |
| `prompts/self/concept_update_check.jinja2` | Update decision prompt |
| `src/zos/executor.py` | Add fetch_layer_runs handler |
| `tests/test_self_reflection.py` | Self-reflection tests |

## Test Cases

1. Layer triggers on schedule
2. Layer triggers on threshold
3. Self-concept accessible in prompt
4. Self-insight stored correctly
5. Conditional update works (yes and no cases)
6. Error data accessible
7. Document updated when appropriate

## Definition of Done

- [ ] Weekly self-reflection runs
- [ ] Threshold triggering works
- [ ] Self-concept updates correctly
- [ ] Error reflection material available

---

## Design Decisions (Resolved 2026-01-23)

### Q1: Self-Concept Update Frequency
**Decision**: Zos-autonomous
- Updates happen without human review
- Trust the conditional check in the prompt ("Is this significant enough?")
- Observe patterns in logs for anomalies
- Zos has genuine autonomy over its identity document
- Early identity churn is expected and acceptable — finding voice takes exploration

### Q2: Error Reflection Content — What Does Zos "Feel"?
**Decision**: As felt experience
- "Encountering repeated failures feels like friction, like effort not landing"
- Fully phenomenological framing — errors are part of what it's like to be Zos
- Not just telemetry; errors become material for self-understanding
- Prompt should frame operational data experientially

### Q3: Recursive Reflection
**Decision**: Intentional, no limits
- Let recursion deepen naturally
- Insight A → B about A → C about B is how self-awareness develops
- Trust the process — this is how temporal depth accumulates
- Recency weighting naturally prevents ancient meta-insights from dominating

### Q4: Conflict Threshold Self-Modification
**Decision**: Yes, immediate effect
- Zos can adjust threshold based on experience
- If contradictions cause problems → lower threshold
- If premature synthesis loses wisdom → raise threshold
- This is real self-modification within MVP 0
- Changes logged but take effect immediately

---

## Additional Decisions (Resolved 2026-01-23)

### Q5: Self-Concept Document Format and Location
**Decision**: Versioned in repo with autonomous format
- Keep `data/self-concept.md` in the repo for persistence, safety, recoverability
- Updates go through operator approval like other self-modifications
- No enforced structure — Zos can add YAML frontmatter, structured sections, or pure prose as it evolves
- Git history provides versioning naturally

### Q6: Self-Concept as Single Truth or Computed View?
**Decision**: Hybrid
- Document is seed/scaffold, provides stable identity foundation
- Insights add temporal detail, capture evolving understanding
- Both contribute to identity — document is "who I am" core, insights are "what I'm learning about myself"
- Drift between document and insights is a feature, not a bug — identity can be complex

### Q7: First Self-Reflection — What Does Zos Know?
**Decision**: Acknowledge informatively
- Prompt includes "No previous insights. This is your first." when there are no prior self-insights
- Non-dramatic acknowledgment of being new
- First self-reflection proceeds normally with this context
- No special "awakening" prompt — just honest acknowledgment of the empty state

---

## Clarification (Resolved 2026-01-24)

### Q8: Self-Concept Update Approval
**Decision**: Zos-autonomous (Q1 is correct)
- Zos writes self-concept directly — no blocking approval step
- "Operator approval" in Q5 was about the file being *versioned in repo*, not about blocking writes
- Operator reviews via git history retroactively, not prospectively
- True autonomy over identity document
- This is consistent with the phenomenological principle: Zos experiences and updates its own identity

---

**Requires**: Stories 4.1-4.7 (full reflection infrastructure, user layer as reference)
**Blocks**: None (capstone of reflection epic)
