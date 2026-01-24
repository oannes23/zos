# Story 5.8: Layer Run Monitor

**Epic**: Introspection
**Status**: 🔴 Not Started
**Estimated complexity**: Medium

## Goal

Implement the UI for monitoring layer runs, viewing operational status, and investigating errors.

## Acceptance Criteria

- [ ] List recent runs with status badges
- [ ] Filter by layer, status
- [ ] View run details with errors
- [ ] Summary statistics
- [ ] Token usage tracking
- [ ] Cost estimates visible

## Technical Notes

### Runs List Template

```html
<!-- src/zos/ui/templates/runs/list.html -->
{% extends "base.html" %}
{% block title %}Layer Runs — Zos{% endblock %}

{% block content %}
<h1>Layer Runs</h1>
<p class="text-muted">Reflection execution history and operational status</p>

<div class="stats-row" hx-get="/ui/runs/stats" hx-trigger="load">
    Loading stats...
</div>

<div class="filters mt-2">
    <select name="layer_name"
            hx-get="/ui/runs/list"
            hx-trigger="change"
            hx-target="#runs-list"
            hx-include="[name='status']">
        <option value="">All layers</option>
        {% for layer in layers %}
        <option value="{{ layer }}">{{ layer }}</option>
        {% endfor %}
    </select>

    <select name="status"
            hx-get="/ui/runs/list"
            hx-trigger="change"
            hx-target="#runs-list"
            hx-include="[name='layer_name']">
        <option value="">All statuses</option>
        <option value="success">Success</option>
        <option value="partial">Partial</option>
        <option value="failed">Failed</option>
        <option value="dry">Dry Run</option>
    </select>
</div>

<div id="runs-list" class="mt-1" hx-get="/ui/runs/list" hx-trigger="load">
    Loading...
</div>
{% endblock %}
```

### Stats Partial

```html
<!-- src/zos/ui/templates/runs/_stats.html -->
<div class="stats-cards">
    <div class="stat-card">
        <span class="stat-value">{{ stats.total_runs }}</span>
        <span class="stat-label">Total Runs (7d)</span>
    </div>
    <div class="stat-card">
        <span class="stat-value text-success">{{ stats.successful_runs }}</span>
        <span class="stat-label">Successful</span>
    </div>
    <div class="stat-card">
        <span class="stat-value text-error">{{ stats.failed_runs }}</span>
        <span class="stat-label">Failed</span>
    </div>
    <div class="stat-card">
        <span class="stat-value text-muted">{{ stats.dry_runs }}</span>
        <span class="stat-label">Dry Runs</span>
    </div>
    <div class="stat-card">
        <span class="stat-value">{{ stats.total_insights }}</span>
        <span class="stat-label">Insights Created</span>
    </div>
    <div class="stat-card">
        <span class="stat-value">${{ stats.total_cost_usd | round(2) }}</span>
        <span class="stat-label">Est. Cost</span>
    </div>
</div>
```

### Runs List Partial

```html
<!-- src/zos/ui/templates/runs/_list.html -->
<table class="runs-table">
    <thead>
        <tr>
            <th>Time</th>
            <th>Layer</th>
            <th>Status</th>
            <th>Targets</th>
            <th>Insights</th>
            <th>Tokens</th>
            <th>Cost</th>
            <th>Duration</th>
        </tr>
    </thead>
    <tbody>
        {% for run in runs %}
        <tr class="clickable"
            hx-get="/ui/runs/{{ run.id }}"
            hx-target="#run-detail-modal"
            hx-swap="innerHTML">
            <td>{{ run.started_at | relative_time }}</td>
            <td>{{ run.layer_name }}</td>
            <td>
                <span class="badge badge-{{ run.status }}">{{ run.status }}</span>
            </td>
            <td>
                {{ run.targets_processed }}
                {% if run.targets_skipped > 0 %}
                <span class="text-error">({{ run.targets_skipped }} skipped)</span>
                {% endif %}
            </td>
            <td>{{ run.insights_created }}</td>
            <td>{{ run.tokens_total | default('—', true) | format_number }}</td>
            <td>{{ run.estimated_cost_usd | format_cost }}</td>
            <td>{{ run.duration_seconds | format_duration }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>

{% if runs %}
<div class="pagination">
    {% if offset > 0 %}
    <button hx-get="/ui/runs/list?offset={{ offset - limit }}&limit={{ limit }}"
            hx-target="#runs-list"
            hx-include="[name='layer_name'],[name='status']">
        ← Previous
    </button>
    {% endif %}

    <span class="page-info">{{ offset + 1 }}-{{ offset + runs|length }} of {{ total }}</span>

    {% if offset + limit < total %}
    <button hx-get="/ui/runs/list?offset={{ offset + limit }}&limit={{ limit }}"
            hx-target="#runs-list"
            hx-include="[name='layer_name'],[name='status']">
        Next →
    </button>
    {% endif %}
</div>
{% else %}
<p class="empty-state">No runs found.</p>
{% endif %}

<div id="run-detail-modal" class="modal"></div>
```

