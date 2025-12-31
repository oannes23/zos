"""Token ledger for tracking budget consumption."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zos.budget.models import AllocationPlan
from zos.exceptions import BudgetExhaustedError
from zos.topics.topic_key import TopicKey

if TYPE_CHECKING:
    from zos.db import Database


class TokenLedger:
    """Tracks token spending against allocation."""

    def __init__(self, db: Database) -> None:
        """Initialize ledger.

        Args:
            db: Database instance.
        """
        self.db = db
        self._plan: AllocationPlan | None = None
        self._spent: dict[str, int] = {}  # topic_key -> tokens spent

    def load_plan(self, plan: AllocationPlan) -> None:
        """Load an allocation plan and persist to database.

        Args:
            plan: The allocation plan to load.
        """
        self._plan = plan
        self._spent = {}

        # Persist to database
        for topic_alloc in plan.all_topic_allocations():
            self.db.execute(
                """
                INSERT INTO token_allocations
                    (run_id, topic_key, category, allocated_tokens, spent_tokens)
                VALUES (?, ?, ?, ?, 0)
                """,
                (
                    plan.run_id,
                    topic_alloc.topic_key.key,
                    topic_alloc.topic_key.category.value,
                    topic_alloc.allocated_tokens,
                ),
            )

    def get_remaining(self, topic_key: TopicKey) -> int:
        """Get remaining budget for a topic.

        Args:
            topic_key: The topic to check.

        Returns:
            Remaining tokens available.
        """
        if self._plan is None:
            return 0

        allocated = self._plan.get_allocation(topic_key)
        spent = self._spent.get(topic_key.key, 0)
        return max(0, allocated - spent)

    def get_total_remaining(self) -> int:
        """Get total remaining budget across all topics.

        Returns:
            Total remaining tokens.
        """
        if self._plan is None:
            return 0

        total_allocated = sum(
            a.allocated_tokens for a in self._plan.all_topic_allocations()
        )
        total_spent = sum(self._spent.values())
        return max(0, total_allocated - total_spent)

    def can_afford(self, topic_key: TopicKey, tokens: int) -> bool:
        """Check if tokens can be spent for a topic.

        Args:
            topic_key: The topic to spend from.
            tokens: Number of tokens to spend.

        Returns:
            True if budget is available.
        """
        return self.get_remaining(topic_key) >= tokens

    def spend(
        self,
        topic_key: TopicKey,
        tokens: int,
        enforce: bool = True,
    ) -> None:
        """Spend tokens from a topic's allocation.

        Args:
            topic_key: The topic to spend from.
            tokens: Number of tokens to spend.
            enforce: If True, raises BudgetExhaustedError when over budget.

        Raises:
            BudgetExhaustedError: If enforce=True and budget exceeded.
        """
        if self._plan is None:
            if enforce:
                raise BudgetExhaustedError("No allocation plan loaded")
            return

        remaining = self.get_remaining(topic_key)
        if enforce and tokens > remaining:
            raise BudgetExhaustedError(
                f"Budget exhausted for {topic_key.key}: "
                f"requested {tokens}, remaining {remaining}"
            )

        key = topic_key.key
        self._spent[key] = self._spent.get(key, 0) + tokens

        # Update database
        self.db.execute(
            """
            UPDATE token_allocations
            SET spent_tokens = ?
            WHERE run_id = ? AND topic_key = ?
            """,
            (self._spent[key], self._plan.run_id, key),
        )

    def get_spending_summary(self) -> dict[str, dict[str, int]]:
        """Get spending summary for all topics.

        Returns:
            Dict mapping topic_key to {allocated, spent, remaining}.
        """
        if self._plan is None:
            return {}

        summary = {}
        for topic_alloc in self._plan.all_topic_allocations():
            key = topic_alloc.topic_key.key
            spent = self._spent.get(key, 0)
            summary[key] = {
                "allocated": topic_alloc.allocated_tokens,
                "spent": spent,
                "remaining": topic_alloc.allocated_tokens - spent,
            }
        return summary
