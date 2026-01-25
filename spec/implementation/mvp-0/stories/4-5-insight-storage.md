# Story 4.5: Insight Storage

**Epic**: Reflection
**Status**: 🟢 Complete
**Estimated complexity**: Medium

## Goal

Implement insight storage and retrieval with configurable profiles and temporal formatting.

## Acceptance Criteria

- [x] Insights stored with all fields from schema
- [x] Retrieval profiles (recent, balanced, deep, comprehensive)
- [x] Retrieval returns formatted insights with temporal markers
- [x] Quarantined insights excluded from retrieval
- [x] Conflict tracking fields populated
- [x] Global topic refs computed at query time

## Technical Notes

### Insight Storage

```python
# src/zos/database.py

async def insert_insight(self, insight: Insight):
    """Insert a new insight."""
    stmt = insights_table.insert().values(**model_to_dict(insight))
    await self.execute(stmt)

async def get_insight(self, insight_id: str) -> Insight | None:
    """Get a single insight by ID."""
    stmt = select(insights_table).where(insights_table.c.id == insight_id)
    row = await self.fetch_one(stmt)
    return row_to_model(row, Insight) if row else None
```

### Retrieval with Profiles

```python
# src/zos/insights.py

@dataclass
class RetrievalProfile:
    """Configuration for insight retrieval."""
    recency_weight: float = 0.5
    strength_weight: float = 0.5
    max_age_days: int | None = None
    include_conflicting: bool = False

PROFILES = {
    'recent': RetrievalProfile(recency_weight=0.8, strength_weight=0.2),
    'balanced': RetrievalProfile(recency_weight=0.5, strength_weight=0.5),
    'deep': RetrievalProfile(recency_weight=0.3, strength_weight=0.7, max_age_days=None),
    'comprehensive': RetrievalProfile(
        recency_weight=0.5,
        strength_weight=0.5,
        include_conflicting=True,
    ),
}

class InsightRetriever:
    """Retrieves insights with configurable profiles."""

    def __init__(self, db: Database):
        self.db = db

    async def retrieve(
        self,
        topic_key: str,
        profile: str | RetrievalProfile = 'balanced',
        limit: int = 10,
    ) -> list[FormattedInsight]:
        """Retrieve insights for a topic."""
        if isinstance(profile, str):
            profile = PROFILES.get(profile, PROFILES['balanced'])

        # Split budget between recent and strong
        recent_limit = int(limit * profile.recency_weight)
        strong_limit = limit - recent_limit

        # Get most recent
        recent = await self._get_recent(
            topic_key, recent_limit, profile.max_age_days
        )

        # Get highest strength (excluding already-retrieved)
        exclude_ids = [i.id for i in recent]
        strong = await self._get_strongest(
            topic_key, strong_limit, exclude_ids, profile.max_age_days
        )

        # Combine and format
        all_insights = recent + strong
        return [self._format_insight(i) for i in all_insights]

    async def _get_recent(
        self,
        topic_key: str,
        limit: int,
        max_age_days: int | None,
    ) -> list[Insight]:
        """Get most recent insights."""
        stmt = select(insights_table).where(
            insights_table.c.topic_key == topic_key,
            insights_table.c.quarantined == False,
        ).order_by(
            insights_table.c.created_at.desc()
        ).limit(limit)

        if max_age_days:
            since = datetime.utcnow() - timedelta(days=max_age_days)
            stmt = stmt.where(insights_table.c.created_at >= since)

        rows = await self.db.fetch_all(stmt)
        return [row_to_model(r, Insight) for r in rows]

    async def _get_strongest(
        self,
        topic_key: str,
        limit: int,
        exclude_ids: list[str],
        max_age_days: int | None,
    ) -> list[Insight]:
        """Get highest strength insights."""
        stmt = select(insights_table).where(
            insights_table.c.topic_key == topic_key,
            insights_table.c.quarantined == False,
        ).order_by(
            insights_table.c.strength.desc()
        ).limit(limit)

        if exclude_ids:
            stmt = stmt.where(~insights_table.c.id.in_(exclude_ids))

        if max_age_days:
            since = datetime.utcnow() - timedelta(days=max_age_days)
            stmt = stmt.where(insights_table.c.created_at >= since)

        rows = await self.db.fetch_all(stmt)
        return [row_to_model(r, Insight) for r in rows]
```

### Temporal Formatting

```python
@dataclass
class FormattedInsight:
    """Insight formatted for display/prompt context."""
    id: str
    content: str
    temporal_marker: str
    strength: float
    confidence: float
    category: str
    created_at: datetime

def _format_insight(self, insight: Insight) -> FormattedInsight:
    """Add temporal marker and format for context."""
    age = self._relative_time(insight.created_at)
    strength_label = self._strength_label(insight.strength)

    return FormattedInsight(
        id=insight.id,
        content=insight.content,
        temporal_marker=f"{strength_label} from {age}",
        strength=insight.strength,
        confidence=insight.confidence,
        category=insight.category,
        created_at=insight.created_at,
    )

def _relative_time(self, dt: datetime) -> str:
    """Human-relative time description."""
    delta = datetime.utcnow() - dt
    if delta < timedelta(hours=1):
        return "just now"
    elif delta < timedelta(days=1):
        hours = int(delta.total_seconds() / 3600)
        return f"{hours} hours ago"
    elif delta < timedelta(days=7):
        return f"{delta.days} days ago"
    elif delta < timedelta(days=30):
        weeks = delta.days // 7
        return f"{weeks} weeks ago"
    else:
        months = delta.days // 30
        return f"{months} months ago"

def _strength_label(self, strength: float) -> str:
    """Human-readable strength description."""
    if strength >= 8:
        return "strong memory"
    elif strength >= 5:
        return "clear memory"
    elif strength >= 2:
        return "fading memory"
    else:
        return "distant memory"
```

