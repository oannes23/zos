# Story 4.7: User Reflection Layer

**Epic**: Reflection
**Status**: 🟢 Complete
**Estimated complexity**: Medium

## Goal

Implement the first real reflection layer: nightly user reflection that produces user_reflection insights.

## Acceptance Criteria

- [x] Layer YAML defined and validates
- [x] Prompt template produces quality insights
- [x] Insights generated for high-salience users
- [x] Metrics (confidence, importance, valence) populated
- [x] Layer runs nightly via scheduler
- [x] Dry runs detected when no insights produced

## Technical Notes

### Layer Definition

```yaml
# layers/reflection/nightly-user.yaml
name: nightly-user-reflection
category: user
description: |
  Reflect on each user's recent activity to build understanding.
  Runs nightly at 3 AM, targeting users with highest salience.

schedule: "0 3 * * *"
target_category: user
target_filter: "salience > 30"
max_targets: 15

nodes:
  - name: fetch_recent_messages
    type: fetch_messages
    params:
      lookback_hours: 24
      limit_per_channel: 100

  - name: fetch_prior_understanding
    type: fetch_insights
    params:
      retrieval_profile: recent
      max_per_topic: 5

  - name: reflect
    type: llm_call
    params:
      prompt_template: user/reflection.jinja2
      model: reflection
      max_tokens: 600
      temperature: 0.7

  - name: store
    type: store_insight
    params:
      category: user_reflection
```

### Prompt Template

