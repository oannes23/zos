"""Salience API endpoints for Zos.

Provides endpoints for querying salience balances, transaction history,
and budget group summaries.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from zos.api.deps import get_config, get_ledger
from zos.salience import BudgetGroup, get_budget_group

if TYPE_CHECKING:
    from zos.config import Config
    from zos.salience import SalienceLedger

router = APIRouter(prefix="/salience", tags=["salience"])


# =============================================================================
# Response Models
# =============================================================================


class SalienceBalance(BaseModel):
    """Salience balance for a topic."""

    topic_key: str
    balance: float
    cap: float
    last_activity: Optional[datetime]
    budget_group: str


class SalienceTransaction(BaseModel):
    """A salience transaction entry."""

    id: str
    topic_key: str
    transaction_type: str
    amount: float
    reason: Optional[str]
    source_topic: Optional[str]
    created_at: datetime


class TopicSalienceResponse(BaseModel):
    """Full salience details for a specific topic."""

    topic_key: str
    balance: float
    cap: float
    utilization: float  # balance / cap
    last_activity: Optional[datetime]
    budget_group: str
    recent_transactions: list[SalienceTransaction]


class BudgetGroupSummary(BaseModel):
    """Summary of a budget group's salience."""

    group: str
    allocation: float
    total_salience: float
    topic_count: int
    top_topics: list[SalienceBalance]


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/groups", response_model=list[BudgetGroupSummary])
async def get_budget_groups(
    ledger: "SalienceLedger" = Depends(get_ledger),
    config: "Config" = Depends(get_config),
) -> list[BudgetGroupSummary]:
    """Get summary of each budget group.

    Returns allocation, total salience, topic count, and top topics for each
    budget group.
    """
    groups: list[BudgetGroupSummary] = []

    for group in BudgetGroup:
        # Get allocation from config
        if group == BudgetGroup.SELF:
            allocation = config.salience.self_budget
        else:
            allocation = getattr(config.salience.budget, group.value, 0)
            # Handle the global_group alias
            if group == BudgetGroup.GLOBAL:
                allocation = config.salience.budget.global_group

        # Get topics in this group
        topics_list = await ledger.get_topics_by_group(group)

        if not topics_list:
            groups.append(
                BudgetGroupSummary(
                    group=group.value,
                    allocation=allocation,
                    total_salience=0.0,
                    topic_count=0,
                    top_topics=[],
                )
            )
            continue

        # Get balances for all topics
        topic_keys = [t.key for t in topics_list]
        balances = await ledger.get_balances(topic_keys)

        total = sum(balances.values())

        # Sort by balance and get top 5
        sorted_topics = sorted(
            topics_list, key=lambda t: balances.get(t.key, 0), reverse=True
        )[:5]

        top_topic_balances = [
            SalienceBalance(
                topic_key=t.key,
                balance=balances.get(t.key, 0),
                cap=ledger.get_cap(t.key),
                last_activity=t.last_activity_at,
                budget_group=group.value,
            )
            for t in sorted_topics
        ]

        groups.append(
            BudgetGroupSummary(
                group=group.value,
                allocation=allocation,
                total_salience=total,
                topic_count=len(topics_list),
                top_topics=top_topic_balances,
            )
        )

    return groups


@router.get("", response_model=list[SalienceBalance])
async def list_top_topics(
    group: Optional[str] = Query(None, description="Filter by budget group"),
    limit: int = Query(50, ge=1, le=200),
    ledger: "SalienceLedger" = Depends(get_ledger),
) -> list[SalienceBalance]:
    """List topics by salience balance (descending).

    Optionally filter by budget group (social, global, spaces, semantic, culture, self).
    """
    # Validate group if provided
    group_enum: Optional[BudgetGroup] = None
    if group:
        try:
            group_enum = BudgetGroup(group)
        except ValueError:
            valid_groups = [g.value for g in BudgetGroup]
            raise HTTPException(
                status_code=400,
                detail=f"Invalid budget group: {group}. Valid groups: {valid_groups}",
            )

    topics_with_balance = await ledger.get_top_topics(group=group_enum, limit=limit)

    return [
        SalienceBalance(
            topic_key=t.key,
            balance=t.balance,
            cap=ledger.get_cap(t.key),
            last_activity=t.last_activity_at,
            budget_group=get_budget_group(t.key).value,
        )
        for t in topics_with_balance
    ]


@router.get("/{topic_key:path}", response_model=TopicSalienceResponse)
async def get_topic_salience(
    topic_key: str,
    transaction_limit: int = Query(20, ge=1, le=100),
    ledger: "SalienceLedger" = Depends(get_ledger),
) -> TopicSalienceResponse:
    """Get salience details for a specific topic.

    Returns current balance, cap, utilization, and recent transactions.
    """
    balance = await ledger.get_balance(topic_key)
    cap = ledger.get_cap(topic_key)
    topic = await ledger.get_topic(topic_key)

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
