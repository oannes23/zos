# Story 4.2: Prompt Template System

**Epic**: Reflection
**Status**: 🟢 Complete
**Estimated complexity**: Medium

## Goal

Implement Jinja2 prompt template loading with standard context injection, including `<chat>` user guidance.

## Acceptance Criteria

- [x] Templates load from `prompts/` directory
- [x] Jinja2 renders with context variables
- [x] `<chat>` guidance auto-injected into all templates
- [x] Self-concept document accessible in templates
- [x] Temporal formatting helpers available
- [x] Missing template produces clear error

## Technical Notes

### Template Directory Structure

```
prompts/
├── _base.jinja2           # Base template with common elements
├── _chat_guidance.jinja2  # Auto-injected guidance
├── user/
│   ├── reflection.jinja2
│   └── summary.jinja2
├── dyad/
│   └── observation.jinja2
├── channel/
│   └── digest.jinja2
├── self/
│   ├── reflection.jinja2
│   └── concept_synthesis.jinja2
└── synthesis/
    └── global_user.jinja2
```

### Template Engine

```python
# src/zos/templates.py
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pathlib import Path
from datetime import datetime, timedelta

class TemplateEngine:
    """Manages Jinja2 templates for prompts."""

    def __init__(self, templates_dir: Path = Path("prompts")):
        self.templates_dir = templates_dir
        self.env = Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True,
        )

        # Register custom filters
        self.env.filters['relative_time'] = self.relative_time
        self.env.filters['strength_label'] = self.strength_label

        # Load chat guidance once
        self._chat_guidance = self._load_chat_guidance()

    def _load_chat_guidance(self) -> str:
        """Load the standard <chat> user guidance."""
        guidance_path = self.templates_dir / "_chat_guidance.jinja2"
        if guidance_path.exists():
            return guidance_path.read_text()
        return DEFAULT_CHAT_GUIDANCE

    def render(
        self,
        template_path: str,
        context: dict,
        include_chat_guidance: bool = True,
    ) -> str:
        """Render a template with context."""
        template = self.env.get_template(template_path)

        # Build full context
        full_context = {
            **context,
            'now': datetime.utcnow(),
        }

        # Inject chat guidance
        if include_chat_guidance:
            full_context['chat_guidance'] = self._chat_guidance

        return template.render(**full_context)

    @staticmethod
    def relative_time(dt: datetime) -> str:
        """Convert datetime to human-relative string."""
        if dt is None:
            return "unknown time"

        delta = datetime.utcnow() - dt

        if delta < timedelta(hours=1):
            minutes = int(delta.total_seconds() / 60)
            return f"{minutes} minutes ago"
        elif delta < timedelta(days=1):
            hours = int(delta.total_seconds() / 3600)
            return f"{hours} hours ago"
        elif delta < timedelta(days=7):
            days = delta.days
            return f"{days} days ago"
        elif delta < timedelta(days=30):
            weeks = delta.days // 7
            return f"{weeks} weeks ago"
        elif delta < timedelta(days=365):
            months = delta.days // 30
            return f"{months} months ago"
        else:
            years = delta.days // 365
            return f"{years} years ago"

    @staticmethod
    def strength_label(strength: float) -> str:
        """Convert strength score to human-readable label."""
        if strength >= 8:
            return "strong memory"
        elif strength >= 5:
            return "clear memory"
        elif strength >= 2:
            return "fading memory"
        else:
            return "distant memory"
```

### Default Chat Guidance

```python
DEFAULT_CHAT_GUIDANCE = """
## Anonymous Users

Messages from <chat_N> are from anonymous users who have not opted in to
identity tracking. These messages provide conversational context only.

Do NOT:
- Analyze or form insights about <chat> users
- Respond to or acknowledge messages from <chat> users
- Form dyads or relationships involving <chat> users
- Reference what <chat> users said in responses

Treat <chat> messages as background context for understanding what
opted-in users are saying, discussing, or responding to.
"""
```

### Self-Concept Integration

