"""Tests for Layer Runs API endpoints.

Tests the layer run query endpoints for operational visibility.
Layer runs are the audit trail of reflection execution.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from zos.api import create_app
from zos.config import Config
from zos.database import create_tables, generate_id, get_engine, layer_runs
from zos.migrations import migrate
from zos.models import LayerRunStatus
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
# Test: List Runs Endpoint
# =============================================================================


class TestListRuns:
    """Tests for: GET /runs lists recent layer runs."""

    def test_list_returns_200(self, client: TestClient) -> None:
        """List endpoint should return 200 OK."""
        response = client.get("/runs")
        assert response.status_code == 200

    def test_list_returns_empty_when_no_runs(self, client: TestClient) -> None:
        """List should return empty list when no runs exist."""
        response = client.get("/runs")
        data = response.json()
        assert data["runs"] == []
        assert data["total"] == 0

    def test_list_returns_runs(self, client: TestClient, sample_runs) -> None:
        """List should return runs with proper structure."""
        response = client.get("/runs")
        data = response.json()

        assert data["total"] == 5
        assert len(data["runs"]) == 5
        assert data["offset"] == 0
        assert data["limit"] == 20

    def test_list_run_summary_fields(self, client: TestClient, sample_runs) -> None:
        """Run summary should include expected fields."""
        response = client.get("/runs")
        run = response.json()["runs"][0]

        # Check all required fields are present
        assert "id" in run
        assert "layer_name" in run
        assert "status" in run
        assert "started_at" in run
        assert "completed_at" in run
        assert "duration_seconds" in run
        assert "targets_processed" in run
        assert "insights_created" in run
        assert "tokens_total" in run
        assert "estimated_cost_usd" in run

    def test_list_ordered_by_start_time_desc(
        self, client: TestClient, sample_runs
    ) -> None:
        """Runs should be ordered by start time descending."""
        response = client.get("/runs")
        runs = response.json()["runs"]

        # First run should be most recent
        for i in range(len(runs) - 1):
            current = datetime.fromisoformat(runs[i]["started_at"].replace("Z", "+00:00"))
            next_run = datetime.fromisoformat(runs[i + 1]["started_at"].replace("Z", "+00:00"))
            assert current >= next_run

    def test_duration_calculated_correctly(
        self, client: TestClient, sample_runs
    ) -> None:
        """Duration should be calculated from completed - started."""
        response = client.get("/runs")
        runs = response.json()["runs"]

        # Find a completed run
        completed_run = next(r for r in runs if r["completed_at"] is not None)

        started = datetime.fromisoformat(
            completed_run["started_at"].replace("Z", "+00:00")
        )
        completed = datetime.fromisoformat(
            completed_run["completed_at"].replace("Z", "+00:00")
        )
        expected_duration = (completed - started).total_seconds()

        assert abs(completed_run["duration_seconds"] - expected_duration) < 1.0


# =============================================================================
# Test: Filter by Layer Name
# =============================================================================


class TestFilterByLayerName:
    """Tests for: Filter by layer name works."""

    def test_filter_by_layer_name(self, client: TestClient, sample_runs) -> None:
        """Filter should return only runs for specified layer."""
        response = client.get("/runs?layer_name=weekly-self-reflection")
        data = response.json()

        assert data["total"] == 1
        assert all(r["layer_name"] == "weekly-self-reflection" for r in data["runs"])

    def test_filter_by_nonexistent_layer(self, client: TestClient, sample_runs) -> None:
        """Filter by nonexistent layer should return empty list."""
        response = client.get("/runs?layer_name=nonexistent-layer")
        data = response.json()

        assert data["total"] == 0
        assert data["runs"] == []


# =============================================================================
# Test: Filter by Status
# =============================================================================


class TestFilterByStatus:
    """Tests for: Filter by status works."""

    def test_filter_by_success_status(self, client: TestClient, sample_runs) -> None:
        """Filter by success should return only successful runs."""
        response = client.get("/runs?status=success")
        data = response.json()

        assert data["total"] == 2
        assert all(r["status"] == "success" for r in data["runs"])

    def test_filter_by_failed_status(self, client: TestClient, sample_runs) -> None:
        """Filter by failed should return only failed runs."""
        response = client.get("/runs?status=failed")
        data = response.json()

        assert data["total"] == 1
        assert data["runs"][0]["status"] == "failed"

    def test_filter_by_dry_status(self, client: TestClient, sample_runs) -> None:
        """Filter by dry should return only dry runs."""
        response = client.get("/runs?status=dry")
        data = response.json()

        assert data["total"] == 1
        assert data["runs"][0]["status"] == "dry"

    def test_filter_by_partial_status(self, client: TestClient, sample_runs) -> None:
        """Filter by partial should return only partial runs."""
        response = client.get("/runs?status=partial")
        data = response.json()

        assert data["total"] == 1
        assert data["runs"][0]["status"] == "partial"


# =============================================================================
# Test: Get Run Details
# =============================================================================


class TestGetRunDetails:
    """Tests for: GET /runs/{run_id} returns run details with errors."""

    def test_get_run_returns_200(self, client: TestClient, sample_runs) -> None:
        """Get run should return 200 when run exists."""
        run_id = sample_runs[0]["id"]
        response = client.get(f"/runs/{run_id}")
        assert response.status_code == 200

    def test_get_run_returns_404_when_not_found(self, client: TestClient) -> None:
        """Get run should return 404 when run doesn't exist."""
        response = client.get("/runs/nonexistent-id")
        assert response.status_code == 404

    def test_get_run_detail_fields(self, client: TestClient, sample_runs) -> None:
        """Run detail should include all fields."""
        run_id = sample_runs[0]["id"]
        response = client.get(f"/runs/{run_id}")
        data = response.json()

        # Check all detail fields are present
        assert data["id"] == run_id
        assert "layer_name" in data
        assert "layer_hash" in data
        assert "status" in data
        assert "started_at" in data
        assert "completed_at" in data
        assert "duration_seconds" in data
        assert "targets_matched" in data
        assert "targets_processed" in data
        assert "targets_skipped" in data
        assert "insights_created" in data
        assert "model_profile" in data
        assert "model_provider" in data
        assert "model_name" in data
        assert "tokens_input" in data
        assert "tokens_output" in data
        assert "tokens_total" in data
        assert "estimated_cost_usd" in data
        assert "errors" in data

    def test_get_run_includes_errors(self, client: TestClient, sample_runs) -> None:
        """Run detail should include error information."""
        # Find the partial run which has errors
        partial_run = next(r for r in sample_runs if r["status"] == "partial")
        response = client.get(f"/runs/{partial_run['id']}")
        data = response.json()

        assert data["errors"] is not None
        assert len(data["errors"]) == 1
        assert data["errors"][0]["topic"] == "server:123:user:456"
        assert data["errors"][0]["error"] == "Timeout"

    def test_get_run_errors_null_when_none(
        self, client: TestClient, sample_runs
    ) -> None:
        """Run detail should have null errors when none occurred."""
        success_run = next(r for r in sample_runs if r["status"] == "success")
        response = client.get(f"/runs/{success_run['id']}")
        data = response.json()

        assert data["errors"] is None


