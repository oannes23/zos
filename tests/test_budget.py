"""Tests for budget allocation system."""

from datetime import UTC, datetime, timedelta

import pytest

from zos.budget import (
    AllocationPlan,
    BudgetAllocator,
    CostTracker,
    LLMCallRecord,
    TokenLedger,
)
from zos.config import BudgetConfig, CategoryWeights
from zos.db import Database
from zos.exceptions import BudgetExhaustedError
from zos.salience.repository import SalienceRepository
from zos.topics.topic_key import TopicCategory, TopicKey


@pytest.fixture
def budget_config() -> BudgetConfig:
    """Default budget config for tests."""
    return BudgetConfig(
        total_tokens_per_run=100000,
        per_topic_cap=10000,
        category_weights=CategoryWeights(
            user=40, channel=40, user_in_channel=15, dyad=5, dyad_in_channel=0
        ),
    )


@pytest.fixture
def allocator(test_db: Database, budget_config: BudgetConfig) -> BudgetAllocator:
    """Create budget allocator with test database."""
    return BudgetAllocator(test_db, budget_config)


@pytest.fixture
def ledger(test_db: Database) -> TokenLedger:
    """Create token ledger with test database."""
    return TokenLedger(test_db)


@pytest.fixture
def tracker(test_db: Database) -> CostTracker:
    """Create cost tracker with test database."""
    return CostTracker(test_db)


