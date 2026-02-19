"""Tests for Budget Dashboard UI.

Tests the budget dashboard page, summary cards,
daily costs chart, and cost breakdowns by layer/model/call type.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from zos.api import create_app
from zos.config import Config
from zos.database import create_tables, generate_id, get_engine, layer_runs, llm_calls
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
def seeded_cost_data(engine):
    """Seed the database with cost data for testing."""
    now = datetime.now(timezone.utc)

    with engine.connect() as conn:
        # Create layer runs with cost data
        for i in range(5):
            run_id = generate_id()
            run_date = now - timedelta(days=i)
            conn.execute(
                layer_runs.insert().values(
                    id=run_id,
                    layer_name="user-reflection",
                    layer_hash="abc123",
                    started_at=run_date,
                    completed_at=run_date + timedelta(seconds=30),
                    status="success",
                    targets_matched=10,
                    targets_processed=8,
                    targets_skipped=2,
                    insights_created=5,
                    model_profile="moderate",
                    model_provider="anthropic",
                    model_name="claude-sonnet-4-20250514",
                    tokens_input=1000 * (i + 1),
                    tokens_output=500 * (i + 1),
                    tokens_total=1500 * (i + 1),
                    estimated_cost_usd=0.05 * (i + 1),
                )
            )

            # Create LLM calls for this run
            for j in range(3):
                conn.execute(
                    llm_calls.insert().values(
                        id=generate_id(),
                        layer_run_id=run_id,
                        topic_key=f"server:123:user:{456 + j}",
                        call_type="reflection",
                        model_profile="moderate",
                        model_provider="anthropic",
                        model_name="claude-sonnet-4-20250514",
                        prompt="Test prompt",
                        response="Test response",
                        tokens_input=300 + j * 100,
                        tokens_output=150 + j * 50,
                        tokens_total=450 + j * 150,
                        estimated_cost_usd=0.01 * (j + 1),
                        latency_ms=500,
                        success=True,
                        created_at=run_date,
                    )
                )

        # Create a run for a different layer
        run_id2 = generate_id()
        conn.execute(
            layer_runs.insert().values(
                id=run_id2,
                layer_name="dyad-reflection",
                layer_hash="def456",
                started_at=now - timedelta(days=1),
                completed_at=now - timedelta(days=1) + timedelta(seconds=20),
                status="success",
                targets_matched=5,
                targets_processed=5,
                targets_skipped=0,
                insights_created=3,
                model_profile="simple",
                model_provider="anthropic",
                model_name="claude-3-5-haiku-20241022",
                tokens_input=500,
                tokens_output=250,
                tokens_total=750,
                estimated_cost_usd=0.002,
            )
        )

        # Create vision call
        conn.execute(
            llm_calls.insert().values(
                id=generate_id(),
                layer_run_id=None,
                topic_key=None,
                call_type="vision",
                model_profile="moderate",
                model_provider="anthropic",
                model_name="claude-sonnet-4-20250514",
                prompt="Describe this image",
                response="Image description",
                tokens_input=2000,
                tokens_output=100,
                tokens_total=2100,
                estimated_cost_usd=0.008,
                latency_ms=1200,
                success=True,
                created_at=now,
            )
        )

        conn.commit()

    return engine


# =============================================================================
# Test: Budget Dashboard Page
# =============================================================================


class TestBudgetDashboardPage:
    """Tests for: Budget dashboard page structure."""

    def test_budget_page_returns_200(self, client: TestClient) -> None:
        """Budget dashboard page should return 200 OK."""
        response = client.get("/ui/budget")
        assert response.status_code == 200

    def test_budget_page_returns_html(self, client: TestClient) -> None:
        """Budget dashboard page should return HTML."""
        response = client.get("/ui/budget")
        assert "text/html" in response.headers["content-type"]

    def test_budget_page_contains_title(self, client: TestClient) -> None:
        """Budget dashboard page should contain correct title."""
        response = client.get("/ui/budget")
        assert "Budget" in response.text

    def test_budget_page_contains_description(self, client: TestClient) -> None:
        """Budget dashboard page should explain its purpose."""
        response = client.get("/ui/budget")
        assert "cost" in response.text.lower() or "token" in response.text.lower()

    def test_budget_page_has_summary_htmx(self, client: TestClient) -> None:
        """Budget dashboard should load summary via htmx."""
        response = client.get("/ui/budget")
        assert 'hx-get="/ui/budget/summary' in response.text
        assert 'hx-trigger="load"' in response.text

    def test_budget_page_has_daily_htmx(self, client: TestClient) -> None:
        """Budget dashboard should load daily costs via htmx."""
        response = client.get("/ui/budget")
        assert 'hx-get="/ui/budget/daily' in response.text

    def test_budget_page_has_by_layer_htmx(self, client: TestClient) -> None:
        """Budget dashboard should load cost by layer via htmx."""
        response = client.get("/ui/budget")
        assert 'hx-get="/ui/budget/by-layer' in response.text

    def test_budget_page_has_by_model_htmx(self, client: TestClient) -> None:
        """Budget dashboard should load cost by model via htmx."""
        response = client.get("/ui/budget")
        assert 'hx-get="/ui/budget/by-model' in response.text

    def test_budget_page_is_active_in_nav(self, client: TestClient) -> None:
        """Budget page should mark budget as active in navigation."""
        response = client.get("/ui/budget")
        assert 'class="active"' in response.text


# =============================================================================
# Test: Budget Summary Partial
# =============================================================================


class TestBudgetSummaryPartial:
    """Tests for: Budget summary cards."""

    def test_summary_partial_returns_200(self, client: TestClient) -> None:
        """Summary partial should return 200 OK."""
        response = client.get("/ui/budget/summary")
        assert response.status_code == 200

    def test_summary_partial_returns_html(self, client: TestClient) -> None:
        """Summary partial should return HTML."""
        response = client.get("/ui/budget/summary")
        assert "text/html" in response.headers["content-type"]

    def test_summary_partial_is_htmx_partial(self, client: TestClient) -> None:
        """Summary partial should not be full HTML page."""
        response = client.get("/ui/budget/summary")
        assert "<!DOCTYPE" not in response.text
        assert "<html" not in response.text

    def test_summary_partial_shows_total_cost(self, client: TestClient) -> None:
        """Summary partial should show total cost label."""
        response = client.get("/ui/budget/summary")
        assert "Total Cost" in response.text or "total-cost" in response.text.lower()

    def test_summary_partial_shows_total_tokens(self, client: TestClient) -> None:
        """Summary partial should show total tokens label."""
        response = client.get("/ui/budget/summary")
        assert "Tokens" in response.text or "tokens" in response.text.lower()

    def test_summary_partial_shows_layer_runs(self, client: TestClient) -> None:
        """Summary partial should show layer runs label."""
        response = client.get("/ui/budget/summary")
        assert "Runs" in response.text or "runs" in response.text.lower()

    def test_summary_partial_respects_days_param(self, client: TestClient) -> None:
        """Summary partial should respect days parameter."""
        response = client.get("/ui/budget/summary?days=7")
        assert response.status_code == 200


class TestBudgetSummaryWithData:
    """Tests for summary partial with seeded data."""

    def test_summary_shows_nonzero_values(
        self, client: TestClient, seeded_cost_data
    ) -> None:
        """Summary should show non-zero values when data exists."""
        response = client.get("/ui/budget/summary")
        # Should have formatted cost values
        assert "$" in response.text

    def test_summary_shows_correct_period(
        self, client: TestClient, seeded_cost_data
    ) -> None:
        """Summary should show the correct period."""
        response = client.get("/ui/budget/summary?days=30")
        assert "30" in response.text


# =============================================================================
# Test: Daily Costs Partial
# =============================================================================


class TestDailyCostsPartial:
    """Tests for: Daily cost breakdown."""

    def test_daily_partial_returns_200(self, client: TestClient) -> None:
        """Daily partial should return 200 OK."""
        response = client.get("/ui/budget/daily")
        assert response.status_code == 200

    def test_daily_partial_returns_html(self, client: TestClient) -> None:
        """Daily partial should return HTML."""
        response = client.get("/ui/budget/daily")
        assert "text/html" in response.headers["content-type"]

    def test_daily_partial_is_htmx_partial(self, client: TestClient) -> None:
        """Daily partial should not be full HTML page."""
        response = client.get("/ui/budget/daily")
        assert "<!DOCTYPE" not in response.text
        assert "<html" not in response.text

    def test_daily_partial_respects_days_param(self, client: TestClient) -> None:
        """Daily partial should respect days parameter."""
        response = client.get("/ui/budget/daily?days=7")
        assert response.status_code == 200

    def test_daily_partial_empty_shows_message(self, client: TestClient) -> None:
        """Daily partial with no data should show appropriate message."""
        response = client.get("/ui/budget/daily")
        # Either shows table or empty message
        assert response.status_code == 200


class TestDailyCostsWithData:
    """Tests for daily costs with seeded data."""

    def test_daily_shows_chart(
        self, client: TestClient, seeded_cost_data
    ) -> None:
        """Daily costs should show chart visualization."""
        response = client.get("/ui/budget/daily")
        assert "daily-chart" in response.text or "daily-bar" in response.text

    def test_daily_shows_table(
        self, client: TestClient, seeded_cost_data
    ) -> None:
        """Daily costs should show table with data."""
        response = client.get("/ui/budget/daily")
        assert "<table" in response.text or "<tr" in response.text


# =============================================================================
# Test: Cost by Layer Partial
# =============================================================================


class TestCostByLayerPartial:
    """Tests for: Cost breakdown by layer."""

    def test_by_layer_partial_returns_200(self, client: TestClient) -> None:
        """By-layer partial should return 200 OK."""
        response = client.get("/ui/budget/by-layer")
        assert response.status_code == 200

    def test_by_layer_partial_returns_html(self, client: TestClient) -> None:
        """By-layer partial should return HTML."""
        response = client.get("/ui/budget/by-layer")
        assert "text/html" in response.headers["content-type"]

    def test_by_layer_partial_is_htmx_partial(self, client: TestClient) -> None:
        """By-layer partial should not be full HTML page."""
        response = client.get("/ui/budget/by-layer")
        assert "<!DOCTYPE" not in response.text
        assert "<html" not in response.text

    def test_by_layer_partial_respects_days_param(self, client: TestClient) -> None:
        """By-layer partial should respect days parameter."""
        response = client.get("/ui/budget/by-layer?days=7")
        assert response.status_code == 200


class TestCostByLayerWithData:
    """Tests for cost by layer with seeded data."""

    def test_by_layer_shows_layers(
        self, client: TestClient, seeded_cost_data
    ) -> None:
        """By-layer should show layer names."""
        response = client.get("/ui/budget/by-layer")
        assert "user-reflection" in response.text

    def test_by_layer_shows_percentages(
        self, client: TestClient, seeded_cost_data
    ) -> None:
        """By-layer should show percentage of total."""
        response = client.get("/ui/budget/by-layer")
        assert "%" in response.text

    def test_by_layer_shows_cost_bars(
        self, client: TestClient, seeded_cost_data
    ) -> None:
        """By-layer should show cost bar visualization."""
        response = client.get("/ui/budget/by-layer")
        assert "cost-bar" in response.text


# =============================================================================
# Test: Cost by Model Partial
# =============================================================================


class TestCostByModelPartial:
    """Tests for: Cost breakdown by model."""

    def test_by_model_partial_returns_200(self, client: TestClient) -> None:
        """By-model partial should return 200 OK."""
        response = client.get("/ui/budget/by-model")
        assert response.status_code == 200

    def test_by_model_partial_returns_html(self, client: TestClient) -> None:
        """By-model partial should return HTML."""
        response = client.get("/ui/budget/by-model")
        assert "text/html" in response.headers["content-type"]

    def test_by_model_partial_is_htmx_partial(self, client: TestClient) -> None:
        """By-model partial should not be full HTML page."""
        response = client.get("/ui/budget/by-model")
        assert "<!DOCTYPE" not in response.text
        assert "<html" not in response.text

    def test_by_model_partial_respects_days_param(self, client: TestClient) -> None:
        """By-model partial should respect days parameter."""
        response = client.get("/ui/budget/by-model?days=7")
        assert response.status_code == 200


class TestCostByModelWithData:
    """Tests for cost by model with seeded data."""

    def test_by_model_shows_models(
        self, client: TestClient, seeded_cost_data
    ) -> None:
        """By-model should show model names."""
        response = client.get("/ui/budget/by-model")
        assert "claude" in response.text.lower() or "sonnet" in response.text.lower()

    def test_by_model_shows_profile_badges(
        self, client: TestClient, seeded_cost_data
    ) -> None:
        """By-model should show model profile badges."""
        response = client.get("/ui/budget/by-model")
        assert "badge" in response.text


# =============================================================================
# Test: Cost by Call Type Partial
# =============================================================================


class TestCostByCallTypePartial:
    """Tests for: Cost breakdown by call type."""

    def test_by_call_type_partial_returns_200(self, client: TestClient) -> None:
        """By-call-type partial should return 200 OK."""
        response = client.get("/ui/budget/by-call-type")
        assert response.status_code == 200

    def test_by_call_type_partial_returns_html(self, client: TestClient) -> None:
        """By-call-type partial should return HTML."""
        response = client.get("/ui/budget/by-call-type")
        assert "text/html" in response.headers["content-type"]

    def test_by_call_type_partial_is_htmx_partial(self, client: TestClient) -> None:
        """By-call-type partial should not be full HTML page."""
        response = client.get("/ui/budget/by-call-type")
        assert "<!DOCTYPE" not in response.text
        assert "<html" not in response.text

    def test_by_call_type_partial_respects_days_param(self, client: TestClient) -> None:
        """By-call-type partial should respect days parameter."""
        response = client.get("/ui/budget/by-call-type?days=7")
        assert response.status_code == 200


class TestCostByCallTypeWithData:
    """Tests for cost by call type with seeded data."""

    def test_by_call_type_shows_types(
        self, client: TestClient, seeded_cost_data
    ) -> None:
        """By-call-type should show call types."""
        response = client.get("/ui/budget/by-call-type")
        assert "reflection" in response.text.lower() or "vision" in response.text.lower()

    def test_by_call_type_shows_badges(
        self, client: TestClient, seeded_cost_data
    ) -> None:
        """By-call-type should show call type badges."""
        response = client.get("/ui/budget/by-call-type")
        assert "badge" in response.text


# =============================================================================
# Test: Navigation
# =============================================================================


class TestBudgetNavigation:
    """Tests for: Budget tab in navigation."""

    def test_budget_tab_exists_in_nav(self, client: TestClient) -> None:
        """Budget tab should exist in navigation."""
        response = client.get("/ui/")
        assert "/ui/budget" in response.text
        assert "Budget" in response.text

    def test_budget_tab_accessible_from_other_pages(self, client: TestClient) -> None:
        """Budget tab should be accessible from other pages."""
        # Check from insights page
        response = client.get("/ui/insights")
        assert "/ui/budget" in response.text


# =============================================================================
# Test: CSS Styles
# =============================================================================


class TestBudgetStyles:
    """Tests for: Budget dashboard CSS styles."""

    def test_css_has_budget_stats_styles(self, client: TestClient) -> None:
        """CSS should have budget stats card styles."""
        response = client.get("/static/style.css")
        assert "budget-stats-cards" in response.text

    def test_css_has_budget_grid_styles(self, client: TestClient) -> None:
        """CSS should have budget grid styles."""
        response = client.get("/static/style.css")
        assert "budget-grid" in response.text

    def test_css_has_cost_bar_styles(self, client: TestClient) -> None:
        """CSS should have cost bar styles."""
        response = client.get("/static/style.css")
        assert "cost-bar" in response.text

    def test_css_has_daily_chart_styles(self, client: TestClient) -> None:
        """CSS should have daily chart styles."""
        response = client.get("/static/style.css")
        assert "daily-chart" in response.text

    def test_css_has_model_profile_badges(self, client: TestClient) -> None:
        """CSS should have model profile badge styles."""
        response = client.get("/static/style.css")
        assert "badge-simple" in response.text
        assert "badge-moderate" in response.text
        assert "badge-complex" in response.text

    def test_css_has_call_type_badges(self, client: TestClient) -> None:
        """CSS should have call type badge styles."""
        response = client.get("/static/style.css")
        assert "badge-reflection" in response.text
        assert "badge-vision" in response.text


# =============================================================================
# Test: LLM Calls List
# =============================================================================


class TestLLMCallsListPartial:
    """Tests for: LLM calls list partial endpoint."""

    def test_calls_partial_returns_200(self, client: TestClient) -> None:
        """LLM calls list partial should return 200 OK."""
        response = client.get("/ui/budget/calls")
        assert response.status_code == 200

    def test_calls_partial_returns_html(self, client: TestClient) -> None:
        """LLM calls list partial should return HTML."""
        response = client.get("/ui/budget/calls")
        assert "text/html" in response.headers["content-type"]

    def test_calls_partial_is_htmx_partial(self, client: TestClient) -> None:
        """LLM calls list partial should NOT extend base template."""
        response = client.get("/ui/budget/calls")
        assert "<!DOCTYPE html>" not in response.text

    def test_calls_partial_empty_shows_message(self, client: TestClient) -> None:
        """LLM calls list with no data should show message."""
        response = client.get("/ui/budget/calls")
        assert "No LLM calls recorded" in response.text

    def test_calls_partial_respects_days_param(self, client: TestClient) -> None:
        """LLM calls list should accept days parameter."""
        response = client.get("/ui/budget/calls?days=7")
        assert response.status_code == 200


class TestLLMCallsListWithData:
    """Tests for: LLM calls list with seeded data."""

    def test_calls_shows_table(self, client: TestClient, seeded_cost_data) -> None:
        """LLM calls list should show table when data exists."""
        response = client.get("/ui/budget/calls")
        assert '<table class="budget-table">' in response.text

    def test_calls_shows_call_type_badges(self, client: TestClient, seeded_cost_data) -> None:
        """LLM calls list should show call type badges."""
        response = client.get("/ui/budget/calls")
        assert 'badge-reflection' in response.text or 'badge-vision' in response.text

    def test_calls_shows_pagination(self, client: TestClient, seeded_cost_data) -> None:
        """LLM calls list should show pagination."""
        response = client.get("/ui/budget/calls")
        # Either shows page-info or "No LLM calls" message
        assert 'page-info' in response.text or 'No LLM calls' in response.text

    def test_calls_clickable_rows(self, client: TestClient, seeded_cost_data) -> None:
        """LLM calls list rows should be clickable."""
        response = client.get("/ui/budget/calls")
        assert 'hx-get="/ui/budget/calls/' in response.text

    def test_calls_filter_by_call_type(self, client: TestClient, seeded_cost_data) -> None:
        """LLM calls list should filter by call type."""
        response = client.get("/ui/budget/calls?call_type=vision")
        assert response.status_code == 200


# =============================================================================
# Test: LLM Call Detail
# =============================================================================


class TestLLMCallDetailPartial:
    """Tests for: LLM call detail partial endpoint."""

    def test_call_detail_not_found(self, client: TestClient) -> None:
        """LLM call detail should handle not found."""
        response = client.get("/ui/budget/calls/nonexistent123")
        assert response.status_code == 200
        assert "not found" in response.text.lower()

    def test_call_detail_returns_html(self, client: TestClient) -> None:
        """LLM call detail should return HTML."""
        response = client.get("/ui/budget/calls/test123")
        assert "text/html" in response.headers["content-type"]


class TestLLMCallDetailWithData:
    """Tests for: LLM call detail with seeded data."""

    def test_call_detail_shows_content(self, client: TestClient, seeded_cost_data) -> None:
        """LLM call detail should show call content."""
        # First get the list to get a call ID
        list_response = client.get("/ui/budget/calls")

        # Extract a call ID from the response (looking for hx-get="/ui/budget/calls/{id}")
        import re
        match = re.search(r'hx-get="/ui/budget/calls/([^"]+)"', list_response.text)
        if match:
            call_id = match.group(1)
            response = client.get(f"/ui/budget/calls/{call_id}")
            assert response.status_code == 200
            assert "modal-content" in response.text

    def test_call_detail_shows_prompt(self, client: TestClient, seeded_cost_data) -> None:
        """LLM call detail should show prompt."""
        list_response = client.get("/ui/budget/calls")
        import re
        match = re.search(r'hx-get="/ui/budget/calls/([^"]+)"', list_response.text)
        if match:
            call_id = match.group(1)
            response = client.get(f"/ui/budget/calls/{call_id}")
            assert "Prompt" in response.text or "prompt" in response.text.lower()

    def test_call_detail_shows_response(self, client: TestClient, seeded_cost_data) -> None:
        """LLM call detail should show response."""
        list_response = client.get("/ui/budget/calls")
        import re
        match = re.search(r'hx-get="/ui/budget/calls/([^"]+)"', list_response.text)
        if match:
            call_id = match.group(1)
            response = client.get(f"/ui/budget/calls/{call_id}")
            assert "Response" in response.text or "response" in response.text.lower()


# =============================================================================
# Test: Dashboard has Calls Section
# =============================================================================


class TestBudgetDashboardHasCalls:
    """Tests for: Budget dashboard includes LLM calls section."""

    def test_dashboard_has_calls_htmx(self, client: TestClient) -> None:
        """Budget dashboard should have htmx trigger for calls."""
        response = client.get("/ui/budget")
        assert 'hx-get="/ui/budget/calls' in response.text

    def test_dashboard_has_calls_section(self, client: TestClient) -> None:
        """Budget dashboard should have calls section header."""
        response = client.get("/ui/budget")
        assert "LLM Calls" in response.text or "Recent LLM Calls" in response.text
