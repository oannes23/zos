"""Repository for insight storage operations."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from zos.insights.models import Insight
from zos.logging import get_logger

if TYPE_CHECKING:
    from zos.db import Database
    from zos.topics.topic_key import TopicKey

logger = get_logger("insights.repository")


class InsightRepository:
    """Repository for insight CRUD operations."""

    def __init__(self, db: Database) -> None:
        """Initialize the repository.

        Args:
            db: Database instance for operations.
        """
        self.db = db

    def store(
        self,
        topic_key: TopicKey,
        summary: str,
        *,
        source_refs: list[int] | None = None,
        sources_scope_max: str = "public",
        run_id: str | None = None,
        layer: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> Insight:
        """Store a new insight.

        Args:
            topic_key: The topic this insight is about.
            summary: Main insight text content.
            source_refs: List of source message IDs.
            sources_scope_max: Privacy scope ('public' or 'dm').
            run_id: UUID of the generating run.
            layer: Layer that generated this insight.
            payload: Optional structured data.

        Returns:
            The created Insight object.
        """
        insight_id = str(uuid.uuid4())
        created_at = datetime.now(UTC)
        source_refs = source_refs or []

        self.db.execute(
            """
            INSERT INTO insights
                (insight_id, topic_key, created_at, summary, payload,
                 source_refs, sources_scope_max, run_id, layer)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                insight_id,
                topic_key.key,
                created_at.isoformat(),
                summary,
                json.dumps(payload) if payload else None,
                json.dumps(source_refs),
                sources_scope_max,
                run_id,
                layer,
            ),
        )

        logger.debug(f"Stored insight {insight_id} for {topic_key.key}")

        return Insight(
            insight_id=insight_id,
            topic_key=topic_key.key,
            created_at=created_at,
            summary=summary,
            payload=payload,
            source_refs=source_refs,
            sources_scope_max=sources_scope_max,
            run_id=run_id,
            layer=layer,
        )

    def get_insight(self, insight_id: str) -> Insight | None:
        """Get a single insight by ID.

        Args:
            insight_id: The insight UUID.

        Returns:
            The Insight object, or None if not found.
        """
        row = self.db.execute(
            "SELECT * FROM insights WHERE insight_id = ?",
            (insight_id,),
        ).fetchone()

        if row is None:
            return None

        return self._row_to_insight(row)

    def get_insights(
        self,
        topic_key: TopicKey,
        *,
        limit: int = 10,
        since: datetime | None = None,
        scope: str | None = None,
        layer: str | list[str] | None = None,
    ) -> list[Insight]:
        """Get insights for a topic.

        Args:
            topic_key: The topic to query.
            limit: Maximum number of insights to return.
            since: Only return insights created after this time.
            scope: Filter by scope ('public', 'dm', or None for all).
            layer: Filter by layer name(s). Single string or list.

        Returns:
            List of Insight objects, ordered by created_at descending.
        """
        conditions = ["topic_key = ?"]
        params: list[str | int] = [topic_key.key]

        if since:
            conditions.append("created_at >= ?")
            params.append(since.isoformat())

        if scope and scope != "all":
            conditions.append("sources_scope_max = ?")
            params.append(scope)

        if layer:
            if isinstance(layer, str):
                conditions.append("layer = ?")
                params.append(layer)
            else:
                placeholders = ",".join("?" for _ in layer)
                conditions.append(f"layer IN ({placeholders})")
                params.extend(layer)

        params.append(limit)

        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT * FROM insights
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ?
        """

        rows = self.db.execute(query, tuple(params)).fetchall()
        return [self._row_to_insight(row) for row in rows]

    def get_insights_by_category(
        self,
        category: str,
        *,
        limit: int = 10,
        since: datetime | None = None,
        scope: str | None = None,
        layer: str | list[str] | None = None,
    ) -> list[Insight]:
        """Get insights for all topics in a category.

        Args:
            category: Topic category prefix (e.g., 'user', 'channel').
            limit: Maximum number of insights to return.
            since: Only return insights created after this time.
            scope: Filter by scope ('public', 'dm', or None for all).
            layer: Filter by layer name(s). Single string or list.

        Returns:
            List of Insight objects, ordered by created_at descending.
        """
        # Topic keys are formatted as "category:..." so we match the prefix
        prefix = f"{category}:"
        conditions = ["topic_key LIKE ?"]
        params: list[str | int] = [f"{prefix}%"]

        if since:
            conditions.append("created_at >= ?")
            params.append(since.isoformat())

        if scope and scope != "all":
            conditions.append("sources_scope_max = ?")
            params.append(scope)

        if layer:
            if isinstance(layer, str):
                conditions.append("layer = ?")
                params.append(layer)
            else:
                placeholders = ",".join("?" for _ in layer)
                conditions.append(f"layer IN ({placeholders})")
                params.extend(layer)

        params.append(limit)

        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT * FROM insights
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ?
        """

        rows = self.db.execute(query, tuple(params)).fetchall()
        return [self._row_to_insight(row) for row in rows]

    def get_insights_by_run(self, run_id: str) -> list[Insight]:
        """Get all insights generated by a specific run.

        Args:
            run_id: The run UUID.

        Returns:
            List of Insight objects.
        """
        rows = self.db.execute(
            """
            SELECT * FROM insights
            WHERE run_id = ?
            ORDER BY created_at DESC
            """,
            (run_id,),
        ).fetchall()
        return [self._row_to_insight(row) for row in rows]

    def count_by_topic(self, topic_key: TopicKey) -> int:
        """Count insights for a topic.

        Args:
            topic_key: The topic to query.

        Returns:
            Number of insights for this topic.
        """
        result = self.db.execute(
            "SELECT COUNT(*) FROM insights WHERE topic_key = ?",
            (topic_key.key,),
        ).fetchone()
        return int(result[0]) if result else 0

    def get_all_insights(
        self,
        *,
        limit: int = 50,
        since: datetime | None = None,
        scope: str | None = None,
    ) -> list[Insight]:
        """Get all insights with optional filters.

        Args:
            limit: Maximum number of insights to return.
            since: Only return insights created after this time.
            scope: Filter by scope ('public', 'dm', or None for all).

        Returns:
            List of Insight objects, ordered by created_at descending.
        """
        conditions: list[str] = []
        params: list[str | int] = []

        if since:
            conditions.append("created_at >= ?")
            params.append(since.isoformat())

        if scope and scope != "all":
            conditions.append("sources_scope_max = ?")
            params.append(scope)

        params.append(limit)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        query = f"""
            SELECT * FROM insights
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ?
        """

        rows = self.db.execute(query, tuple(params)).fetchall()
        return [self._row_to_insight(row) for row in rows]

    def _row_to_insight(self, row: sqlite3.Row) -> Insight:
        """Convert a database row to an Insight object.

        Args:
            row: SQLite row object.

        Returns:
            Insight object.
        """
        payload_str = row["payload"]
        payload = json.loads(payload_str) if payload_str else None

        source_refs_str = row["source_refs"]
        source_refs = json.loads(source_refs_str) if source_refs_str else []

        return Insight(
            insight_id=row["insight_id"],
            topic_key=row["topic_key"],
            created_at=datetime.fromisoformat(row["created_at"]),
            summary=row["summary"],
            payload=payload,
            source_refs=source_refs,
            sources_scope_max=row["sources_scope_max"],
            run_id=row["run_id"],
            layer=row["layer"],
        )
