# Story 5.9: Dev Mode CRUD

**Epic**: Introspection
**Status**: 🔴 Not Started
**Estimated complexity**: Small

## Goal

Implement development-only CRUD operations for insights, enabling manual data adjustment during early development.

## Acceptance Criteria

- [ ] Create/update/delete insights via API
- [ ] Operations protected by dev mode flag
- [ ] Audit logging for all mutations
- [ ] UI for manual insight creation
- [ ] Bulk operations for cleanup

## Technical Notes

### Dev Mode Configuration

```yaml
# config.yaml
development:
  dev_mode: true  # Enable dev-only features
  allow_mutations: true  # Allow CRUD operations
```

### API Endpoints

```python
# src/zos/api/dev.py
from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/dev", tags=["development"])

def require_dev_mode(config: Config = Depends(get_config)):
    """Dependency that ensures dev mode is enabled."""
    if not config.development.dev_mode:
        raise HTTPException(
            status_code=403,
            detail="Dev mode is not enabled. Set development.dev_mode: true in config."
        )
    return True

class InsightCreate(BaseModel):
    topic_key: str
    category: str
    content: str
    confidence: float = 0.5
    importance: float = 0.5
    novelty: float = 0.5
    strength_adjustment: float = 1.0
    valence_joy: Optional[float] = None
    valence_concern: Optional[float] = None
    valence_curiosity: Optional[float] = 0.5  # Default to satisfy constraint
    valence_warmth: Optional[float] = None
    valence_tension: Optional[float] = None

class InsightUpdate(BaseModel):
    content: Optional[str] = None
    confidence: Optional[float] = None
    importance: Optional[float] = None
    novelty: Optional[float] = None
    quarantined: Optional[bool] = None

@router.post("/insights", dependencies=[Depends(require_dev_mode)])
async def create_insight(
    data: InsightCreate,
    db: Database = Depends(get_db),
):
    """Create a new insight (dev mode only)."""
    insight = Insight(
        id=generate_id(),
        topic_key=data.topic_key,
        category=data.category,
        content=data.content,
        sources_scope_max=VisibilityScope.PUBLIC,
        created_at=datetime.utcnow(),
        layer_run_id="dev_manual",
        salience_spent=0,
        strength_adjustment=data.strength_adjustment,
        strength=data.strength_adjustment,  # No salience spent
        confidence=data.confidence,
        importance=data.importance,
        novelty=data.novelty,
        valence_joy=data.valence_joy,
        valence_concern=data.valence_concern,
        valence_curiosity=data.valence_curiosity,
        valence_warmth=data.valence_warmth,
        valence_tension=data.valence_tension,
    )

    await db.insert_insight(insight)

    log.info(
        "dev_insight_created",
        insight_id=insight.id,
        topic=data.topic_key,
    )

    return {"id": insight.id, "message": "Insight created"}

@router.patch("/insights/{insight_id}", dependencies=[Depends(require_dev_mode)])
async def update_insight(
    insight_id: str,
    data: InsightUpdate,
    db: Database = Depends(get_db),
):
    """Update an existing insight (dev mode only)."""
    insight = await db.get_insight(insight_id)
    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found")

    updates = data.dict(exclude_none=True)
    if updates:
        await db.update_insight(insight_id, updates)

        log.info(
            "dev_insight_updated",
            insight_id=insight_id,
            updates=list(updates.keys()),
        )

    return {"message": "Insight updated"}

@router.delete("/insights/{insight_id}", dependencies=[Depends(require_dev_mode)])
async def delete_insight(
    insight_id: str,
    db: Database = Depends(get_db),
):
    """Delete an insight (dev mode only). Memory is sacred — use sparingly."""
    insight = await db.get_insight(insight_id)
    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found")

    await db.delete_insight(insight_id)

    log.warning(
        "dev_insight_deleted",
        insight_id=insight_id,
        topic=insight.topic_key,
        content_preview=insight.content[:50],
    )

    return {"message": "Insight deleted"}

@router.post("/insights/bulk-delete", dependencies=[Depends(require_dev_mode)])
async def bulk_delete_insights(
    topic_key: str = Body(None),
    category: str = Body(None),
    before: datetime = Body(None),
    db: Database = Depends(get_db),
):
    """Bulk delete insights matching criteria (dev mode only)."""
    if not any([topic_key, category, before]):
        raise HTTPException(
            status_code=400,
            detail="Must specify at least one filter"
        )

    count = await db.bulk_delete_insights(
        topic_key=topic_key,
        category=category,
        before=before,
    )

    log.warning(
        "dev_bulk_delete",
        count=count,
        topic_key=topic_key,
        category=category,
    )

    return {"deleted": count}
```

### Database Operations

```python
# src/zos/database.py

async def update_insight(self, insight_id: str, updates: dict):
    """Update insight fields."""
    stmt = insights_table.update().where(
        insights_table.c.id == insight_id
    ).values(**updates)
    await self.execute(stmt)

async def delete_insight(self, insight_id: str):
    """Delete an insight."""
    stmt = insights_table.delete().where(
        insights_table.c.id == insight_id
    )
    await self.execute(stmt)

async def bulk_delete_insights(
    self,
    topic_key: str | None = None,
    category: str | None = None,
    before: datetime | None = None,
) -> int:
    """Bulk delete insights matching criteria."""
    stmt = insights_table.delete()

    if topic_key:
        stmt = stmt.where(insights_table.c.topic_key == topic_key)
    if category:
        stmt = stmt.where(insights_table.c.category == category)
    if before:
        stmt = stmt.where(insights_table.c.created_at < before)

    result = await self.execute(stmt)
    return result.rowcount
```

