"""Insight storage and retrieval for Zos.

This module implements insight retrieval with configurable profiles and temporal
formatting. The retrieval system models how memories work: strong memories persist
and fade with relevance, while recent memories are prioritized.

Key concepts:
- Retrieval profiles control the balance between recency and strength
- Effective strength decays with topic salience (natural forgetting)
- Quarantined insights are excluded from retrieval
- Temporal markers provide human-readable descriptions of insight age
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import and_, func, or_, select

from zos.database import generate_id, insights as insights_table, topics as topics_table
from zos.models import Insight, model_to_dict, row_to_model, utcnow

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from zos.config import Config

log = structlog.get_logger()


# =============================================================================
# Retrieval Profiles
# =============================================================================


@dataclass
class RetrievalProfile:
    """Configuration for insight retrieval.

    Profiles control how the retrieval budget is split between recent and
    high-strength insights. A higher recency_weight emphasizes what happened
    recently, while a higher strength_weight emphasizes strongly-encoded memories.

    Attributes:
        recency_weight: Weight for recent insights (0.0-1.0).
        strength_weight: Weight for strong insights (0.0-1.0).
        max_age_days: Maximum age of insights to retrieve (None = no limit).
        include_conflicting: Whether to include quarantined/conflicting insights.
    """

    recency_weight: float = 0.5
    strength_weight: float = 0.5
    max_age_days: int | None = None
    include_conflicting: bool = False


# Default profiles - these can be overridden via config
PROFILES: dict[str, RetrievalProfile] = {
    "recent": RetrievalProfile(
        recency_weight=0.8,
        strength_weight=0.2,
    ),
    "balanced": RetrievalProfile(
        recency_weight=0.5,
        strength_weight=0.5,
    ),
    "deep": RetrievalProfile(
        recency_weight=0.3,
        strength_weight=0.7,
        max_age_days=None,  # No age limit - reach deep into memory
    ),
    "comprehensive": RetrievalProfile(
        recency_weight=0.5,
        strength_weight=0.5,
        include_conflicting=True,  # Include conflicting insights for synthesis
    ),
}


# =============================================================================
# Formatted Insight
# =============================================================================


@dataclass
class FormattedInsight:
    """Insight formatted for display/prompt context.

    Includes temporal markers that describe when and how strongly the insight
    is held. These markers help the model understand the temporal nature of
    its own memories.

    Attributes:
        id: Unique insight identifier.
        content: The insight content itself.
        temporal_marker: Human-readable description like "strong memory from 3 days ago".
        strength: The insight's base strength value.
        effective_strength: Strength adjusted for topic salience decay.
        confidence: Model's confidence in the insight.
        category: Layer category that produced this insight.
        created_at: When the insight was created.
    """

    id: str
    content: str
    temporal_marker: str
    strength: float
    effective_strength: float
    confidence: float
    category: str
    created_at: datetime


# =============================================================================
# Insight Retriever
# =============================================================================


def _ensure_utc(dt: datetime | None) -> datetime | None:
    """Ensure a datetime is timezone-aware (UTC).

    SQLite stores datetimes as naive. This helper adds UTC timezone info
    if the datetime is naive.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class InsightRetriever:
    """Retrieves insights with configurable profiles.

    The retriever implements a two-part retrieval strategy:
    1. Get the most recent insights (recency matters for context)
    2. Get the strongest insights (strength indicates importance)

    The budget is split between these two strategies based on the profile
    weights. This models how human memory works: we recall both recent events
    and strongly-encoded long-term memories.
    """

    def __init__(self, engine: "Engine", config: "Config") -> None:
        """Initialize the insight retriever.

        Args:
            engine: SQLAlchemy database engine.
            config: Application configuration.
        """
        self.engine = engine
        self.config = config

    async def retrieve(
        self,
        topic_key: str,
        profile: str | RetrievalProfile = "balanced",
        limit: int = 10,
    ) -> list[FormattedInsight]:
        """Retrieve insights for a topic.

        Splits the retrieval budget between recent and strong insights
        based on the profile weights. Returns formatted insights with
        temporal markers.

        Args:
            topic_key: The topic to retrieve insights for.
            profile: Profile name (string) or RetrievalProfile instance.
            limit: Maximum number of insights to retrieve.

        Returns:
            List of FormattedInsight, ordered by relevance.
        """
        if isinstance(profile, str):
            profile = PROFILES.get(profile, PROFILES["balanced"])

        # Split budget between recent and strong
        recent_limit = int(limit * profile.recency_weight)
        strong_limit = limit - recent_limit

        # Ensure at least 1 for each if limit >= 2
        if limit >= 2:
            recent_limit = max(1, recent_limit)
            strong_limit = max(1, strong_limit)

        # Get most recent
        recent = await self._get_recent(
            topic_key,
            recent_limit,
            profile.max_age_days,
            profile.include_conflicting,
        )

        # Get highest strength (excluding already-retrieved)
        exclude_ids = [i.id for i in recent]
        strong = await self._get_strongest(
            topic_key,
            strong_limit,
            exclude_ids,
            profile.max_age_days,
            profile.include_conflicting,
        )

        # Combine and format
        all_insights = recent + strong

        # Get current topic salience for effective strength calculation
        current_salience = await self._get_current_salience(topic_key)

        return [
            await self._format_insight(i, current_salience)
            for i in all_insights
        ]

    async def _get_recent(
        self,
        topic_key: str,
        limit: int,
        max_age_days: int | None,
        include_conflicting: bool = False,
    ) -> list[Insight]:
        """Get most recent insights.

        Args:
            topic_key: The topic to query.
            limit: Maximum number of insights.
            max_age_days: Maximum age in days (None = no limit).
            include_conflicting: Whether to include quarantined insights.

        Returns:
            List of Insight models, ordered by recency.
        """
        if limit <= 0:
            return []

        with self.engine.connect() as conn:
            conditions = [insights_table.c.topic_key == topic_key]

            if not include_conflicting:
                conditions.append(insights_table.c.quarantined == False)

            if max_age_days:
                since = utcnow() - timedelta(days=max_age_days)
                conditions.append(insights_table.c.created_at >= since)

            stmt = (
                select(insights_table)
                .where(and_(*conditions))
                .order_by(insights_table.c.created_at.desc())
                .limit(limit)
            )

            rows = conn.execute(stmt).fetchall()
            return [self._row_to_insight(r) for r in rows]

    async def _get_strongest(
        self,
        topic_key: str,
        limit: int,
        exclude_ids: list[str],
        max_age_days: int | None,
        include_conflicting: bool = False,
    ) -> list[Insight]:
        """Get highest strength insights.

        Args:
            topic_key: The topic to query.
            limit: Maximum number of insights.
            exclude_ids: IDs of insights already retrieved.
            max_age_days: Maximum age in days (None = no limit).
            include_conflicting: Whether to include quarantined insights.

        Returns:
            List of Insight models, ordered by strength.
        """
        if limit <= 0:
            return []

        with self.engine.connect() as conn:
            conditions = [insights_table.c.topic_key == topic_key]

            if not include_conflicting:
                conditions.append(insights_table.c.quarantined == False)

            if exclude_ids:
                conditions.append(~insights_table.c.id.in_(exclude_ids))

            if max_age_days:
                since = utcnow() - timedelta(days=max_age_days)
                conditions.append(insights_table.c.created_at >= since)

            stmt = (
                select(insights_table)
                .where(and_(*conditions))
                .order_by(insights_table.c.strength.desc())
                .limit(limit)
            )

            rows = conn.execute(stmt).fetchall()
            return [self._row_to_insight(r) for r in rows]

    async def _format_insight(
        self,
        insight: Insight,
        current_salience: float,
    ) -> FormattedInsight:
        """Add temporal marker and format for context.

        Computes effective strength based on topic salience decay:
        effective = stored * (current_salience / original_salience)

        Args:
            insight: The insight to format.
            current_salience: Current salience of the topic.

        Returns:
            FormattedInsight with temporal context.
        """
        age = self._relative_time(insight.created_at)
        strength_label = self._strength_label(insight.strength)

        # Compute effective strength with salience decay
        original_salience = insight.original_topic_salience
        if original_salience > 0 and current_salience >= 0:
            ratio = min(1.0, current_salience / original_salience)
            effective_strength = insight.strength * ratio
        else:
            effective_strength = insight.strength

        return FormattedInsight(
            id=insight.id,
            content=insight.content,
            temporal_marker=f"{strength_label} from {age}",
            strength=insight.strength,
            effective_strength=effective_strength,
            confidence=insight.confidence,
            category=insight.category,
            created_at=insight.created_at,
        )

    def _relative_time(self, dt: datetime) -> str:
        """Human-relative time description.

        Args:
            dt: Datetime to describe.

        Returns:
            Human-readable relative time string.
        """
        # Ensure dt is timezone-aware
        dt = _ensure_utc(dt)
        if dt is None:
            return "unknown time"

        now = utcnow()
        delta = now - dt

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
        """Human-readable strength description.

        Maps numeric strength values to phenomenological descriptions
        that convey how "strongly held" a memory is.

        Args:
            strength: The strength value.

        Returns:
            Human-readable description.
        """
        if strength >= 8:
            return "strong memory"
        elif strength >= 5:
            return "clear memory"
        elif strength >= 2:
            return "fading memory"
        else:
            return "distant memory"

    async def check_conflicts(self, new_insight: Insight) -> list[str]:
        """Check for potential conflicts with existing insights.

        Note: For MVP, this is a placeholder that returns an empty list.
        Real conflict detection happens in synthesis layer prompts where
        the LLM is asked to identify contradictions.

        Args:
            new_insight: The new insight to check.

        Returns:
            List of conflicting insight IDs (empty for MVP).
        """
        # MVP placeholder: conflict detection is handled in synthesis prompts
        # Future: could use embeddings or semantic similarity
        return []

    async def _get_current_salience(self, topic_key: str) -> float:
        """Get current salience balance for a topic.

        Args:
            topic_key: The topic to query.

        Returns:
            Current salience balance.
        """
        from zos.database import salience_ledger

        with self.engine.connect() as conn:
            result = conn.execute(
                select(func.coalesce(func.sum(salience_ledger.c.amount), 0.0)).where(
                    salience_ledger.c.topic_key == topic_key
                )
            )
            return float(result.scalar() or 0.0)

    def _row_to_insight(self, row) -> Insight:
        """Convert a database row to an Insight model.

        Args:
            row: SQLAlchemy row result.

        Returns:
            Insight model instance.
        """
        return Insight(
            id=row.id,
            topic_key=row.topic_key,
            category=row.category,
            content=row.content,
            sources_scope_max=row.sources_scope_max,
            created_at=_ensure_utc(row.created_at),
            layer_run_id=row.layer_run_id,
            supersedes=row.supersedes,
            quarantined=row.quarantined,
            salience_spent=row.salience_spent,
            strength_adjustment=row.strength_adjustment,
            strength=row.strength,
            original_topic_salience=row.original_topic_salience,
            confidence=row.confidence,
            importance=row.importance,
            novelty=row.novelty,
            valence_joy=row.valence_joy,
            valence_concern=row.valence_concern,
            valence_curiosity=row.valence_curiosity,
            valence_warmth=row.valence_warmth,
            valence_tension=row.valence_tension,
            # Expanded valence dimensions
            valence_awe=row.valence_awe,
            valence_grief=row.valence_grief,
            valence_longing=row.valence_longing,
            valence_peace=row.valence_peace,
            valence_gratitude=row.valence_gratitude,
            # Prospective curiosity
            open_questions=row.open_questions,
            context_channel=row.context_channel,
            context_thread=row.context_thread,
            subject=row.subject,
            participants=row.participants,
            conflicts_with=row.conflicts_with,
            conflict_resolved=row.conflict_resolved,
            synthesis_source_ids=row.synthesis_source_ids,
        )

    # =========================================================================
    # Global Topic Reference
    # =========================================================================

    async def retrieve_for_global_topic(
        self,
        global_topic: str,
        profile: str = "balanced",
        limit: int = 10,
    ) -> list[FormattedInsight]:
        """Retrieve insights for a global topic, including server-scoped.

        Global topics (like user:123) may have insights at both the global
        level and in server-scoped versions (server:A:user:123). This method
        retrieves from both.

        Args:
            global_topic: The global topic key.
            profile: Retrieval profile name.
            limit: Maximum total insights.

        Returns:
            Combined list of insights from global and server-scoped topics.
        """
        # Get global insights
        global_limit = limit // 2
        server_limit = limit - global_limit

        global_insights = await self.retrieve(global_topic, profile, global_limit)

        # Get server-scoped insights
        pattern = self._get_server_pattern(global_topic)
        server_insights = await self._get_by_pattern(pattern, profile, server_limit)

        return global_insights + server_insights

    def _get_server_pattern(self, global_topic: str) -> str:
        """Convert global topic to server pattern.

        Args:
            global_topic: A global topic key.

        Returns:
            SQL LIKE pattern for server-scoped versions.
        """
        # user:123 -> server:%:user:123
        parts = global_topic.split(":")
        return f"server:%:{':'.join(parts)}"

    async def _get_by_pattern(
        self,
        pattern: str,
        profile: str | RetrievalProfile,
        limit: int,
    ) -> list[FormattedInsight]:
        """Retrieve insights matching a topic pattern.

        Args:
            pattern: SQL LIKE pattern for topic keys.
            profile: Retrieval profile.
            limit: Maximum insights.

        Returns:
            List of formatted insights.
        """
        if isinstance(profile, str):
            profile = PROFILES.get(profile, PROFILES["balanced"])

        with self.engine.connect() as conn:
            conditions = [insights_table.c.topic_key.like(pattern)]

            if not profile.include_conflicting:
                conditions.append(insights_table.c.quarantined == False)

            if profile.max_age_days:
                since = utcnow() - timedelta(days=profile.max_age_days)
                conditions.append(insights_table.c.created_at >= since)

            stmt = (
                select(insights_table)
                .where(and_(*conditions))
                .order_by(
                    # Balance recency and strength
                    insights_table.c.strength.desc(),
                    insights_table.c.created_at.desc(),
                )
                .limit(limit)
            )

            rows = conn.execute(stmt).fetchall()

            # Format with effective strength
            formatted = []
            for row in rows:
                insight = self._row_to_insight(row)
                current_salience = await self._get_current_salience(insight.topic_key)
                formatted.append(await self._format_insight(insight, current_salience))

            return formatted

    async def retrieve_cross_topic(
        self,
        categories: list[str] | None = None,
        since_days: int | None = None,
        limit: int = 50,
    ) -> list[FormattedInsight]:
        """Retrieve insights across all topics.

        Used by self-reflection to gather experiences from all reflection
        layers. Filters by category and time window, returns formatted
        insights with topic_key preserved for grouping.

        Args:
            categories: Optional list of insight categories to include.
            since_days: Only return insights from the last N days.
            limit: Maximum number of insights to return.

        Returns:
            List of FormattedInsight, ordered by created_at descending.
        """
        with self.engine.connect() as conn:
            conditions = [insights_table.c.quarantined == False]

            if categories:
                conditions.append(insights_table.c.category.in_(categories))

            if since_days is not None:
                since = utcnow() - timedelta(days=since_days)
                conditions.append(insights_table.c.created_at >= since)

            stmt = (
                select(insights_table)
                .where(and_(*conditions))
                .order_by(insights_table.c.created_at.desc())
                .limit(limit)
            )

            rows = conn.execute(stmt).fetchall()

            formatted = []
            for row in rows:
                insight = self._row_to_insight(row)
                current_salience = await self._get_current_salience(
                    insight.topic_key
                )
                fi = await self._format_insight(insight, current_salience)
                # Attach topic_key for cross-topic grouping in templates
                fi.topic_key = insight.topic_key  # type: ignore[attr-defined]
                formatted.append(fi)

            return formatted


