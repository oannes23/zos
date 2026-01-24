# Story 5.2: Insights API

**Epic**: Introspection
**Status**: 🔴 Not Started
**Estimated complexity**: Medium

## Goal

Implement API endpoints for querying insights by topic, searching, and listing recent insights.

## Acceptance Criteria

- [ ] GET `/insights/{topic_key}` returns insights for a topic
- [ ] GET `/insights` lists recent insights with pagination
- [ ] GET `/insights/search` searches insight content
- [ ] Retrieval profiles supported via query param
- [ ] Quarantined insights excluded by default
- [ ] Response includes temporal markers

## Technical Notes

### Endpoints

```python
# src/zos/api/insights.py
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

router = APIRouter(prefix="/insights", tags=["insights"])

class InsightResponse(BaseModel):
    id: str
    topic_key: str
    category: str
    content: str
    created_at: datetime
    temporal_marker: str
    strength: float
    confidence: float
    importance: float
    novelty: float
    valence: dict[str, Optional[float]]

    class Config:
        from_attributes = True

class InsightListResponse(BaseModel):
    insights: list[InsightResponse]
    total: int
    offset: int
    limit: int

@router.get("/{topic_key:path}", response_model=list[InsightResponse])
async def get_insights_for_topic(
    topic_key: str,
    profile: str = Query("balanced", description="Retrieval profile"),
    limit: int = Query(10, ge=1, le=100),
    include_quarantined: bool = Query(False),
    db: Database = Depends(get_db),
):
    """Get insights for a specific topic."""
    retriever = InsightRetriever(db)

    insights = await retriever.retrieve(
        topic_key=topic_key,
        profile=profile,
        limit=limit,
        include_quarantined=include_quarantined,
    )

    return [_format_insight_response(i) for i in insights]

@router.get("", response_model=InsightListResponse)
async def list_insights(
    category: Optional[str] = Query(None),
    since: Optional[datetime] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Database = Depends(get_db),
):
    """List recent insights with optional filters."""
    insights, total = await db.list_insights(
        category=category,
        since=since,
        offset=offset,
        limit=limit,
    )

    return InsightListResponse(
        insights=[_format_insight_response(i) for i in insights],
        total=total,
        offset=offset,
        limit=limit,
    )

@router.get("/search", response_model=InsightListResponse)
async def search_insights(
    q: str = Query(..., min_length=2, description="Search query"),
    category: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Database = Depends(get_db),
):
    """Search insights by content."""
    insights, total = await db.search_insights(
        query=q,
        category=category,
        offset=offset,
        limit=limit,
    )

    return InsightListResponse(
        insights=[_format_insight_response(i) for i in insights],
        total=total,
        offset=offset,
        limit=limit,
    )
```

### Response Formatting

```python
def _format_insight_response(insight: Insight | FormattedInsight) -> InsightResponse:
    """Format insight for API response."""
    # Calculate temporal marker if not already present
    if hasattr(insight, 'temporal_marker'):
        temporal_marker = insight.temporal_marker
    else:
        age = _relative_time(insight.created_at)
        strength_label = _strength_label(insight.strength)
        temporal_marker = f"{strength_label} from {age}"

    return InsightResponse(
        id=insight.id,
        topic_key=insight.topic_key,
        category=insight.category,
        content=insight.content,
        created_at=insight.created_at,
        temporal_marker=temporal_marker,
        strength=insight.strength,
        confidence=insight.confidence,
        importance=insight.importance,
        novelty=insight.novelty,
        valence={
            'joy': insight.valence_joy,
            'concern': insight.valence_concern,
            'curiosity': insight.valence_curiosity,
            'warmth': insight.valence_warmth,
            'tension': insight.valence_tension,
        },
    )
```

### Database Queries

```python
# src/zos/database.py

async def list_insights(
    self,
    category: str | None = None,
    since: datetime | None = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[Insight], int]:
    """List insights with pagination."""
    # Count query
    count_stmt = select(func.count()).select_from(insights_table).where(
        insights_table.c.quarantined == False
    )
    if category:
        count_stmt = count_stmt.where(insights_table.c.category == category)
    if since:
        count_stmt = count_stmt.where(insights_table.c.created_at >= since)

    total = await self.fetch_scalar(count_stmt)

    # Data query
    stmt = select(insights_table).where(
        insights_table.c.quarantined == False
    ).order_by(
        insights_table.c.created_at.desc()
    ).offset(offset).limit(limit)

    if category:
        stmt = stmt.where(insights_table.c.category == category)
    if since:
        stmt = stmt.where(insights_table.c.created_at >= since)

    rows = await self.fetch_all(stmt)
    return [row_to_model(r, Insight) for r in rows], total

async def search_insights(
    self,
    query: str,
    category: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[Insight], int]:
    """Search insights by content."""
    # SQLite FTS or LIKE search
    search_pattern = f"%{query}%"

    count_stmt = select(func.count()).select_from(insights_table).where(
        insights_table.c.quarantined == False,
        insights_table.c.content.like(search_pattern),
    )
    if category:
        count_stmt = count_stmt.where(insights_table.c.category == category)

    total = await self.fetch_scalar(count_stmt)

    stmt = select(insights_table).where(
        insights_table.c.quarantined == False,
        insights_table.c.content.like(search_pattern),
    ).order_by(
        insights_table.c.created_at.desc()
    ).offset(offset).limit(limit)

    if category:
        stmt = stmt.where(insights_table.c.category == category)

    rows = await self.fetch_all(stmt)
    return [row_to_model(r, Insight) for r in rows], total
```

### Topic Key URL Encoding

Topic keys contain colons, which need handling in URLs:

```python
# Topic key: server:123:user:456
# URL: /insights/server:123:user:456

# FastAPI handles this with path converter
@router.get("/{topic_key:path}")  # :path allows slashes and colons
```

### Example Responses

**GET /insights/server:123:user:456**
```json
[
  {
    "id": "01HQXYZ...",
    "topic_key": "server:123:user:456",
    "category": "user_reflection",
    "content": "Alice shows a pattern of deflecting compliments...",
    "created_at": "2026-01-22T03:15:00Z",
    "temporal_marker": "strong memory from 2 days ago",
    "strength": 10.2,
    "confidence": 0.8,
    "importance": 0.7,
    "novelty": 0.4,
    "valence": {
      "joy": 0.6,
      "concern": 0.3,
      "curiosity": 0.5,
      "warmth": 0.4,
      "tension": 0.2
    }
  }
]
```

**GET /insights?category=self_reflection&limit=5**
```json
{
  "insights": [...],
  "total": 42,
  "offset": 0,
  "limit": 5
}
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/api/insights.py` | Insights endpoints |
| `src/zos/api/__init__.py` | Register router |
| `src/zos/database.py` | List/search queries |
| `tests/test_api_insights.py` | API tests |

## Test Cases

1. Get insights for topic returns correct data
2. Profile affects retrieval
3. Pagination works correctly
4. Search finds matching content
5. Category filter works
6. Quarantined excluded by default
7. Topic key with colons works

## Definition of Done

- [ ] All endpoints work
- [ ] Temporal markers included
- [ ] Pagination correct
- [ ] Search functional

---

**Requires**: Story 5.1 (API scaffold), Story 4.5 (insight storage)
**Blocks**: Story 5.6 (UI needs API)