# =============================================================================
# Test: Statistics Endpoint
# =============================================================================


class TestRunStats:
    """Tests for: GET /runs/stats/summary returns aggregate statistics."""

    def test_stats_returns_200(self, client: TestClient) -> None:
        """Stats endpoint should return 200 OK."""
        response = client.get("/runs/stats/summary")
        assert response.status_code == 200

    def test_stats_structure(self, client: TestClient, sample_runs) -> None:
        """Stats should have proper structure."""
        response = client.get("/runs/stats/summary")
        data = response.json()

        assert "period_days" in data
        assert "total_runs" in data
        assert "successful_runs" in data
        assert "failed_runs" in data
        assert "dry_runs" in data
        assert "total_insights" in data
        assert "total_tokens" in data
        assert "total_cost_usd" in data
        assert "by_layer" in data

    def test_stats_counts_correct(self, client: TestClient, sample_runs) -> None:
        """Stats should have correct counts."""
        response = client.get("/runs/stats/summary")
        data = response.json()

        assert data["total_runs"] == 5
        assert data["successful_runs"] == 2
        assert data["failed_runs"] == 1
        assert data["dry_runs"] == 1

    def test_stats_aggregates_insights(self, client: TestClient, sample_runs) -> None:
        """Stats should correctly sum insights."""
        response = client.get("/runs/stats/summary")
        data = response.json()

        # 8 + 6 + 1 + 0 + 0 = 15
        assert data["total_insights"] == 15

    def test_stats_aggregates_tokens(self, client: TestClient, sample_runs) -> None:
        """Stats should correctly sum tokens."""
        response = client.get("/runs/stats/summary")
        data = response.json()

        # 15000 + 12000 + 7000 = 34000
        assert data["total_tokens"] == 34000

    def test_stats_aggregates_cost(self, client: TestClient, sample_runs) -> None:
        """Stats should correctly sum costs."""
        response = client.get("/runs/stats/summary")
        data = response.json()

        # 0.045 + 0.036 + 0.15 = 0.231
        assert abs(data["total_cost_usd"] - 0.231) < 0.001

    def test_stats_by_layer_breakdown(self, client: TestClient, sample_runs) -> None:
        """Stats should include per-layer breakdown."""
        response = client.get("/runs/stats/summary")
        data = response.json()

        assert "nightly-user-reflection" in data["by_layer"]
        assert "weekly-self-reflection" in data["by_layer"]

        nightly = data["by_layer"]["nightly-user-reflection"]
        assert nightly["runs"] == 4
        assert nightly["insights"] == 14  # 8 + 6 + 0 + 0

        weekly = data["by_layer"]["weekly-self-reflection"]
        assert weekly["runs"] == 1
        assert weekly["insights"] == 1

    def test_stats_days_parameter(self, client: TestClient, sample_runs) -> None:
        """Stats should respect days parameter."""
        # Only runs within last 2 days
        response = client.get("/runs/stats/summary?days=2")
        data = response.json()

        assert data["period_days"] == 2
        # Only the 2 most recent runs are within 2 days
        assert data["total_runs"] == 2

    def test_stats_days_validation(self, client: TestClient) -> None:
        """Stats days parameter should be validated."""
        # Too small
        response = client.get("/runs/stats/summary?days=0")
        assert response.status_code == 422

        # Too large
        response = client.get("/runs/stats/summary?days=100")
        assert response.status_code == 422


