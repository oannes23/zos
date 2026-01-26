# Story 5.5: UI Base

**Epic**: Introspection
**Status**: 🟢 Complete
**Estimated complexity**: Medium

## Goal

Establish the htmx + Jinja2 UI foundation with base template, navigation, and styling.

## Acceptance Criteria

- [x] Base template with navigation
- [x] htmx loaded and working
- [x] Simple CSS styling (no build step)
- [x] Navigation between sections
- [x] UI served from FastAPI
- [x] Dark mode friendly

## Technical Notes

### UI Structure

```
src/zos/ui/
├── templates/
│   ├── base.html         # Base template with nav
│   ├── index.html        # Dashboard/home
│   ├── insights/
│   │   ├── list.html
│   │   ├── detail.html
│   │   └── _card.html    # Partial for htmx
│   ├── salience/
│   │   ├── dashboard.html
│   │   └── _topic.html
│   └── runs/
│       ├── list.html
│       └── detail.html
└── static/
    ├── style.css
    └── htmx.min.js       # Local copy of htmx
```

### Base Template

```html
<!-- src/zos/ui/templates/base.html -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Zos{% endblock %}</title>
    <link rel="stylesheet" href="/static/style.css">
    <script src="/static/htmx.min.js"></script>
</head>
<body>
    <nav class="main-nav">
        <div class="nav-brand">
            <a href="/">Zos</a>
        </div>
        <ul class="nav-links">
            <li><a href="/ui/insights" {% if active == 'insights' %}class="active"{% endif %}>Insights</a></li>
            <li><a href="/ui/salience" {% if active == 'salience' %}class="active"{% endif %}>Salience</a></li>
            <li><a href="/ui/runs" {% if active == 'runs' %}class="active"{% endif %}>Layer Runs</a></li>
        </ul>
        <div class="nav-status">
            <span class="status-indicator" hx-get="/ui/status" hx-trigger="every 30s" hx-swap="innerHTML">
                Loading...
            </span>
        </div>
    </nav>

    <main class="content">
        {% block content %}{% endblock %}
    </main>

    <footer class="main-footer">
        <p>Zos v0.1.0 — <a href="/docs">API Docs</a></p>
    </footer>
</body>
</html>
```

### CSS Styling

```css
/* src/zos/ui/static/style.css */
:root {
    --bg-primary: #1a1a2e;
    --bg-secondary: #16213e;
    --bg-card: #0f3460;
    --text-primary: #eaeaea;
    --text-secondary: #a0a0a0;
    --accent: #e94560;
    --accent-hover: #ff6b6b;
    --success: #4ecca3;
    --warning: #ffc107;
    --error: #ff6b6b;
}

* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    line-height: 1.6;
}

/* Navigation */
.main-nav {
    display: flex;
    align-items: center;
    padding: 1rem 2rem;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--bg-card);
}

.nav-brand a {
    font-size: 1.5rem;
    font-weight: bold;
    color: var(--accent);
    text-decoration: none;
}

.nav-links {
    display: flex;
    list-style: none;
    margin-left: 2rem;
    gap: 1rem;
}

.nav-links a {
    color: var(--text-secondary);
    text-decoration: none;
    padding: 0.5rem 1rem;
    border-radius: 4px;
    transition: all 0.2s;
}

.nav-links a:hover,
.nav-links a.active {
    color: var(--text-primary);
    background: var(--bg-card);
}

.nav-status {
    margin-left: auto;
}

.status-indicator {
    padding: 0.25rem 0.75rem;
    border-radius: 12px;
    font-size: 0.875rem;
    background: var(--bg-card);
}

/* Content */
.content {
    max-width: 1200px;
    margin: 0 auto;
    padding: 2rem;
}

/* Cards */
.card {
    background: var(--bg-card);
    border-radius: 8px;
    padding: 1.5rem;
    margin-bottom: 1rem;
}

.card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1rem;
}

.card-title {
    font-size: 1.125rem;
    font-weight: 600;
}

.card-meta {
    color: var(--text-secondary);
    font-size: 0.875rem;
}

/* Badges */
.badge {
    display: inline-block;
    padding: 0.25rem 0.5rem;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 500;
}

.badge-success { background: var(--success); color: #000; }
.badge-warning { background: var(--warning); color: #000; }
.badge-error { background: var(--error); color: #fff; }
.badge-dry { background: var(--text-secondary); color: #000; }

/* Tables */
table {
    width: 100%;
    border-collapse: collapse;
}

th, td {
    padding: 0.75rem;
    text-align: left;
    border-bottom: 1px solid var(--bg-secondary);
}

th {
    color: var(--text-secondary);
    font-weight: 500;
}

/* Progress bars */
.progress {
    height: 8px;
    background: var(--bg-secondary);
    border-radius: 4px;
    overflow: hidden;
}

.progress-bar {
    height: 100%;
    background: var(--accent);
    transition: width 0.3s;
}

/* Footer */
.main-footer {
    text-align: center;
    padding: 2rem;
    color: var(--text-secondary);
    font-size: 0.875rem;
}

.main-footer a {
    color: var(--accent);
}

/* Utilities */
.text-muted { color: var(--text-secondary); }
.text-success { color: var(--success); }
.text-error { color: var(--error); }
.mt-1 { margin-top: 0.5rem; }
.mt-2 { margin-top: 1rem; }
.mb-1 { margin-bottom: 0.5rem; }
.mb-2 { margin-bottom: 1rem; }
```

