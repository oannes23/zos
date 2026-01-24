# Story 5.6: Insights Browser

**Epic**: Introspection
**Status**: 🔴 Not Started
**Estimated complexity**: Medium

## Goal

Implement the UI for browsing and searching insights, the primary window into Zos's accumulated understanding.

## Acceptance Criteria

- [ ] List view with pagination
- [ ] Filter by category
- [ ] Search by content
- [ ] Click to view detail
- [ ] Temporal markers displayed
- [ ] Valence visualization

## Technical Notes

### Templates

```html
<!-- src/zos/ui/templates/insights/list.html -->
{% extends "base.html" %}
{% block title %}Insights — Zos{% endblock %}

{% block content %}
<div class="page-header">
    <h1>Insights</h1>
    <div class="page-actions">
        <input type="search"
               name="q"
               placeholder="Search insights..."
               hx-get="/ui/insights/search"
               hx-trigger="keyup changed delay:300ms"
               hx-target="#insights-list"
               class="search-input">
    </div>
</div>

<div class="filters">
    <select name="category"
            hx-get="/ui/insights"
            hx-trigger="change"
            hx-target="#insights-list"
            hx-include="[name='q']">
        <option value="">All categories</option>
        <option value="user_reflection">User Reflection</option>
        <option value="dyad_observation">Dyad Observation</option>
        <option value="channel_reflection">Channel Reflection</option>
        <option value="self_reflection">Self Reflection</option>
        <option value="synthesis">Synthesis</option>
        <option value="social_texture">Social Texture</option>
    </select>
</div>

<div id="insights-list" hx-get="/ui/insights/list" hx-trigger="load">
    Loading...
</div>
{% endblock %}
```

### Insight List Partial

```html
<!-- src/zos/ui/templates/insights/_list.html -->
{% for insight in insights %}
<div class="card insight-card"
     hx-get="/ui/insights/{{ insight.id }}"
     hx-target="#insight-detail"
     hx-swap="innerHTML">
    <div class="card-header">
        <span class="card-title">{{ insight.topic_key }}</span>
        <span class="badge badge-{{ insight.category }}">{{ insight.category }}</span>
    </div>
    <p class="insight-content">{{ insight.content | truncate(200) }}</p>
    <div class="card-meta">
        <span class="temporal-marker">{{ insight.temporal_marker }}</span>
        <span class="confidence">{{ (insight.confidence * 100) | int }}% confident</span>
    </div>
    <div class="valence-bar">
        {% if insight.valence.joy %}<span class="valence-joy" style="width: {{ insight.valence.joy * 20 }}px" title="Joy: {{ insight.valence.joy }}"></span>{% endif %}
        {% if insight.valence.concern %}<span class="valence-concern" style="width: {{ insight.valence.concern * 20 }}px" title="Concern: {{ insight.valence.concern }}"></span>{% endif %}
        {% if insight.valence.curiosity %}<span class="valence-curiosity" style="width: {{ insight.valence.curiosity * 20 }}px" title="Curiosity: {{ insight.valence.curiosity }}"></span>{% endif %}
        {% if insight.valence.warmth %}<span class="valence-warmth" style="width: {{ insight.valence.warmth * 20 }}px" title="Warmth: {{ insight.valence.warmth }}"></span>{% endif %}
        {% if insight.valence.tension %}<span class="valence-tension" style="width: {{ insight.valence.tension * 20 }}px" title="Tension: {{ insight.valence.tension }}"></span>{% endif %}
    </div>
</div>
{% endfor %}

{% if insights %}
<div class="pagination">
    {% if offset > 0 %}
    <button hx-get="/ui/insights/list?offset={{ offset - limit }}&limit={{ limit }}"
            hx-target="#insights-list">
        ← Previous
    </button>
    {% endif %}

    <span class="page-info">{{ offset + 1 }}-{{ offset + insights|length }} of {{ total }}</span>

    {% if offset + limit < total %}
    <button hx-get="/ui/insights/list?offset={{ offset + limit }}&limit={{ limit }}"
            hx-target="#insights-list">
        Next →
    </button>
    {% endif %}
</div>
{% else %}
<p class="empty-state">No insights found.</p>
{% endif %}
```

### Insight Detail View