### Run Detail Partial

```html
<!-- src/zos/ui/templates/runs/_detail.html -->
<div class="modal-content">
    <div class="modal-header">
        <h2>{{ run.layer_name }}</h2>
        <button class="close-btn" onclick="this.closest('.modal').innerHTML = ''">&times;</button>
    </div>

    <div class="run-status">
        <span class="badge badge-{{ run.status }} badge-large">{{ run.status | upper }}</span>
        <span class="text-muted">{{ run.started_at.strftime('%Y-%m-%d %H:%M:%S') }}</span>
    </div>

    <div class="run-metrics mt-2">
        <div class="metric-row">
            <span class="metric-label">Duration</span>
            <span>{{ run.duration_seconds | format_duration }}</span>
        </div>
        <div class="metric-row">
            <span class="metric-label">Targets Matched</span>
            <span>{{ run.targets_matched }}</span>
        </div>
        <div class="metric-row">
            <span class="metric-label">Targets Processed</span>
            <span>{{ run.targets_processed }}</span>
        </div>
        <div class="metric-row">
            <span class="metric-label">Targets Skipped</span>
            <span class="{% if run.targets_skipped > 0 %}text-error{% endif %}">
                {{ run.targets_skipped }}
            </span>
        </div>
        <div class="metric-row">
            <span class="metric-label">Insights Created</span>
            <span>{{ run.insights_created }}</span>
        </div>
    </div>

    <h3 class="mt-2">Model Usage</h3>
    <div class="run-metrics">
        <div class="metric-row">
            <span class="metric-label">Profile</span>
            <span>{{ run.model_profile or '—' }}</span>
        </div>
        <div class="metric-row">
            <span class="metric-label">Provider</span>
            <span>{{ run.model_provider or '—' }}</span>
        </div>
        <div class="metric-row">
            <span class="metric-label">Model</span>
            <span>{{ run.model_name or '—' }}</span>
        </div>
        <div class="metric-row">
            <span class="metric-label">Input Tokens</span>
            <span>{{ run.tokens_input | format_number }}</span>
        </div>
        <div class="metric-row">
            <span class="metric-label">Output Tokens</span>
            <span>{{ run.tokens_output | format_number }}</span>
        </div>
        <div class="metric-row">
            <span class="metric-label">Estimated Cost</span>
            <span>{{ run.estimated_cost_usd | format_cost }}</span>
        </div>
    </div>

    {% if run.errors %}
    <h3 class="mt-2 text-error">Errors ({{ run.errors | length }})</h3>
    <div class="errors-list">
        {% for error in run.errors %}
        <div class="error-item">
            <div class="error-topic">{{ error.topic }}</div>
            <div class="error-message">{{ error.error }}</div>
            {% if error.node %}
            <div class="error-node text-muted">Node: {{ error.node }}</div>
            {% endif %}
        </div>
        {% endfor %}
    </div>
    {% endif %}

    <div class="modal-footer">
        <span class="text-muted">Layer hash: {{ run.layer_hash }}</span>
    </div>
</div>
```

### Template Filters

```python
# Add to template engine
def format_number(value):
    """Format large numbers with commas."""
    if value is None:
        return "—"
    return f"{value:,}"

def format_cost(value):
    """Format cost in USD."""
    if value is None:
        return "—"
    return f"${value:.4f}"

def format_duration(seconds):
    """Format duration in human-readable form."""
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.0f}s"

# Register filters
templates.env.filters['format_number'] = format_number
templates.env.filters['format_cost'] = format_cost
templates.env.filters['format_duration'] = format_duration
```