class TestBudgetAllocator:
    """Tests for BudgetAllocator."""

    def test_empty_salience_creates_empty_plan(
        self, allocator: BudgetAllocator
    ) -> None:
        """Plan with no salience data has no allocations."""
        plan = allocator.create_allocation_plan()

        assert plan.run_id is not None
        assert plan.total_budget == 100000

        # No topics should be allocated
        for cat_alloc in plan.category_allocations.values():
            assert cat_alloc.topic_allocations == []

    def test_proportional_allocation(self, test_db: Database) -> None:
        """Topics allocated proportionally by salience."""
        # Use a higher cap so proportional allocation is visible
        config = BudgetConfig(
            total_tokens_per_run=100000,
            per_topic_cap=50000,  # High cap to avoid capping
            category_weights=CategoryWeights(
                user=40, channel=40, user_in_channel=15, dyad=5, dyad_in_channel=0
            ),
        )
        allocator = BudgetAllocator(test_db, config)

        repo = SalienceRepository(test_db)
        now = datetime.now(UTC)

        # Create salience: user:1 = 60, user:2 = 40
        repo.earn(TopicKey.user(1), 60.0, "message", now)
        repo.earn(TopicKey.user(2), 40.0, "message", now)

        plan = allocator.create_allocation_plan()

        user_alloc = plan.category_allocations[TopicCategory.USER]
        assert len(user_alloc.topic_allocations) == 2

        # Check proportions (60% and 40% of 40,000 = 24,000 and 16,000)
        allocs = {
            a.topic_key.key: a.allocated_tokens for a in user_alloc.topic_allocations
        }
        assert allocs["user:1"] == 24000
        assert allocs["user:2"] == 16000

    def test_per_topic_cap_enforced(
        self, test_db: Database, allocator: BudgetAllocator
    ) -> None:
        """Topics are capped at per_topic_cap."""
        repo = SalienceRepository(test_db)
        now = datetime.now(UTC)

        # One user with high salience should be capped
        repo.earn(TopicKey.user(1), 1000.0, "message", now)
        repo.earn(TopicKey.user(2), 1.0, "message", now)

        plan = allocator.create_allocation_plan()

        user_alloc = plan.category_allocations[TopicCategory.USER]
        allocs = {
            a.topic_key.key: a.allocated_tokens for a in user_alloc.topic_allocations
        }

        # user:1 should be capped at 10,000
        assert allocs["user:1"] == 10000

    def test_leftover_redistribution(self, test_db: Database) -> None:
        """Leftover from capped topics redistributed to uncapped."""
        # Use smaller budget to make redistribution more visible
        config = BudgetConfig(
            total_tokens_per_run=10000,
            per_topic_cap=3000,
            category_weights=CategoryWeights(
                user=100, channel=0, user_in_channel=0, dyad=0, dyad_in_channel=0
            ),
        )
        allocator = BudgetAllocator(test_db, config)

        repo = SalienceRepository(test_db)
        now = datetime.now(UTC)

        # Two users: one will cap, one won't
        repo.earn(TopicKey.user(1), 90.0, "message", now)
        repo.earn(TopicKey.user(2), 10.0, "message", now)

        plan = allocator.create_allocation_plan()

        user_alloc = plan.category_allocations[TopicCategory.USER]
        allocs = {
            a.topic_key.key: a.allocated_tokens for a in user_alloc.topic_allocations
        }

        # Raw: user:1 = 9000 (cap 3000), user:2 = 1000
        # After redistribution, user:2 gets leftover
        assert allocs["user:1"] == 3000  # Capped
        assert allocs["user:2"] == 3000  # Gets redistribution, also caps

    def test_since_filter(
        self, test_db: Database, allocator: BudgetAllocator
    ) -> None:
        """Time filter excludes old salience."""
        repo = SalienceRepository(test_db)
        old = datetime.now(UTC) - timedelta(days=10)
        recent = datetime.now(UTC) - timedelta(hours=1)
        cutoff = datetime.now(UTC) - timedelta(days=5)

        repo.earn(TopicKey.user(1), 100.0, "message", old)
        repo.earn(TopicKey.user(2), 50.0, "message", recent)

        plan = allocator.create_allocation_plan(since=cutoff)

        user_alloc = plan.category_allocations[TopicCategory.USER]
        allocs = {
            a.topic_key.key: a.allocated_tokens for a in user_alloc.topic_allocations
        }

        # Only user:2 should be allocated
        assert "user:1" not in allocs
        assert "user:2" in allocs

    def test_zero_salience_excluded(
        self, test_db: Database, allocator: BudgetAllocator
    ) -> None:
        """Topics with zero balance get no allocation."""
        repo = SalienceRepository(test_db)
        now = datetime.now(UTC)

        repo.earn(TopicKey.user(1), 100.0, "message", now)
        repo.spend(TopicKey.user(1), 100.0, "run-1", "test")  # Balance = 0
        repo.earn(TopicKey.user(2), 50.0, "message", now)

        plan = allocator.create_allocation_plan()

        user_alloc = plan.category_allocations[TopicCategory.USER]
        allocs = {
            a.topic_key.key: a.allocated_tokens for a in user_alloc.topic_allocations
        }

        assert "user:1" not in allocs
        assert "user:2" in allocs

    def test_multiple_categories(
        self, test_db: Database, allocator: BudgetAllocator
    ) -> None:
        """Different categories get different budgets."""
        repo = SalienceRepository(test_db)
        now = datetime.now(UTC)

        repo.earn(TopicKey.user(1), 100.0, "message", now)
        repo.earn(TopicKey.channel(100), 100.0, "message", now)

        plan = allocator.create_allocation_plan()

        # Both should have allocations
        user_alloc = plan.category_allocations[TopicCategory.USER]
        chan_alloc = plan.category_allocations[TopicCategory.CHANNEL]

        # Single topic in each category gets full budget (up to cap)
        assert user_alloc.topic_allocations[0].allocated_tokens == 10000  # Capped
        assert chan_alloc.topic_allocations[0].allocated_tokens == 10000  # Capped

    def test_deterministic_allocation(
        self, test_db: Database, allocator: BudgetAllocator
    ) -> None:
        """Same input produces same output."""
        repo = SalienceRepository(test_db)
        now = datetime.now(UTC)

        repo.earn(TopicKey.user(1), 50.0, "message", now)
        repo.earn(TopicKey.user(2), 30.0, "message", now)
        repo.earn(TopicKey.user(3), 20.0, "message", now)

        plan1 = allocator.create_allocation_plan(run_id="test-run-1")
        plan2 = allocator.create_allocation_plan(run_id="test-run-2")

        # Allocations should be identical (different run IDs)
        allocs1 = {
            a.topic_key.key: a.allocated_tokens
            for a in plan1.category_allocations[TopicCategory.USER].topic_allocations
        }
        allocs2 = {
            a.topic_key.key: a.allocated_tokens
            for a in plan2.category_allocations[TopicCategory.USER].topic_allocations
        }

        assert allocs1 == allocs2

    def test_allocation_plan_get_allocation(
        self, test_db: Database, allocator: BudgetAllocator
    ) -> None:
        """AllocationPlan.get_allocation returns correct value."""
        repo = SalienceRepository(test_db)
        now = datetime.now(UTC)
        repo.earn(TopicKey.user(1), 100.0, "message", now)

        plan = allocator.create_allocation_plan()

        assert plan.get_allocation(TopicKey.user(1)) > 0
        assert plan.get_allocation(TopicKey.user(999)) == 0  # Unknown topic

    def test_all_topic_allocations(
        self, test_db: Database, allocator: BudgetAllocator
    ) -> None:
        """AllocationPlan.all_topic_allocations returns flat list."""
        repo = SalienceRepository(test_db)
        now = datetime.now(UTC)
        repo.earn(TopicKey.user(1), 100.0, "message", now)
        repo.earn(TopicKey.channel(100), 100.0, "message", now)

        plan = allocator.create_allocation_plan()

        all_allocs = plan.all_topic_allocations()
        assert len(all_allocs) == 2


