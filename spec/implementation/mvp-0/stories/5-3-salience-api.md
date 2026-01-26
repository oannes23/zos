# Story 5.3: Salience API

**Epic**: Introspection
**Status**: 🟢 Complete
**Estimated complexity**: Medium

## Goal

Implement API endpoints for querying salience balances and transaction history.

## Acceptance Criteria

- [x] GET `/salience/{topic_key}` returns balance and recent transactions
- [x] GET `/salience` lists topics by salience (top N)
- [x] GET `/salience/groups` returns budget group summaries
- [x] Transaction history queryable
- [x] Balances computed from ledger

## Technical Notes

### Endpoints

```python
# src/zos/api/salience.py
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

router = APIRouter(prefix="/salience", tags=["salience"])

class SalienceBalance(BaseModel):
    topic_key: str
    balance: float
    cap: float
    last_activity: Optional[datetime]
    budget_group: str

class SalienceTransaction(BaseModel):
    id: str
    topic_key: str
    transaction_type: str
    amount: float
    reason: Optional[str]
    source_topic: Optional[str]
    created_at: datetime

class TopicSalienceResponse(BaseModel):
    topic_key: str
    balance: float
    cap: float
    utilization: float  # balance / cap
    last_activity: Optional[datetime]
    budget_group: str
    recent_transactions: list[SalienceTransaction]

class BudgetGroupSummary(BaseModel):
    group: str
    allocation: float
    total_salience: float
    topic_count: int
    top_topics: list[SalienceBalance]

@router.get("/{topic_key:path}", response_model=TopicSalienceResponse)
async def get_topic_salience(
    topic_key: str,
    transaction_limit: int = Query(20, ge=1, le=100),
    ledger: SalienceLedger = Depends(get_ledger),
):
    """Get salience details for a specific topic."""
    balance = await ledger.get_balance(topic_key)
    cap = ledger.get_cap(topic_key)
    topic = await ledger.db.get_topic(topic_key)

    transactions = await ledger.get_history(topic_key, limit=transaction_limit)

    return TopicSalienceResponse(
        topic_key=topic_key,
        balance=balance,
        cap=cap,
        utilization=balance / cap if cap > 0 else 0,
        last_activity=topic.last_activity_at if topic else None,
        budget_group=get_budget_group(topic_key).value,
        recent_transactions=[
            SalienceTransaction(
                id=t.id,
                topic_key=t.topic_key,
                transaction_type=t.transaction_type.value,
                amount=t.amount,
                reason=t.reason,
                source_topic=t.source_topic,
                created_at=t.created_at,
            )
            for t in transactions
        ],
    )

@router.get("", response_model=list[SalienceBalance])
async def list_top_topics(
    group: Optional[str] = Query(None, description="Filter by budget group"),
    limit: int = Query(50, ge=1, le=200),
    ledger: SalienceLedger = Depends(get_ledger),
):
    """List topics by salience balance (descending)."""
    topics = await ledger.get_top_topics(group=group, limit=limit)

    return [
        SalienceBalance(
            topic_key=t.key,
            balance=t.balance,
            cap=ledger.get_cap(t.key),
            last_activity=t.last_activity_at,
            budget_group=get_budget_group(t.key).value,
        )
        for t in topics
    ]

@router.get("/groups", response_model=list[BudgetGroupSummary])
async def get_budget_groups(
    ledger: SalienceLedger = Depends(get_ledger),
    config: Config = Depends(get_config),
):
    """Get summary of each budget group."""
    groups = []

    for group in BudgetGroup:
        if group == BudgetGroup.SELF:
            allocation = config.salience.self_budget.daily_allocation
        else:
            allocation = getattr(config.salience.budget, group.value, 0)

        topics = await ledger.get_topics_by_group(group)
        balances = await ledger.get_balances([t.key for t in topics])

        total = sum(balances.values())
        top = sorted(topics, key=lambda t: balances.get(t.key, 0), reverse=True)[:5]

        groups.append(BudgetGroupSummary(
            group=group.value,
            allocation=allocation,
            total_salience=total,
            topic_count=len(topics),
            top_topics=[
                SalienceBalance(
                    topic_key=t.key,
                    balance=balances.get(t.key, 0),
                    cap=ledger.get_cap(t.key),
                    last_activity=t.last_activity_at,
                    budget_group=group.value,
                )
                for t in top
            ],
        ))

    return groups
```

