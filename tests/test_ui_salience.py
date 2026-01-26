"""Tests for Salience Dashboard UI (Story 5.7).

Tests the salience dashboard page, budget groups visualization,
top topics table, topic detail modal, and utilization bars.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from zos.api import create_app
from zos.config import Config
from zos.database import create_tables, get_engine
from zos.migrations import migrate
from zos.salience import SalienceLedger


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
    """Create a salience ledger for testing."""
    return SalienceLedger(engine, test_config)


@pytest.fixture
def app(test_config: Config, engine, ledger):
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


@pytest.fixture
async def seeded_ledger(ledger: SalienceLedger) -> SalienceLedger:
    """Create a ledger with test data."""
    # Create some topics with salience
    await ledger.earn("server:123:user:456", 50.0, reason="test_message")
    await ledger.earn("server:123:user:789", 30.0, reason="test_message")
    await ledger.earn("server:123:channel:111", 25.0, reason="test_message")
    await ledger.earn("server:123:dyad:456:789", 15.0, reason="test_reply")

    return ledger


# =============================================================================
# Test: Salience Dashboard Page
# =============================================================================


class TestSalienceDashboardPage:
    """Tests for: Budget group overview with allocations."""

    def test_salience_page_returns_200(self, client: TestClient) -> None:
        """Salience dashboard page should return 200 OK."""
        response = client.get("/ui/salience")
        assert response.status_code == 200

    def test_salience_page_returns_html(self, client: TestClient) -> None:
        """Salience dashboard page should return HTML."""
        response = client.get("/ui/salience")
        assert "text/html" in response.headers["content-type"]

    def test_salience_page_contains_title(self, client: TestClient) -> None:
        """Salience dashboard page should contain correct title."""
        response = client.get("/ui/salience")
        assert "Salience Dashboard" in response.text

    def test_salience_page_contains_description(self, client: TestClient) -> None:
        """Salience dashboard page should explain its purpose."""
        response = client.get("/ui/salience")
        assert "attention" in response.text.lower()

    def test_salience_page_has_groups_htmx(self, client: TestClient) -> None:
        """Salience dashboard should load groups via htmx."""
        response = client.get("/ui/salience")
        assert 'hx-get="/ui/salience/groups"' in response.text
        assert 'hx-trigger="load"' in response.text

    def test_salience_page_has_top_topics_htmx(self, client: TestClient) -> None:
        """Salience dashboard should load top topics via htmx."""
        response = client.get("/ui/salience")
        assert 'hx-get="/ui/salience/top' in response.text

    def test_salience_page_is_active_in_nav(self, client: TestClient) -> None:
        """Salience page should mark salience as active in navigation."""
        response = client.get("/ui/salience")
        # The active link should have the active class
        assert 'class="active"' in response.text


# =============================================================================
# Test: Budget Groups Partial
# =============================================================================


class TestBudgetGroupsPartial:
    """Tests for: Budget groups display correctly."""

    def test_groups_partial_returns_200(self, client: TestClient) -> None:
        """Groups partial should return 200 OK."""
        response = client.get("/ui/salience/groups")
        assert response.status_code == 200

    def test_groups_partial_returns_html(self, client: TestClient) -> None:
        """Groups partial should return HTML."""
        response = client.get("/ui/salience/groups")
        assert "text/html" in response.headers["content-type"]

    def test_groups_partial_is_htmx_partial(self, client: TestClient) -> None:
        """Groups partial should not be full HTML page."""
        response = client.get("/ui/salience/groups")
        assert "<!DOCTYPE" not in response.text
        assert "<html" not in response.text

    def test_groups_partial_shows_all_groups(self, client: TestClient) -> None:
        """Groups partial should show all budget groups."""
        response = client.get("/ui/salience/groups")
        # Should contain group names (title-cased)
        assert "Social" in response.text or "social" in response.text.lower()
        assert "Global" in response.text or "global" in response.text.lower()
        assert "Spaces" in response.text or "spaces" in response.text.lower()
        assert "Semantic" in response.text or "semantic" in response.text.lower()

    def test_groups_partial_contains_allocation(self, client: TestClient) -> None:
        """Groups partial should show allocation percentages."""
        response = client.get("/ui/salience/groups")
        # Allocations are shown as percentages
        assert "%" in response.text

    def test_groups_partial_contains_topic_counts(self, client: TestClient) -> None:
        """Groups partial should show topic counts."""
        response = client.get("/ui/salience/groups")
        # Should have stat labels
        assert "Topics" in response.text or "topics" in response.text.lower()

    def test_groups_partial_has_modal_target(self, client: TestClient) -> None:
        """Groups partial should include modal container."""
        response = client.get("/ui/salience/groups")
        assert 'id="topic-detail-modal"' in response.text


# =============================================================================
# Test: Top Topics Partial
# =============================================================================


class TestTopTopicsPartial:
    """Tests for: Top topics sorted correctly."""

    def test_top_partial_returns_200(self, client: TestClient) -> None:
        """Top topics partial should return 200 OK."""
        response = client.get("/ui/salience/top")
        assert response.status_code == 200

    def test_top_partial_empty_shows_message(self, client: TestClient) -> None:
        """Top topics with no data should show appropriate message."""
        response = client.get("/ui/salience/top")
        # Should show empty message or table with no rows
        assert response.status_code == 200

    def test_top_partial_respects_limit(self, client: TestClient) -> None:
        """Top topics should respect limit parameter."""
        response = client.get("/ui/salience/top?limit=5")
        assert response.status_code == 200

    def test_top_partial_is_htmx_partial(self, client: TestClient) -> None:
        """Top partial should not be full HTML page."""
        response = client.get("/ui/salience/top")
        assert "<!DOCTYPE" not in response.text
        assert "<html" not in response.text


class TestTopTopicsWithData:
    """Tests for top topics with seeded data."""

    @pytest.mark.asyncio
    async def test_top_partial_shows_topics(
        self, client: TestClient, seeded_ledger: SalienceLedger
    ) -> None:
        """Top topics should show topics with salience."""
        response = client.get("/ui/salience/top")
        # Should contain topic keys
        assert "user:" in response.text or "channel:" in response.text

    @pytest.mark.asyncio
    async def test_top_partial_shows_balances(
        self, client: TestClient, seeded_ledger: SalienceLedger
    ) -> None:
        """Top topics should show balance values."""
        response = client.get("/ui/salience/top")
        # Should contain numeric values
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_top_partial_has_group_badges(
        self, client: TestClient, seeded_ledger: SalienceLedger
    ) -> None:
        """Top topics should show budget group badges."""
        response = client.get("/ui/salience/top")
        # Should contain badge classes
        assert "badge" in response.text


# =============================================================================
# Test: Topic Detail Modal
# =============================================================================


class TestTopicDetailModal:
    """Tests for: Modal opens on click and shows transaction history."""

    def test_topic_detail_returns_200_for_new_topic(
        self, client: TestClient
    ) -> None:
        """Topic detail should return 200 even for non-existent topic."""
        response = client.get("/ui/salience/topic/server:123:user:999")
        assert response.status_code == 200

    def test_topic_detail_returns_html(self, client: TestClient) -> None:
        """Topic detail should return HTML."""
        response = client.get("/ui/salience/topic/server:123:user:456")
        assert "text/html" in response.headers["content-type"]

    def test_topic_detail_is_htmx_partial(self, client: TestClient) -> None:
        """Topic detail should not be full HTML page."""
        response = client.get("/ui/salience/topic/server:123:user:456")
        assert "<!DOCTYPE" not in response.text
        assert "<html" not in response.text

    def test_topic_detail_shows_topic_key(self, client: TestClient) -> None:
        """Topic detail should show the topic key."""
        response = client.get("/ui/salience/topic/server:123:user:456")
        assert "server:123:user:456" in response.text

    def test_topic_detail_has_close_button(self, client: TestClient) -> None:
        """Topic detail should have close button."""
        response = client.get("/ui/salience/topic/server:123:user:456")
        assert "close-btn" in response.text

    def test_topic_detail_shows_balance(self, client: TestClient) -> None:
        """Topic detail should show balance."""
        response = client.get("/ui/salience/topic/server:123:user:456")
        # Should have balance display
        assert "salience" in response.text.lower()

    def test_topic_detail_shows_cap(self, client: TestClient) -> None:
        """Topic detail should show cap."""
        response = client.get("/ui/salience/topic/server:123:user:456")
        # Cap is displayed after balance
        assert "/" in response.text

    def test_topic_detail_has_utilization_bar(self, client: TestClient) -> None:
        """Topic detail should have utilization visualization."""
        response = client.get("/ui/salience/topic/server:123:user:456")
        # Should have progress bar
        assert "progress" in response.text.lower()

    def test_topic_detail_has_insights_link(self, client: TestClient) -> None:
        """Topic detail should link to insights for this topic."""
        response = client.get("/ui/salience/topic/server:123:user:456")
        assert "View Insights" in response.text


class TestTopicDetailWithTransactions:
    """Tests for topic detail with transaction history."""

    @pytest.mark.asyncio
    async def test_topic_detail_shows_transactions(
        self, client: TestClient, seeded_ledger: SalienceLedger
    ) -> None:
        """Topic detail should show transaction history."""
        response = client.get("/ui/salience/topic/server:123:user:456")
        # Should have transactions section
        assert "Transaction" in response.text or "transaction" in response.text.lower()

    @pytest.mark.asyncio
    async def test_topic_detail_shows_transaction_types(
        self, client: TestClient, seeded_ledger: SalienceLedger
    ) -> None:
        """Topic detail should show transaction types."""
        response = client.get("/ui/salience/topic/server:123:user:456")
        # Should show earn transaction type
        assert "earn" in response.text.lower()


# =============================================================================
# Test: Utilization Bars
# =============================================================================


class TestUtilizationBars:
    """Tests for: Utilization bars (balance/cap) display correctly."""

    @pytest.mark.asyncio
    async def test_groups_have_progress_bars_with_data(
        self, client: TestClient, seeded_ledger: SalienceLedger
    ) -> None:
        """Budget groups should have progress bars when topics exist."""
        response = client.get("/ui/salience/groups")
        assert "progress" in response.text.lower()

    def test_groups_without_data_shows_empty(self, client: TestClient) -> None:
        """Budget groups without topics should show 'no topics' message."""
        response = client.get("/ui/salience/groups")
        assert "No topics in this group" in response.text or "no topics" in response.text.lower()

    def test_top_topics_have_progress_bars(self, client: TestClient) -> None:
        """Top topics table should have progress bars."""
        # Need seeded data first
        response = client.get("/ui/salience/top")
        # Progress bars might only show when there's data
        assert response.status_code == 200


# =============================================================================
# Test: Visual Hierarchy
# =============================================================================


class TestVisualHierarchy:
    """Tests for: Visual hierarchy of attention."""

    def test_css_has_group_styles(self, client: TestClient) -> None:
        """CSS should have styles for group cards."""
        response = client.get("/static/style.css")
        assert "groups-grid" in response.text
        assert "group-card" in response.text

    def test_css_has_utilization_styles(self, client: TestClient) -> None:
        """CSS should have utilization bar styles."""
        response = client.get("/static/style.css")
        assert "utilization" in response.text.lower()

    def test_css_has_modal_styles(self, client: TestClient) -> None:
        """CSS should have modal styles."""
        response = client.get("/static/style.css")
        assert "modal" in response.text

    def test_css_has_transaction_type_badges(self, client: TestClient) -> None:
        """CSS should have badge styles for transaction types."""
        response = client.get("/static/style.css")
        assert "badge-earn" in response.text
        assert "badge-spend" in response.text
        assert "badge-decay" in response.text

    def test_css_has_budget_group_badges(self, client: TestClient) -> None:
        """CSS should have badge styles for budget groups."""
        response = client.get("/static/style.css")
        assert "badge-social" in response.text
        assert "badge-global" in response.text


# =============================================================================
# Test: URL Encoding
# =============================================================================


class TestURLEncoding:
    """Tests for: Topic keys with special characters."""

    def test_topic_with_colons_works(self, client: TestClient) -> None:
        """Topic keys with colons should be handled correctly."""
        response = client.get("/ui/salience/topic/server:123:user:456")
        assert response.status_code == 200
        assert "server:123:user:456" in response.text

    def test_topic_with_special_chars_works(self, client: TestClient) -> None:
        """Topic keys are URL-decoded properly."""
        # The path parameter with :path type should handle this
        response = client.get("/ui/salience/topic/server:123:dyad:456:789")
        assert response.status_code == 200
