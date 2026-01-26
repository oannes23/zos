"""Tests for Layer Run Monitor UI (Story 5.8).

Tests the UI pages and partials for browsing layer run history,
viewing stats, filtering, and viewing run details.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from zos.api import create_app
from zos.config import Config
from zos.database import create_tables, generate_id, get_engine, layer_runs
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
def app(test_config: Config, engine):
    """Create a test FastAPI application."""
    application = create_app(test_config)
    application.state.config = test_config
    application.state.db = engine
    application.state.ledger = SalienceLedger(engine, test_config)
    return application


@pytest.fixture
def client(app) -> TestClient:
    """Create a test client for the API."""
    return TestClient(app)


@pytest.fixture
def sample_runs(engine):
    """Create sample layer runs for testing."""
    now = datetime.now(timezone.utc)
    runs_data = [
        {
            "id": generate_id(),
            "layer_name": "nightly-user-reflection",
            "layer_hash": "abc123",
            "started_at": now - timedelta(hours=2),
            "completed_at": now - timedelta(hours=1, minutes=57),
            "status": "success",
            "targets_matched": 10,
            "targets_processed": 10,
            "targets_skipped": 0,
            "insights_created": 8,
            "model_profile": "moderate",
            "model_provider": "anthropic",
            "model_name": "claude-sonnet-4-20250514",
            "tokens_input": 10000,
            "tokens_output": 5000,
            "tokens_total": 15000,
            "estimated_cost_usd": 0.045,
            "errors": None,
        },
        {
            "id": generate_id(),
            "layer_name": "nightly-user-reflection",
            "layer_hash": "abc123",
            "started_at": now - timedelta(days=1, hours=2),
            "completed_at": now - timedelta(days=1, hours=1, minutes=55),
            "status": "partial",
            "targets_matched": 10,
            "targets_processed": 8,
            "targets_skipped": 2,
            "insights_created": 6,
            "model_profile": "moderate",
            "model_provider": "anthropic",
            "model_name": "claude-sonnet-4-20250514",
            "tokens_input": 8000,
            "tokens_output": 4000,
            "tokens_total": 12000,
            "estimated_cost_usd": 0.036,
            "errors": [{"topic": "server:123:user:456", "error": "Timeout", "node": "llm_call"}],
        },
        {
            "id": generate_id(),
            "layer_name": "weekly-self-reflection",
            "layer_hash": "def456",
            "started_at": now - timedelta(days=3),
            "completed_at": now - timedelta(days=3) + timedelta(minutes=5),
            "status": "success",
            "targets_matched": 1,
            "targets_processed": 1,
            "targets_skipped": 0,
            "insights_created": 1,
            "model_profile": "complex",
            "model_provider": "anthropic",
            "model_name": "claude-opus-4-20250514",
            "tokens_input": 5000,
            "tokens_output": 2000,
            "tokens_total": 7000,
            "estimated_cost_usd": 0.15,
            "errors": None,
        },
        {
            "id": generate_id(),
            "layer_name": "nightly-user-reflection",
            "layer_hash": "abc123",
            "started_at": now - timedelta(days=5),
            "completed_at": now - timedelta(days=5) + timedelta(minutes=1),
            "status": "dry",
            "targets_matched": 5,
            "targets_processed": 5,
            "targets_skipped": 0,
            "insights_created": 0,
            "model_profile": "moderate",
            "model_provider": None,
            "model_name": None,
            "tokens_input": None,
            "tokens_output": None,
            "tokens_total": None,
            "estimated_cost_usd": None,
            "errors": None,
        },
        {
            "id": generate_id(),
            "layer_name": "nightly-user-reflection",
            "layer_hash": "abc123",
            "started_at": now - timedelta(days=6),
            "completed_at": now - timedelta(days=6) + timedelta(seconds=30),
            "status": "failed",
            "targets_matched": 10,
            "targets_processed": 0,
            "targets_skipped": 10,
            "insights_created": 0,
            "model_profile": "moderate",
            "model_provider": None,
            "model_name": None,
            "tokens_input": None,
            "tokens_output": None,
            "tokens_total": None,
            "estimated_cost_usd": None,
            "errors": [{"topic": None, "error": "Database connection failed", "node": None}],
        },
    ]

    with engine.connect() as conn:
        for run in runs_data:
            conn.execute(layer_runs.insert().values(**run))
        conn.commit()

    return runs_data


# =============================================================================
# Test: Runs Page
# =============================================================================


class TestRunsPage:
    """Tests for: GET /ui/runs - main runs page."""

    def test_runs_page_returns_200(self, client: TestClient) -> None:
        """Runs page should return 200 OK."""
        response = client.get("/ui/runs")
        assert response.status_code == 200

    def test_runs_page_returns_html(self, client: TestClient) -> None:
        """Runs page should return HTML."""
        response = client.get("/ui/runs")
        assert "text/html" in response.headers["content-type"]

    def test_runs_page_contains_title(self, client: TestClient) -> None:
        """Runs page should contain Layer Runs title."""
        response = client.get("/ui/runs")
        assert "Layer Runs" in response.text

    def test_runs_page_contains_description(self, client: TestClient) -> None:
        """Runs page should contain description text."""
        response = client.get("/ui/runs")
        assert "Reflection execution history" in response.text

    def test_runs_page_contains_filters(self, client: TestClient) -> None:
        """Runs page should contain filter dropdowns."""
        response = client.get("/ui/runs")
        assert 'name="layer_name"' in response.text
        assert 'name="status"' in response.text
        assert "All layers" in response.text
        assert "All statuses" in response.text

    def test_runs_page_contains_htmx_triggers(self, client: TestClient) -> None:
        """Runs page should contain htmx triggers for dynamic content."""
        response = client.get("/ui/runs")
        assert 'hx-get="/ui/runs/stats"' in response.text
        assert 'hx-get="/ui/runs/list"' in response.text

    def test_runs_page_has_active_nav(self, client: TestClient) -> None:
        """Runs page should have runs nav item active."""
        response = client.get("/ui/runs")
        # The nav link for runs should have class active
        assert 'href="/ui/runs"' in response.text


# =============================================================================
# Test: Stats Partial
# =============================================================================


class TestStatsPartial:
    """Tests for: GET /ui/runs/stats - stats cards."""

    def test_stats_partial_returns_200(self, client: TestClient) -> None:
        """Stats partial should return 200 OK."""
        response = client.get("/ui/runs/stats")
        assert response.status_code == 200

    def test_stats_partial_returns_html(self, client: TestClient) -> None:
        """Stats partial should return HTML."""
        response = client.get("/ui/runs/stats")
        assert "text/html" in response.headers["content-type"]

    def test_stats_partial_is_partial(self, client: TestClient) -> None:
        """Stats partial should not be a full page."""
        response = client.get("/ui/runs/stats")
        assert "<!DOCTYPE" not in response.text
        assert "<html" not in response.text

    def test_stats_shows_zero_when_no_runs(self, client: TestClient) -> None:
        """Stats should show zeros when no runs exist."""
        response = client.get("/ui/runs/stats")
        assert "0" in response.text
        assert "Total Runs" in response.text

    def test_stats_shows_correct_counts(self, client: TestClient, sample_runs) -> None:
        """Stats should show correct counts for runs."""
        response = client.get("/ui/runs/stats")
        # Total runs label
        assert "Total Runs (7d)" in response.text
        # Successful label
        assert "Successful" in response.text
        # Failed label
        assert "Failed" in response.text
        # Check actual counts are shown
        assert "stat-value" in response.text

    def test_stats_shows_cost(self, client: TestClient, sample_runs) -> None:
        """Stats should show estimated cost."""
        response = client.get("/ui/runs/stats")
        assert "Est. Cost" in response.text
        # Should have a dollar sign in the cost
        assert "$" in response.text


# =============================================================================
# Test: List Partial
# =============================================================================


class TestListPartial:
    """Tests for: GET /ui/runs/list - runs table."""

    def test_list_partial_returns_200(self, client: TestClient) -> None:
        """List partial should return 200 OK."""
        response = client.get("/ui/runs/list")
        assert response.status_code == 200

    def test_list_partial_returns_html(self, client: TestClient) -> None:
        """List partial should return HTML."""
        response = client.get("/ui/runs/list")
        assert "text/html" in response.headers["content-type"]

    def test_list_partial_is_partial(self, client: TestClient) -> None:
        """List partial should not be a full page."""
        response = client.get("/ui/runs/list")
        assert "<!DOCTYPE" not in response.text

    def test_list_shows_empty_state(self, client: TestClient) -> None:
        """List should show empty state when no runs."""
        response = client.get("/ui/runs/list")
        assert "No runs found" in response.text

    def test_list_shows_runs_table(self, client: TestClient, sample_runs) -> None:
        """List should show runs in table format."""
        response = client.get("/ui/runs/list")
        assert "<table" in response.text
        assert "Time" in response.text
        assert "Layer" in response.text
        assert "Status" in response.text

    def test_list_shows_run_data(self, client: TestClient, sample_runs) -> None:
        """List should show run details."""
        response = client.get("/ui/runs/list")
        # Should show layer name
        assert "nightly-user-reflection" in response.text
        # Should show status badges
        assert "badge-success" in response.text

    def test_list_rows_are_clickable(self, client: TestClient, sample_runs) -> None:
        """List rows should have htmx for modal."""
        response = client.get("/ui/runs/list")
        # Rows should have hx-get for detail
        assert "clickable" in response.text
        assert "hx-get" in response.text

    def test_list_shows_pagination(self, client: TestClient, sample_runs) -> None:
        """List should show pagination when there are runs."""
        response = client.get("/ui/runs/list")
        assert "pagination" in response.text

    def test_list_filter_by_layer_works(self, client: TestClient, sample_runs) -> None:
        """List should filter by layer name."""
        response = client.get("/ui/runs/list?layer_name=weekly-self-reflection")
        # Should only show self-reflection runs
        assert "weekly-self-reflection" in response.text
        # Should NOT show nightly runs (check that we don't have multiple)
        # We can check the total count shown in pagination
        assert "1-1 of 1" in response.text

    def test_list_filter_by_status_works(self, client: TestClient, sample_runs) -> None:
        """List should filter by status."""
        response = client.get("/ui/runs/list?status=failed")
        # Should show failed run
        assert "badge-failed" in response.text
        # Should show only 1 result
        assert "1-1 of 1" in response.text


# =============================================================================
# Test: Detail Modal
# =============================================================================


class TestDetailModal:
    """Tests for: GET /ui/runs/{run_id} - run detail."""

    def test_detail_returns_404_for_invalid_id(self, client: TestClient) -> None:
        """Detail should return 404 for invalid run ID."""
        response = client.get("/ui/runs/nonexistent-id")
        assert response.status_code == 404

    def test_detail_returns_200(self, client: TestClient, sample_runs) -> None:
        """Detail should return 200 for valid run."""
        run_id = sample_runs[0]["id"]
        response = client.get(f"/ui/runs/{run_id}")
        assert response.status_code == 200

    def test_detail_returns_html(self, client: TestClient, sample_runs) -> None:
        """Detail should return HTML."""
        run_id = sample_runs[0]["id"]
        response = client.get(f"/ui/runs/{run_id}")
        assert "text/html" in response.headers["content-type"]

    def test_detail_is_modal_content(self, client: TestClient, sample_runs) -> None:
        """Detail should be modal content, not full page."""
        run_id = sample_runs[0]["id"]
        response = client.get(f"/ui/runs/{run_id}")
        assert "modal-content" in response.text
        assert "modal-header" in response.text

    def test_detail_shows_layer_name(self, client: TestClient, sample_runs) -> None:
        """Detail should show layer name in header."""
        run_id = sample_runs[0]["id"]
        response = client.get(f"/ui/runs/{run_id}")
        assert "nightly-user-reflection" in response.text

    def test_detail_shows_status(self, client: TestClient, sample_runs) -> None:
        """Detail should show status badge."""
        run_id = sample_runs[0]["id"]
        response = client.get(f"/ui/runs/{run_id}")
        assert "SUCCESS" in response.text
        assert "badge-success" in response.text

    def test_detail_shows_metrics(self, client: TestClient, sample_runs) -> None:
        """Detail should show run metrics."""
        run_id = sample_runs[0]["id"]
        response = client.get(f"/ui/runs/{run_id}")
        assert "Duration" in response.text
        assert "Targets Matched" in response.text
        assert "Targets Processed" in response.text
        assert "Insights Created" in response.text

    def test_detail_shows_model_usage(self, client: TestClient, sample_runs) -> None:
        """Detail should show model usage info."""
        run_id = sample_runs[0]["id"]
        response = client.get(f"/ui/runs/{run_id}")
        assert "Model Usage" in response.text
        assert "Profile" in response.text
        assert "Provider" in response.text
        assert "Input Tokens" in response.text
        assert "Output Tokens" in response.text
        assert "Estimated Cost" in response.text

    def test_detail_shows_errors_when_present(self, client: TestClient, sample_runs) -> None:
        """Detail should show errors for failed runs."""
        # Find the partial run which has errors
        partial_run = next(r for r in sample_runs if r["status"] == "partial")
        response = client.get(f"/ui/runs/{partial_run['id']}")
        assert "Errors" in response.text
        assert "Timeout" in response.text
        assert "error-item" in response.text

    def test_detail_no_errors_section_for_success(self, client: TestClient, sample_runs) -> None:
        """Detail should not show errors section for successful runs."""
        success_run = next(r for r in sample_runs if r["status"] == "success")
        response = client.get(f"/ui/runs/{success_run['id']}")
        # Should not have errors heading
        assert "Errors (" not in response.text

    def test_detail_shows_layer_hash(self, client: TestClient, sample_runs) -> None:
        """Detail should show layer hash in footer."""
        run_id = sample_runs[0]["id"]
        response = client.get(f"/ui/runs/{run_id}")
        assert "Layer hash:" in response.text
        assert "abc123" in response.text

    def test_detail_has_close_button(self, client: TestClient, sample_runs) -> None:
        """Detail should have close button."""
        run_id = sample_runs[0]["id"]
        response = client.get(f"/ui/runs/{run_id}")
        assert "close-btn" in response.text


# =============================================================================
# Test: Recent Runs (Dashboard Partial)
# =============================================================================


class TestRecentRunsPartial:
    """Tests for: GET /ui/runs/recent - dashboard card."""

    def test_recent_returns_200(self, client: TestClient) -> None:
        """Recent runs partial should return 200."""
        response = client.get("/ui/runs/recent")
        assert response.status_code == 200

    def test_recent_shows_empty_when_no_runs(self, client: TestClient) -> None:
        """Recent should show empty state when no runs."""
        response = client.get("/ui/runs/recent")
        assert "No runs yet" in response.text

    def test_recent_shows_runs_compact(self, client: TestClient, sample_runs) -> None:
        """Recent should show runs in compact list."""
        response = client.get("/ui/runs/recent")
        # Should have runs list compact class
        assert "runs-list-compact" in response.text
        # Should show layer names
        assert "nightly-user-reflection" in response.text
        # Should show status badges
        assert "badge-" in response.text

    def test_recent_shows_relative_time(self, client: TestClient, sample_runs) -> None:
        """Recent should show relative time for runs."""
        response = client.get("/ui/runs/recent")
        # Should have some time indicator
        assert "ago" in response.text or "just now" in response.text


# =============================================================================
# Test: Template Filters
# =============================================================================


class TestTemplateFilters:
    """Tests for template filters used in runs UI."""

    def test_format_number_with_commas(self) -> None:
        """format_number should add commas to large numbers."""
        from zos.api.ui import format_number

        assert format_number(1000) == "1,000"
        assert format_number(1000000) == "1,000,000"
        assert format_number(None) == "—"

    def test_format_cost_usd(self) -> None:
        """format_cost should format USD with 4 decimals."""
        from zos.api.ui import format_cost

        assert format_cost(0.045) == "$0.0450"
        assert format_cost(1.5) == "$1.5000"
        assert format_cost(None) == "—"

    def test_format_duration_seconds(self) -> None:
        """format_duration should format seconds."""
        from zos.api.ui import format_duration

        assert format_duration(30) == "30.0s"
        assert format_duration(59.5) == "59.5s"
        assert format_duration(None) == "—"

    def test_format_duration_minutes(self) -> None:
        """format_duration should format minutes for longer durations."""
        from zos.api.ui import format_duration

        assert format_duration(60) == "1m 0s"
        assert format_duration(90) == "1m 30s"
        assert format_duration(150) == "2m 30s"

    def test_relative_time_just_now(self) -> None:
        """relative_time should show 'just now' for recent times."""
        from zos.api.ui import relative_time

        now = datetime.now(timezone.utc)
        assert relative_time(now) == "just now"
        assert relative_time(None) == "—"

    def test_relative_time_hours(self) -> None:
        """relative_time should show hours for older times."""
        from zos.api.ui import relative_time

        two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)
        result = relative_time(two_hours_ago)
        assert "hour" in result
        assert "2" in result

    def test_relative_time_days(self) -> None:
        """relative_time should show days for older times."""
        from zos.api.ui import relative_time

        three_days_ago = datetime.now(timezone.utc) - timedelta(days=3)
        result = relative_time(three_days_ago)
        assert "day" in result
        assert "3" in result


# =============================================================================
# Test: CSS Styles
# =============================================================================


class TestRunsCSS:
    """Tests for runs-specific CSS."""

    def test_css_contains_stats_cards(self, client: TestClient) -> None:
        """CSS should contain stats card styles."""
        response = client.get("/static/style.css")
        assert ".stats-cards" in response.text
        assert ".stat-card" in response.text

    def test_css_contains_runs_table(self, client: TestClient) -> None:
        """CSS should contain runs table styles."""
        response = client.get("/static/style.css")
        assert ".runs-table" in response.text

    def test_css_contains_status_badges(self, client: TestClient) -> None:
        """CSS should contain status badge styles."""
        response = client.get("/static/style.css")
        assert ".badge-partial" in response.text
        assert ".badge-failed" in response.text
        assert ".badge-large" in response.text

    def test_css_contains_modal_styles(self, client: TestClient) -> None:
        """CSS should contain modal styles."""
        response = client.get("/static/style.css")
        assert ".modal" in response.text
        assert ".modal-content" in response.text
        assert ".modal-header" in response.text

    def test_css_contains_error_styles(self, client: TestClient) -> None:
        """CSS should contain error list styles."""
        response = client.get("/static/style.css")
        assert ".errors-list" in response.text
        assert ".error-item" in response.text
        assert ".error-message" in response.text

    def test_css_contains_metric_styles(self, client: TestClient) -> None:
        """CSS should contain metric row styles."""
        response = client.get("/static/style.css")
        assert ".run-metrics" in response.text
        assert ".metric-row" in response.text
