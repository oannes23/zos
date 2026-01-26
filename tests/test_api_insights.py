"""Tests for Insights API endpoints.

Tests the following endpoints:
- GET /insights/{topic_key} - insights for a topic
- GET /insights - list recent insights with pagination
- GET /insights/search - search insight content

Covers:
- Retrieval profiles (recent, balanced, deep, comprehensive)
- Pagination (offset, limit)
- Category filtering
- Since filtering
- Search functionality
- Topic key with colons handling
- Quarantined insight exclusion
- Temporal markers in responses
"""

from datetime import datetime, timedelta, timezone
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
    salience_ledger,
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
    # Parse category from topic key
    parts = topic_key.split(":")
    if parts[0] == "server":
        category = parts[2]
        is_global = False
    else:
        category = parts[0]
        is_global = True

    # Map to category enum
    try:
        cat_enum = TopicCategory(category)
    except ValueError:
        cat_enum = TopicCategory.USER

    with engine.connect() as conn:
        # Check if exists
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
    created_at: datetime | None = None,
    quarantined: bool = False,
    original_topic_salience: float = 10.0,
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
                original_topic_salience=original_topic_salience,
                confidence=0.8,
                importance=0.7,
                novelty=0.6,
                valence_curiosity=0.5,
            )
        )
        conn.commit()

    return insight_id


def add_salience(engine, topic_key: str, amount: float = 10.0) -> None:
    """Add salience to a topic."""
    with engine.connect() as conn:
        conn.execute(
            salience_ledger.insert().values(
                id=generate_id(),
                topic_key=topic_key,
                transaction_type="earn",
                amount=amount,
                created_at=utcnow(),
            )
        )
        conn.commit()


# =============================================================================
# Test: GET /insights/{topic_key} - Get insights for topic
# =============================================================================


