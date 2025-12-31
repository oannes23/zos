"""Budget allocation logic."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from zos.budget.models import AllocationPlan, CategoryAllocation, TopicAllocation
from zos.config import BudgetConfig, CategoryWeights
from zos.salience.repository import SalienceRepository, TopicBalance
from zos.topics.topic_key import TopicCategory, TopicKey

if TYPE_CHECKING:
    from zos.db import Database


class BudgetAllocator:
    """Allocates token budget based on salience."""

    def __init__(
        self,
        db: Database,
        config: BudgetConfig,
    ) -> None:
        """Initialize allocator.

        Args:
            db: Database instance.
            config: Budget configuration.
        """
        self.salience_repo = SalienceRepository(db)
        self.config = config

    def create_allocation_plan(
        self,
        since: datetime | None = None,
        run_id: str | None = None,
    ) -> AllocationPlan:
        """Create a budget allocation plan.

        Args:
            since: Only consider salience earned after this time.
            run_id: Optional run ID. If None, generates UUID.

        Returns:
            AllocationPlan with token allocations.
        """
        if run_id is None:
            run_id = str(uuid.uuid4())

        total_budget = self.config.total_tokens_per_run
        per_topic_cap = self.config.per_topic_cap
        weights = self.config.category_weights

        # Step 1: Calculate budget per category
        category_budgets = self._calculate_category_budgets(total_budget, weights)

        # Step 2: For each category, allocate to topics by salience
        category_allocations: dict[TopicCategory, CategoryAllocation] = {}

        for category in TopicCategory:
            cat_budget = category_budgets.get(category, 0)
            if cat_budget == 0:
                continue

            cat_alloc = self._allocate_category(
                category=category,
                budget=cat_budget,
                per_topic_cap=per_topic_cap,
                since=since,
                weight=weights.get_weight(category),
            )
            category_allocations[category] = cat_alloc

        return AllocationPlan(
            run_id=run_id,
            total_budget=total_budget,
            per_topic_cap=per_topic_cap,
            category_allocations=category_allocations,
            created_at=datetime.now(UTC),
        )

    def _calculate_category_budgets(
        self,
        total_budget: int,
        weights: CategoryWeights,
    ) -> dict[TopicCategory, int]:
        """Divide total budget across categories by weight.

        Args:
            total_budget: Total tokens available.
            weights: Category weight configuration.

        Returns:
            Mapping of category to allocated budget.
        """
        weight_map = {
            TopicCategory.USER: weights.user,
            TopicCategory.CHANNEL: weights.channel,
            TopicCategory.USER_IN_CHANNEL: weights.user_in_channel,
            TopicCategory.DYAD: weights.dyad,
            TopicCategory.DYAD_IN_CHANNEL: weights.dyad_in_channel,
        }

        total_weight = sum(weight_map.values())
        if total_weight == 0:
            return {}

        budgets = {}
        for category, weight in weight_map.items():
            if weight > 0:
                budgets[category] = int(total_budget * weight / total_weight)

        return budgets

    def _allocate_category(
        self,
        category: TopicCategory,
        budget: int,
        per_topic_cap: int,
        since: datetime | None,
        weight: int,
    ) -> CategoryAllocation:
        """Allocate budget within a category based on salience.

        Uses proportional allocation with cap redistribution.

        Args:
            category: The topic category.
            budget: Total budget for this category.
            per_topic_cap: Maximum per topic.
            since: Time filter for salience.
            weight: The category weight from config.

        Returns:
            CategoryAllocation with topic allocations.
        """
        # Get top topics by salience (limit to reasonable number)
        top_topics = self.salience_repo.get_top_by_category(
            category=category,
            limit=100,  # Cap at 100 topics per category
            since=since,
        )

        # Filter to topics with positive balance
        topics_with_salience = [t for t in top_topics if t.balance > 0]

        if not topics_with_salience:
            return CategoryAllocation(
                category=category,
                weight=weight,
                total_tokens=budget,
                topic_allocations=[],
            )

        # Calculate total salience
        total_salience = sum(t.balance for t in topics_with_salience)

        # Allocate proportionally with cap enforcement and redistribution
        allocations = self._proportional_allocate_with_caps(
            topics=topics_with_salience,
            budget=budget,
            per_topic_cap=per_topic_cap,
            total_salience=total_salience,
        )

        return CategoryAllocation(
            category=category,
            weight=weight,
            total_tokens=budget,
            topic_allocations=allocations,
        )

    def _proportional_allocate_with_caps(
        self,
        topics: list[TopicBalance],
        budget: int,
        per_topic_cap: int,
        total_salience: float,
    ) -> list[TopicAllocation]:
        """Proportionally allocate with cap redistribution.

        Algorithm:
        1. Calculate raw proportional allocation
        2. Apply caps, track "leftover" from capped topics
        3. Redistribute leftover to uncapped topics (proportionally)
        4. Repeat until no more redistribution needed

        Args:
            topics: Topics with salience balances.
            budget: Budget to allocate.
            per_topic_cap: Per-topic maximum.
            total_salience: Sum of all salience.

        Returns:
            List of TopicAllocation objects.
        """
        # Build initial allocations - internal structure with mixed types
        allocations: dict[str, dict[str, Any]] = {}
        for topic in topics:
            proportion = topic.balance / total_salience if total_salience > 0 else 0
            raw_allocation = int(budget * proportion)
            allocations[topic.topic_key] = {
                "topic": topic,
                "proportion": proportion,
                "allocated": min(raw_allocation, per_topic_cap),
                "capped": raw_allocation > per_topic_cap,
            }

        # Redistribute leftover from capped topics
        iterations = 0
        max_iterations = 10  # Prevent infinite loops

        while iterations < max_iterations:
            iterations += 1

            total_allocated = sum(a["allocated"] for a in allocations.values())
            leftover = budget - total_allocated

            if leftover <= 0:
                break

            # Find uncapped topics
            uncapped = {k: v for k, v in allocations.items() if not v["capped"]}
            if not uncapped:
                break

            # Calculate uncapped salience total
            uncapped_salience = sum(v["topic"].balance for v in uncapped.values())
            if uncapped_salience <= 0:
                break

            # Distribute leftover proportionally to uncapped topics
            any_change = False
            for _key, alloc in uncapped.items():
                share = leftover * (alloc["topic"].balance / uncapped_salience)
                additional = int(share)
                if additional <= 0:
                    continue

                new_total = alloc["allocated"] + additional

                if new_total >= per_topic_cap:
                    alloc["allocated"] = per_topic_cap
                    alloc["capped"] = True
                    any_change = True
                else:
                    alloc["allocated"] = new_total
                    any_change = True

            # Check if we made progress
            if not any_change:
                break

        # Convert to TopicAllocation objects
        result = []
        for key, alloc in allocations.items():
            if alloc["allocated"] > 0:
                result.append(
                    TopicAllocation(
                        topic_key=TopicKey.parse(key),
                        allocated_tokens=alloc["allocated"],
                        salience_balance=alloc["topic"].balance,
                        salience_proportion=alloc["proportion"],
                    )
                )

        # Sort by allocation descending
        result.sort(key=lambda x: x.allocated_tokens, reverse=True)
        return result