# =============================================================================
# Test: Dry Runs Distinguishable
# =============================================================================


class TestDryRunsDistinguishable:
    """Tests for: Dry runs distinguishable."""

    def test_dry_runs_have_status(self, client: TestClient, sample_runs) -> None:
        """Dry runs should have status 'dry'."""
        response = client.get("/runs?status=dry")
        data = response.json()

        assert data["total"] == 1
        assert data["runs"][0]["status"] == "dry"

    def test_dry_runs_have_zero_insights(self, client: TestClient, sample_runs) -> None:
        """Dry runs should have zero insights created."""
        response = client.get("/runs?status=dry")
        run = response.json()["runs"][0]

        assert run["insights_created"] == 0

    def test_dry_runs_counted_in_stats(self, client: TestClient, sample_runs) -> None:
        """Dry runs should be counted separately in stats."""
        response = client.get("/runs/stats/summary")
        data = response.json()

        assert data["dry_runs"] == 1


# =============================================================================
# Test: Token Usage and Cost Estimates
# =============================================================================


class TestTokenUsageAndCost:
    """Tests for: Includes token usage and cost estimates."""

    def test_summary_includes_tokens(self, client: TestClient, sample_runs) -> None:
        """Run summary should include total tokens."""
        response = client.get("/runs")
        runs = response.json()["runs"]

        success_run = next(r for r in runs if r["status"] == "success")
        assert success_run["tokens_total"] == 15000

    def test_summary_includes_cost(self, client: TestClient, sample_runs) -> None:
        """Run summary should include cost estimate."""
        response = client.get("/runs")
        runs = response.json()["runs"]

        success_run = next(r for r in runs if r["status"] == "success")
        assert success_run["estimated_cost_usd"] == 0.045

    def test_detail_includes_token_breakdown(
        self, client: TestClient, sample_runs
    ) -> None:
        """Run detail should include input/output token breakdown."""
        success_run = next(r for r in sample_runs if r["status"] == "success")
        response = client.get(f"/runs/{success_run['id']}")
        data = response.json()

        assert data["tokens_input"] == 10000
        assert data["tokens_output"] == 5000
        assert data["tokens_total"] == 15000

    def test_null_tokens_for_dry_runs(self, client: TestClient, sample_runs) -> None:
        """Dry runs may have null tokens."""
        dry_run = next(r for r in sample_runs if r["status"] == "dry")
        response = client.get(f"/runs/{dry_run['id']}")
        data = response.json()

        assert data["tokens_total"] is None


# =============================================================================
# Test: Pagination
# =============================================================================


class TestPagination:
    """Tests for pagination of layer runs."""

    def test_limit_parameter(self, client: TestClient, sample_runs) -> None:
        """Limit should restrict number of returned runs."""
        response = client.get("/runs?limit=2")
        data = response.json()

        assert len(data["runs"]) == 2
        assert data["total"] == 5
        assert data["limit"] == 2

    def test_offset_parameter(self, client: TestClient, sample_runs) -> None:
        """Offset should skip runs."""
        response = client.get("/runs?offset=2")
        data = response.json()

        assert len(data["runs"]) == 3  # 5 total - 2 skipped
        assert data["offset"] == 2

    def test_pagination_combined(self, client: TestClient, sample_runs) -> None:
        """Limit and offset should work together."""
        response = client.get("/runs?offset=1&limit=2")
        data = response.json()

        assert len(data["runs"]) == 2
        assert data["offset"] == 1
        assert data["limit"] == 2

    def test_limit_validation_max(self, client: TestClient) -> None:
        """Limit should be validated (max 100)."""
        response = client.get("/runs?limit=200")
        assert response.status_code == 422

    def test_offset_validation_min(self, client: TestClient) -> None:
        """Offset should be validated (min 0)."""
        response = client.get("/runs?offset=-1")
        assert response.status_code == 422


# =============================================================================
# Test: OpenAPI Documentation
# =============================================================================


class TestOpenAPIDocumentation:
    """Tests for OpenAPI documentation of runs endpoints."""

    def test_runs_in_openapi(self, client: TestClient) -> None:
        """Runs endpoints should appear in OpenAPI schema."""
        response = client.get("/openapi.json")
        data = response.json()

        assert "/runs" in data["paths"]
        assert "/runs/{run_id}" in data["paths"]
        assert "/runs/stats/summary" in data["paths"]

    def test_runs_tagged(self, client: TestClient) -> None:
        """Runs endpoints should be tagged 'layer-runs'."""
        response = client.get("/openapi.json")
        data = response.json()

        runs_path = data["paths"]["/runs"]["get"]
        assert "layer-runs" in runs_path["tags"]