### UI for Manual Creation

```html
<!-- src/zos/ui/templates/dev/create_insight.html -->
{% extends "base.html" %}
{% block title %}Create Insight (Dev) — Zos{% endblock %}

{% block content %}
<h1>Create Insight <span class="badge badge-warning">Dev Mode</span></h1>

<form hx-post="/dev/insights"
      hx-target="#result"
      class="card">
    <div class="form-group">
        <label>Topic Key</label>
        <input type="text" name="topic_key" required
               placeholder="server:123:user:456">
    </div>

    <div class="form-group">
        <label>Category</label>
        <select name="category" required>
            <option value="user_reflection">User Reflection</option>
            <option value="dyad_observation">Dyad Observation</option>
            <option value="channel_reflection">Channel Reflection</option>
            <option value="self_reflection">Self Reflection</option>
            <option value="social_texture">Social Texture</option>
        </select>
    </div>

    <div class="form-group">
        <label>Content</label>
        <textarea name="content" rows="4" required
                  placeholder="The insight content..."></textarea>
    </div>

    <div class="form-row">
        <div class="form-group">
            <label>Confidence</label>
            <input type="number" name="confidence" value="0.5"
                   min="0" max="1" step="0.1">
        </div>
        <div class="form-group">
            <label>Importance</label>
            <input type="number" name="importance" value="0.5"
                   min="0" max="1" step="0.1">
        </div>
        <div class="form-group">
            <label>Novelty</label>
            <input type="number" name="novelty" value="0.5"
                   min="0" max="1" step="0.1">
        </div>
    </div>

    <h3>Valence (at least one required)</h3>
    <div class="form-row">
        <div class="form-group">
            <label>Joy</label>
            <input type="number" name="valence_joy"
                   min="0" max="1" step="0.1">
        </div>
        <div class="form-group">
            <label>Curiosity</label>
            <input type="number" name="valence_curiosity" value="0.5"
                   min="0" max="1" step="0.1">
        </div>
        <div class="form-group">
            <label>Warmth</label>
            <input type="number" name="valence_warmth"
                   min="0" max="1" step="0.1">
        </div>
    </div>

    <button type="submit" class="btn btn-primary">Create Insight</button>
</form>

<div id="result" class="mt-2"></div>
{% endblock %}
```

### UI Routes

```python
@router.get("/create-insight", response_class=HTMLResponse)
async def create_insight_page(
    request: Request,
    _: bool = Depends(require_dev_mode),
):
    """Manual insight creation page (dev mode only)."""
    return templates.TemplateResponse(
        "dev/create_insight.html",
        {"request": request, "active": None},
    )
```

### Navigation Update

Add dev link when dev mode is enabled:

```html
<!-- In base.html, add conditionally -->
{% if dev_mode %}
<li class="nav-dev">
    <a href="/dev/create-insight">Dev Tools</a>
</li>
{% endif %}
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/api/dev.py` | Dev mode endpoints |
| `src/zos/api/__init__.py` | Register router |
| `src/zos/database.py` | Mutation operations |
| `src/zos/ui/templates/dev/create_insight.html` | Creation form |
| `tests/test_api_dev.py` | Dev endpoint tests |

## Test Cases

1. CRUD works in dev mode
2. CRUD blocked when dev mode off
3. Bulk delete filters correctly
4. Audit logging captures operations
5. UI form creates valid insight
6. Valence constraint enforced

## Definition of Done

- [ ] CRUD endpoints work
- [ ] Protected by dev mode
- [ ] Audit logged
- [ ] UI form functional

---

## Design Decisions (Resolved 2026-01-23)

### Q1: Insight Deletion Semantics
**Decision**: Hard delete ("never knew")
- Row removed from database
- Supersedes chains may orphan — acceptable for dev cleanup
- Dev mode is for cleanup during development, not production
- Production won't have delete capability
- Phenomenologically: dev deletion is retroactive erasure, not forgetting

### Q2: Dev Mode Scope
**Decision**: All or nothing (process-wide, MVP only)
- `dev_mode: true` enables all dev features for all callers
- Not intended for production — production runs with `dev_mode: false`
- Multi-operator access control is post-MVP concern
- Adding auth now would be premature optimization

### Q3: Audit Trail Durability
**Decision**: Database via LLMCallLog (comprehensive audit)
- All LLM calls tracked in `llm_calls` table (per-call granularity)
- Dev mutations logged via structlog AND database
- Comprehensive audit enables future fine-tuning and self-reflection on operations
- Zos can reflect on its own operational history

**Note**: Dev CRUD mutations should also write to an audit table for durability, but this can be a simple append-only mutations log.

---

**Requires**: Stories 5.1, 5.2 (API, insights)
**Blocks**: None (optional development convenience)