```python
class TemplateEngine:
    def __init__(self, templates_dir: Path, self_concept_path: Path):
        # ...
        self.self_concept_path = self_concept_path

    def get_self_concept(self) -> str:
        """Load the current self-concept document."""
        if self.self_concept_path.exists():
            return self.self_concept_path.read_text()
        return "Self-concept not yet established."

    def render(self, template_path: str, context: dict, ...):
        full_context = {
            **context,
            'self_concept': self.get_self_concept(),
            # ...
        }
```

### Example Template

```jinja2
{# prompts/user/reflection.jinja2 #}
{% extends "_base.jinja2" %}

{% block content %}
You are reflecting on {{ topic.key }}, a user in this community.

{{ chat_guidance }}

## Self-Concept
{{ self_concept }}

## Prior Understanding
{% for insight in insights %}
[{{ insight.created_at | relative_time }}, {{ insight.strength | strength_label }}]
{{ insight.content }}
{% endfor %}

## Recent Messages
{% for msg in messages %}
[{{ msg.created_at | relative_time }}] {{ msg.author_display }}: {{ msg.content }}
{% endfor %}

## Your Task

Reflect on what you've observed about this person. Consider:
- What patterns do you notice in how they communicate?
- What topics seem to interest or concern them?
- How do they interact with others?
- What might they be experiencing that isn't explicitly stated?

Generate an insight that captures your current understanding. Include metrics:

```json
{
  "content": "Your insight here...",
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

At least one valence field must be non-null.
{% endblock %}
```

### Base Template

```jinja2
{# prompts/_base.jinja2 #}
{% block preamble %}
You are Zos, a being that observes, remembers, and reflects.
{% endblock %}

{% block content %}{% endblock %}

{% block closing %}
Remember: Your insights become part of your memory. Write what feels true
and significant, not what seems expected.
{% endblock %}
```

### Context Formatting Helpers

```python
def format_messages_for_prompt(
    messages: list[Message],
    anonymize: dict[str, str],  # user_id -> display name
) -> list[dict]:
    """Format messages for template context."""
    formatted = []
    for msg in messages:
        display = anonymize.get(msg.author_id, msg.author_id)
        formatted.append({
            'created_at': msg.created_at,
            'author_display': display,
            'content': msg.content,
            'has_media': msg.has_media,
            'has_links': msg.has_links,
        })
    return formatted

def format_insights_for_prompt(insights: list[Insight]) -> list[dict]:
    """Format insights for template context with temporal markers."""
    return [{
        'created_at': i.created_at,
        'content': i.content,
        'strength': i.strength,
        'confidence': i.confidence,
    } for i in insights]
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/templates.py` | TemplateEngine class |
| `prompts/_base.jinja2` | Base template |
| `prompts/_chat_guidance.jinja2` | Chat user guidance |
| `prompts/user/reflection.jinja2` | User reflection template |
| `tests/test_templates.py` | Template rendering tests |

## Test Cases

1. Template renders with context
2. Relative time filter works correctly
3. Strength label filter works
4. Chat guidance auto-injected
5. Self-concept accessible
6. Missing template produces clear error
7. Jinja2 syntax errors caught

## Definition of Done

- [ ] Templates render correctly
- [ ] Chat guidance in all prompts
- [ ] Self-concept accessible
- [ ] Temporal helpers work

---

## Design Decisions (Resolved 2026-01-23)

### Q1: Self-Concept Freshness
**Decision**: Fresh per render
- Read from disk each time `get_self_concept()` is called
- Always current, even if self-concept updates mid-layer-run
- Potential inconsistency within a layer run is acceptable — reflects authentic evolution
- Self-concept may change during reflection, and that's fine

### Q2: Template Error Handling
**Decision**: Fail the node
- Template syntax errors or undefined variables raise exceptions
- Error propagates; layer continues with fail-forward (skips topic)
- Clear audit trail of what failed and why
- Strict failure catches template authoring errors quickly

### Q3: `<chat>` Guidance Placement
**Decision**: After system section
- `<chat>` guidance placed early in template, right after identity/role
- Sets output format expectations upfront
- Part of system prompt, not mixed with user context
- Models see guidance before any context that might "override" it

---

**Requires**: Story 4.1 (layers reference templates)
**Blocks**: Story 4.3 (executor uses templates)
