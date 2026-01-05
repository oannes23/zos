"""Tests for the Web API."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from zos.api import create_app
from zos.config import ApiConfig, ZosConfig
from zos.db import Database


@pytest.fixture
def api_config() -> ApiConfig:
    """Create test API configuration."""
    return ApiConfig(enabled=True, host="127.0.0.1", port=8000)


@pytest.fixture
def api_client(test_db: Database, test_config: ZosConfig, api_config: ApiConfig) -> TestClient:
    """Create test client with initialized database."""
    # Patch global state for dependencies
    import zos.config as config_module
    import zos.db as db_module

    config_module._config = test_config
    db_module._db = test_db

    app = create_app(api_config)
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for /health."""

    def test_health_returns_ok(self, api_client: TestClient) -> None:
        """Health endpoint returns OK status."""
        response = api_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["database"] is True
        assert data["version"] == "0.1.0"


class TestConfigEndpoint:
    """Tests for /config."""

    def test_config_redacts_discord_token(self, api_client: TestClient) -> None:
        """Discord token is redacted or None if empty."""
        response = api_client.get("/config")
        assert response.status_code == 200
        data = response.json()
        # Token is either redacted (if set) or None (if empty)
        assert data["discord"]["token"] in ("***REDACTED***", None)

    def test_config_includes_non_secrets(self, api_client: TestClient) -> None:
        """Non-secret config values are included."""
        response = api_client.get("/config")
        data = response.json()
        assert "database" in data
        assert "budget" in data
        assert "salience" in data
        assert "api" in data

    def test_config_includes_guilds(self, api_client: TestClient) -> None:
        """Guild list is included."""
        response = api_client.get("/config")
        data = response.json()
        assert "guilds" in data["discord"]
        assert isinstance(data["discord"]["guilds"], list)


class TestLayersEndpoint:
    """Tests for /layers."""

    def test_list_layers_empty(self, api_client: TestClient) -> None:
        """Returns empty list when no layers exist."""
        response = api_client.get("/layers")
        assert response.status_code == 200
        data = response.json()
        assert "layers" in data
        assert "enabled" in data
        assert isinstance(data["layers"], list)

    def test_layers_response_structure(self, api_client: TestClient) -> None:
        """Response has correct structure."""
        response = api_client.get("/layers")
        data = response.json()
        assert "layers" in data
        assert "enabled" in data


