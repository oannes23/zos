"""Tests for the insights storage system."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from zos.insights import Insight, InsightRepository
from zos.topics.topic_key import TopicKey

if TYPE_CHECKING:
    from zos.db import Database


@pytest.fixture
def insight_repo(test_db: Database) -> InsightRepository:
    """Create an insight repository with test database."""
    return InsightRepository(test_db)


class TestInsightRepository:
    """Tests for InsightRepository."""

    def test_store_creates_insight(self, insight_repo: InsightRepository) -> None:
        """Test that store creates an insight with all fields."""
        topic = TopicKey.channel(123456)

        insight = insight_repo.store(
            topic_key=topic,
            summary="Test insight summary",
            source_refs=[1, 2, 3],
            sources_scope_max="public",
            layer="test_layer",
            payload={"key": "value"},
        )

        assert insight.insight_id is not None
        assert len(insight.insight_id) == 36  # UUID format
        assert insight.topic_key == "channel:123456"
        assert insight.summary == "Test insight summary"
        assert insight.source_refs == [1, 2, 3]
        assert insight.sources_scope_max == "public"
        assert insight.run_id is None
        assert insight.layer == "test_layer"
        assert insight.payload == {"key": "value"}
        assert insight.created_at is not None

    def test_store_generates_unique_id(self, insight_repo: InsightRepository) -> None:
        """Test that each store generates a unique ID."""
        topic = TopicKey.user(789)

        insight1 = insight_repo.store(topic_key=topic, summary="Insight 1")
        insight2 = insight_repo.store(topic_key=topic, summary="Insight 2")

        assert insight1.insight_id != insight2.insight_id

    def test_store_with_minimal_fields(self, insight_repo: InsightRepository) -> None:
        """Test storing with only required fields."""
        topic = TopicKey.channel(999)

        insight = insight_repo.store(
            topic_key=topic,
            summary="Minimal insight",
        )

        assert insight.insight_id is not None
        assert insight.topic_key == "channel:999"
        assert insight.summary == "Minimal insight"
        assert insight.source_refs == []
        assert insight.sources_scope_max == "public"
        assert insight.run_id is None
        assert insight.layer is None
        assert insight.payload is None

    def test_get_insight_by_id(self, insight_repo: InsightRepository) -> None:
        """Test retrieving insight by ID."""
        topic = TopicKey.channel(123)
        stored = insight_repo.store(
            topic_key=topic,
            summary="Test summary",
            source_refs=[10, 20],
            payload={"data": 42},
        )

        retrieved = insight_repo.get_insight(stored.insight_id)

        assert retrieved is not None
        assert retrieved.insight_id == stored.insight_id
        assert retrieved.topic_key == stored.topic_key
        assert retrieved.summary == stored.summary
        assert retrieved.source_refs == [10, 20]
        assert retrieved.payload == {"data": 42}

    def test_get_insight_not_found(self, insight_repo: InsightRepository) -> None:
        """Test getting non-existent insight returns None."""
        result = insight_repo.get_insight("non-existent-id")
        assert result is None

    def test_get_insights_by_topic(self, insight_repo: InsightRepository) -> None:
        """Test retrieving insights by topic."""
        topic1 = TopicKey.channel(111)
        topic2 = TopicKey.channel(222)

        # Store insights for different topics
        insight_repo.store(topic_key=topic1, summary="Topic 1 - A")
        insight_repo.store(topic_key=topic1, summary="Topic 1 - B")
        insight_repo.store(topic_key=topic2, summary="Topic 2 - A")

        insights = insight_repo.get_insights(topic1)

        assert len(insights) == 2
        assert all(i.topic_key == "channel:111" for i in insights)

    def test_get_insights_limit(self, insight_repo: InsightRepository) -> None:
        """Test limit parameter restricts results."""
        topic = TopicKey.user(500)

        # Store 5 insights
        for i in range(5):
            insight_repo.store(topic_key=topic, summary=f"Insight {i}")

        insights = insight_repo.get_insights(topic, limit=3)

        assert len(insights) == 3

    def test_get_insights_ordered_by_created_desc(
        self, insight_repo: InsightRepository
    ) -> None:
        """Test insights are returned in descending order by created_at."""
        topic = TopicKey.channel(777)

        insight_repo.store(topic_key=topic, summary="First")
        insight_repo.store(topic_key=topic, summary="Second")
        insight_repo.store(topic_key=topic, summary="Third")

        insights = insight_repo.get_insights(topic)

        # Most recent should be first
        assert insights[0].summary == "Third"
        assert insights[1].summary == "Second"
        assert insights[2].summary == "First"

    def test_get_insights_since(self, insight_repo: InsightRepository) -> None:
        """Test since parameter filters by time."""
        topic = TopicKey.channel(888)

        # Store an insight
        insight_repo.store(topic_key=topic, summary="Recent insight")

        # Query with since in the past - should find it
        past = datetime.now(UTC) - timedelta(hours=1)
        insights = insight_repo.get_insights(topic, since=past)
        assert len(insights) == 1

        # Query with since in the future - should not find it
        future = datetime.now(UTC) + timedelta(hours=1)
        insights = insight_repo.get_insights(topic, since=future)
        assert len(insights) == 0

    def test_get_insights_scope_filter(self, insight_repo: InsightRepository) -> None:
        """Test scope parameter filters results."""
        topic = TopicKey.channel(999)

        insight_repo.store(
            topic_key=topic,
            summary="Public insight",
            sources_scope_max="public",
        )
        insight_repo.store(
            topic_key=topic,
            summary="DM insight",
            sources_scope_max="dm",
        )

        # Get only public
        public_insights = insight_repo.get_insights(topic, scope="public")
        assert len(public_insights) == 1
        assert public_insights[0].sources_scope_max == "public"

        # Get only dm
        dm_insights = insight_repo.get_insights(topic, scope="dm")
        assert len(dm_insights) == 1
        assert dm_insights[0].sources_scope_max == "dm"

        # Get all (no scope filter)
        all_insights = insight_repo.get_insights(topic)
        assert len(all_insights) == 2

    def test_get_insights_by_run(
        self, insight_repo: InsightRepository, test_db: "Database"
    ) -> None:
        """Test retrieving insights by run ID."""
        from zos.scheduler.repository import RunRepository
        from zos.scheduler.models import Run, RunStatus, TriggerType

        # Create run entries first (needed for foreign key constraint)
        run_repo = RunRepository(test_db)
        now = datetime.now(UTC)
        run_repo.create_run(Run(
            run_id="run-1",
            layer_name="test_layer",
            triggered_by=TriggerType.MANUAL,
            status=RunStatus.PENDING,
            started_at=now,
            window_start=now,
            window_end=now,
        ))
        run_repo.create_run(Run(
            run_id="run-2",
            layer_name="test_layer",
            triggered_by=TriggerType.MANUAL,
            status=RunStatus.PENDING,
            started_at=now,
            window_start=now,
            window_end=now,
        ))

        topic1 = TopicKey.channel(100)
        topic2 = TopicKey.channel(200)

        # Store insights for different runs
        insight_repo.store(
            topic_key=topic1,
            summary="Run 1 - A",
            run_id="run-1",
        )
        insight_repo.store(
            topic_key=topic2,
            summary="Run 1 - B",
            run_id="run-1",
        )
        insight_repo.store(
            topic_key=topic1,
            summary="Run 2 - A",
            run_id="run-2",
        )

        run1_insights = insight_repo.get_insights_by_run("run-1")
        assert len(run1_insights) == 2

        run2_insights = insight_repo.get_insights_by_run("run-2")
        assert len(run2_insights) == 1

    def test_count_by_topic(self, insight_repo: InsightRepository) -> None:
        """Test counting insights for a topic."""
        topic = TopicKey.user(321)

        assert insight_repo.count_by_topic(topic) == 0

        insight_repo.store(topic_key=topic, summary="One")
        assert insight_repo.count_by_topic(topic) == 1

        insight_repo.store(topic_key=topic, summary="Two")
        assert insight_repo.count_by_topic(topic) == 2

    def test_get_all_insights(self, insight_repo: InsightRepository) -> None:
        """Test get_all_insights returns insights from all topics."""
        insight_repo.store(topic_key=TopicKey.channel(1), summary="A")
        insight_repo.store(topic_key=TopicKey.channel(2), summary="B")
        insight_repo.store(topic_key=TopicKey.user(3), summary="C")

        all_insights = insight_repo.get_all_insights()
        assert len(all_insights) == 3

    def test_get_all_insights_with_filters(
        self, insight_repo: InsightRepository
    ) -> None:
        """Test get_all_insights respects filters."""
        insight_repo.store(
            topic_key=TopicKey.channel(1),
            summary="Public",
            sources_scope_max="public",
        )
        insight_repo.store(
            topic_key=TopicKey.channel(2),
            summary="DM",
            sources_scope_max="dm",
        )

        public_only = insight_repo.get_all_insights(scope="public")
        assert len(public_only) == 1
        assert public_only[0].summary == "Public"


class TestInsightModel:
    """Tests for the Insight dataclass."""

    def test_insight_fields(self) -> None:
        """Test Insight has all expected fields."""
        now = datetime.now(UTC)
        insight = Insight(
            insight_id="test-id",
            topic_key="user:123",
            created_at=now,
            summary="Test",
            payload={"key": "value"},
            source_refs=[1, 2],
            sources_scope_max="public",
            run_id="run-123",
            layer="test_layer",
        )

        assert insight.insight_id == "test-id"
        assert insight.topic_key == "user:123"
        assert insight.created_at == now
        assert insight.summary == "Test"
        assert insight.payload == {"key": "value"}
        assert insight.source_refs == [1, 2]
        assert insight.sources_scope_max == "public"
        assert insight.run_id == "run-123"
        assert insight.layer == "test_layer"