### FastAPI Routes

```python
# src/zos/api/ui.py
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

router = APIRouter(prefix="/ui", tags=["ui"])

templates = Jinja2Templates(directory=Path(__file__).parent.parent / "ui" / "templates")

@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """UI home page."""
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "active": "home"},
    )

@router.get("/status")
async def status_badge(request: Request, db: Database = Depends(get_db)):
    """Status indicator for nav bar (htmx partial)."""
    try:
        await db.execute("SELECT 1")
        return HTMLResponse('<span class="badge badge-success">Healthy</span>')
    except Exception:
        return HTMLResponse('<span class="badge badge-error">Error</span>')

# Mount static files
def setup_ui(app: FastAPI):
    """Setup UI routes and static files."""
    static_dir = Path(__file__).parent.parent / "ui" / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.include_router(router)
```

### Index Page

```html
<!-- src/zos/ui/templates/index.html -->
{% extends "base.html" %}
{% block title %}Zos — Dashboard{% endblock %}

{% block content %}
<h1>Zos Dashboard</h1>

<div class="dashboard-grid">
    <div class="card">
        <div class="card-header">
            <span class="card-title">Recent Insights</span>
            <a href="/ui/insights" class="text-muted">View all →</a>
        </div>
        <div hx-get="/ui/insights/recent" hx-trigger="load" hx-swap="innerHTML">
            Loading...
        </div>
    </div>

    <div class="card">
        <div class="card-header">
            <span class="card-title">Top Topics</span>
            <a href="/ui/salience" class="text-muted">View all →</a>
        </div>
        <div hx-get="/ui/salience/top" hx-trigger="load" hx-swap="innerHTML">
            Loading...
        </div>
    </div>

    <div class="card">
        <div class="card-header">
            <span class="card-title">Recent Runs</span>
            <a href="/ui/runs" class="text-muted">View all →</a>
        </div>
        <div hx-get="/ui/runs/recent" hx-trigger="load" hx-swap="innerHTML">
            Loading...
        </div>
    </div>
</div>
{% endblock %}
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/ui/templates/base.html` | Base template |
| `src/zos/ui/templates/index.html` | Dashboard |
| `src/zos/ui/static/style.css` | Styling |
| `src/zos/ui/static/htmx.min.js` | htmx library |
| `src/zos/api/ui.py` | UI routes |
| `src/zos/api/__init__.py` | Setup UI |

## Test Cases

1. UI loads without errors
2. Navigation works
3. htmx partials load
4. Status indicator updates
5. Styling renders correctly

## Definition of Done

- [x] Base template complete
- [x] Navigation functional
- [x] htmx working
- [x] Dark theme applied

---

**Requires**: Story 5.1 (FastAPI)
**Blocks**: Stories 5.6-5.8 (content pages)