### Global Topic Reference

```python
async def retrieve_for_global_topic(
    self,
    global_topic: str,
    profile: str = 'balanced',
    limit: int = 10,
) -> list[FormattedInsight]:
    """Retrieve insights for a global topic, including server-scoped."""
    # user:123 -> also get server:*:user:123
    # dyad:A:B -> also get server:*:dyad:A:B

    # Get global insights
    global_insights = await self.retrieve(global_topic, profile, limit // 2)

    # Get server-scoped insights
    pattern = self._get_server_pattern(global_topic)
    server_insights = await self._get_by_pattern(pattern, profile, limit // 2)

    return global_insights + server_insights

def _get_server_pattern(self, global_topic: str) -> str:
    """Convert global topic to server pattern."""
    # user:123 -> server:%:user:123
    parts = global_topic.split(':')
    return f"server:%:{':'.join(parts)}"
```

### Conflict Detection

```python
async def check_conflicts(
    self,
    new_insight: Insight,
) -> list[str]:
    """Check for potential conflicts with existing insights."""
    # Get recent insights on same topic
    recent = await self._get_recent(new_insight.topic_key, limit=10, max_age_days=30)

    conflicts = []
    for existing in recent:
        if self._may_conflict(new_insight, existing):
            conflicts.append(existing.id)

    return conflicts

def _may_conflict(self, new: Insight, existing: Insight) -> bool:
    """Simple heuristic for potential conflict."""
    # This is a placeholder - real implementation might use
    # semantic similarity or LLM-based comparison
    # For MVP, we might skip automatic detection and let
    # synthesis layer handle conflicts explicitly
    return False
```

## Database Queries

```python
async def get_insights_for_topic(
    self,
    topic_key: str,
    profile: str = 'balanced',
    limit: int = 10,
) -> list[Insight]:
    """Get insights for a topic using retrieval profile."""
    retriever = InsightRetriever(self)
    formatted = await retriever.retrieve(topic_key, profile, limit)
    # Return raw insights, not formatted (formatting in templates)
    return [await self.get_insight(f.id) for f in formatted]

async def get_insights_by_category(
    self,
    category: str,
    limit: int = 100,
    since: datetime | None = None,
) -> list[Insight]:
    """Get insights by category."""
    stmt = select(insights_table).where(
        insights_table.c.category == category,
        insights_table.c.quarantined == False,
    ).order_by(
        insights_table.c.created_at.desc()
    ).limit(limit)

    if since:
        stmt = stmt.where(insights_table.c.created_at >= since)

    rows = await self.fetch_all(stmt)
    return [row_to_model(r, Insight) for r in rows]
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/insights.py` | InsightRetriever class |
| `src/zos/database.py` | Insight queries |
| `tests/test_insights.py` | Retrieval tests |

## Test Cases

1. Insights store with all fields
2. Recent profile emphasizes recency
3. Deep profile emphasizes strength
4. Quarantined insights excluded
5. Temporal markers accurate
6. Global topic retrieves server-scoped too
7. Max age respected

## Definition of Done

- [x] All retrieval profiles work
- [x] Temporal formatting accurate
- [x] Quarantine respected
- [ ] Integrated with executor (pending Story 4.3)

---

## Design Decisions (Resolved 2026-01-23)

### Q1: Retrieval Profile Location
**Decision**: Config-defined
- Profiles defined in `config.yaml`, adjustable without code change
- Self-modification can propose config changes more easily than code changes
- Layer YAML references profiles by name; config defines their semantics

**Config example**:
```yaml
insights:
  profiles:
    recent:
      recency_weight: 0.8
      strength_weight: 0.2
    balanced:
      recency_weight: 0.5
      strength_weight: 0.5
    deep:
      recency_weight: 0.3
      strength_weight: 0.7
```

### Q2: Strength Decay
**Decision**: Decay with topic salience
- `effective_strength = stored_strength × (current_topic_salience / original_topic_salience)`
- Insights on cold topics fade naturally
- Feels like natural forgetting — memories of people you haven't thought about become dim
- Requires storing `original_topic_salience` on insight at creation time

**Schema addition**: `original_topic_salience` float field on Insight table

### Q3: Conflict Detection
**Decision**: Deferred to synthesis layer prompts (MVP bootstrap)
- For MVP, `_may_conflict` remains a placeholder returning `False`
- Conflict detection happens explicitly in synthesis layer prompts
- LLM is asked "Do any of these insights contradict each other?" during synthesis
- Automatic detection (embeddings, heuristics) is post-MVP enhancement
- Conflict threshold self-determination happens through self-reflection, not code

---

**Requires**: Stories 1.3 (schema), 1.5 (models)
**Blocks**: Story 4.3 (executor stores insights)
