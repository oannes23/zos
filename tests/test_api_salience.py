"""Tests for Salience API endpoints.

Tests the salience API including topic salience queries, top topics listing,
and budget group summaries.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from zos.api import create_app
from zos.config import Config
from zos.database import create_tables, get_engine
from zos.migrations import migrate
from zos.salience import BudgetGroup, SalienceLedger


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def test_config(tmp_path: Path) -> Config:
    """Create a test configuration with temp database."""
    return Config(
        data_dir=tmp_path,
        log_level="DEBUG",
    )


@pytest.fixture
def engine(test_config: Config):
    """Create a test database engine with migrations applied."""
    eng = get_engine(test_config)
    migrate(eng)
    create_tables(eng)
    return eng


@pytest.fixture
def ledger(engine, test_config: Config) -> SalienceLedger:
    """Create a SalienceLedger instance for testing."""
    return SalienceLedger(engine, test_config)


@pytest.fixture
def app(test_config: Config, engine, ledger: SalienceLedger):
    """Create a test FastAPI application."""
    application = create_app(test_config)
    application.state.config = test_config
    application.state.db = engine
    application.state.ledger = ledger
    return application


@pytest.fixture
def client(app) -> TestClient:
    """Create a test client for the API."""
    return TestClient(app)


# =============================================================================
# Test: GET /salience/{topic_key}
# =============================================================================


class TestGetTopicSalience:
    """Tests for: GET /salience/{topic_key} returns balance and transactions."""

    @pytest.mark.asyncio
    async def test_returns_correct_balance(
        self, client: TestClient, ledger: SalienceLedger
    ) -> None:
        """Topic salience should return correct balance."""
        topic_key = "server:123:user:456"
        await ledger.earn(topic_key, 25.0, reason="test_message")

        response = client.get(f"/salience/{topic_key}")

        assert response.status_code == 200
        data = response.json()
        assert data["topic_key"] == topic_key
        assert data["balance"] == 25.0

    @pytest.mark.asyncio
    async def test_returns_cap_and_utilization(
        self, client: TestClient, ledger: SalienceLedger
    ) -> None:
        """Topic salience should return cap and utilization."""
        topic_key = "server:123:user:456"
        await ledger.earn(topic_key, 50.0)

        response = client.get(f"/salience/{topic_key}")

        assert response.status_code == 200
        data = response.json()
        assert data["cap"] == 100  # Default server_user cap
        assert data["utilization"] == 0.5  # 50/100

    @pytest.mark.asyncio
    async def test_includes_recent_transactions(
        self, client: TestClient, ledger: SalienceLedger
    ) -> None:
        """Topic salience should include recent transactions."""
        topic_key = "server:123:user:456"
        await ledger.earn(topic_key, 10.0, reason="message_1")
        await ledger.earn(topic_key, 5.0, reason="message_2")

        response = client.get(f"/salience/{topic_key}")

        assert response.status_code == 200
        data = response.json()
        assert len(data["recent_transactions"]) == 2
        # Most recent first
        assert data["recent_transactions"][0]["reason"] == "message_2"
        assert data["recent_transactions"][1]["reason"] == "message_1"

    @pytest.mark.asyncio
    async def test_transaction_limit_parameter(
        self, client: TestClient, ledger: SalienceLedger
    ) -> None:
        """Transaction limit parameter should work."""
        topic_key = "server:123:user:456"
        for i in range(10):
            await ledger.earn(topic_key, 1.0, reason=f"message_{i}")

        response = client.get(f"/salience/{topic_key}?transaction_limit=3")

        assert response.status_code == 200
        data = response.json()
        assert len(data["recent_transactions"]) == 3

    @pytest.mark.asyncio
    async def test_returns_budget_group(
        self, client: TestClient, ledger: SalienceLedger
    ) -> None:
        """Topic salience should return budget group."""
        topic_key = "server:123:user:456"
        await ledger.earn(topic_key, 10.0)

        response = client.get(f"/salience/{topic_key}")

        assert response.status_code == 200
        data = response.json()
        assert data["budget_group"] == "social"

    @pytest.mark.asyncio
    async def test_nonexistent_topic_returns_zero_balance(
        self, client: TestClient
    ) -> None:
        """Nonexistent topic should return zero balance."""
        topic_key = "server:123:user:nonexistent"

        response = client.get(f"/salience/{topic_key}")

        assert response.status_code == 200
        data = response.json()
        assert data["balance"] == 0.0
        assert data["recent_transactions"] == []

    @pytest.mark.asyncio
    async def test_topic_key_with_colons_works(
        self, client: TestClient, ledger: SalienceLedger
    ) -> None:
        """Topic key with colons should work (path parameter)."""
        topic_key = "server:123:dyad:456:789"
        await ledger.earn(topic_key, 15.0)

        response = client.get(f"/salience/{topic_key}")

        assert response.status_code == 200
        data = response.json()
        assert data["topic_key"] == topic_key
        assert data["balance"] == 15.0
        assert data["budget_group"] == "social"


# =============================================================================
# Test: GET /salience
# =============================================================================


class TestListTopTopics:
    """Tests for: GET /salience lists topics by salience."""

    @pytest.mark.asyncio
    async def test_returns_topics_sorted_by_balance(
        self, client: TestClient, ledger: SalienceLedger
    ) -> None:
        """Topics should be sorted by balance descending."""
        await ledger.earn("server:123:user:1", 10.0)
        await ledger.earn("server:123:user:2", 30.0)
        await ledger.earn("server:123:user:3", 20.0)

        response = client.get("/salience")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        # Sorted by balance descending
        assert data[0]["topic_key"] == "server:123:user:2"
        assert data[0]["balance"] == 30.0
        assert data[1]["topic_key"] == "server:123:user:3"
        assert data[2]["topic_key"] == "server:123:user:1"

    @pytest.mark.asyncio
    async def test_limit_parameter(
        self, client: TestClient, ledger: SalienceLedger
    ) -> None:
        """Limit parameter should restrict results."""
        for i in range(10):
            await ledger.earn(f"server:123:user:{i}", float(i + 1))

        response = client.get("/salience?limit=3")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3

    @pytest.mark.asyncio
    async def test_group_filter(
        self, client: TestClient, ledger: SalienceLedger
    ) -> None:
        """Group filter should work."""
        # Social topic
        await ledger.earn("server:123:user:1", 10.0)
        # Spaces topic
        await ledger.earn("server:123:channel:1", 20.0)

        response = client.get("/salience?group=spaces")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["topic_key"] == "server:123:channel:1"

    @pytest.mark.asyncio
    async def test_invalid_group_returns_400(self, client: TestClient) -> None:
        """Invalid group filter should return 400."""
        response = client.get("/salience?group=invalid")

        assert response.status_code == 400
        assert "Invalid budget group" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_excludes_zero_balance_topics(
        self, client: TestClient, ledger: SalienceLedger
    ) -> None:
        """Topics with zero balance should be excluded."""
        await ledger.earn("server:123:user:1", 10.0)
        # Create a topic but don't earn (balance 0)
        await ledger.ensure_topic("server:123:user:2")

        response = client.get("/salience")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["topic_key"] == "server:123:user:1"

    @pytest.mark.asyncio
    async def test_includes_cap_and_budget_group(
        self, client: TestClient, ledger: SalienceLedger
    ) -> None:
        """Results should include cap and budget_group."""
        await ledger.earn("server:123:user:1", 10.0)

        response = client.get("/salience")

        assert response.status_code == 200
        data = response.json()
        assert data[0]["cap"] == 100
        assert data[0]["budget_group"] == "social"

    @pytest.mark.asyncio
    async def test_empty_database_returns_empty_list(
        self, client: TestClient
    ) -> None:
        """Empty database should return empty list."""
        response = client.get("/salience")

        assert response.status_code == 200
        data = response.json()
        assert data == []


# =============================================================================
# Test: GET /salience/groups
# =============================================================================


class TestGetBudgetGroups:
    """Tests for: GET /salience/groups returns budget group summaries."""

    @pytest.mark.asyncio
    async def test_returns_all_groups(self, client: TestClient) -> None:
        """Should return all budget groups."""
        response = client.get("/salience/groups")

        assert response.status_code == 200
        data = response.json()
        group_names = [g["group"] for g in data]
        assert set(group_names) == {"social", "global", "spaces", "semantic", "culture", "self"}

    @pytest.mark.asyncio
    async def test_returns_allocation(self, client: TestClient) -> None:
        """Should return allocation for each group."""
        response = client.get("/salience/groups")

        assert response.status_code == 200
        data = response.json()

        # Find social group
        social = next(g for g in data if g["group"] == "social")
        assert social["allocation"] == 0.30

    @pytest.mark.asyncio
    async def test_returns_total_salience(
        self, client: TestClient, ledger: SalienceLedger
    ) -> None:
        """Should return total salience for each group."""
        await ledger.earn("server:123:user:1", 10.0)
        await ledger.earn("server:123:user:2", 15.0)

        response = client.get("/salience/groups")

        assert response.status_code == 200
        data = response.json()

        social = next(g for g in data if g["group"] == "social")
        assert social["total_salience"] == 25.0
        assert social["topic_count"] == 2

    @pytest.mark.asyncio
    async def test_returns_top_topics(
        self, client: TestClient, ledger: SalienceLedger
    ) -> None:
        """Should return top 5 topics per group."""
        # Create 7 user topics
        for i in range(7):
            await ledger.earn(f"server:123:user:{i}", float(10 - i))

        response = client.get("/salience/groups")

        assert response.status_code == 200
        data = response.json()

        social = next(g for g in data if g["group"] == "social")
        assert len(social["top_topics"]) == 5
        # Should be sorted by balance
        assert social["top_topics"][0]["balance"] == 10.0

    @pytest.mark.asyncio
    async def test_empty_group_returns_zeros(self, client: TestClient) -> None:
        """Empty group should return zeros."""
        response = client.get("/salience/groups")

        assert response.status_code == 200
        data = response.json()

        # Semantic group should be empty
        semantic = next(g for g in data if g["group"] == "semantic")
        assert semantic["total_salience"] == 0.0
        assert semantic["topic_count"] == 0
        assert semantic["top_topics"] == []

    @pytest.mark.asyncio
    async def test_global_group_allocation(
        self, client: TestClient, test_config: Config
    ) -> None:
        """Global group should have correct allocation."""
        response = client.get("/salience/groups")

        assert response.status_code == 200
        data = response.json()

        global_group = next(g for g in data if g["group"] == "global")
        assert global_group["allocation"] == test_config.salience.budget.global_group

    @pytest.mark.asyncio
    async def test_self_budget_separate(
        self, client: TestClient, test_config: Config
    ) -> None:
        """Self group should use separate budget value."""
        response = client.get("/salience/groups")

        assert response.status_code == 200
        data = response.json()

        self_group = next(g for g in data if g["group"] == "self")
        assert self_group["allocation"] == test_config.salience.self_budget


# =============================================================================
# Test: Transaction Types in History
# =============================================================================


class TestTransactionTypes:
    """Tests for different transaction types in history."""

    @pytest.mark.asyncio
    async def test_earn_transaction_type(
        self, client: TestClient, ledger: SalienceLedger
    ) -> None:
        """Earn transactions should have correct type."""
        topic_key = "server:123:user:456"
        await ledger.earn(topic_key, 10.0)

        response = client.get(f"/salience/{topic_key}")

        assert response.status_code == 200
        data = response.json()
        assert data["recent_transactions"][0]["transaction_type"] == "earn"

    @pytest.mark.asyncio
    async def test_spend_transaction_type(
        self, client: TestClient, ledger: SalienceLedger
    ) -> None:
        """Spend transactions should have correct type."""
        topic_key = "server:123:user:456"
        await ledger.earn(topic_key, 50.0)
        await ledger.spend(topic_key, 10.0)

        response = client.get(f"/salience/{topic_key}")

        assert response.status_code == 200
        data = response.json()
        # Most recent first: retain, spend, earn
        assert data["recent_transactions"][0]["transaction_type"] == "retain"
        assert data["recent_transactions"][1]["transaction_type"] == "spend"

    @pytest.mark.asyncio
    async def test_propagate_transaction_includes_source(
        self, client: TestClient, ledger: SalienceLedger
    ) -> None:
        """Propagate transactions should include source topic."""
        source = "server:123:user:456"
        target = "server:123:dyad:456:789"

        # Make target warm first
        await ledger.earn(target, 5.0)

        await ledger.propagate(target, 3.0, source_topic=source)

        response = client.get(f"/salience/{target}")

        assert response.status_code == 200
        data = response.json()
        prop_txn = next(
            t for t in data["recent_transactions"]
            if t["transaction_type"] == "propagate"
        )
        assert prop_txn["source_topic"] == source


# =============================================================================
# Test: Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    @pytest.mark.asyncio
    async def test_global_user_topic(
        self, client: TestClient, ledger: SalienceLedger
    ) -> None:
        """Global user topic should work."""
        topic_key = "user:456"
        await ledger.warm(topic_key, 10.0, reason="dm")

        response = client.get(f"/salience/{topic_key}")

        assert response.status_code == 200
        data = response.json()
        assert data["topic_key"] == topic_key
        assert data["balance"] == 10.0
        assert data["budget_group"] == "global"

    @pytest.mark.asyncio
    async def test_self_topic(
        self, client: TestClient, ledger: SalienceLedger
    ) -> None:
        """Self topic should work."""
        topic_key = "self:zos"
        await ledger.earn(topic_key, 20.0)

        response = client.get(f"/salience/{topic_key}")

        assert response.status_code == 200
        data = response.json()
        assert data["budget_group"] == "self"

    @pytest.mark.asyncio
    async def test_channel_topic(
        self, client: TestClient, ledger: SalienceLedger
    ) -> None:
        """Channel topic should work."""
        topic_key = "server:123:channel:456"
        await ledger.earn(topic_key, 30.0)

        response = client.get(f"/salience/{topic_key}")

        assert response.status_code == 200
        data = response.json()
        assert data["cap"] == 150  # Channel cap
        assert data["budget_group"] == "spaces"

    @pytest.mark.asyncio
    async def test_emoji_topic(
        self, client: TestClient, ledger: SalienceLedger
    ) -> None:
        """Emoji topic should work."""
        topic_key = "server:123:emoji:custom123"
        await ledger.earn(topic_key, 5.0)

        response = client.get(f"/salience/{topic_key}")

        assert response.status_code == 200
        data = response.json()
        assert data["cap"] == 60  # Emoji cap
        assert data["budget_group"] == "culture"