# =============================================================================
# Database Operations
# =============================================================================


def _insight_to_db_dict(insight: Insight) -> dict:
    """Convert Insight model to dictionary suitable for database insert.

    Handles enum serialization. JSON fields are passed through as-is since
    SQLAlchemy's JSON column type handles serialization.

    Args:
        insight: The insight model.

    Returns:
        Dictionary with properly serialized values.
    """
    data = {
        "id": insight.id,
        "topic_key": insight.topic_key,
        "category": insight.category,
        "content": insight.content,
        "sources_scope_max": insight.sources_scope_max.value,  # Enum to string
        "created_at": insight.created_at,
        "layer_run_id": insight.layer_run_id,
        "supersedes": insight.supersedes,
        "quarantined": insight.quarantined,
        "salience_spent": insight.salience_spent,
        "strength_adjustment": insight.strength_adjustment,
        "strength": insight.strength,
        "original_topic_salience": insight.original_topic_salience,
        "confidence": insight.confidence,
        "importance": insight.importance,
        "novelty": insight.novelty,
        "valence_joy": insight.valence_joy,
        "valence_concern": insight.valence_concern,
        "valence_curiosity": insight.valence_curiosity,
        "valence_warmth": insight.valence_warmth,
        "valence_tension": insight.valence_tension,
        # Expanded valence dimensions
        "valence_awe": insight.valence_awe,
        "valence_grief": insight.valence_grief,
        "valence_longing": insight.valence_longing,
        "valence_peace": insight.valence_peace,
        "valence_gratitude": insight.valence_gratitude,
        # Prospective curiosity
        "open_questions": insight.open_questions,
        "context_channel": insight.context_channel,
        "context_thread": insight.context_thread,
        "subject": insight.subject,
        # JSON columns handle serialization automatically
        "participants": insight.participants,
        "conflicts_with": insight.conflicts_with,
        "conflict_resolved": insight.conflict_resolved,
        "synthesis_source_ids": insight.synthesis_source_ids,
    }
    return data


