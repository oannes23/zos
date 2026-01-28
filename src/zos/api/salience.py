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
    topic_key_original: Optional[str] = None  # Present when readable=true
    balance: float
    cap: float
    last_activity: Optional[datetime]
    budget_group: str


class SalienceTransaction(BaseModel):
    """A salience transaction entry."""

    id: str
    topic_key: str
    topic_key_original: Optional[str] = None  # Present when readable=true
    transaction_type: str
    amount: float
    reason: Optional[str]
    source_topic: Optional[str]
    source_topic_original: Optional[str] = None  # Present when readable=true
    created_at: datetime


class TopicSalienceResponse(BaseModel):
    """Full salience details for a specific topic."""

    readable: bool = False  # True when human-readable names are enabled
    topic_key: str
    topic_key_original: Optional[str] = None  # Present when readable=true
    balance: float
    cap: float
    utilization: float  # balance / cap
    last_activity: Optional[datetime]
    budget_group: str
    recent_transactions: list[SalienceTransaction]


class BudgetGroupSummary(BaseModel):
    """Summary of a budget group's salience."""

    readable: bool = False  # True when human-readable names are enabled
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
    readable: bool = Query(False, description="Replace IDs with human-readable names"),
    ledger: "SalienceLedger" = Depends(get_ledger),
    config: "Config" = Depends(get_config),
) -> list[BudgetGroupSummary]:
    """Get summary of each budget group.

    Returns allocation, total salience, topic count, and top topics for each
    budget group.
    """
    from zos.api.readable import NameResolver

    groups: list[BudgetGroupSummary] = []
    all_topic_keys: list[str] = []

    # First pass: collect all topic keys for batch resolution
    group_data: list[tuple] = []
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
            group_data.append((group, allocation, [], {}, []))
            continue

        # Get balances for all topics
        topic_keys = [t.key for t in topics_list]
        balances = await ledger.get_balances(topic_keys)
        total = sum(balances.values())

        # Sort by balance and get top 5
        sorted_topics = sorted(
            topics_list, key=lambda t: balances.get(t.key, 0), reverse=True
        )[:5]

        group_data.append((group, allocation, topics_list, balances, sorted_topics))
        all_topic_keys.extend([t.key for t in sorted_topics])

    # Resolve names if readable mode is enabled
    resolved_map: dict[str, str] = {}
    if readable and all_topic_keys:
        resolver = NameResolver(ledger.engine)
        resolved = await resolver.resolve_batch(all_topic_keys)
        resolved_map = {orig: readable_key for readable_key, orig in resolved}

    # Second pass: build responses
    for group, allocation, topics_list, balances, sorted_topics in group_data:
        if not topics_list:
            groups.append(
                BudgetGroupSummary(
                    readable=readable,
                    group=group.value,
                    allocation=allocation,
                    total_salience=0.0,
                    topic_count=0,
                    top_topics=[],
                )
            )
            continue

        total = sum(balances.values())

        top_topic_balances = [
            SalienceBalance(
                topic_key=resolved_map.get(t.key, t.key) if readable else t.key,
                topic_key_original=t.key if readable else None,
                balance=balances.get(t.key, 0),
                cap=ledger.get_cap(t.key),
                last_activity=t.last_activity_at,
                budget_group=group.value,
            )
            for t in sorted_topics
        ]

        groups.append(
            BudgetGroupSummary(
                readable=readable,
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
    readable: bool = Query(False, description="Replace IDs with human-readable names"),
    limit: int = Query(50, ge=1, le=200),
    ledger: "SalienceLedger" = Depends(get_ledger),
) -> list[SalienceBalance]:
    """List topics by salience balance (descending).

    Optionally filter by budget group (social, global, spaces, semantic, culture, self).
    """
    from zos.api.readable import NameResolver

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

    # Resolve names if readable mode is enabled
    resolved_map: dict[str, str] = {}
    if readable and topics_with_balance:
        resolver = NameResolver(ledger.engine)
        topic_keys = [t.key for t in topics_with_balance]
        resolved = await resolver.resolve_batch(topic_keys)
        resolved_map = {orig: readable_key for readable_key, orig in resolved}

    return [
        SalienceBalance(
            topic_key=resolved_map.get(t.key, t.key) if readable else t.key,
            topic_key_original=t.key if readable else None,
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
    readable: bool = Query(False, description="Replace IDs with human-readable names"),
    transaction_limit: int = Query(20, ge=1, le=100),
    ledger: "SalienceLedger" = Depends(get_ledger),
) -> TopicSalienceResponse:
    """Get salience details for a specific topic.

    Returns current balance, cap, utilization, and recent transactions.
    """
    from zos.api.readable import NameResolver

    balance = await ledger.get_balance(topic_key)
    cap = ledger.get_cap(topic_key)
    topic = await ledger.get_topic(topic_key)

    transactions = await ledger.get_history(topic_key, limit=transaction_limit)

    # Resolve names if readable mode is enabled
    readable_topic_key = topic_key
    resolved_map: dict[str, str] = {}
    if readable:
        resolver = NameResolver(ledger.engine)
        # Collect all topic keys that need resolution
        all_keys = [topic_key]
        for t in transactions:
            if t.source_topic:
                all_keys.append(t.source_topic)

        resolved = await resolver.resolve_batch(all_keys)
        resolved_map = {orig: readable_key for readable_key, orig in resolved}
        readable_topic_key = resolved_map.get(topic_key, topic_key)

    return TopicSalienceResponse(
        readable=readable,
        topic_key=readable_topic_key if readable else topic_key,
        topic_key_original=topic_key if readable else None,
        balance=balance,
        cap=cap,
        utilization=balance / cap if cap > 0 else 0,
        last_activity=topic.last_activity_at if topic else None,
        budget_group=get_budget_group(topic_key).value,
        recent_transactions=[
            SalienceTransaction(
                id=t.id,
                topic_key=resolved_map.get(t.topic_key, t.topic_key) if readable else t.topic_key,
                topic_key_original=t.topic_key if readable else None,
                transaction_type=t.transaction_type.value,
                amount=t.amount,
                reason=t.reason,
                source_topic=resolved_map.get(t.source_topic, t.source_topic) if readable and t.source_topic else t.source_topic,
                source_topic_original=t.source_topic if readable and t.source_topic else None,
                created_at=t.created_at,
            )
            for t in transactions
        ],
    )
