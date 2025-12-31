"""LLM call cost tracking."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from zos.budget.models import LLMCallRecord
from zos.topics.topic_key import TopicKey

if TYPE_CHECKING:
    from zos.db import Database


class CostTracker:
    """Records and aggregates LLM call costs."""

    def __init__(self, db: Database) -> None:
        """Initialize tracker.

        Args:
            db: Database instance.
        """
        self.db = db

    def record_call(self, record: LLMCallRecord) -> None:
        """Record an LLM call.

        Args:
            record: The LLM call record.
        """
        self.db.execute(
            """
            INSERT INTO llm_calls
                (run_id, topic_key, layer, node, model,
                 prompt_tokens, completion_tokens, total_tokens,
                 estimated_cost_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.run_id,
                record.topic_key.key if record.topic_key else None,
                record.layer,
                record.node,
                record.model,
                record.prompt_tokens,
                record.completion_tokens,
                record.total_tokens,
                record.estimated_cost_usd,
            ),
        )

    def get_run_totals(self, run_id: str) -> dict[str, Any]:
        """Get total tokens and cost for a run.

        Args:
            run_id: The run to query.

        Returns:
            Dict with total_tokens, prompt_tokens, completion_tokens, estimated_cost_usd.
        """
        result = self.db.execute(
            """
            SELECT
                COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                COALESCE(SUM(total_tokens), 0) as total_tokens,
                SUM(estimated_cost_usd) as estimated_cost_usd
            FROM llm_calls
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()

        return {
            "prompt_tokens": result["prompt_tokens"],
            "completion_tokens": result["completion_tokens"],
            "total_tokens": result["total_tokens"],
            "estimated_cost_usd": result["estimated_cost_usd"],
        }

    def get_topic_totals(self, run_id: str, topic_key: TopicKey) -> dict[str, Any]:
        """Get total tokens for a specific topic in a run.

        Args:
            run_id: The run to query.
            topic_key: The topic to query.

        Returns:
            Dict with token totals.
        """
        result = self.db.execute(
            """
            SELECT
                COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                COALESCE(SUM(total_tokens), 0) as total_tokens,
                SUM(estimated_cost_usd) as estimated_cost_usd
            FROM llm_calls
            WHERE run_id = ? AND topic_key = ?
            """,
            (run_id, topic_key.key),
        ).fetchone()

        return {
            "prompt_tokens": result["prompt_tokens"],
            "completion_tokens": result["completion_tokens"],
            "total_tokens": result["total_tokens"],
            "estimated_cost_usd": result["estimated_cost_usd"],
        }

    def get_calls_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """Get all LLM calls for a run.

        Args:
            run_id: The run to query.

        Returns:
            List of call records as dicts.
        """
        rows = self.db.execute(
            """
            SELECT * FROM llm_calls
            WHERE run_id = ?
            ORDER BY created_at ASC
            """,
            (run_id,),
        ).fetchall()

        return [dict(row) for row in rows]