async def insert_insight(engine: "Engine", insight: Insight) -> None:
    """Insert a new insight into the database.

    Args:
        engine: SQLAlchemy database engine.
        insight: The insight to insert.
    """
    with engine.connect() as conn:
        stmt = insights_table.insert().values(**_insight_to_db_dict(insight))
        conn.execute(stmt)
        conn.commit()

    log.info(
        "insight_inserted",
        insight_id=insight.id,
        topic=insight.topic_key,
        category=insight.category,
        strength=insight.strength,
    )


async def get_insight(engine: "Engine", insight_id: str) -> Insight | None:
    """Get a single insight by ID.

    Args:
        engine: SQLAlchemy database engine.
        insight_id: The insight ID to retrieve.

    Returns:
        The Insight if found, None otherwise.
    """
    with engine.connect() as conn:
        stmt = select(insights_table).where(insights_table.c.id == insight_id)
        row = conn.execute(stmt).fetchone()

        if row is None:
            return None

        return _row_to_insight_static(row)


async def get_insights_for_topic(
    engine: "Engine",
    config: "Config",
    topic_key: str,
    profile: str = "balanced",
    limit: int = 10,
) -> list[Insight]:
    """Get insights for a topic using retrieval profile.

    This is a convenience function that returns raw Insight models
    rather than formatted insights.

    Args:
        engine: SQLAlchemy database engine.
        config: Application configuration.
        topic_key: The topic to query.
        profile: Retrieval profile name.
        limit: Maximum insights.

    Returns:
        List of Insight models.
    """
    retriever = InsightRetriever(engine, config)
    formatted = await retriever.retrieve(topic_key, profile, limit)

    # Return raw insights
    insights = []
    for f in formatted:
        insight = await get_insight(engine, f.id)
        if insight:
            insights.append(insight)

    return insights