```html
<!-- src/zos/ui/templates/insights/detail.html -->
{% extends "base.html" %}
{% block title %}{{ insight.topic_key }} — Zos{% endblock %}

{% block content %}
<nav class="breadcrumb">
    <a href="/ui/insights">Insights</a> → {{ insight.topic_key }}
</nav>

<div class="card">
    <div class="card-header">
        <h1 class="card-title">{{ insight.topic_key }}</h1>
        <span class="badge badge-{{ insight.category }}">{{ insight.category }}</span>
    </div>

    <div class="insight-content-full">
        {{ insight.content }}
    </div>

    <div class="insight-meta mt-2">
        <div class="meta-row">
            <span class="meta-label">Created</span>
            <span>{{ insight.created_at.strftime('%Y-%m-%d %H:%M') }}</span>
        </div>
        <div class="meta-row">
            <span class="meta-label">Memory</span>
            <span>{{ insight.temporal_marker }}</span>
        </div>
        <div class="meta-row">
            <span class="meta-label">Strength</span>
            <span>{{ insight.strength | round(1) }}</span>
        </div>
    </div>

    <h3 class="mt-2">Metrics</h3>
    <div class="metrics-grid">
        <div class="metric">
            <span class="metric-value">{{ (insight.confidence * 100) | int }}%</span>
            <span class="metric-label">Confidence</span>
        </div>
        <div class="metric">
            <span class="metric-value">{{ (insight.importance * 100) | int }}%</span>
            <span class="metric-label">Importance</span>
        </div>
        <div class="metric">
            <span class="metric-value">{{ (insight.novelty * 100) | int }}%</span>
            <span class="metric-label">Novelty</span>
        </div>
    </div>

    <h3 class="mt-2">Emotional Valence</h3>
    <div class="valence-detail">
        {% for name, value in insight.valence.items() %}
        {% if value is not none %}
        <div class="valence-row">
            <span class="valence-name">{{ name | capitalize }}</span>
            <div class="progress" style="width: 200px">
                <div class="progress-bar valence-{{ name }}" style="width: {{ value * 100 }}%"></div>
            </div>
            <span class="valence-value">{{ (value * 100) | int }}%</span>
        </div>
        {% endif %}
        {% endfor %}
    </div>

    {% if insight.supersedes %}
    <h3 class="mt-2">Supersedes</h3>
    <a href="/ui/insights/{{ insight.supersedes }}">View previous insight</a>
    {% endif %}
</div>

<div class="related-insights mt-2">
    <h3>Other Insights on This Topic</h3>
    <div hx-get="/ui/insights/topic/{{ insight.topic_key }}?exclude={{ insight.id }}"
         hx-trigger="load">
        Loading...
    </div>
</div>
{% endblock %}
```

### UI Routes

```python
# src/zos/api/ui.py (additions)

@router.get("/insights", response_class=HTMLResponse)
async def insights_page(request: Request):
    """Insights browser page."""
    return templates.TemplateResponse(
        "insights/list.html",
        {"request": request, "active": "insights"},
    )

@router.get("/insights/list", response_class=HTMLResponse)
async def insights_list_partial(
    request: Request,
    category: str = None,
    q: str = None,
    offset: int = 0,
    limit: int = 20,
    db: Database = Depends(get_db),
):
    """Partial for insights list (htmx)."""
    if q:
        insights, total = await db.search_insights(q, category, offset, limit)
    else:
        insights, total = await db.list_insights(category, None, offset, limit)

    formatted = [_format_insight_for_ui(i) for i in insights]

    return templates.TemplateResponse(
        "insights/_list.html",
        {
            "request": request,
            "insights": formatted,
            "total": total,
            "offset": offset,
            "limit": limit,
        },
    )

@router.get("/insights/{insight_id}", response_class=HTMLResponse)
async def insight_detail(
    request: Request,
    insight_id: str,
    db: Database = Depends(get_db),
):
    """Insight detail page."""
    insight = await db.get_insight(insight_id)
    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found")

    formatted = _format_insight_for_ui(insight)

    return templates.TemplateResponse(
        "insights/detail.html",
        {"request": request, "insight": formatted, "active": "insights"},
    )

def _format_insight_for_ui(insight: Insight) -> dict:
    """Format insight for UI templates."""
    age = _relative_time(insight.created_at)
    strength_label = _strength_label(insight.strength)

    return {
        "id": insight.id,
        "topic_key": insight.topic_key,
        "category": insight.category,
        "content": insight.content,
        "created_at": insight.created_at,
        "temporal_marker": f"{strength_label} from {age}",
        "strength": insight.strength,
        "confidence": insight.confidence,
        "importance": insight.importance,
        "novelty": insight.novelty,
        "valence": {
            "joy": insight.valence_joy,
            "concern": insight.valence_concern,
            "curiosity": insight.valence_curiosity,
            "warmth": insight.valence_warmth,
            "tension": insight.valence_tension,
        },
        "supersedes": insight.supersedes,
    }
```

### Additional CSS

```css
/* Insights-specific styles */
.insight-card {
    cursor: pointer;
    transition: transform 0.1s;
}

.insight-card:hover {
    transform: translateY(-2px);
}

.insight-content {
    color: var(--text-primary);
    margin: 0.5rem 0;
}

.valence-bar {
    display: flex;
    gap: 2px;
    height: 4px;
    margin-top: 0.5rem;
}

.valence-joy { background: #ffd700; }
.valence-concern { background: #ff6b6b; }
.valence-curiosity { background: #4ecdc4; }
.valence-warmth { background: #ff9f43; }
.valence-tension { background: #a55eea; }

.metrics-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1rem;
}

.metric {
    text-align: center;
}

.metric-value {
    display: block;
    font-size: 2rem;
    font-weight: bold;
    color: var(--accent);
}

.metric-label {
    color: var(--text-secondary);
    font-size: 0.875rem;
}

.search-input {
    padding: 0.5rem 1rem;
    border: 1px solid var(--bg-card);
    border-radius: 4px;
    background: var(--bg-secondary);
    color: var(--text-primary);
    width: 250px;
}
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/ui/templates/insights/list.html` | List page |
| `src/zos/ui/templates/insights/_list.html` | List partial |
| `src/zos/ui/templates/insights/detail.html` | Detail page |
| `src/zos/api/ui.py` | UI routes |
| `src/zos/ui/static/style.css` | Additional styles |

## Test Cases

1. List loads insights
2. Category filter works
3. Search returns matches
4. Pagination works
5. Detail view shows all data
6. Valence visualization correct

## Definition of Done

- [ ] Browse insights by category
- [ ] Search works
- [ ] Detail view complete
- [ ] Valence visualized

---

**Requires**: Stories 5.2, 5.5 (API, UI base)
**Blocks**: None