class TestTokenLedger:
    """Tests for TokenLedger."""

    def test_load_plan(
        self,
        test_db: Database,
        ledger: TokenLedger,
        allocator: BudgetAllocator,
    ) -> None:
        """Loading plan persists allocations."""
        repo = SalienceRepository(test_db)
        now = datetime.now(UTC)
        repo.earn(TopicKey.user(1), 100.0, "message", now)

        plan = allocator.create_allocation_plan()
        ledger.load_plan(plan)

        # Check database
        row = test_db.execute(
            "SELECT * FROM token_allocations WHERE run_id = ?",
            (plan.run_id,),
        ).fetchone()
        assert row is not None
        assert row["topic_key"] == "user:1"

    def test_get_remaining(
        self,
        test_db: Database,
        ledger: TokenLedger,
        budget_config: BudgetConfig,
    ) -> None:
        """Remaining budget decreases with spending."""
        repo = SalienceRepository(test_db)
        now = datetime.now(UTC)
        repo.earn(TopicKey.user(1), 100.0, "message", now)

        allocator = BudgetAllocator(test_db, budget_config)
        plan = allocator.create_allocation_plan()
        ledger.load_plan(plan)

        topic = TopicKey.user(1)
        initial = ledger.get_remaining(topic)

        ledger.spend(topic, 1000)

        assert ledger.get_remaining(topic) == initial - 1000

    def test_can_afford(
        self,
        test_db: Database,
        ledger: TokenLedger,
        budget_config: BudgetConfig,
    ) -> None:
        """can_afford checks remaining budget."""
        repo = SalienceRepository(test_db)
        now = datetime.now(UTC)
        repo.earn(TopicKey.user(1), 100.0, "message", now)

        allocator = BudgetAllocator(test_db, budget_config)
        plan = allocator.create_allocation_plan()
        ledger.load_plan(plan)

        topic = TopicKey.user(1)
        remaining = ledger.get_remaining(topic)

        assert ledger.can_afford(topic, remaining)
        assert ledger.can_afford(topic, remaining - 1)
        assert not ledger.can_afford(topic, remaining + 1)

    def test_spend_enforces_budget(
        self,
        test_db: Database,
        ledger: TokenLedger,
        budget_config: BudgetConfig,
    ) -> None:
        """Spending over budget raises error when enforce=True."""
        repo = SalienceRepository(test_db)
        now = datetime.now(UTC)
        repo.earn(TopicKey.user(1), 100.0, "message", now)

        allocator = BudgetAllocator(test_db, budget_config)
        plan = allocator.create_allocation_plan()
        ledger.load_plan(plan)

        topic = TopicKey.user(1)
        remaining = ledger.get_remaining(topic)

        with pytest.raises(BudgetExhaustedError):
            ledger.spend(topic, remaining + 1, enforce=True)

    def test_spend_without_enforcement(
        self,
        test_db: Database,
        ledger: TokenLedger,
        budget_config: BudgetConfig,
    ) -> None:
        """Spending over budget allowed when enforce=False."""
        repo = SalienceRepository(test_db)
        now = datetime.now(UTC)
        repo.earn(TopicKey.user(1), 100.0, "message", now)

        allocator = BudgetAllocator(test_db, budget_config)
        plan = allocator.create_allocation_plan()
        ledger.load_plan(plan)

        topic = TopicKey.user(1)
        remaining = ledger.get_remaining(topic)

        # Should not raise
        ledger.spend(topic, remaining + 1, enforce=False)

    def test_spending_summary(
        self,
        test_db: Database,
        ledger: TokenLedger,
        budget_config: BudgetConfig,
    ) -> None:
        """Spending summary shows all topics."""
        repo = SalienceRepository(test_db)
        now = datetime.now(UTC)
        repo.earn(TopicKey.user(1), 50.0, "message", now)
        repo.earn(TopicKey.user(2), 50.0, "message", now)

        allocator = BudgetAllocator(test_db, budget_config)
        plan = allocator.create_allocation_plan()
        ledger.load_plan(plan)

        ledger.spend(TopicKey.user(1), 1000)

        summary = ledger.get_spending_summary()

        assert "user:1" in summary
        assert summary["user:1"]["spent"] == 1000
        assert "user:2" in summary
        assert summary["user:2"]["spent"] == 0

    def test_get_total_remaining(
        self,
        test_db: Database,
        ledger: TokenLedger,
        budget_config: BudgetConfig,
    ) -> None:
        """Get total remaining budget across all topics."""
        repo = SalienceRepository(test_db)
        now = datetime.now(UTC)
        repo.earn(TopicKey.user(1), 50.0, "message", now)
        repo.earn(TopicKey.user(2), 50.0, "message", now)

        allocator = BudgetAllocator(test_db, budget_config)
        plan = allocator.create_allocation_plan()
        ledger.load_plan(plan)

        total_before = ledger.get_total_remaining()
        ledger.spend(TopicKey.user(1), 1000)
        total_after = ledger.get_total_remaining()

        assert total_after == total_before - 1000

    def test_no_plan_loaded(self, ledger: TokenLedger) -> None:
        """Operations without a plan loaded behave correctly."""
        topic = TopicKey.user(1)

        assert ledger.get_remaining(topic) == 0
        assert ledger.get_total_remaining() == 0
        assert not ledger.can_afford(topic, 1)
        assert ledger.get_spending_summary() == {}

        with pytest.raises(BudgetExhaustedError):
            ledger.spend(topic, 100, enforce=True)

        # Should not raise with enforce=False
        ledger.spend(topic, 100, enforce=False)