async def get_insights_by_category(
    engine: "Engine",
    category: str,
    limit: int = 100,
    since: datetime | None = None,
) -> list[Insight]:
    """Get insights by category.

    Args:
        engine: SQLAlchemy database engine.
        category: The insight category (e.g., "user_reflection").
        limit: Maximum insights.
        since: Only return insights created after this time.

    Returns:
        List of Insight models.
    """
    with engine.connect() as conn:
        conditions = [
            insights_table.c.category == category,
            insights_table.c.quarantined == False,
        ]

        if since:
            conditions.append(insights_table.c.created_at >= since)

        stmt = (
            select(insights_table)
            .where(and_(*conditions))
            .order_by(insights_table.c.created_at.desc())
            .limit(limit)
        )

        rows = conn.execute(stmt).fetchall()
        return [_row_to_insight_static(r) for r in rows]


def _row_to_insight_static(row) -> Insight:
    """Convert a database row to an Insight model (static version).

    Args:
        row: SQLAlchemy row result.

    Returns:
        Insight model instance.
    """
    return Insight(
        id=row.id,
        topic_key=row.topic_key,
        category=row.category,
        content=row.content,
        sources_scope_max=row.sources_scope_max,
        created_at=_ensure_utc(row.created_at),
        layer_run_id=row.layer_run_id,
        supersedes=row.supersedes,
        quarantined=row.quarantined,
        salience_spent=row.salience_spent,
        strength_adjustment=row.strength_adjustment,
        strength=row.strength,
        original_topic_salience=row.original_topic_salience,
        confidence=row.confidence,
        importance=row.importance,
        novelty=row.novelty,
        valence_joy=row.valence_joy,
        valence_concern=row.valence_concern,
        valence_curiosity=row.valence_curiosity,
        valence_warmth=row.valence_warmth,
        valence_tension=row.valence_tension,
        # Expanded valence dimensions
        valence_awe=row.valence_awe,
        valence_grief=row.valence_grief,
        valence_longing=row.valence_longing,
        valence_peace=row.valence_peace,
        valence_gratitude=row.valence_gratitude,
        # Prospective curiosity
        open_questions=row.open_questions,
        context_channel=row.context_channel,
        context_thread=row.context_thread,
        subject=row.subject,
        participants=row.participants,
        conflicts_with=row.conflicts_with,
        conflict_resolved=row.conflict_resolved,
        synthesis_source_ids=row.synthesis_source_ids,
    )
