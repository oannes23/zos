"""Budget allocation data models."""

from dataclasses import dataclass, field
from datetime import datetime

from zos.topics.topic_key import TopicCategory, TopicKey


@dataclass(frozen=True)
class TopicAllocation:
    """Token allocation for a single topic."""

    topic_key: TopicKey
    allocated_tokens: int
    salience_balance: float  # For reference/debugging
    salience_proportion: float  # Within category (0-1)


@dataclass
class CategoryAllocation:
    """Token allocation for a category."""

    category: TopicCategory
    weight: int  # From config (e.g., 40)
    total_tokens: int  # Budget for this category
    topic_allocations: list[TopicAllocation] = field(default_factory=list)

    @property
    def allocated_tokens(self) -> int:
        """Sum of all topic allocations."""
        return sum(a.allocated_tokens for a in self.topic_allocations)


@dataclass
class AllocationPlan:
    """Complete budget allocation plan for a run."""

    run_id: str
    total_budget: int
    per_topic_cap: int
    category_allocations: dict[TopicCategory, CategoryAllocation]
    created_at: datetime

    def get_allocation(self, topic_key: TopicKey) -> int:
        """Get allocated tokens for a topic.

        Args:
            topic_key: The topic to look up.

        Returns:
            Allocated tokens, or 0 if not found.
        """
        cat_alloc = self.category_allocations.get(topic_key.category)
        if not cat_alloc:
            return 0
        for topic_alloc in cat_alloc.topic_allocations:
            if topic_alloc.topic_key == topic_key:
                return topic_alloc.allocated_tokens
        return 0

    def all_topic_allocations(self) -> list[TopicAllocation]:
        """Get flat list of all topic allocations.

        Returns:
            List of all TopicAllocation objects across categories.
        """
        result = []
        for cat_alloc in self.category_allocations.values():
            result.extend(cat_alloc.topic_allocations)
        return result


@dataclass
class LLMCallRecord:
    """Record of a single LLM call."""

    run_id: str
    topic_key: TopicKey | None
    layer: str
    node: str | None
    model: str
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float | None = None

    @property
    def total_tokens(self) -> int:
        """Total tokens used (prompt + completion)."""
        return self.prompt_tokens + self.completion_tokens