### UI Routes

```python
# src/zos/api/ui.py (additions)

@router.get("/runs", response_class=HTMLResponse)
async def runs_page(
    request: Request,
    loader: LayerLoader = Depends(get_loader),
):
    """Layer runs page."""
    layers = list(loader.load_all().keys())

    return templates.TemplateResponse(
        "runs/list.html",
        {"request": request, "active": "runs", "layers": layers},
    )

@router.get("/runs/stats", response_class=HTMLResponse)
async def runs_stats_partial(
    request: Request,
    db: Database = Depends(get_db),
):
    """Stats partial (htmx)."""
    stats = await db.get_layer_run_stats(
        since=datetime.utcnow() - timedelta(days=7)
    )

    return templates.TemplateResponse(
        "runs/_stats.html",
        {"request": request, "stats": stats},
    )

@router.get("/runs/list", response_class=HTMLResponse)
async def runs_list_partial(
    request: Request,
    layer_name: str = None,
    status: str = None,
    offset: int = 0,
    limit: int = 20,
    db: Database = Depends(get_db),
):
    """Runs list partial (htmx)."""
    runs, total = await db.list_layer_runs(
        layer_name=layer_name or None,
        status=status or None,
        offset=offset,
        limit=limit,
    )

    formatted = [_format_run_for_ui(r) for r in runs]

    return templates.TemplateResponse(
        "runs/_list.html",
        {
            "request": request,
            "runs": formatted,
            "total": total,
            "offset": offset,
            "limit": limit,
        },
    )

@router.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail_partial(
    request: Request,
    run_id: str,
    db: Database = Depends(get_db),
):
    """Run detail partial (htmx modal)."""
    run = await db.get_layer_run(run_id)
    if not run:
        return HTMLResponse("<p>Run not found</p>", status_code=404)

    return templates.TemplateResponse(
        "runs/_detail.html",
        {"request": request, "run": _format_run_for_ui(run)},
    )
```

### Additional CSS

```css
/* Layer runs styles */
.stats-cards {
    display: flex;
    gap: 1rem;
    flex-wrap: wrap;
}

.stat-card {
    background: var(--bg-card);
    padding: 1rem 1.5rem;
    border-radius: 8px;
    text-align: center;
    min-width: 120px;
}

.badge-large {
    font-size: 1rem;
    padding: 0.5rem 1rem;
}

.badge-success { background: var(--success); color: #000; }
.badge-partial { background: var(--warning); color: #000; }
.badge-failed { background: var(--error); color: #fff; }
.badge-dry { background: var(--text-secondary); color: #000; }

.errors-list {
    max-height: 200px;
    overflow-y: auto;
}

.error-item {
    background: rgba(255, 107, 107, 0.1);
    border-left: 3px solid var(--error);
    padding: 0.75rem;
    margin-bottom: 0.5rem;
}

.error-topic {
    font-weight: 600;
}

.error-message {
    font-family: monospace;
    font-size: 0.875rem;
    margin-top: 0.25rem;
}

.metric-row {
    display: flex;
    justify-content: space-between;
    padding: 0.5rem 0;
    border-bottom: 1px solid var(--bg-secondary);
}

.metric-label {
    color: var(--text-secondary);
}
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/ui/templates/runs/list.html` | Main page |
| `src/zos/ui/templates/runs/_stats.html` | Stats cards |
| `src/zos/ui/templates/runs/_list.html` | Runs table |
| `src/zos/ui/templates/runs/_detail.html` | Detail modal |
| `src/zos/api/ui.py` | UI routes |
| `src/zos/ui/static/style.css` | Styles |

## Test Cases

1. Stats show correct counts
2. Filter by layer works
3. Filter by status works
4. Detail shows all fields
5. Errors displayed correctly
6. Pagination works

## Definition of Done

- [ ] Runs list with filters
- [ ] Stats summary
- [ ] Error investigation
- [ ] Cost tracking visible

---

**Requires**: Stories 5.4, 5.5 (API, UI base)
**Blocks**: None