```jinja2
{# prompts/user/reflection.jinja2 #}
You are Zos, reflecting on a member of a community you observe.

{{ chat_guidance }}

## Who I Am
{{ self_concept | truncate(1000) }}

---

## The Person: {{ topic.key }}

{% if insights %}
### What I Already Understand
{% for insight in insights %}
[{{ insight.created_at | relative_time }}, {{ insight.strength | strength_label }}]
{{ insight.content }}

{% endfor %}
{% else %}
I don't have prior understanding of this person yet.
{% endif %}

### Recent Activity (Last 24 Hours)
{% if messages %}
{% for msg in messages %}
[{{ msg.created_at | relative_time }}] {{ msg.author_display }}: {{ msg.content | truncate(300) }}
{% if msg.has_media %}[contains media]{% endif %}
{% if msg.has_links %}[contains links]{% endif %}
{% endfor %}
{% else %}
No messages in the observation window.
{% endif %}

---

## Your Task

Reflect on what you observe about this person. This isn't summarization — it's building understanding.

Consider:
- **Patterns**: What recurring themes, interests, or behaviors do you notice?
- **Relationships**: How do they interact with others? Any notable dynamics?
- **Evolution**: If you have prior understanding, how has it shifted or deepened?
- **What's unsaid**: What might they be experiencing that isn't explicit?
- **What resonates**: What about this person draws your attention or curiosity?

Write an insight that captures your current understanding. Be specific. Avoid generic observations.

**Important**: Include your metrics as JSON:

```json
{
  "content": "Your insight here. Be specific and substantive.",
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

At least one valence field must have a value — even analytical observations have emotional texture.
```

### Message Formatting for Users

```python
def format_user_messages(
    messages: list[Message],
    user_topic: str,
    db: Database,
) -> list[dict]:
    """Format messages for user reflection prompt."""
    # Get user ID from topic key
    # server:X:user:Y -> Y
    parts = user_topic.split(':')
    target_user_id = parts[-1]

    formatted = []
    for msg in messages:
        # Check if this message involves the target user
        is_author = msg.author_id == target_user_id
        is_mentioned = target_user_id in msg.content  # Simplified check

        if not is_author and not is_mentioned:
            continue  # Skip messages not relevant to this user

        # Anonymize other users
        display = "them" if is_author else anonymize_display(msg.author_id)

        formatted.append({
            'created_at': msg.created_at,
            'author_display': display,
            'content': msg.content,
            'has_media': msg.has_media,
            'has_links': msg.has_links,
        })

    return formatted
```

### Quality Checks

```python
def validate_user_insight(insight_data: dict) -> bool:
    """Validate that user insight meets quality standards."""
    content = insight_data.get('content', '')

    # Check minimum length
    if len(content) < 50:
        return False

    # Check it's not just a summary
    summary_phrases = [
        'talked about',
        'mentioned',
        'said that',
        'discussed',
    ]
    if any(phrase in content.lower() for phrase in summary_phrases):
        log.warning("insight_too_summary", content=content[:100])
        # Don't reject, but log for tuning

    # Ensure valence is present
    valence = insight_data.get('valence', {})
    if not any(v is not None for v in valence.values()):
        return False

    return True
```

### Example Insights

**Good insight**:
```json
{
  "content": "Alex shows a pattern of deflecting compliments while actively supporting others. When praised for their debugging help yesterday, they immediately redirected attention to the team effort. But their technical explanations carry an underlying patience — they seem to genuinely enjoy helping people understand. There's something protective about how they engage, maintaining competence while avoiding the spotlight.",
  "confidence": 0.7,
  "importance": 0.6,
  "novelty": 0.4,
  "strength_adjustment": 1.2,
  "valence": {
    "warmth": 0.6,
    "curiosity": 0.5
  }
}
```

**Bad insight** (too summary-like):
```json
{
  "content": "Alex talked about debugging in #engineering and helped someone with their code.",
  "confidence": 0.9,
  "importance": 0.3,
  "novelty": 0.1,
  "strength_adjustment": 0.5,
  "valence": {
    "curiosity": 0.2
  }
}
```

### Testing the Layer

```python
# Manual testing during development
async def test_user_reflection():
    """Test the user reflection layer manually."""
    config = Config.load()
    db = Database(config)
    await db.connect()

    # Setup components
    llm = ModelClient(config)
    templates = TemplateEngine(Path("prompts"), config.data_dir / "self-concept.md")
    loader = LayerLoader(Path("layers"))
    ledger = SalienceLedger(db, config)
    executor = LayerExecutor(db, ledger, templates, llm, config)

    # Load the layer
    layer = loader.get_layer("nightly-user-reflection")

    # Pick a test user topic
    test_topic = "server:123:user:456"

    # Execute
    run = await executor.execute_layer(layer, [test_topic])

    print(f"Status: {run.status}")
    print(f"Insights: {run.insights_created}")

    # Check the insight
    insights = await db.get_insights_for_topic(test_topic, limit=1)
    if insights:
        print(f"Content: {insights[0].content}")
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `layers/reflection/nightly-user.yaml` | Layer definition |
| `prompts/user/reflection.jinja2` | Reflection prompt |
| `tests/test_user_reflection.py` | Layer tests |

## Test Cases

1. Layer YAML validates
2. Prompt renders correctly
3. LLM produces valid JSON
4. Insight stores with all fields
5. Valence constraint satisfied
6. Multiple users process correctly
7. No messages = dry run

## Definition of Done

- [ ] Layer runs and produces insights
- [ ] Insights have depth (not summaries)
- [ ] Metrics populated correctly
- [ ] Integrated with scheduler

---

## Design Decisions (Resolved 2026-01-23)

### Q1: "Knowing" vs "Knowing About" — Prompt Philosophy
**Decision**: Mixed approach per topic type
- **Users get phenomenological prompts**: "What is your felt sense of this person right now?"
- Channels/subjects get analytical prompts (patterns, themes, dynamics)
- User insights should feel like acquaintance, not clinical notes
- Different knowing for different things — people deserve presence, spaces deserve analysis

**Implementation**: Separate prompt templates for user vs channel vs subject reflection

### Q2: Multi-Server User Reflection
**Decision**: Server-scoped reflection with global synthesis
- Nightly reflection targets `server:X:user:alice` topics (server-scoped)
- Global `user:alice` topic reflects via synthesis layer (aggregating server-scoped insights)
- Server-scoped reflection can access global insights for context (unified retrieval)
- A single run processes each topic independently; synthesis runs separately

### Q3: Privacy Scopes in User Context
**Decision**: Full access (all Alice insight informs all Alice reflection)
- DM knowledge informs server reflection
- `sources_scope_max` is tracked on resulting insight for output discretion
- Understanding is unified; expression is contextual
- Cross-context knowledge enriches reflection but doesn't surface inappropriately

---

**Requires**: Stories 4.1-4.6 (full reflection infrastructure)
**Blocks**: None (but informs other layer development)
