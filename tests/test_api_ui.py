"""Tests for UI base (htmx + Jinja2 foundation).

Tests the UI routes, templates, static files, and htmx integration.
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
# Test: UI Home Page
# =============================================================================


class TestUIHomePage:
    """Tests for: UI home page loads correctly."""

    def test_ui_index_returns_200(self, client: TestClient) -> None:
        """UI home page should return 200 OK."""
        response = client.get("/ui/")
        assert response.status_code == 200

    def test_ui_index_returns_html(self, client: TestClient) -> None:
        """UI home page should return HTML."""
        response = client.get("/ui/")
        assert "text/html" in response.headers["content-type"]

    def test_ui_index_contains_title(self, client: TestClient) -> None:
        """UI home page should contain Zos Dashboard title."""
        response = client.get("/ui/")
        assert "Zos Dashboard" in response.text

    def test_ui_index_contains_navigation(self, client: TestClient) -> None:
        """UI home page should contain navigation links."""
        response = client.get("/ui/")
        assert "Insights" in response.text
        assert "Salience" in response.text
        assert "Layer Runs" in response.text

    def test_ui_index_contains_htmx_triggers(self, client: TestClient) -> None:
        """UI home page should contain htmx triggers for dynamic content."""
        response = client.get("/ui/")
        # Check for htmx attributes
        assert "hx-get" in response.text
        assert "hx-trigger" in response.text

    def test_ui_index_contains_dashboard_cards(self, client: TestClient) -> None:
        """UI home page should contain dashboard cards."""
        response = client.get("/ui/")
        assert "Recent Insights" in response.text
        assert "Top Topics" in response.text
        assert "Recent Runs" in response.text


# =============================================================================
# Test: Status Badge (htmx partial)
# =============================================================================


class TestStatusBadge:
    """Tests for: Status badge updates via htmx."""

    def test_status_returns_200(self, client: TestClient) -> None:
        """Status endpoint should return 200 OK."""
        response = client.get("/ui/status")
        assert response.status_code == 200

    def test_status_returns_html(self, client: TestClient) -> None:
        """Status endpoint should return HTML."""
        response = client.get("/ui/status")
        assert "text/html" in response.headers["content-type"]

    def test_status_returns_healthy_badge(self, client: TestClient) -> None:
        """Status endpoint should return healthy badge when DB is OK."""
        response = client.get("/ui/status")
        assert "Healthy" in response.text
        assert "badge-success" in response.text

    def test_status_is_htmx_partial(self, client: TestClient) -> None:
        """Status endpoint should return just a badge element, not full page."""
        response = client.get("/ui/status")
        # Should not contain full HTML structure
        assert "<!DOCTYPE" not in response.text
        assert "<html" not in response.text
        # Should just be a span
        assert "<span" in response.text


# =============================================================================
# Test: Static Files
# =============================================================================


class TestStaticFiles:
    """Tests for: Static files served correctly."""

    def test_static_css_returns_200(self, client: TestClient) -> None:
        """Style.css should be accessible."""
        response = client.get("/static/style.css")
        assert response.status_code == 200

    def test_static_css_is_css(self, client: TestClient) -> None:
        """Style.css should have correct content type."""
        response = client.get("/static/style.css")
        assert "text/css" in response.headers["content-type"]

    def test_static_css_contains_dark_theme(self, client: TestClient) -> None:
        """Style.css should contain dark theme variables."""
        response = client.get("/static/style.css")
        assert "--bg-primary" in response.text
        assert "#1a1a2e" in response.text

    def test_static_htmx_returns_200(self, client: TestClient) -> None:
        """htmx.min.js should be accessible."""
        response = client.get("/static/htmx.min.js")
        assert response.status_code == 200

    def test_static_htmx_is_javascript(self, client: TestClient) -> None:
        """htmx.min.js should have correct content type."""
        response = client.get("/static/htmx.min.js")
        content_type = response.headers["content-type"]
        assert "javascript" in content_type or "text/plain" in content_type


# =============================================================================
# Test: Navigation
# =============================================================================


class TestNavigation:
    """Tests for: Navigation between sections."""

    def test_nav_links_to_insights(self, client: TestClient) -> None:
        """Navigation should link to insights page."""
        response = client.get("/ui/")
        assert 'href="/ui/insights"' in response.text

    def test_nav_links_to_salience(self, client: TestClient) -> None:
        """Navigation should link to salience page."""
        response = client.get("/ui/")
        assert 'href="/ui/salience"' in response.text

    def test_nav_links_to_runs(self, client: TestClient) -> None:
        """Navigation should link to runs page."""
        response = client.get("/ui/")
        assert 'href="/ui/runs"' in response.text

    def test_nav_links_to_api_docs(self, client: TestClient) -> None:
        """Footer should link to API docs."""
        response = client.get("/ui/")
        assert 'href="/docs"' in response.text


# =============================================================================
# Test: htmx Integration
# =============================================================================


class TestHtmxIntegration:
    """Tests for: htmx loaded and working."""

    def test_htmx_script_included(self, client: TestClient) -> None:
        """Base template should include htmx script."""
        response = client.get("/ui/")
        assert 'src="/static/htmx.min.js"' in response.text

    def test_status_has_htmx_trigger(self, client: TestClient) -> None:
        """Status indicator should have htmx polling trigger."""
        response = client.get("/ui/")
        assert 'hx-get="/ui/status"' in response.text
        assert 'hx-trigger=' in response.text

    def test_dashboard_cards_have_htmx_load(self, client: TestClient) -> None:
        """Dashboard cards should load content via htmx."""
        response = client.get("/ui/")
        # Should have htmx load triggers for dashboard content
        assert 'hx-get="/ui/insights/recent"' in response.text
        assert 'hx-get="/ui/salience/top' in response.text  # May have query params
        assert 'hx-get="/ui/runs/recent"' in response.text


# =============================================================================
# Test: Dashboard Partials (Placeholders)
# =============================================================================


class TestDashboardPartials:
    """Tests for: Dashboard partial endpoints."""

    def test_insights_recent_returns_200(self, client: TestClient) -> None:
        """Insights recent partial should return 200."""
        response = client.get("/ui/insights/recent")
        assert response.status_code == 200

    def test_insights_recent_returns_html(self, client: TestClient) -> None:
        """Insights recent partial should return HTML."""
        response = client.get("/ui/insights/recent")
        assert "text/html" in response.headers["content-type"]

    def test_salience_top_returns_200(self, client: TestClient) -> None:
        """Salience top partial should return 200."""
        response = client.get("/ui/salience/top")
        assert response.status_code == 200

    def test_runs_recent_returns_200(self, client: TestClient) -> None:
        """Runs recent partial should return 200."""
        response = client.get("/ui/runs/recent")
        assert response.status_code == 200


# =============================================================================
# Test: Dark Theme
# =============================================================================


class TestDarkTheme:
    """Tests for: Dark mode friendly styling."""

    def test_css_has_dark_background(self, client: TestClient) -> None:
        """CSS should define dark background colors."""
        response = client.get("/static/style.css")
        # Check for dark theme colors from spec
        assert "--bg-primary: #1a1a2e" in response.text
        assert "--bg-secondary: #16213e" in response.text
        assert "--bg-card: #0f3460" in response.text

    def test_css_has_light_text(self, client: TestClient) -> None:
        """CSS should define light text colors."""
        response = client.get("/static/style.css")
        assert "--text-primary: #eaeaea" in response.text
        assert "--text-secondary: #a0a0a0" in response.text

    def test_css_has_accent_color(self, client: TestClient) -> None:
        """CSS should define accent color."""
        response = client.get("/static/style.css")
        assert "--accent: #e94560" in response.text

    def test_css_has_status_colors(self, client: TestClient) -> None:
        """CSS should define status colors."""
        response = client.get("/static/style.css")
        assert "--success: #4ecca3" in response.text
        assert "--warning: #ffc107" in response.text
        assert "--error: #ff6b6b" in response.text


# =============================================================================
# Test: Topic Display Formatting
# =============================================================================


class TestFormatTopicDisplay:
    """Tests for: _format_topic_display handles names correctly."""

    def test_user_name_with_space(self) -> None:
        """User names with spaces should be preserved."""
        from zos.api.ui import _format_topic_display

        # Simulates resolved key with user name containing space
        resolved_key = "server:Test Server:user:Ron Juggeri"
        result = _format_topic_display(resolved_key)
        assert result == "Test Server - Ron Juggeri"

    def test_server_name_with_space(self) -> None:
        """Server names with spaces should be preserved."""
        from zos.api.ui import _format_topic_display

        resolved_key = "server:My Cool Server:user:Alice"
        result = _format_topic_display(resolved_key)
        assert result == "My Cool Server - Alice"

    def test_both_names_with_spaces(self) -> None:
        """Both server and user names can have spaces."""
        from zos.api.ui import _format_topic_display

        resolved_key = "server:Test Server:user:Ron Juggeri"
        result = _format_topic_display(resolved_key)
        assert result == "Test Server - Ron Juggeri"

    def test_unknown_user_displays_correctly(self) -> None:
        """Unknown user placeholder should display completely."""
        from zos.api.ui import _format_topic_display

        # Uses pipe instead of colon to avoid breaking split
        resolved_key = "server:Test Server:user:[unknown|123456789]"
        result = _format_topic_display(resolved_key)
        assert result == "Test Server - [unknown|123456789]"

    def test_unknown_server_displays_correctly(self) -> None:
        """Unknown server placeholder should display completely."""
        from zos.api.ui import _format_topic_display

        resolved_key = "server:[unknown|987654321]:user:Alice"
        result = _format_topic_display(resolved_key)
        assert result == "[unknown|987654321] - Alice"

    def test_unknown_both_displays_correctly(self) -> None:
        """Both unknown placeholders should display completely."""
        from zos.api.ui import _format_topic_display

        resolved_key = "server:[unknown|111]:user:[unknown|222]"
        result = _format_topic_display(resolved_key)
        assert result == "[unknown|111] - [unknown|222]"

    def test_dyad_names_with_spaces(self) -> None:
        """Dyad topic with names containing spaces."""
        from zos.api.ui import _format_topic_display

        resolved_key = "server:Test Server:dyad:Ron Juggeri:Alice Smith"
        result = _format_topic_display(resolved_key)
        assert result == "Test Server - Ron Juggeri & Alice Smith"

    def test_channel_name_with_space(self) -> None:
        """Channel names can have spaces."""
        from zos.api.ui import _format_topic_display

        resolved_key = "server:Test Server:channel:#general chat"
        result = _format_topic_display(resolved_key)
        assert result == "Test Server - #general chat"

    def test_global_user_with_space(self) -> None:
        """Global user topic with name containing space."""
        from zos.api.ui import _format_topic_display

        resolved_key = "user:Ron Juggeri"
        result = _format_topic_display(resolved_key)
        assert result == "Ron Juggeri"

    def test_global_dyad_with_spaces(self) -> None:
        """Global dyad topic with names containing spaces."""
        from zos.api.ui import _format_topic_display

        resolved_key = "dyad:Ron Juggeri:Alice Smith"
        result = _format_topic_display(resolved_key)
        assert result == "Ron Juggeri & Alice Smith"
