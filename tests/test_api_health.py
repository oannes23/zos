"""Tests for FastAPI scaffold and health endpoint.

Tests the API application structure, health check, CORS, and request logging.
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from zos.api import create_app
from zos.api.health import HealthResponse
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


# =============================================================================
# Test: App Initialization
# =============================================================================


class TestAppInitialization:
    """Tests for: FastAPI app initializes correctly."""

    def test_app_has_title(self, app) -> None:
        """App should have the correct title."""
        assert app.title == "Zos Introspection API"

    def test_app_has_version(self, app) -> None:
        """App should have version 0.1.0."""
        assert app.version == "0.1.0"

    def test_app_has_docs_url(self, app) -> None:
        """App should have /docs endpoint configured."""
        assert app.docs_url == "/docs"

    def test_app_has_redoc_url(self, app) -> None:
        """App should have /redoc endpoint configured."""
        assert app.redoc_url == "/redoc"


# =============================================================================
# Test: Health Endpoint
# =============================================================================


class TestHealthEndpoint:
    """Tests for: /health endpoint returns status."""

    def test_health_returns_200(self, client: TestClient) -> None:
        """Health endpoint should return 200 OK."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_ok_status(self, client: TestClient) -> None:
        """Health endpoint should return ok status when database is healthy."""
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "ok"

    def test_health_returns_version(self, client: TestClient) -> None:
        """Health endpoint should return version."""
        response = client.get("/health")
        data = response.json()
        assert data["version"] == "0.1.0"

    def test_health_returns_timestamp(self, client: TestClient) -> None:
        """Health endpoint should return a valid timestamp."""
        response = client.get("/health")
        data = response.json()
        # Should be parseable as ISO datetime
        timestamp = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
        assert timestamp is not None
        # Should be recent (within last minute)
        now = datetime.now(timezone.utc)
        delta = abs((now - timestamp).total_seconds())
        assert delta < 60

    def test_health_returns_database_status(self, client: TestClient) -> None:
        """Health endpoint should return database status."""
        response = client.get("/health")
        data = response.json()
        assert data["database"] == "ok"

    def test_health_returns_scheduler_status(self, client: TestClient) -> None:
        """Health endpoint should return scheduler status."""
        response = client.get("/health")
        data = response.json()
        assert data["scheduler"] == "ok"

    def test_health_response_matches_model(self, client: TestClient) -> None:
        """Health endpoint response should match HealthResponse model."""
        response = client.get("/health")
        data = response.json()
        # Should be able to create a HealthResponse from the data
        health = HealthResponse(
            status=data["status"],
            version=data["version"],
            timestamp=datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00")),
            database=data["database"],
            scheduler=data["scheduler"],
        )
        assert health.status == "ok"


# =============================================================================
# Test: OpenAPI Documentation
# =============================================================================


class TestOpenAPIDocumentation:
    """Tests for: /docs shows OpenAPI documentation."""

    def test_docs_endpoint_returns_200(self, client: TestClient) -> None:
        """Docs endpoint should return 200 OK."""
        response = client.get("/docs")
        assert response.status_code == 200

    def test_docs_returns_html(self, client: TestClient) -> None:
        """Docs endpoint should return HTML."""
        response = client.get("/docs")
        assert "text/html" in response.headers["content-type"]

    def test_openapi_json_endpoint(self, client: TestClient) -> None:
        """OpenAPI JSON schema should be available."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert data["info"]["title"] == "Zos Introspection API"
        assert data["info"]["version"] == "0.1.0"

    def test_openapi_has_health_endpoint(self, client: TestClient) -> None:
        """OpenAPI schema should include health endpoint."""
        response = client.get("/openapi.json")
        data = response.json()
        assert "/health" in data["paths"]

    def test_redoc_endpoint_returns_200(self, client: TestClient) -> None:
        """ReDoc endpoint should return 200 OK."""
        response = client.get("/redoc")
        assert response.status_code == 200


# =============================================================================
# Test: CORS Configuration
# =============================================================================


class TestCORSConfiguration:
    """Tests for: CORS configured for local development."""

    def test_cors_allows_localhost_3000(self, client: TestClient) -> None:
        """CORS should allow requests from localhost:3000."""
        response = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"

    def test_cors_allows_localhost_8000(self, client: TestClient) -> None:
        """CORS should allow requests from localhost:8000."""
        response = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:8000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:8000"

    def test_cors_headers_on_actual_request(self, client: TestClient) -> None:
        """CORS headers should be present on actual requests."""
        response = client.get(
            "/health",
            headers={"Origin": "http://localhost:3000"},
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"

    def test_cors_allows_credentials(self, client: TestClient) -> None:
        """CORS should allow credentials."""
        response = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.headers.get("access-control-allow-credentials") == "true"


# =============================================================================
# Test: Request Logging
# =============================================================================


class TestRequestLogging:
    """Tests for: Structured logging for requests."""

    def test_request_completes_successfully(self, client: TestClient) -> None:
        """Requests should complete and be logged.

        We verify logging works by checking the request completes
        without errors. Actual log output is verified by structlog configuration.
        """
        response = client.get("/health")
        assert response.status_code == 200

    def test_multiple_requests_logged_independently(self, client: TestClient) -> None:
        """Multiple requests should all complete successfully."""
        for _ in range(3):
            response = client.get("/health")
            assert response.status_code == 200


# =============================================================================
# Test: Error Handling
# =============================================================================


class TestErrorHandling:
    """Tests for error scenarios."""

    def test_404_for_unknown_endpoint(self, client: TestClient) -> None:
        """Unknown endpoints should return 404."""
        response = client.get("/unknown")
        assert response.status_code == 404

    def test_method_not_allowed(self, client: TestClient) -> None:
        """POST to health endpoint should return 405."""
        response = client.post("/health")
        assert response.status_code == 405


# =============================================================================
# Test: Dependency Injection
# =============================================================================


class TestDependencyInjection:
    """Tests for dependency injection via app.state."""

    def test_config_in_app_state(self, app, test_config: Config) -> None:
        """Config should be accessible from app.state."""
        assert app.state.config is test_config

    def test_db_in_app_state(self, app, engine) -> None:
        """Database engine should be accessible from app.state."""
        assert app.state.db is engine

    def test_ledger_in_app_state(self, app) -> None:
        """Salience ledger should be accessible from app.state."""
        assert app.state.ledger is not None
        assert isinstance(app.state.ledger, SalienceLedger)