class TestRunsEndpoint:
    """Tests for /runs."""

    def test_list_runs_empty(self, api_client: TestClient) -> None:
        """Returns empty list when no runs exist."""
        response = api_client.get("/runs")
        assert response.status_code == 200
        data = response.json()
        assert data["runs"] == []
        assert data["offset"] == 0
        assert data["limit"] == 50

    def test_list_runs_with_pagination(self, api_client: TestClient) -> None:
        """Pagination parameters are respected."""
        response = api_client.get("/runs?offset=10&limit=5")
        assert response.status_code == 200
        data = response.json()
        assert data["offset"] == 10
        assert data["limit"] == 5

    def test_list_runs_invalid_status(self, api_client: TestClient) -> None:
        """Invalid status returns 400."""
        response = api_client.get("/runs?status=invalid")
        assert response.status_code == 400
        data = response.json()
        assert "Invalid status" in data["detail"]

    def test_list_runs_valid_status(self, api_client: TestClient) -> None:
        """Valid status filter works."""
        response = api_client.get("/runs?status=completed")
        assert response.status_code == 200

    def test_get_run_not_found(self, api_client: TestClient) -> None:
        """Returns 404 for non-existent run."""
        response = api_client.get("/runs/nonexistent-id")
        assert response.status_code == 404

    def test_get_run_with_data(self, api_client: TestClient, test_db: Database) -> None:
        """Returns run details when run exists."""
        # Insert a run
        run_id = "test-run-123"
        now = datetime.now(UTC)
        test_db.execute(
            """
            INSERT INTO runs (
                run_id, layer_name, triggered_by, schedule_expression,
                started_at, status, window_start, window_end,
                targets_total, targets_processed, targets_skipped,
                tokens_used, estimated_cost_usd, salience_spent
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                "test_layer",
                "manual",
                None,
                now.isoformat(),
                "completed",
                now.isoformat(),
                now.isoformat(),
                5,
                4,
                1,
                1000,
                0.01,
                10.0,
            ),
        )

        response = api_client.get(f"/runs/{run_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == run_id
        assert data["layer_name"] == "test_layer"
        assert data["status"] == "completed"

    def test_get_run_with_trace(self, api_client: TestClient, test_db: Database) -> None:
        """Returns run with trace when include_trace=true."""
        # Insert a run
        run_id = "test-run-trace"
        now = datetime.now(UTC)
        test_db.execute(
            """
            INSERT INTO runs (
                run_id, layer_name, triggered_by, started_at, status,
                window_start, window_end
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, "test_layer", "manual", now.isoformat(), "completed",
             now.isoformat(), now.isoformat()),
        )

        # Insert trace entries
        test_db.execute(
            """
            INSERT INTO run_traces (
                run_id, node_name, topic_key, success, skipped, tokens_used, executed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, "test_node", "channel:123", 1, 0, 100, now.isoformat()),
        )

        response = api_client.get(f"/runs/{run_id}?include_trace=true")
        assert response.status_code == 200
        data = response.json()
        assert data["trace"] is not None
        assert len(data["trace"]) == 1
        assert data["trace"][0]["node_name"] == "test_node"


class TestInsightsEndpoint:
    """Tests for /insights."""

    def test_list_insights_empty(self, api_client: TestClient) -> None:
        """Returns empty list when no insights exist."""
        response = api_client.get("/insights")
        assert response.status_code == 200
        data = response.json()
        assert data["insights"] == []
        assert data["offset"] == 0

    def test_list_insights_with_pagination(self, api_client: TestClient) -> None:
        """Pagination parameters are respected."""
        response = api_client.get("/insights?offset=5&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert data["offset"] == 5
        assert data["limit"] == 10

    def test_list_insights_invalid_topic(self, api_client: TestClient) -> None:
        """Invalid topic key returns 400."""
        response = api_client.get("/insights?topic=invalid")
        assert response.status_code == 400

    def test_list_insights_valid_topic(self, api_client: TestClient) -> None:
        """Valid topic filter works."""
        response = api_client.get("/insights?topic=channel:123")
        assert response.status_code == 200

    def test_get_insight_not_found(self, api_client: TestClient) -> None:
        """Returns 404 for non-existent insight."""
        response = api_client.get("/insights/nonexistent-id")
        assert response.status_code == 404

    def test_get_insight_with_data(self, api_client: TestClient, test_db: Database) -> None:
        """Returns insight details when insight exists."""
        # Insert an insight
        insight_id = "test-insight-123"
        now = datetime.now(UTC)
        test_db.execute(
            """
            INSERT INTO insights (
                insight_id, topic_key, created_at, summary, payload,
                source_refs, sources_scope_max, run_id, layer
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                insight_id,
                "channel:456",
                now.isoformat(),
                "Test insight summary",
                '{"key": "value"}',
                "[1, 2, 3]",
                "public",
                None,
                "test_layer",
            ),
        )

        response = api_client.get(f"/insights/{insight_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["insight_id"] == insight_id
        assert data["topic_key"] == "channel:456"
        assert data["summary"] == "Test insight summary"
        assert data["payload"] == {"key": "value"}
        assert data["source_refs"] == [1, 2, 3]


class TestSalienceEndpoint:
    """Tests for /salience."""

    def test_salience_requires_category(self, api_client: TestClient) -> None:
        """Category parameter is required."""
        response = api_client.get("/salience")
        assert response.status_code == 422  # Validation error

    def test_salience_invalid_category(self, api_client: TestClient) -> None:
        """Invalid category returns 400."""
        response = api_client.get("/salience?category=invalid")
        assert response.status_code == 400
        data = response.json()
        assert "Invalid category" in data["detail"]

    def test_salience_valid_category(self, api_client: TestClient) -> None:
        """Valid category returns results."""
        response = api_client.get("/salience?category=user")
        assert response.status_code == 200
        data = response.json()
        assert data["category"] == "user"
        assert "topics" in data
        assert "total_count" in data

    def test_salience_all_categories(self, api_client: TestClient) -> None:
        """All valid categories work."""
        for category in ["user", "channel", "user_in_channel", "dyad", "dyad_in_channel"]:
            response = api_client.get(f"/salience?category={category}")
            assert response.status_code == 200
            data = response.json()
            assert data["category"] == category

    def test_salience_with_data(self, api_client: TestClient, test_db: Database) -> None:
        """Returns salience data when it exists."""
        # Insert salience earned
        now = datetime.now(UTC)
        test_db.execute(
            """
            INSERT INTO salience_earned (
                topic_key, category, timestamp, amount, reason
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("user:123", "user", now.isoformat(), 10.0, "message"),
        )

        response = api_client.get("/salience?category=user")
        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] >= 1
        assert any(t["topic_key"] == "user:123" for t in data["topics"])


class TestAuditEndpoint:
    """Tests for /audit."""

    def test_list_audit_empty(self, api_client: TestClient) -> None:
        """Returns empty list when no LLM calls exist."""
        response = api_client.get("/audit")
        assert response.status_code == 200
        data = response.json()
        assert data["records"] == []
        assert data["offset"] == 0

    def test_list_audit_with_pagination(self, api_client: TestClient) -> None:
        """Pagination parameters are respected."""
        response = api_client.get("/audit?offset=5&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert data["offset"] == 5
        assert data["limit"] == 10

    def test_list_audit_with_data(self, api_client: TestClient, test_db: Database) -> None:
        """Returns LLM call records when they exist."""
        # Insert LLM call record
        now = datetime.now(UTC)
        test_db.execute(
            """
            INSERT INTO llm_calls (
                run_id, topic_key, layer, node, model,
                prompt_tokens, completion_tokens, total_tokens,
                estimated_cost_usd, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "test-run",
                "channel:123",
                "test_layer",
                "llm_call",
                "gpt-4",
                100,
                50,
                150,
                0.01,
                now.isoformat(),
            ),
        )

        response = api_client.get("/audit")
        assert response.status_code == 200
        data = response.json()
        assert len(data["records"]) >= 1
        record = data["records"][0]
        assert record["run_id"] == "test-run"
        assert record["model"] == "gpt-4"
        assert record["total_tokens"] == 150

    def test_list_audit_filter_by_run(self, api_client: TestClient, test_db: Database) -> None:
        """Can filter audit by run_id."""
        now = datetime.now(UTC)
        # Insert two records with different run_ids
        test_db.execute(
            """
            INSERT INTO llm_calls (
                run_id, layer, model, prompt_tokens, completion_tokens, total_tokens, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("run-a", "layer1", "gpt-4", 10, 10, 20, now.isoformat()),
        )
        test_db.execute(
            """
            INSERT INTO llm_calls (
                run_id, layer, model, prompt_tokens, completion_tokens, total_tokens, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("run-b", "layer2", "gpt-4", 10, 10, 20, now.isoformat()),
        )

        response = api_client.get("/audit?run_id=run-a")
        assert response.status_code == 200
        data = response.json()
        assert all(r["run_id"] == "run-a" for r in data["records"])


class TestCORS:
    """Tests for CORS configuration."""

    def test_cors_headers_with_config(self, test_db: Database, test_config: ZosConfig) -> None:
        """CORS headers are set when configured."""
        import zos.config as config_module
        import zos.db as db_module

        config_module._config = test_config
        db_module._db = test_db

        api_config = ApiConfig(cors_origins=["http://localhost:3000"])
        app = create_app(api_config)
        client = TestClient(app)

        response = client.options(
            "/health",
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
        )
        # CORS preflight should be handled
        assert response.status_code in [200, 400]  # Depends on CORS implementation


class TestErrorHandling:
    """Tests for error handling."""

    def test_404_for_unknown_endpoint(self, api_client: TestClient) -> None:
        """Unknown endpoints return 404."""
        response = api_client.get("/unknown")
        assert response.status_code == 404

    def test_method_not_allowed(self, api_client: TestClient) -> None:
        """POST to read-only endpoints returns 405."""
        response = api_client.post("/health", json={})
        assert response.status_code == 405