### Database Queries

```python
# src/zos/salience.py

async def get_top_topics(
    self,
    group: str | None = None,
    limit: int = 50,
) -> list[TopicWithBalance]:
    """Get topics sorted by salience balance."""
    # Subquery for balances
    balance_subquery = (
        select(
            salience_ledger.c.topic_key,
            func.sum(salience_ledger.c.amount).label('balance')
        )
        .group_by(salience_ledger.c.topic_key)
        .subquery()
    )

    # Join with topics
    stmt = (
        select(topics, balance_subquery.c.balance)
        .join(balance_subquery, topics.c.key == balance_subquery.c.topic_key)
        .order_by(balance_subquery.c.balance.desc())
        .limit(limit)
    )

    if group:
        # Filter by budget group (requires category mapping)
        categories = self._group_to_categories(group)
        stmt = stmt.where(topics.c.category.in_(categories))

    rows = await self.db.fetch_all(stmt)
    return [
        TopicWithBalance(
            key=row['key'],
            category=row['category'],
            balance=row['balance'] or 0,
            last_activity_at=row['last_activity_at'],
        )
        for row in rows
    ]
```

### Transaction History Query

```python
async def get_transactions(
    self,
    topic_key: str | None = None,
    transaction_type: str | None = None,
    since: datetime | None = None,
    limit: int = 100,
) -> list[SalienceEntry]:
    """Query transaction history with filters."""
    stmt = select(salience_ledger).order_by(
        salience_ledger.c.created_at.desc()
    ).limit(limit)

    if topic_key:
        stmt = stmt.where(salience_ledger.c.topic_key == topic_key)
    if transaction_type:
        stmt = stmt.where(salience_ledger.c.transaction_type == transaction_type)
    if since:
        stmt = stmt.where(salience_ledger.c.created_at >= since)

    rows = await self.db.fetch_all(stmt)
    return [row_to_model(r, SalienceEntry) for r in rows]
```

### Example Responses

**GET /salience/server:123:user:456**
```json
{
  "topic_key": "server:123:user:456",
  "balance": 72.5,
  "cap": 100,
  "utilization": 0.725,
  "last_activity": "2026-01-23T14:30:00Z",
  "budget_group": "social",
  "recent_transactions": [
    {
      "id": "01HQABC...",
      "topic_key": "server:123:user:456",
      "transaction_type": "earn",
      "amount": 1.2,
      "reason": "message:123456789",
      "source_topic": null,
      "created_at": "2026-01-23T14:30:00Z"
    },
    {
      "id": "01HQABD...",
      "topic_key": "server:123:user:456",
      "transaction_type": "propagate",
      "amount": 0.3,
      "reason": "propagate:server:123:dyad:456:789",
      "source_topic": "server:123:dyad:456:789",
      "created_at": "2026-01-23T14:25:00Z"
    }
  ]
}
```

**GET /salience/groups**
```json
[
  {
    "group": "social",
    "allocation": 0.30,
    "total_salience": 1250.5,
    "topic_count": 45,
    "top_topics": [
      {"topic_key": "server:123:user:456", "balance": 72.5, ...},
      ...
    ]
  },
  ...
]
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/api/salience.py` | Salience endpoints |
| `src/zos/api/__init__.py` | Register router |
| `src/zos/salience.py` | Query methods |
| `tests/test_api_salience.py` | API tests |

## Test Cases

1. Topic salience returns correct balance
2. Transactions included in response
3. Top topics sorted correctly
4. Group filter works
5. Budget group summaries accurate
6. Cap and utilization calculated

## Definition of Done

- [x] All endpoints work
- [x] Balances accurate
- [x] Groups summary works
- [x] Ready for dashboard

---

**Requires**: Story 5.1, Epic 3 (salience system)
**Blocks**: Story 5.7 (UI dashboard)