class TestGetInsightsForTopic:
    """Tests for GET /insights/{topic_key}."""

    def test_returns_insights_for_topic(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Get insights for a topic returns correct data."""
        topic_key = "server:123:user:456"
        create_insight_in_db(
            engine,
            layer_run_id,
            topic_key,
            content="Alice is friendly and helpful",
            strength=8.0,
        )
        add_salience(engine, topic_key)

        response = client.get(f"/insights/{topic_key}")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["content"] == "Alice is friendly and helpful"
        assert data[0]["topic_key"] == topic_key

    def test_topic_key_with_colons_works(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Topic key containing colons is handled correctly."""
        topic_key = "server:123:user:456"
        create_insight_in_db(engine, layer_run_id, topic_key)
        add_salience(engine, topic_key)

        # The path converter should handle the colons
        response = client.get(f"/insights/{topic_key}")

        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert data[0]["topic_key"] == topic_key

    def test_profile_affects_retrieval(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Different profiles affect which insights are retrieved."""
        topic_key = "server:123:user:789"
        now = utcnow()

        # Create old but strong insight
        create_insight_in_db(
            engine,
            layer_run_id,
            topic_key,
            content="Old strong insight",
            strength=9.0,
            created_at=now - timedelta(days=30),
        )

        # Create recent but weak insight
        create_insight_in_db(
            engine,
            layer_run_id,
            topic_key,
            content="Recent weak insight",
            strength=2.0,
            created_at=now - timedelta(hours=1),
        )

        add_salience(engine, topic_key)

        # Recent profile should include the recent insight
        response = client.get(f"/insights/{topic_key}?profile=recent&limit=10")
        assert response.status_code == 200
        data = response.json()
        contents = [i["content"] for i in data]
        assert "Recent weak insight" in contents

    def test_invalid_profile_returns_400(self, client: TestClient) -> None:
        """Invalid profile name returns 400 error."""
        response = client.get("/insights/server:123:user:456?profile=invalid")

        assert response.status_code == 400
        assert "Invalid profile" in response.json()["detail"]

    def test_quarantined_excluded_by_default(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Quarantined insights are excluded by default."""
        topic_key = "server:123:user:quarantine_test"

        create_insight_in_db(
            engine,
            layer_run_id,
            topic_key,
            content="Normal insight",
            quarantined=False,
        )
        create_insight_in_db(
            engine,
            layer_run_id,
            topic_key,
            content="Quarantined insight",
            quarantined=True,
        )

        add_salience(engine, topic_key)

        response = client.get(f"/insights/{topic_key}")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["content"] == "Normal insight"

    def test_include_quarantined_flag(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Include_quarantined flag includes quarantined insights."""
        topic_key = "server:123:user:quarantine_include"

        create_insight_in_db(
            engine,
            layer_run_id,
            topic_key,
            content="Normal insight",
            quarantined=False,
        )
        create_insight_in_db(
            engine,
            layer_run_id,
            topic_key,
            content="Quarantined insight",
            quarantined=True,
        )

        add_salience(engine, topic_key)

        response = client.get(f"/insights/{topic_key}?include_quarantined=true")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_response_includes_temporal_marker(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Response includes temporal markers."""
        topic_key = "server:123:user:temporal_test"
        create_insight_in_db(
            engine,
            layer_run_id,
            topic_key,
            content="Test insight",
            strength=8.0,
            created_at=utcnow() - timedelta(days=2),
        )
        add_salience(engine, topic_key)

        response = client.get(f"/insights/{topic_key}")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        # Should have temporal marker like "strong memory from 2 days ago"
        assert "temporal_marker" in data[0]
        assert "memory" in data[0]["temporal_marker"]
        assert "ago" in data[0]["temporal_marker"]

    def test_response_includes_valence(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Response includes valence dictionary."""
        topic_key = "server:123:user:valence_test"
        create_insight_in_db(engine, layer_run_id, topic_key)
        add_salience(engine, topic_key)

        response = client.get(f"/insights/{topic_key}")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert "valence" in data[0]
        assert "joy" in data[0]["valence"]
        assert "concern" in data[0]["valence"]
        assert "curiosity" in data[0]["valence"]
        assert "warmth" in data[0]["valence"]
        assert "tension" in data[0]["valence"]

    def test_limit_parameter(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Limit parameter restricts number of results."""
        topic_key = "server:123:user:limit_test"

        for i in range(5):
            create_insight_in_db(
                engine,
                layer_run_id,
                topic_key,
                content=f"Insight {i}",
            )

        add_salience(engine, topic_key)

        response = client.get(f"/insights/{topic_key}?limit=2")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_empty_topic_returns_empty_list(self, client: TestClient) -> None:
        """Topic with no insights returns empty list."""
        response = client.get("/insights/server:123:user:nonexistent")

        assert response.status_code == 200
        data = response.json()
        assert data == []


# =============================================================================
# Test: GET /insights - List recent insights
# =============================================================================


class TestListInsights:
    """Tests for GET /insights."""

    def test_returns_recent_insights(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Lists recent insights across all topics."""
        topic1 = "server:123:user:list1"
        topic2 = "server:123:user:list2"

        create_insight_in_db(engine, layer_run_id, topic1, content="Insight 1")
        create_insight_in_db(engine, layer_run_id, topic2, content="Insight 2")

        response = client.get("/insights")

        assert response.status_code == 200
        data = response.json()
        assert "insights" in data
        assert len(data["insights"]) == 2

    def test_pagination_works_correctly(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Pagination offset and limit work correctly."""
        topic = "server:123:user:pagination"

        for i in range(10):
            create_insight_in_db(
                engine,
                layer_run_id,
                topic,
                content=f"Insight {i}",
                created_at=utcnow() - timedelta(hours=i),
            )

        # Get first page
        response = client.get("/insights?limit=3&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert len(data["insights"]) == 3
        assert data["total"] == 10
        assert data["offset"] == 0
        assert data["limit"] == 3

        # Get second page
        response = client.get("/insights?limit=3&offset=3")
        data = response.json()
        assert len(data["insights"]) == 3
        assert data["offset"] == 3

    def test_category_filter_works(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Category filter returns only matching insights."""
        topic = "server:123:user:category_filter"

        create_insight_in_db(
            engine,
            layer_run_id,
            topic,
            content="User insight",
            category="user_reflection",
        )
        create_insight_in_db(
            engine,
            layer_run_id,
            topic,
            content="Synthesis insight",
            category="synthesis",
        )

        response = client.get("/insights?category=user_reflection")

        assert response.status_code == 200
        data = response.json()
        assert len(data["insights"]) == 1
        assert data["insights"][0]["content"] == "User insight"
        assert data["total"] == 1

    def test_since_filter_works(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Since filter returns only insights after the specified time."""
        from urllib.parse import quote

        topic = "server:123:user:since_filter"
        now = utcnow()

        create_insight_in_db(
            engine,
            layer_run_id,
            topic,
            content="Old insight",
            created_at=now - timedelta(days=10),
        )
        create_insight_in_db(
            engine,
            layer_run_id,
            topic,
            content="Recent insight",
            created_at=now - timedelta(hours=1),
        )

        since = (now - timedelta(days=1)).isoformat()
        # URL encode the datetime string (especially the + in timezone)
        response = client.get(f"/insights?since={quote(since)}")

        assert response.status_code == 200
        data = response.json()
        assert len(data["insights"]) == 1
        assert data["insights"][0]["content"] == "Recent insight"

    def test_quarantined_excluded(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Quarantined insights are excluded from listing."""
        topic = "server:123:user:list_quarantine"

        create_insight_in_db(
            engine,
            layer_run_id,
            topic,
            content="Normal",
            quarantined=False,
        )
        create_insight_in_db(
            engine,
            layer_run_id,
            topic,
            content="Quarantined",
            quarantined=True,
        )

        response = client.get("/insights")

        assert response.status_code == 200
        data = response.json()
        assert len(data["insights"]) == 1
        assert data["insights"][0]["content"] == "Normal"

    def test_response_includes_all_fields(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Response includes all required fields."""
        topic = "server:123:user:fields_test"
        create_insight_in_db(engine, layer_run_id, topic)

        response = client.get("/insights")

        assert response.status_code == 200
        data = response.json()
        insight = data["insights"][0]

        # Check required fields
        assert "id" in insight
        assert "topic_key" in insight
        assert "category" in insight
        assert "content" in insight
        assert "created_at" in insight
        assert "temporal_marker" in insight
        assert "strength" in insight
        assert "confidence" in insight
        assert "importance" in insight
        assert "novelty" in insight
        assert "valence" in insight


# =============================================================================
# Test: GET /insights/search - Search insights
# =============================================================================


class TestSearchInsights:
    """Tests for GET /insights/search."""

    def test_search_finds_matching_content(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Search finds insights with matching content."""
        topic = "server:123:user:search"

        create_insight_in_db(
            engine,
            layer_run_id,
            topic,
            content="Alice loves programming",
        )
        create_insight_in_db(
            engine,
            layer_run_id,
            topic,
            content="Bob enjoys music",
        )

        response = client.get("/insights/search?q=programming")

        assert response.status_code == 200
        data = response.json()
        assert len(data["insights"]) == 1
        assert "programming" in data["insights"][0]["content"]

    def test_search_is_case_insensitive(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Search is case-insensitive."""
        topic = "server:123:user:case"

        create_insight_in_db(
            engine,
            layer_run_id,
            topic,
            content="Alice LOVES Programming",
        )

        response = client.get("/insights/search?q=loves")

        assert response.status_code == 200
        data = response.json()
        assert len(data["insights"]) == 1

    def test_search_minimum_query_length(self, client: TestClient) -> None:
        """Search requires minimum query length."""
        response = client.get("/insights/search?q=a")

        assert response.status_code == 422  # Validation error

    def test_search_pagination(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Search supports pagination."""
        topic = "server:123:user:search_page"

        for i in range(10):
            create_insight_in_db(
                engine,
                layer_run_id,
                topic,
                content=f"Pattern match {i}",
                created_at=utcnow() - timedelta(hours=i),
            )

        response = client.get("/insights/search?q=Pattern&limit=3&offset=0")

        assert response.status_code == 200
        data = response.json()
        assert len(data["insights"]) == 3
        assert data["total"] == 10
        assert data["offset"] == 0
        assert data["limit"] == 3

    def test_search_with_category_filter(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Search can be combined with category filter."""
        topic = "server:123:user:search_cat"

        create_insight_in_db(
            engine,
            layer_run_id,
            topic,
            content="User pattern match",
            category="user_reflection",
        )
        create_insight_in_db(
            engine,
            layer_run_id,
            topic,
            content="Synthesis pattern match",
            category="synthesis",
        )

        response = client.get(
            "/insights/search?q=pattern&category=user_reflection"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["insights"]) == 1
        assert data["insights"][0]["category"] == "user_reflection"

    def test_search_quarantined_excluded(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Quarantined insights are excluded from search."""
        topic = "server:123:user:search_q"

        create_insight_in_db(
            engine,
            layer_run_id,
            topic,
            content="Searchable normal",
            quarantined=False,
        )
        create_insight_in_db(
            engine,
            layer_run_id,
            topic,
            content="Searchable quarantined",
            quarantined=True,
        )

        response = client.get("/insights/search?q=Searchable")

        assert response.status_code == 200
        data = response.json()
        assert len(data["insights"]) == 1
        assert data["insights"][0]["content"] == "Searchable normal"

    def test_search_no_matches(self, client: TestClient) -> None:
        """Search with no matches returns empty list."""
        response = client.get("/insights/search?q=nonexistenttermxyz")

        assert response.status_code == 200
        data = response.json()
        assert data["insights"] == []
        assert data["total"] == 0


# =============================================================================
# Test: OpenAPI Documentation
# =============================================================================


class TestOpenAPIInsightsEndpoints:
    """Tests for insights endpoints in OpenAPI documentation."""

    def test_openapi_has_insights_endpoints(self, client: TestClient) -> None:
        """OpenAPI schema includes insights endpoints."""
        response = client.get("/openapi.json")

        assert response.status_code == 200
        data = response.json()
        paths = data["paths"]

        # Check that our endpoints are documented
        assert "/insights" in paths
        assert "/insights/search" in paths
        # Path with parameter
        matching_paths = [p for p in paths if p.startswith("/insights/{")]
        assert len(matching_paths) >= 1

    def test_insights_endpoints_have_tags(self, client: TestClient) -> None:
        """Insights endpoints are tagged correctly."""
        response = client.get("/openapi.json")

        assert response.status_code == 200
        data = response.json()

        # Check that insights tag exists in at least one endpoint
        for path, methods in data["paths"].items():
            if path.startswith("/insights"):
                for method, spec in methods.items():
                    if method in ["get", "post", "put", "delete"]:
                        if "tags" in spec:
                            assert "insights" in spec["tags"]
                            return  # Found one, that's enough

        # If we get here, no insights endpoints had tags
        pytest.fail("No insights endpoints found with 'insights' tag")
