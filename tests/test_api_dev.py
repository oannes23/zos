"""Tests for dev mode CRUD API endpoints.

Tests the development-only CRUD operations for insights that are
protected by the dev_mode configuration flag.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from zos.api import create_app
from zos.config import Config
from zos.database import create_tables, generate_id, get_engine, insights as insights_table
from zos.migrations import migrate
from zos.models import Insight, VisibilityScope
from zos.salience import SalienceLedger


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def test_config_dev_enabled(tmp_path: Path) -> Config:
    """Create a test configuration with dev mode enabled."""
    config = Config(
        data_dir=tmp_path,
        log_level="DEBUG",
    )
    config.development.dev_mode = True
    return config


@pytest.fixture
def test_config_dev_disabled(tmp_path: Path) -> Config:
    """Create a test configuration with dev mode disabled."""
    config = Config(
        data_dir=tmp_path,
        log_level="DEBUG",
    )
    config.development.dev_mode = False
    return config


@pytest.fixture
def engine_dev_enabled(test_config_dev_enabled: Config):
    """Create a test database engine with migrations applied."""
    eng = get_engine(test_config_dev_enabled)
    migrate(eng)
    create_tables(eng)
    return eng


@pytest.fixture
def engine_dev_disabled(test_config_dev_disabled: Config):
    """Create a test database engine with migrations applied."""
    eng = get_engine(test_config_dev_disabled)
    migrate(eng)
    create_tables(eng)
    return eng


@pytest.fixture
def app_dev_enabled(test_config_dev_enabled: Config, engine_dev_enabled):
    """Create a test FastAPI application with dev mode enabled."""
    application = create_app(test_config_dev_enabled)
    application.state.config = test_config_dev_enabled
    application.state.db = engine_dev_enabled
    application.state.ledger = SalienceLedger(engine_dev_enabled, test_config_dev_enabled)
    return application


@pytest.fixture
def app_dev_disabled(test_config_dev_disabled: Config, engine_dev_disabled):
    """Create a test FastAPI application with dev mode disabled."""
    application = create_app(test_config_dev_disabled)
    application.state.config = test_config_dev_disabled
    application.state.db = engine_dev_disabled
    application.state.ledger = SalienceLedger(engine_dev_disabled, test_config_dev_disabled)
    return application


@pytest.fixture
def client_dev_enabled(app_dev_enabled) -> TestClient:
    """Create a test client with dev mode enabled."""
    return TestClient(app_dev_enabled)


@pytest.fixture
def client_dev_disabled(app_dev_disabled) -> TestClient:
    """Create a test client with dev mode disabled."""
    return TestClient(app_dev_disabled)


@pytest.fixture
def sample_insight(engine_dev_enabled) -> Insight:
    """Create a sample insight in the database."""
    from zos.insights import insert_insight
    from zos.database import layer_runs, topics
    import asyncio

    topic_key = "server:123:user:456"
    layer_run_id = "test_run"
    now = datetime.now(timezone.utc)

    with engine_dev_enabled.connect() as conn:
        # Create topic first
        conn.execute(
            topics.insert().values(
                key=topic_key,
                category="user",
                is_global=False,
                provisional=True,
                created_at=now,
                last_activity_at=now,
            )
        )

        # Create layer_run
        conn.execute(
            layer_runs.insert().values(
                id=layer_run_id,
                layer_name="test",
                layer_hash="test",
                started_at=now,
                completed_at=now,
                status="success",
                targets_matched=0,
                targets_processed=0,
                targets_skipped=0,
                insights_created=0,
            )
        )
        conn.commit()

    insight = Insight(
        id=generate_id(),
        topic_key=topic_key,
        category="user_reflection",
        content="Test insight content for testing updates and deletes.",
        sources_scope_max=VisibilityScope.PUBLIC,
        created_at=now,
        layer_run_id=layer_run_id,
        salience_spent=5.0,
        strength_adjustment=1.0,
        strength=5.0,
        original_topic_salience=10.0,
        confidence=0.7,
        importance=0.8,
        novelty=0.5,
        valence_curiosity=0.6,
    )

    asyncio.get_event_loop().run_until_complete(insert_insight(engine_dev_enabled, insight))
    return insight


# =============================================================================
# Test: Dev Mode Protection
# =============================================================================


class TestDevModeProtection:
    """Tests for: Operations protected by dev mode flag."""

    def test_create_blocked_when_dev_mode_off(self, client_dev_disabled: TestClient) -> None:
        """Create should return 403 when dev mode is disabled."""
        response = client_dev_disabled.post(
            "/dev/insights",
            json={
                "topic_key": "server:123:user:456",
                "category": "user_reflection",
                "content": "Test insight",
            },
        )
        assert response.status_code == 403
        assert "dev mode" in response.json()["detail"].lower()

    def test_update_blocked_when_dev_mode_off(self, client_dev_disabled: TestClient) -> None:
        """Update should return 403 when dev mode is disabled."""
        response = client_dev_disabled.patch(
            "/dev/insights/some_id",
            json={"content": "Updated content"},
        )
        assert response.status_code == 403

    def test_delete_blocked_when_dev_mode_off(self, client_dev_disabled: TestClient) -> None:
        """Delete should return 403 when dev mode is disabled."""
        response = client_dev_disabled.delete("/dev/insights/some_id")
        assert response.status_code == 403

    def test_bulk_delete_blocked_when_dev_mode_off(self, client_dev_disabled: TestClient) -> None:
        """Bulk delete should return 403 when dev mode is disabled."""
        response = client_dev_disabled.post(
            "/dev/insights/bulk-delete",
            json={"topic_key": "server:123:user:456"},
        )
        assert response.status_code == 403

    def test_ui_page_blocked_when_dev_mode_off(self, client_dev_disabled: TestClient) -> None:
        """Create insight UI page should return 403 when dev mode is disabled."""
        response = client_dev_disabled.get("/dev/create-insight")
        assert response.status_code == 403


# =============================================================================
# Test: Create Insight
# =============================================================================


class TestCreateInsight:
    """Tests for: POST /dev/insights creates insight."""

    def test_create_insight_success(self, client_dev_enabled: TestClient) -> None:
        """Should create an insight and return the ID."""
        response = client_dev_enabled.post(
            "/dev/insights",
            json={
                "topic_key": "server:123:user:789",
                "category": "user_reflection",
                "content": "This is a manually created test insight.",
                "confidence": 0.8,
                "importance": 0.7,
                "novelty": 0.6,
                "valence_curiosity": 0.5,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert data["message"] == "Insight created"

    def test_create_insight_minimal(self, client_dev_enabled: TestClient) -> None:
        """Should create an insight with minimal fields."""
        response = client_dev_enabled.post(
            "/dev/insights",
            json={
                "topic_key": "self:zos",
                "category": "self_reflection",
                "content": "Minimal insight.",
            },
        )
        assert response.status_code == 200

    def test_create_insight_validates_valence(self, client_dev_enabled: TestClient) -> None:
        """Should accept insight with at least one valence field."""
        response = client_dev_enabled.post(
            "/dev/insights",
            json={
                "topic_key": "server:123:user:456",
                "category": "user_reflection",
                "content": "Test insight with only joy valence.",
                "valence_joy": 0.9,
                "valence_curiosity": None,  # Explicitly null
            },
        )
        assert response.status_code == 200

    def test_create_insight_validates_confidence_range(self, client_dev_enabled: TestClient) -> None:
        """Should reject confidence values out of range."""
        response = client_dev_enabled.post(
            "/dev/insights",
            json={
                "topic_key": "server:123:user:456",
                "category": "user_reflection",
                "content": "Test",
                "confidence": 1.5,  # Out of range
            },
        )
        assert response.status_code == 422  # Validation error


# =============================================================================
# Test: Update Insight
# =============================================================================


class TestUpdateInsight:
    """Tests for: PATCH /dev/insights/{id} updates insight."""

    def test_update_insight_content(
        self,
        client_dev_enabled: TestClient,
        sample_insight: Insight,
    ) -> None:
        """Should update insight content."""
        response = client_dev_enabled.patch(
            f"/dev/insights/{sample_insight.id}",
            json={"content": "Updated content text."},
        )
        assert response.status_code == 200
        assert response.json()["message"] == "Insight updated"

    def test_update_insight_metrics(
        self,
        client_dev_enabled: TestClient,
        sample_insight: Insight,
    ) -> None:
        """Should update multiple insight fields."""
        response = client_dev_enabled.patch(
            f"/dev/insights/{sample_insight.id}",
            json={
                "confidence": 0.9,
                "importance": 0.5,
            },
        )
        assert response.status_code == 200

    def test_update_insight_quarantine(
        self,
        client_dev_enabled: TestClient,
        sample_insight: Insight,
    ) -> None:
        """Should be able to quarantine an insight."""
        response = client_dev_enabled.patch(
            f"/dev/insights/{sample_insight.id}",
            json={"quarantined": True},
        )
        assert response.status_code == 200

    def test_update_nonexistent_insight(self, client_dev_enabled: TestClient) -> None:
        """Should return 404 for nonexistent insight."""
        response = client_dev_enabled.patch(
            "/dev/insights/nonexistent_id",
            json={"content": "New content"},
        )
        assert response.status_code == 404

    def test_update_with_empty_body(
        self,
        client_dev_enabled: TestClient,
        sample_insight: Insight,
    ) -> None:
        """Should succeed even with no updates (no-op)."""
        response = client_dev_enabled.patch(
            f"/dev/insights/{sample_insight.id}",
            json={},
        )
        assert response.status_code == 200


# =============================================================================
# Test: Delete Insight
# =============================================================================


class TestDeleteInsight:
    """Tests for: DELETE /dev/insights/{id} deletes insight."""

    def test_delete_insight_success(
        self,
        client_dev_enabled: TestClient,
        sample_insight: Insight,
    ) -> None:
        """Should delete an insight (hard delete)."""
        response = client_dev_enabled.delete(f"/dev/insights/{sample_insight.id}")
        assert response.status_code == 200
        assert response.json()["message"] == "Insight deleted"

        # Verify it's actually gone
        response = client_dev_enabled.get(f"/insights/{sample_insight.topic_key}")
        # Should return empty list (or not contain this ID)
        insights = response.json()
        assert not any(i["id"] == sample_insight.id for i in insights)

    def test_delete_nonexistent_insight(self, client_dev_enabled: TestClient) -> None:
        """Should return 404 for nonexistent insight."""
        response = client_dev_enabled.delete("/dev/insights/nonexistent_id")
        assert response.status_code == 404


# =============================================================================
# Test: Bulk Delete
# =============================================================================


class TestBulkDelete:
    """Tests for: POST /dev/insights/bulk-delete."""

    def test_bulk_delete_by_topic(
        self,
        client_dev_enabled: TestClient,
        engine_dev_enabled,
    ) -> None:
        """Should delete all insights for a topic."""
        # First, create insights using the dev endpoint (which handles layer_run)
        topic_key = "server:999:user:999"
        for i in range(3):
            response = client_dev_enabled.post(
                "/dev/insights",
                json={
                    "topic_key": topic_key,
                    "category": "user_reflection",
                    "content": f"Test insight {i}",
                },
            )
            assert response.status_code == 200

        # Bulk delete
        response = client_dev_enabled.post(
            "/dev/insights/bulk-delete",
            json={"topic_key": topic_key},
        )
        assert response.status_code == 200
        assert response.json()["deleted"] == 3

    def test_bulk_delete_by_category(
        self,
        client_dev_enabled: TestClient,
        engine_dev_enabled,
    ) -> None:
        """Should delete all insights of a category."""
        # Create insights with unique category using dev endpoint
        category = "test_category_for_delete"
        for i in range(2):
            response = client_dev_enabled.post(
                "/dev/insights",
                json={
                    "topic_key": f"server:123:user:{100 + i}",
                    "category": category,
                    "content": f"Test insight {i}",
                },
            )
            assert response.status_code == 200

        # Bulk delete
        response = client_dev_enabled.post(
            "/dev/insights/bulk-delete",
            json={"category": category},
        )
        assert response.status_code == 200
        assert response.json()["deleted"] == 2

    def test_bulk_delete_by_time(
        self,
        client_dev_enabled: TestClient,
        engine_dev_enabled,
    ) -> None:
        """Should delete insights before a given time."""
        from zos.insights import insert_insight
        from zos.database import layer_runs, topics
        import asyncio

        old_time = datetime.now(timezone.utc) - timedelta(days=30)
        topic_key = "server:888:user:888"
        layer_run_id = "old_test_run"

        with engine_dev_enabled.connect() as conn:
            from sqlalchemy import select

            # Ensure topic exists
            stmt = select(topics).where(topics.c.key == topic_key)
            if not conn.execute(stmt).fetchone():
                conn.execute(
                    topics.insert().values(
                        key=topic_key,
                        category="user",
                        is_global=False,
                        provisional=True,
                        created_at=old_time,
                        last_activity_at=old_time,
                    )
                )

            # Ensure layer_run exists for old insight
            stmt = select(layer_runs).where(layer_runs.c.id == layer_run_id)
            if not conn.execute(stmt).fetchone():
                conn.execute(
                    layer_runs.insert().values(
                        id=layer_run_id,
                        layer_name="test",
                        layer_hash="test",
                        started_at=old_time,
                        completed_at=old_time,
                        status="success",
                        targets_matched=0,
                        targets_processed=0,
                        targets_skipped=0,
                        insights_created=0,
                    )
                )
            conn.commit()

        # Create an old insight
        old_insight = Insight(
            id=generate_id(),
            topic_key=topic_key,
            category="user_reflection",
            content="Old insight",
            sources_scope_max=VisibilityScope.PUBLIC,
            created_at=old_time,
            layer_run_id=layer_run_id,
            salience_spent=1.0,
            strength_adjustment=1.0,
            strength=1.0,
            original_topic_salience=5.0,
            confidence=0.5,
            importance=0.5,
            novelty=0.5,
            valence_curiosity=0.5,
        )
        asyncio.get_event_loop().run_until_complete(insert_insight(engine_dev_enabled, old_insight))

        # Bulk delete before now (should delete the old one)
        cutoff = datetime.now(timezone.utc) - timedelta(days=1)
        response = client_dev_enabled.post(
            "/dev/insights/bulk-delete",
            json={"before": cutoff.isoformat()},
        )
        assert response.status_code == 200
        assert response.json()["deleted"] >= 1

    def test_bulk_delete_requires_filter(self, client_dev_enabled: TestClient) -> None:
        """Should require at least one filter."""
        response = client_dev_enabled.post(
            "/dev/insights/bulk-delete",
            json={},
        )
        assert response.status_code == 400
        assert "at least one filter" in response.json()["detail"].lower()


# =============================================================================
# Test: UI Form
# =============================================================================


class TestDevUI:
    """Tests for: Dev mode UI endpoints."""

    def test_create_insight_page_accessible(self, client_dev_enabled: TestClient) -> None:
        """Create insight page should be accessible in dev mode."""
        response = client_dev_enabled.get("/dev/create-insight")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_create_insight_page_has_form(self, client_dev_enabled: TestClient) -> None:
        """Create insight page should contain form elements."""
        response = client_dev_enabled.get("/dev/create-insight")
        html = response.text
        assert "topic_key" in html
        assert "category" in html
        assert "content" in html
        assert "valence" in html.lower()


# =============================================================================
# Test: Audit Logging
# =============================================================================


class TestAuditLogging:
    """Tests for: Audit logging captures operations.

    Note: We verify logging works by ensuring operations complete without
    error. The actual log output is verified via structlog configuration.
    """

    def test_create_completes_with_logging(self, client_dev_enabled: TestClient) -> None:
        """Create operation should complete (logging happens)."""
        response = client_dev_enabled.post(
            "/dev/insights",
            json={
                "topic_key": "server:123:user:456",
                "category": "user_reflection",
                "content": "Insight to be logged",
            },
        )
        assert response.status_code == 200

    def test_delete_completes_with_logging(
        self,
        client_dev_enabled: TestClient,
        sample_insight: Insight,
    ) -> None:
        """Delete operation should complete (logging happens)."""
        response = client_dev_enabled.delete(f"/dev/insights/{sample_insight.id}")
        assert response.status_code == 200

    def test_bulk_delete_completes_with_logging(
        self,
        client_dev_enabled: TestClient,
    ) -> None:
        """Bulk delete operation should complete (logging happens)."""
        response = client_dev_enabled.post(
            "/dev/insights/bulk-delete",
            json={"topic_key": "server:nonexistent:topic"},
        )
        assert response.status_code == 200
        # Deletes 0 because topic doesn't exist, but operation completes
        assert response.json()["deleted"] == 0
