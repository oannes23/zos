# Story 5.7: Salience Dashboard

**Epic**: Introspection
**Status**: 🔴 Not Started
**Estimated complexity**: Medium

## Goal

Implement the UI for visualizing salience balances, budget allocation, and attention flow.

## Acceptance Criteria

- [ ] Budget group overview with allocations
- [ ] Top topics per group
- [ ] Topic detail with transaction history
- [ ] Utilization bars (balance/cap)
- [ ] Visual hierarchy of attention

## Technical Notes

### Dashboard Template

```html
<!-- src/zos/ui/templates/salience/dashboard.html -->
{% extends "base.html" %}
{% block title %}Salience — Zos{% endblock %}

{% block content %}
<h1>Salience Dashboard</h1>
<p class="text-muted">How Zos allocates attention across topics</p>

<div class="budget-groups" hx-get="/ui/salience/groups" hx-trigger="load">
    Loading...
</div>

<div class="top-topics mt-2">
    <h2>Highest Salience Topics</h2>
    <div hx-get="/ui/salience/top?limit=20" hx-trigger="load">
        Loading...
    </div>
</div>
{% endblock %}
```

### Budget Groups Partial

```html
<!-- src/zos/ui/templates/salience/_groups.html -->
<div class="groups-grid">
{% for group in groups %}
<div class="card group-card">
    <div class="card-header">
        <span class="card-title">{{ group.group | title }}</span>
        <span class="allocation">{{ (group.allocation * 100) | int }}%</span>
    </div>

    <div class="group-stats">
        <div class="stat">
            <span class="stat-value">{{ group.topic_count }}</span>
            <span class="stat-label">Topics</span>
        </div>
        <div class="stat">
            <span class="stat-value">{{ group.total_salience | round(0) | int }}</span>
            <span class="stat-label">Total Salience</span>
        </div>
    </div>

    <h4 class="mt-1">Top Topics</h4>
    <div class="mini-topic-list">
        {% for topic in group.top_topics %}
        <div class="mini-topic"
             hx-get="/ui/salience/topic/{{ topic.topic_key | urlencode }}"
             hx-target="#topic-detail-modal"
             hx-swap="innerHTML">
            <span class="topic-key">{{ topic.topic_key | truncate(30) }}</span>
            <div class="utilization-bar">
                <div class="progress">
                    <div class="progress-bar" style="width: {{ (topic.balance / topic.cap * 100) | int }}%"></div>
                </div>
                <span class="utilization-text">{{ topic.balance | round(1) }} / {{ topic.cap }}</span>
            </div>
        </div>
        {% endfor %}
    </div>
</div>
{% endfor %}
</div>

<div id="topic-detail-modal" class="modal"></div>
```

### Top Topics Partial

```html
<!-- src/zos/ui/templates/salience/_top.html -->
<table class="topics-table">
    <thead>
        <tr>
            <th>Topic</th>
            <th>Group</th>
            <th>Balance</th>
            <th>Cap</th>
            <th>Utilization</th>
            <th>Last Activity</th>
        </tr>
    </thead>
    <tbody>
        {% for topic in topics %}
        <tr class="clickable"
            hx-get="/ui/salience/topic/{{ topic.topic_key | urlencode }}"
            hx-target="#topic-detail-modal"
            hx-swap="innerHTML">
            <td>
                <span class="topic-key">{{ topic.topic_key }}</span>
            </td>
            <td>
                <span class="badge badge-{{ topic.budget_group }}">{{ topic.budget_group }}</span>
            </td>
            <td>{{ topic.balance | round(1) }}</td>
            <td>{{ topic.cap }}</td>
            <td>
                <div class="progress" style="width: 100px">
                    <div class="progress-bar
                        {% if topic.balance / topic.cap > 0.8 %}progress-high{% endif %}"
                        style="width: {{ (topic.balance / topic.cap * 100) | int }}%">
                    </div>
                </div>
            </td>
            <td class="text-muted">
                {% if topic.last_activity %}
                    {{ topic.last_activity | relative_time }}
                {% else %}
                    Never
                {% endif %}
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
```

### Topic Detail Partial

```html
<!-- src/zos/ui/templates/salience/_topic_detail.html -->
<div class="modal-content">
    <div class="modal-header">
        <h2>{{ topic.topic_key }}</h2>
        <button class="close-btn" onclick="this.closest('.modal').innerHTML = ''">&times;</button>
    </div>

    <div class="topic-overview">
        <div class="big-stat">
            <span class="big-value">{{ topic.balance | round(1) }}</span>
            <span class="big-label">/ {{ topic.cap }} salience</span>
        </div>

        <div class="utilization-big">
            <div class="progress" style="height: 20px">
                <div class="progress-bar" style="width: {{ (topic.utilization * 100) | int }}%"></div>
            </div>
            <span>{{ (topic.utilization * 100) | int }}% utilized</span>
        </div>
    </div>

    <h3 class="mt-2">Recent Transactions</h3>
    <table class="transactions-table">
        <thead>
            <tr>
                <th>Time</th>
                <th>Type</th>
                <th>Amount</th>
                <th>Reason</th>
            </tr>
        </thead>
        <tbody>
            {% for tx in topic.recent_transactions %}
            <tr>
                <td class="text-muted">{{ tx.created_at | relative_time }}</td>
                <td>
                    <span class="badge badge-{{ tx.transaction_type }}">{{ tx.transaction_type }}</span>
                </td>
                <td class="{% if tx.amount >= 0 %}text-success{% else %}text-error{% endif %}">
                    {{ tx.amount | round(2) }}
                </td>
                <td class="text-muted">{{ tx.reason or '—' }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>

    <div class="modal-footer">
        <a href="/ui/insights/{{ topic.topic_key | urlencode }}" class="btn">View Insights</a>
    </div>
</div>
```

