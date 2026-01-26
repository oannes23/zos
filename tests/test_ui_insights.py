"""Tests for Insights Browser UI (Story 5.6).

Tests the following UI endpoints:
- GET /ui/insights - main insights browser page
- GET /ui/insights/list - htmx partial for insights list
- GET /ui/insights/search - search partial
- GET /ui/insights/{insight_id} - insight detail page
- GET /ui/insights/topic/{topic_key} - related insights partial

Covers:
- List view with pagination
- Category filter
- Search functionality with debounce
- Detail view with all metrics
- Temporal markers display
- Valence visualization
"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from zos.api import create_app
from zos.config import Config
from zos.database import (
    create_tables,
    generate_id,
    get_engine,
    insights as insights_table,
    layer_runs as layer_runs_table,
    topics as topics_table,
)
from zos.migrations import migrate
from zos.models import LayerRunStatus, TopicCategory, VisibilityScope, utcnow
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
def layer_run_id(engine) -> str:
    """Create a layer run for insights to reference."""
    run_id = generate_id()
    now = utcnow()

    with engine.connect() as conn:
        conn.execute(
            layer_runs_table.insert().values(
                id=run_id,
                layer_name="test_layer",
                layer_hash="abc123",
                started_at=now,
                completed_at=now,
                status=LayerRunStatus.SUCCESS.value,
                targets_matched=1,
                targets_processed=1,
                targets_skipped=0,
                insights_created=0,
            )
        )
        conn.commit()

    return run_id


def ensure_topic_exists(engine, topic_key: str) -> None:
    """Ensure a topic exists in the database."""
    parts = topic_key.split(":")
    if parts[0] == "server":
        category = parts[2]
        is_global = False
    else:
        category = parts[0]
        is_global = True

    try:
        cat_enum = TopicCategory(category)
    except ValueError:
        cat_enum = TopicCategory.USER

    with engine.connect() as conn:
        result = conn.execute(
            topics_table.select().where(topics_table.c.key == topic_key)
        ).fetchone()

        if result is None:
            conn.execute(
                topics_table.insert().values(
                    key=topic_key,
                    category=cat_enum.value,
                    is_global=is_global,
                    provisional=False,
                    created_at=utcnow(),
                )
            )
            conn.commit()


def create_insight_in_db(
    engine,
    layer_run_id: str,
    topic_key: str,
    content: str = "Test insight content",
    category: str = "user_reflection",
    strength: float = 5.0,
    confidence: float = 0.8,
    importance: float = 0.7,
    novelty: float = 0.6,
    created_at: datetime | None = None,
    quarantined: bool = False,
    valence_joy: float | None = None,
    valence_concern: float | None = None,
    valence_curiosity: float | None = 0.5,
    valence_warmth: float | None = None,
    valence_tension: float | None = None,
    supersedes: str | None = None,
) -> str:
    """Create an insight directly in the database and return its ID."""
    ensure_topic_exists(engine, topic_key)
    insight_id = generate_id()

    with engine.connect() as conn:
        conn.execute(
            insights_table.insert().values(
                id=insight_id,
                topic_key=topic_key,
                category=category,
                content=content,
                sources_scope_max=VisibilityScope.PUBLIC.value,
                created_at=created_at or utcnow(),
                layer_run_id=layer_run_id,
                quarantined=quarantined,
                salience_spent=5.0,
                strength_adjustment=1.0,
                strength=strength,
                original_topic_salience=10.0,
                confidence=confidence,
                importance=importance,
                novelty=novelty,
                valence_joy=valence_joy,
                valence_concern=valence_concern,
                valence_curiosity=valence_curiosity,
                valence_warmth=valence_warmth,
                valence_tension=valence_tension,
                supersedes=supersedes,
            )
        )
        conn.commit()

    return insight_id


# =============================================================================
# Test: Insights Browser Page (GET /ui/insights)
# =============================================================================


class TestInsightsBrowserPage:
    """Tests for: Main insights browser page loads correctly."""

    def test_insights_page_returns_200(self, client: TestClient) -> None:
        """Insights page should return 200 OK."""
        response = client.get("/ui/insights")
        assert response.status_code == 200

    def test_insights_page_returns_html(self, client: TestClient) -> None:
        """Insights page should return HTML."""
        response = client.get("/ui/insights")
        assert "text/html" in response.headers["content-type"]

    def test_insights_page_contains_title(self, client: TestClient) -> None:
        """Insights page should contain Insights title."""
        response = client.get("/ui/insights")
        assert "Insights" in response.text

    def test_insights_page_contains_search_input(self, client: TestClient) -> None:
        """Insights page should have a search input with debounce."""
        response = client.get("/ui/insights")
        assert 'type="search"' in response.text
        assert "delay:300ms" in response.text

    def test_insights_page_contains_category_filter(self, client: TestClient) -> None:
        """Insights page should have category filter dropdown."""
        response = client.get("/ui/insights")
        assert "<select" in response.text
        assert "user_reflection" in response.text
        assert "synthesis" in response.text

    def test_insights_page_contains_htmx_list_trigger(self, client: TestClient) -> None:
        """Insights page should trigger htmx to load the list."""
        response = client.get("/ui/insights")
        assert 'hx-get="/ui/insights/list"' in response.text
        assert 'hx-trigger="load"' in response.text

    def test_insights_page_marks_nav_as_active(self, client: TestClient) -> None:
        """Insights page should mark insights nav link as active."""
        response = client.get("/ui/insights")
        # The active class should be on the insights nav link
        assert 'class="active"' in response.text


# =============================================================================
# Test: Insights List Partial (GET /ui/insights/list)
# =============================================================================


class TestInsightsListPartial:
    """Tests for: htmx partial for insights list."""

    def test_list_returns_200(self, client: TestClient) -> None:
        """List partial should return 200 OK."""
        response = client.get("/ui/insights/list")
        assert response.status_code == 200

    def test_list_returns_html(self, client: TestClient) -> None:
        """List partial should return HTML."""
        response = client.get("/ui/insights/list")
        assert "text/html" in response.headers["content-type"]

    def test_list_is_partial(self, client: TestClient) -> None:
        """List partial should not contain full HTML structure."""
        response = client.get("/ui/insights/list")
        assert "<!DOCTYPE" not in response.text
        assert "<html" not in response.text

    def test_list_shows_empty_state(self, client: TestClient) -> None:
        """Empty list should show empty state message."""
        response = client.get("/ui/insights/list")
        assert "No insights found" in response.text

    def test_list_shows_insights(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """List should display insights."""
        create_insight_in_db(
            engine,
            layer_run_id,
            topic_key="server:123:user:456",
            content="Alice is helpful and kind",
        )

        response = client.get("/ui/insights/list")

        assert response.status_code == 200
        assert "Alice is helpful and kind" in response.text
        assert "server:123:user:456" in response.text

    def test_list_shows_temporal_markers(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """List should display temporal markers."""
        create_insight_in_db(
            engine,
            layer_run_id,
            topic_key="server:123:user:temporal",
            strength=8.0,
            created_at=utcnow() - timedelta(days=2),
        )

        response = client.get("/ui/insights/list")

        assert response.status_code == 200
        assert "memory" in response.text
        assert "ago" in response.text

    def test_list_shows_confidence(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """List should display confidence percentage."""
        create_insight_in_db(
            engine,
            layer_run_id,
            topic_key="server:123:user:conf",
            confidence=0.85,
        )

        response = client.get("/ui/insights/list")

        assert response.status_code == 200
        assert "85%" in response.text
        assert "confident" in response.text

    def test_list_shows_valence_bars(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """List should display valence visualization bars."""
        create_insight_in_db(
            engine,
            layer_run_id,
            topic_key="server:123:user:valence",
            valence_joy=0.7,
            valence_curiosity=0.5,
        )

        response = client.get("/ui/insights/list")

        assert response.status_code == 200
        assert "valence-bar" in response.text
        assert "valence-joy" in response.text
        assert "valence-curiosity" in response.text

    def test_list_shows_category_badge(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """List should display category badge."""
        create_insight_in_db(
            engine,
            layer_run_id,
            topic_key="server:123:user:cat",
            category="self_reflection",
        )

        response = client.get("/ui/insights/list")

        assert response.status_code == 200
        assert "badge" in response.text
        assert "self_reflection" in response.text


# =============================================================================
# Test: Pagination
# =============================================================================


class TestPagination:
    """Tests for: List pagination works correctly."""

    def test_pagination_shows_page_info(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Pagination should show page info."""
        for i in range(5):
            create_insight_in_db(
                engine,
                layer_run_id,
                topic_key=f"server:123:user:page{i}",
                content=f"Insight {i}",
            )

        response = client.get("/ui/insights/list?limit=3&offset=0")

        assert response.status_code == 200
        assert "1-3 of 5" in response.text

    def test_pagination_next_button(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Pagination should show Next button when more results exist."""
        for i in range(5):
            create_insight_in_db(
                engine,
                layer_run_id,
                topic_key=f"server:123:user:next{i}",
            )

        response = client.get("/ui/insights/list?limit=3&offset=0")

        assert response.status_code == 200
        assert "Next" in response.text
        assert "offset=3" in response.text

    def test_pagination_previous_button(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Pagination should show Previous button when not on first page."""
        for i in range(5):
            create_insight_in_db(
                engine,
                layer_run_id,
                topic_key=f"server:123:user:prev{i}",
            )

        response = client.get("/ui/insights/list?limit=3&offset=3")

        assert response.status_code == 200
        assert "Previous" in response.text
        assert "offset=0" in response.text

    def test_pagination_no_previous_on_first_page(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """First page should not show Previous button."""
        for i in range(5):
            create_insight_in_db(
                engine,
                layer_run_id,
                topic_key=f"server:123:user:noprev{i}",
            )

        response = client.get("/ui/insights/list?limit=3&offset=0")

        assert response.status_code == 200
        # Should have pagination section but no Previous
        assert "pagination" in response.text
        assert "Previous" not in response.text


# =============================================================================
# Test: Category Filter
# =============================================================================


class TestCategoryFilter:
    """Tests for: Filter by category works."""

    def test_category_filter_returns_matching(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Category filter should return only matching insights."""
        create_insight_in_db(
            engine,
            layer_run_id,
            topic_key="server:123:user:catf1",
            content="User reflection insight",
            category="user_reflection",
        )
        create_insight_in_db(
            engine,
            layer_run_id,
            topic_key="server:123:user:catf2",
            content="Synthesis insight",
            category="synthesis",
        )

        response = client.get("/ui/insights/list?category=user_reflection")

        assert response.status_code == 200
        assert "User reflection insight" in response.text
        assert "Synthesis insight" not in response.text

    def test_category_filter_preserves_in_pagination(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Category filter should be preserved in pagination links."""
        for i in range(5):
            create_insight_in_db(
                engine,
                layer_run_id,
                topic_key=f"server:123:user:catpage{i}",
                category="user_reflection",
            )

        response = client.get("/ui/insights/list?category=user_reflection&limit=3")

        assert response.status_code == 200
        # Pagination links should include category
        assert "category=user_reflection" in response.text


# =============================================================================
# Test: Search
# =============================================================================


class TestSearch:
    """Tests for: Search by content works."""

    def test_search_returns_200(self, client: TestClient) -> None:
        """Search partial should return 200 OK."""
        response = client.get("/ui/insights/search?q=test")
        assert response.status_code == 200

    def test_search_finds_matching(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Search should find insights with matching content."""
        create_insight_in_db(
            engine,
            layer_run_id,
            topic_key="server:123:user:search1",
            content="Alice loves programming",
        )
        create_insight_in_db(
            engine,
            layer_run_id,
            topic_key="server:123:user:search2",
            content="Bob enjoys music",
        )

        response = client.get("/ui/insights/search?q=programming")

        assert response.status_code == 200
        assert "Alice loves programming" in response.text
        assert "Bob enjoys music" not in response.text

    def test_search_requires_minimum_length(self, client: TestClient) -> None:
        """Search should require minimum query length."""
        response = client.get("/ui/insights/search?q=a")
        assert response.status_code == 422

    def test_search_preserves_query_in_pagination(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Search query should be preserved in pagination links."""
        for i in range(5):
            create_insight_in_db(
                engine,
                layer_run_id,
                topic_key=f"server:123:user:searchpage{i}",
                content=f"Pattern match {i}",
            )

        response = client.get("/ui/insights/search?q=Pattern&limit=3")

        assert response.status_code == 200
        assert "q=Pattern" in response.text


# =============================================================================
# Test: Insight Detail Page
# =============================================================================


class TestInsightDetail:
    """Tests for: Click to view detail shows full insight."""

    def test_detail_returns_200(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Detail page should return 200 OK."""
        insight_id = create_insight_in_db(
            engine,
            layer_run_id,
            topic_key="server:123:user:detail",
        )

        response = client.get(f"/ui/insights/{insight_id}")
        assert response.status_code == 200

    def test_detail_returns_404_for_missing(self, client: TestClient) -> None:
        """Detail page should return 404 for non-existent insight."""
        response = client.get("/ui/insights/nonexistent123")
        assert response.status_code == 404

    def test_detail_shows_full_content(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Detail page should show full content (not truncated)."""
        long_content = "This is a very long insight content that would normally be truncated in the list view but should be shown in full on the detail page. " * 5

        insight_id = create_insight_in_db(
            engine,
            layer_run_id,
            topic_key="server:123:user:fullcontent",
            content=long_content,
        )

        response = client.get(f"/ui/insights/{insight_id}")

        assert response.status_code == 200
        assert long_content in response.text

    def test_detail_shows_temporal_marker(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Detail page should show temporal marker."""
        insight_id = create_insight_in_db(
            engine,
            layer_run_id,
            topic_key="server:123:user:detailtemporal",
            strength=8.0,
        )

        response = client.get(f"/ui/insights/{insight_id}")

        assert response.status_code == 200
        assert "Memory" in response.text
        assert "memory" in response.text.lower()

    def test_detail_shows_metrics_grid(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Detail page should show metrics grid with confidence, importance, novelty."""
        insight_id = create_insight_in_db(
            engine,
            layer_run_id,
            topic_key="server:123:user:metrics",
            confidence=0.9,
            importance=0.8,
            novelty=0.7,
        )

        response = client.get(f"/ui/insights/{insight_id}")

        assert response.status_code == 200
        assert "Confidence" in response.text
        assert "90%" in response.text
        assert "Importance" in response.text
        assert "80%" in response.text
        assert "Novelty" in response.text
        assert "70%" in response.text

    def test_detail_shows_valence_detail(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Detail page should show detailed valence visualization."""
        insight_id = create_insight_in_db(
            engine,
            layer_run_id,
            topic_key="server:123:user:valencedetail",
            valence_joy=0.8,
            valence_warmth=0.6,
            valence_curiosity=0.4,
        )

        response = client.get(f"/ui/insights/{insight_id}")

        assert response.status_code == 200
        assert "Emotional Valence" in response.text
        assert "Joy" in response.text
        assert "Warmth" in response.text
        assert "Curiosity" in response.text

    def test_detail_shows_breadcrumb(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Detail page should show breadcrumb navigation."""
        insight_id = create_insight_in_db(
            engine,
            layer_run_id,
            topic_key="server:123:user:breadcrumb",
        )

        response = client.get(f"/ui/insights/{insight_id}")

        assert response.status_code == 200
        assert 'href="/ui/insights"' in response.text
        assert "breadcrumb" in response.text

    def test_detail_shows_supersedes_link(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Detail page should show link to superseded insight."""
        old_insight_id = create_insight_in_db(
            engine,
            layer_run_id,
            topic_key="server:123:user:supersedes",
            content="Old insight",
        )

        new_insight_id = create_insight_in_db(
            engine,
            layer_run_id,
            topic_key="server:123:user:supersedes",
            content="New insight",
            supersedes=old_insight_id,
        )

        response = client.get(f"/ui/insights/{new_insight_id}")

        assert response.status_code == 200
        assert "Supersedes" in response.text
        assert old_insight_id in response.text

    def test_detail_loads_related_insights(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Detail page should have htmx trigger to load related insights."""
        insight_id = create_insight_in_db(
            engine,
            layer_run_id,
            topic_key="server:123:user:related",
        )

        response = client.get(f"/ui/insights/{insight_id}")

        assert response.status_code == 200
        assert "Other Insights on This Topic" in response.text
        assert 'hx-get="/ui/insights/topic/' in response.text


# =============================================================================
# Test: Related Insights Partial
# =============================================================================


class TestRelatedInsightsPartial:
    """Tests for: Related insights by topic partial."""

    def test_related_returns_200(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Related insights partial should return 200 OK."""
        create_insight_in_db(
            engine,
            layer_run_id,
            topic_key="server:123:user:rel",
        )

        response = client.get("/ui/insights/topic/server:123:user:rel")
        assert response.status_code == 200

    def test_related_excludes_current(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Related insights should exclude the specified insight."""
        topic_key = "server:123:user:exclude"

        insight1_id = create_insight_in_db(
            engine,
            layer_run_id,
            topic_key=topic_key,
            content="First insight",
        )
        create_insight_in_db(
            engine,
            layer_run_id,
            topic_key=topic_key,
            content="Second insight",
        )

        response = client.get(f"/ui/insights/topic/{topic_key}?exclude={insight1_id}")

        assert response.status_code == 200
        assert "Second insight" in response.text
        assert "First insight" not in response.text

    def test_related_shows_only_same_topic(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Related insights should only show insights on the same topic."""
        create_insight_in_db(
            engine,
            layer_run_id,
            topic_key="server:123:user:same",
            content="Same topic insight",
        )
        create_insight_in_db(
            engine,
            layer_run_id,
            topic_key="server:123:user:different",
            content="Different topic insight",
        )

        response = client.get("/ui/insights/topic/server:123:user:same")

        assert response.status_code == 200
        assert "Same topic insight" in response.text
        assert "Different topic insight" not in response.text


# =============================================================================
# Test: CSS Styles
# =============================================================================


class TestInsightStyles:
    """Tests for: Insight-specific CSS styles exist."""

    def test_css_has_insight_card_styles(self, client: TestClient) -> None:
        """CSS should have insight card styles."""
        response = client.get("/static/style.css")
        assert response.status_code == 200
        assert ".insight-card" in response.text
        assert "cursor: pointer" in response.text

    def test_css_has_valence_colors(self, client: TestClient) -> None:
        """CSS should have valence color definitions."""
        response = client.get("/static/style.css")
        assert response.status_code == 200
        assert ".valence-joy" in response.text
        assert ".valence-concern" in response.text
        assert ".valence-curiosity" in response.text
        assert ".valence-warmth" in response.text
        assert ".valence-tension" in response.text

    def test_css_has_metrics_grid(self, client: TestClient) -> None:
        """CSS should have metrics grid styles."""
        response = client.get("/static/style.css")
        assert response.status_code == 200
        assert ".metrics-grid" in response.text
        assert ".metric-value" in response.text
        assert ".metric-label" in response.text

    def test_css_has_search_input_styles(self, client: TestClient) -> None:
        """CSS should have search input styles."""
        response = client.get("/static/style.css")
        assert response.status_code == 200
        assert ".search-input" in response.text

    def test_css_has_pagination_styles(self, client: TestClient) -> None:
        """CSS should have pagination styles."""
        response = client.get("/static/style.css")
        assert response.status_code == 200
        assert ".pagination" in response.text

    def test_css_has_category_badge_colors(self, client: TestClient) -> None:
        """CSS should have category badge color definitions."""
        response = client.get("/static/style.css")
        assert response.status_code == 200
        assert ".badge-user_reflection" in response.text
        assert ".badge-synthesis" in response.text
        assert ".badge-self_reflection" in response.text