class TestCostTracker:
    """Tests for CostTracker."""

    def test_record_call(self, test_db: Database, tracker: CostTracker) -> None:
        """LLM calls are recorded to database."""
        record = LLMCallRecord(
            run_id="test-run",
            topic_key=TopicKey.user(1),
            layer="channel_digest",
            node="summarize",
            model="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
            estimated_cost_usd=0.01,
        )

        tracker.record_call(record)

        row = test_db.execute(
            "SELECT * FROM llm_calls WHERE run_id = ?",
            ("test-run",),
        ).fetchone()

        assert row["model"] == "gpt-4"
        assert row["total_tokens"] == 150

    def test_record_call_no_topic(self, test_db: Database, tracker: CostTracker) -> None:
        """LLM calls without topic_key are recorded."""
        record = LLMCallRecord(
            run_id="test-run",
            topic_key=None,
            layer="global_summary",
            node=None,
            model="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
        )

        tracker.record_call(record)

        row = test_db.execute(
            "SELECT * FROM llm_calls WHERE run_id = ?",
            ("test-run",),
        ).fetchone()

        assert row is not None
        assert row["topic_key"] is None

    def test_get_run_totals(self, test_db: Database, tracker: CostTracker) -> None:
        """Run totals aggregate all calls."""
        for i in range(3):
            tracker.record_call(
                LLMCallRecord(
                    run_id="test-run",
                    topic_key=TopicKey.user(i),
                    layer="test",
                    node=None,
                    model="gpt-4",
                    prompt_tokens=100,
                    completion_tokens=50,
                    estimated_cost_usd=0.01,
                )
            )

        totals = tracker.get_run_totals("test-run")

        assert totals["total_tokens"] == 450
        assert totals["prompt_tokens"] == 300
        assert totals["completion_tokens"] == 150

    def test_get_topic_totals(self, test_db: Database, tracker: CostTracker) -> None:
        """Topic totals aggregate calls for specific topic."""
        tracker.record_call(
            LLMCallRecord(
                run_id="test-run",
                topic_key=TopicKey.user(1),
                layer="test",
                node=None,
                model="gpt-4",
                prompt_tokens=100,
                completion_tokens=50,
            )
        )
        tracker.record_call(
            LLMCallRecord(
                run_id="test-run",
                topic_key=TopicKey.user(2),
                layer="test",
                node=None,
                model="gpt-4",
                prompt_tokens=200,
                completion_tokens=100,
            )
        )

        totals = tracker.get_topic_totals("test-run", TopicKey.user(1))

        assert totals["total_tokens"] == 150

    def test_get_calls_for_run(self, test_db: Database, tracker: CostTracker) -> None:
        """Get all calls for a run."""
        for i in range(3):
            tracker.record_call(
                LLMCallRecord(
                    run_id="test-run",
                    topic_key=TopicKey.user(i),
                    layer="test",
                    node=f"node-{i}",
                    model="gpt-4",
                    prompt_tokens=100,
                    completion_tokens=50,
                )
            )

        calls = tracker.get_calls_for_run("test-run")

        assert len(calls) == 3
        assert all(c["model"] == "gpt-4" for c in calls)

    def test_get_run_totals_empty(self, tracker: CostTracker) -> None:
        """Empty run returns zero totals."""
        totals = tracker.get_run_totals("nonexistent-run")

        assert totals["total_tokens"] == 0
        assert totals["prompt_tokens"] == 0
        assert totals["completion_tokens"] == 0


class TestLLMCallRecord:
    """Tests for LLMCallRecord data class."""

    def test_total_tokens_property(self) -> None:
        """total_tokens property computes correctly."""
        record = LLMCallRecord(
            run_id="test",
            topic_key=TopicKey.user(1),
            layer="test",
            node=None,
            model="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
        )

        assert record.total_tokens == 150