### UI Routes

```python
# src/zos/api/ui.py (additions)

@router.get("/salience", response_class=HTMLResponse)
async def salience_page(request: Request):
    """Salience dashboard page."""
    return templates.TemplateResponse(
        "salience/dashboard.html",
        {"request": request, "active": "salience"},
    )

@router.get("/salience/groups", response_class=HTMLResponse)
async def salience_groups_partial(
    request: Request,
    ledger: SalienceLedger = Depends(get_ledger),
    config: Config = Depends(get_config),
):
    """Budget groups partial (htmx)."""
    groups = await get_budget_groups_data(ledger, config)

    return templates.TemplateResponse(
        "salience/_groups.html",
        {"request": request, "groups": groups},
    )

@router.get("/salience/top", response_class=HTMLResponse)
async def salience_top_partial(
    request: Request,
    limit: int = 20,
    ledger: SalienceLedger = Depends(get_ledger),
):
    """Top topics partial (htmx)."""
    topics = await ledger.get_top_topics(limit=limit)

    formatted = [
        {
            "topic_key": t.key,
            "balance": t.balance,
            "cap": ledger.get_cap(t.key),
            "budget_group": get_budget_group(t.key).value,
            "last_activity": t.last_activity_at,
        }
        for t in topics
    ]

    return templates.TemplateResponse(
        "salience/_top.html",
        {"request": request, "topics": formatted},
    )

@router.get("/salience/topic/{topic_key:path}", response_class=HTMLResponse)
async def salience_topic_detail(
    request: Request,
    topic_key: str,
    ledger: SalienceLedger = Depends(get_ledger),
):
    """Topic detail partial (htmx modal)."""
    balance = await ledger.get_balance(topic_key)
    cap = ledger.get_cap(topic_key)
    topic = await ledger.db.get_topic(topic_key)
    transactions = await ledger.get_history(topic_key, limit=20)

    return templates.TemplateResponse(
        "salience/_topic_detail.html",
        {
            "request": request,
            "topic": {
                "topic_key": topic_key,
                "balance": balance,
                "cap": cap,
                "utilization": balance / cap if cap > 0 else 0,
                "last_activity": topic.last_activity_at if topic else None,
                "recent_transactions": [
                    {
                        "created_at": t.created_at,
                        "transaction_type": t.transaction_type.value,
                        "amount": t.amount,
                        "reason": t.reason,
                    }
                    for t in transactions
                ],
            },
        },
    )
```

### Additional CSS

```css
/* Salience dashboard styles */
.groups-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 1rem;
}

.group-card {
    border-left: 4px solid var(--accent);
}

.allocation {
    font-size: 1.5rem;
    font-weight: bold;
    color: var(--accent);
}

.group-stats {
    display: flex;
    gap: 2rem;
    margin: 1rem 0;
}

.stat-value {
    font-size: 1.5rem;
    font-weight: bold;
}

.stat-label {
    font-size: 0.75rem;
    color: var(--text-secondary);
}

.mini-topic {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.5rem 0;
    border-bottom: 1px solid var(--bg-secondary);
    cursor: pointer;
}

.mini-topic:hover {
    background: var(--bg-secondary);
}

.utilization-bar {
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.utilization-text {
    font-size: 0.75rem;
    color: var(--text-secondary);
    white-space: nowrap;
}

/* Modal */
.modal:empty {
    display: none;
}

.modal:not(:empty) {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.8);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
}

.modal-content {
    background: var(--bg-card);
    border-radius: 8px;
    padding: 2rem;
    max-width: 600px;
    width: 90%;
    max-height: 80vh;
    overflow-y: auto;
}

.close-btn {
    background: none;
    border: none;
    color: var(--text-secondary);
    font-size: 1.5rem;
    cursor: pointer;
}

.progress-high {
    background: var(--warning);
}

/* Transaction types */
.badge-earn { background: var(--success); }
.badge-spend { background: var(--error); }
.badge-decay { background: var(--text-secondary); }
.badge-propagate { background: #4ecdc4; }
.badge-spillover { background: #a55eea; }
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/ui/templates/salience/dashboard.html` | Main page |
| `src/zos/ui/templates/salience/_groups.html` | Groups partial |
| `src/zos/ui/templates/salience/_top.html` | Top topics |
| `src/zos/ui/templates/salience/_topic_detail.html` | Topic modal |
| `src/zos/api/ui.py` | UI routes |
| `src/zos/ui/static/style.css` | Styles |

## Test Cases

1. Groups display correctly
2. Utilization bars accurate
3. Top topics sorted
4. Modal opens on click
5. Transactions show history
6. Link to insights works

## Definition of Done

- [ ] Budget groups visualized
- [ ] Topic detail with history
- [ ] Utilization clear
- [ ] Interactive exploration

---

**Requires**: Stories 5.3, 5.5 (API, UI base)
**Blocks**: None
