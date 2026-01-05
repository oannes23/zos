"""Salience endpoint."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from zos.api.dependencies import SalienceRepoDep
from zos.api.models import SalienceResponse
from zos.api.models import TopicBalance as TopicBalanceModel
from zos.topics.topic_key import TopicCategory

router = APIRouter()


@router.get("", response_model=SalienceResponse)
async def get_salience(
    repo: SalienceRepoDep,
    category: str = Query(..., description="Topic category (user, channel, etc.)"),
    days: int | None = None,
    limit: int = Query(50, ge=1, le=100),
) -> SalienceResponse:
    """Get salience balances for a category.

    Returns top topics by salience balance within the specified category.

    Args:
        category: Topic category (user, channel, user_in_channel, dyad, dyad_in_channel).
        days: Only count salience from last N days.
        limit: Maximum number of topics to return.
    """
    try:
        topic_category = TopicCategory(category)
    except ValueError:
        valid = [c.value for c in TopicCategory]
        raise HTTPException(
            400, f"Invalid category: {category}. Valid: {', '.join(valid)}"
        ) from None

    since = None
    if days:
        since = datetime.now(UTC) - timedelta(days=days)

    balances = repo.get_top_by_category(
        category=topic_category,
        limit=limit,
        since=since,
    )

    return SalienceResponse(
        category=category,
        topics=[
            TopicBalanceModel(
                topic_key=b.topic_key,
                category=b.category,
                earned=b.earned,
                spent=b.spent,
                balance=b.balance,
            )
            for b in balances
        ],
        total_count=len(balances),
    )
