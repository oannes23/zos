"""Insights endpoint."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from zos.api.dependencies import InsightRepoDep
from zos.api.models import InsightDetail, InsightSummary, PaginatedInsights
from zos.topics.topic_key import TopicKey

router = APIRouter()


@router.get("", response_model=PaginatedInsights)
async def list_insights(
    repo: InsightRepoDep,
    topic: str | None = None,
    run_id: str | None = None,
    scope: str | None = None,
    days: int | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> PaginatedInsights:
    """List insights with filters.

    Args:
        topic: Filter by topic key (e.g., "channel:123").
        run_id: Filter by run ID.
        scope: Filter by scope ("public" or "dm").
        days: Only show insights from last N days.
        offset: Number of insights to skip.
        limit: Maximum number of insights to return.
    """
    since = None
    if days:
        since = datetime.now(UTC) - timedelta(days=days)

    if topic:
        try:
            topic_key = TopicKey.parse(topic)
        except ValueError as e:
            raise HTTPException(400, f"Invalid topic key: {e}") from None
        insights = repo.get_insights(
            topic_key=topic_key,
            limit=limit,
            since=since,
            scope=scope,
        )
    elif run_id:
        insights = repo.get_insights_by_run(run_id)
        # Apply limit manually since get_insights_by_run doesn't support it
        insights = insights[:limit]
    else:
        insights = repo.get_all_insights(
            limit=limit,
            since=since,
            scope=scope,
        )

    return PaginatedInsights(
        insights=[
            InsightSummary(
                insight_id=i.insight_id,
                topic_key=i.topic_key,
                created_at=i.created_at,
                summary=i.summary[:200] + "..." if len(i.summary) > 200 else i.summary,
                sources_scope_max=i.sources_scope_max,
                run_id=i.run_id,
                layer=i.layer,
                source_count=len(i.source_refs),
            )
            for i in insights
        ],
        total=len(insights) + offset,
        offset=offset,
        limit=limit,
    )


@router.get("/{insight_id}", response_model=InsightDetail)
async def get_insight(insight_id: str, repo: InsightRepoDep) -> InsightDetail:
    """Get detailed insight information.

    Args:
        insight_id: The insight UUID.
    """
    insight = repo.get_insight(insight_id)
    if insight is None:
        raise HTTPException(404, f"Insight not found: {insight_id}")

    return InsightDetail(
        insight_id=insight.insight_id,
        topic_key=insight.topic_key,
        created_at=insight.created_at,
        summary=insight.summary,
        sources_scope_max=insight.sources_scope_max,
        run_id=insight.run_id,
        layer=insight.layer,
        source_count=len(insight.source_refs),
        payload=insight.payload,
        source_refs=insight.source_refs,
    )
