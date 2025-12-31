"""Repository for salience ledger operations."""

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from zos.topics.topic_key import TopicCategory, TopicKey

if TYPE_CHECKING:
    from zos.db import Database


@dataclass
class TopicBalance:
    """Salience balance for a topic."""

    topic_key: str
    category: str
    earned: float
    spent: float

    @property
    def balance(self) -> float:
        """Net salience balance (earned - spent)."""
        return self.earned - self.spent


class SalienceRepository:
    """Repository for salience ledger operations."""

    def __init__(self, db: "Database") -> None:
        """Initialize the repository.

        Args:
            db: Database instance for operations.
        """
        self.db = db

    def earn(
        self,
        topic_key: TopicKey,
        amount: float,
        reason: str,
        timestamp: datetime,
        message_id: int | None = None,
    ) -> None:
        """Record salience earned for a topic.

        Args:
            topic_key: The topic that earned salience.
            amount: Amount of salience earned.
            reason: Why salience was earned (message, reaction_given, etc.).
            timestamp: When the salience was earned.
            message_id: Optional source message ID.
        """
        self.db.execute(
            """
            INSERT INTO salience_earned
                (topic_key, category, timestamp, amount, reason, message_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                topic_key.key,
                topic_key.category.value,
                timestamp.isoformat(),
                amount,
                reason,
                message_id,
            ),
        )

    def earn_batch(
        self,
        entries: list[tuple[TopicKey, float, str, datetime, int | None]],
    ) -> None:
        """Batch insert salience earned entries for efficiency.

        Args:
            entries: List of (topic_key, amount, reason, timestamp, message_id) tuples.
        """
        if not entries:
            return

        self.db.executemany(
            """
            INSERT INTO salience_earned
                (topic_key, category, timestamp, amount, reason, message_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (tk.key, tk.category.value, ts.isoformat(), amt, reason, msg_id)
                for tk, amt, reason, ts, msg_id in entries
            ],
        )

    def spend(
        self,
        topic_key: TopicKey,
        amount: float,
        run_id: str,
        layer: str,
        node: str | None = None,
    ) -> None:
        """Record salience spent for a topic during a reflection run.

        Args:
            topic_key: The topic spending salience.
            amount: Amount of salience spent.
            run_id: UUID of the reflection run.
            layer: Layer that spent this salience.
            node: Optional specific node within the layer.
        """
        self.db.execute(
            """
            INSERT INTO salience_spent
                (topic_key, category, run_id, layer, node, amount)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                topic_key.key,
                topic_key.category.value,
                run_id,
                layer,
                node,
                amount,
            ),
        )

    def get_balance(self, topic_key: TopicKey) -> float:
        """Get current salience balance (earned - spent) for a topic.

        Args:
            topic_key: The topic to query.

        Returns:
            Net salience balance.
        """
        result = self.db.execute(
            """
            SELECT
                COALESCE((SELECT SUM(amount) FROM salience_earned WHERE topic_key = ?), 0) -
                COALESCE((SELECT SUM(amount) FROM salience_spent WHERE topic_key = ?), 0)
                AS balance
            """,
            (topic_key.key, topic_key.key),
        ).fetchone()
        return float(result[0]) if result else 0.0

    def get_balance_since(
        self,
        topic_key: TopicKey,
        since: datetime,
    ) -> float:
        """Get salience balance earned since a given timestamp.

        Args:
            topic_key: The topic to query.
            since: Only count entries after this timestamp.

        Returns:
            Net salience balance since the given time.
        """
        result = self.db.execute(
            """
            SELECT
                COALESCE((SELECT SUM(amount) FROM salience_earned
                          WHERE topic_key = ? AND timestamp >= ?), 0) -
                COALESCE((SELECT SUM(amount) FROM salience_spent
                          WHERE topic_key = ? AND timestamp >= ?), 0)
                AS balance
            """,
            (topic_key.key, since.isoformat(), topic_key.key, since.isoformat()),
        ).fetchone()
        return float(result[0]) if result else 0.0

    def get_top_by_category(
        self,
        category: TopicCategory,
        limit: int = 10,
        since: datetime | None = None,
    ) -> list[TopicBalance]:
        """Get top topics by salience balance within a category.

        Args:
            category: Topic category to query.
            limit: Maximum number of results.
            since: Optional time filter - only count entries after this time.

        Returns:
            List of TopicBalance objects, ordered by balance descending.
        """
        if since:
            rows = self.db.execute(
                """
                WITH earned AS (
                    SELECT topic_key, SUM(amount) as total
                    FROM salience_earned
                    WHERE category = ? AND timestamp >= ?
                    GROUP BY topic_key
                ),
                spent AS (
                    SELECT topic_key, SUM(amount) as total
                    FROM salience_spent
                    WHERE category = ? AND timestamp >= ?
                    GROUP BY topic_key
                )
                SELECT
                    e.topic_key,
                    ? as category,
                    COALESCE(e.total, 0) as earned,
                    COALESCE(s.total, 0) as spent
                FROM earned e
                LEFT JOIN spent s ON e.topic_key = s.topic_key
                ORDER BY (COALESCE(e.total, 0) - COALESCE(s.total, 0)) DESC
                LIMIT ?
                """,
                (
                    category.value,
                    since.isoformat(),
                    category.value,
                    since.isoformat(),
                    category.value,
                    limit,
                ),
            ).fetchall()
        else:
            rows = self.db.execute(
                """
                WITH earned AS (
                    SELECT topic_key, SUM(amount) as total
                    FROM salience_earned
                    WHERE category = ?
                    GROUP BY topic_key
                ),
                spent AS (
                    SELECT topic_key, SUM(amount) as total
                    FROM salience_spent
                    WHERE category = ?
                    GROUP BY topic_key
                )
                SELECT
                    e.topic_key,
                    ? as category,
                    COALESCE(e.total, 0) as earned,
                    COALESCE(s.total, 0) as spent
                FROM earned e
                LEFT JOIN spent s ON e.topic_key = s.topic_key
                ORDER BY (COALESCE(e.total, 0) - COALESCE(s.total, 0)) DESC
                LIMIT ?
                """,
                (category.value, category.value, category.value, limit),
            ).fetchall()
        return [
            TopicBalance(
                topic_key=row["topic_key"],
                category=row["category"],
                earned=float(row["earned"]),
                spent=float(row["spent"]),
            )
            for row in rows
        ]

    def get_total_earned(self, topic_key: TopicKey) -> float:
        """Get total salience earned for a topic.

        Args:
            topic_key: The topic to query.

        Returns:
            Total salience earned.
        """
        result = self.db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM salience_earned WHERE topic_key = ?",
            (topic_key.key,),
        ).fetchone()
        return float(result[0]) if result else 0.0

    def get_total_spent(self, topic_key: TopicKey) -> float:
        """Get total salience spent for a topic.

        Args:
            topic_key: The topic to query.

        Returns:
            Total salience spent.
        """
        result = self.db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM salience_spent WHERE topic_key = ?",
            (topic_key.key,),
        ).fetchone()
        return float(result[0]) if result else 0.0

    def get_total_earned_by_category(
        self,
        category: TopicCategory,
        since: datetime | None = None,
    ) -> float:
        """Get total salience earned for a category.

        Args:
            category: Topic category to query.
            since: Optional time filter.

        Returns:
            Total salience earned for the category.
        """
        if since:
            result = self.db.execute(
                "SELECT SUM(amount) FROM salience_earned WHERE category = ? AND timestamp >= ?",
                (category.value, since.isoformat()),
            ).fetchone()
        else:
            result = self.db.execute(
                "SELECT SUM(amount) FROM salience_earned WHERE category = ?",
                (category.value,),
            ).fetchone()
        return float(result[0]) if result and result[0] else 0.0
