"""Tests for media/link database query functions.

Covers:
- get_media_stats: Counts, top domains, YouTube, failures
- list_media_analysis: Pagination, ordering
- list_link_analysis: Pagination, domain filter, YouTube filter
- get_link_analyses_for_messages: Batch query, grouping
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from zos.api.db_queries import get_media_stats, list_link_analysis, list_media_analysis
from zos.config import Config
from zos.database import (
    channels,
    create_tables,
    get_engine,
    link_analysis,
    media_analysis,
    messages,
    servers,
)
from zos.links import get_link_analyses_for_messages
from zos.migrations import migrate
from zos.models import ContentType


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
def now():
    """Return current time in UTC."""
    return datetime.now(timezone.utc)


@pytest.fixture
def sample_data(engine, now):
    """Create comprehensive sample data for testing."""
    with engine.connect() as conn:
        # Server and channel
        conn.execute(
            servers.insert().values(
                id="server1",
                name="Test Server",
                threads_as_topics=True,
                created_at=now,
            )
        )
        conn.execute(
            channels.insert().values(
                id="channel1",
                server_id="server1",
                name="general",
                type="text",
                created_at=now,
            )
        )

        # Messages
        for i in range(10):
            conn.execute(
                messages.insert().values(
                    id=f"msg{i}",
                    channel_id="channel1",
                    server_id="server1",
                    author_id=f"user{i % 3}",
                    content=f"Message {i}",
                    created_at=now - timedelta(hours=i),
                    visibility_scope="public",
                    has_media=(i < 3),
                    has_links=(i >= 3),
                    ingested_at=now,
                )
            )

        # Link analyses: 5 total, 2 YouTube, 1 failed
        link_data = [
            {
                "id": "link1",
                "message_id": "msg3",
                "url": "https://example.com/article1",
                "domain": "example.com",
                "content_type": "article",
                "title": "First Article",
                "summary": "Summary of first article.",
                "is_youtube": False,
                "fetched_at": now - timedelta(hours=1),
                "fetch_failed": False,
            },
            {
                "id": "link2",
                "message_id": "msg4",
                "url": "https://example.com/article2",
                "domain": "example.com",
                "content_type": "article",
                "title": "Second Article",
                "summary": "Summary of second article.",
                "is_youtube": False,
                "fetched_at": now - timedelta(hours=2),
                "fetch_failed": False,
            },
            {
                "id": "link3",
                "message_id": "msg5",
                "url": "https://youtube.com/watch?v=abc",
                "domain": "youtube.com",
                "content_type": "video",
                "title": "First Video",
                "summary": "Video about coding.",
                "is_youtube": True,
                "duration_seconds": 600,
                "transcript_available": True,
                "fetched_at": now - timedelta(hours=3),
                "fetch_failed": False,
            },
            {
                "id": "link4",
                "message_id": "msg6",
                "url": "https://youtube.com/watch?v=def",
                "domain": "youtube.com",
                "content_type": "video",
                "title": "Second Video",
                "summary": "Video about design.",
                "is_youtube": True,
                "duration_seconds": 1200,
                "transcript_available": False,
                "fetched_at": now - timedelta(hours=4),
                "fetch_failed": False,
            },
            {
                "id": "link5",
                "message_id": "msg7",
                "url": "https://broken.com/fail",
                "domain": "broken.com",
                "content_type": "article",
                "title": None,
                "summary": None,
                "is_youtube": False,
                "fetched_at": now - timedelta(hours=5),
                "fetch_failed": True,
                "fetch_error": "Connection refused",
            },
        ]

        for link in link_data:
            conn.execute(link_analysis.insert().values(**link))

        # Media analyses: 3 images
        media_data = [
            {
                "id": "media1",
                "message_id": "msg0",
                "media_type": "image",
                "url": "https://cdn.discord.com/image1.png",
                "filename": "sunset.png",
                "width": 1920,
                "height": 1080,
                "description": "A beautiful sunset over mountains.",
                "analyzed_at": now - timedelta(minutes=10),
                "analysis_model": "claude-3-5-haiku-20241022",
            },
            {
                "id": "media2",
                "message_id": "msg1",
                "media_type": "gif",
                "url": "https://cdn.discord.com/funny.gif",
                "filename": "funny.gif",
                "description": "A cat falling off a table.",
                "analyzed_at": now - timedelta(minutes=20),
                "analysis_model": "claude-3-5-haiku-20241022",
            },
            {
                "id": "media3",
                "message_id": "msg2",
                "media_type": "image",
                "url": "https://cdn.discord.com/chart.png",
                "filename": "chart.png",
                "width": 800,
                "height": 600,
                "description": "A bar chart showing growth metrics.",
                "analyzed_at": now - timedelta(minutes=30),
                "analysis_model": "claude-3-5-haiku-20241022",
            },
        ]

        for m in media_data:
            conn.execute(media_analysis.insert().values(**m))

        conn.commit()


# =============================================================================
# Test: get_media_stats
# =============================================================================


class TestGetMediaStats:
    """Tests for combined media/link statistics."""

    @pytest.mark.asyncio
    async def test_stats_empty_database(self, engine) -> None:
        """Should return zeros for empty database."""
        stats = await get_media_stats(engine, days=30)
        assert stats["images_analyzed"] == 0
        assert stats["links_fetched"] == 0
        assert stats["youtube_count"] == 0
        assert stats["failures"] == 0
        assert stats["top_domains"] == []

    @pytest.mark.asyncio
    async def test_stats_images_count(self, engine, sample_data) -> None:
        """Should count images analyzed."""
        stats = await get_media_stats(engine, days=30)
        assert stats["images_analyzed"] == 3

    @pytest.mark.asyncio
    async def test_stats_links_count(self, engine, sample_data) -> None:
        """Should count total links fetched."""
        stats = await get_media_stats(engine, days=30)
        assert stats["links_fetched"] == 5

    @pytest.mark.asyncio
    async def test_stats_youtube_count(self, engine, sample_data) -> None:
        """Should count YouTube links."""
        stats = await get_media_stats(engine, days=30)
        assert stats["youtube_count"] == 2

    @pytest.mark.asyncio
    async def test_stats_failures_count(self, engine, sample_data) -> None:
        """Should count failed link fetches."""
        stats = await get_media_stats(engine, days=30)
        assert stats["failures"] == 1

    @pytest.mark.asyncio
    async def test_stats_top_domains(self, engine, sample_data) -> None:
        """Should return top domains ordered by count."""
        stats = await get_media_stats(engine, days=30)
        domains = stats["top_domains"]
        assert len(domains) > 0
        # example.com has 2 entries, youtube.com has 2, broken.com has 1
        domain_names = [d["domain"] for d in domains]
        assert "example.com" in domain_names
        assert "youtube.com" in domain_names

    @pytest.mark.asyncio
    async def test_stats_days_filter(self, engine, now) -> None:
        """Should respect days filter for recent data only."""
        # Insert old data (40 days ago)
        with engine.connect() as conn:
            conn.execute(
                servers.insert().prefix_with("OR IGNORE").values(
                    id="server1",
                    name="Test",
                    threads_as_topics=True,
                    created_at=now,
                )
            )
            conn.execute(
                channels.insert().prefix_with("OR IGNORE").values(
                    id="channel1",
                    server_id="server1",
                    name="test",
                    type="text",
                    created_at=now,
                )
            )
            conn.execute(
                messages.insert().values(
                    id="old_msg",
                    channel_id="channel1",
                    server_id="server1",
                    author_id="user1",
                    content="Old message",
                    created_at=now - timedelta(days=40),
                    visibility_scope="public",
                    has_links=True,
                    has_media=False,
                    ingested_at=now,
                )
            )
            conn.execute(
                link_analysis.insert().values(
                    id="old_link",
                    message_id="old_msg",
                    url="https://old.com/page",
                    domain="old.com",
                    content_type="article",
                    is_youtube=False,
                    fetched_at=now - timedelta(days=40),
                    fetch_failed=False,
                )
            )
            conn.commit()

        stats = await get_media_stats(engine, days=30)
        assert stats["links_fetched"] == 0  # Old link outside window

    @pytest.mark.asyncio
    async def test_stats_includes_days_in_response(self, engine) -> None:
        """Should include days parameter in response."""
        stats = await get_media_stats(engine, days=7)
        assert stats["days"] == 7


# =============================================================================
# Test: list_media_analysis
# =============================================================================


class TestListMediaAnalysis:
    """Tests for paginated media analysis listing."""

    @pytest.mark.asyncio
    async def test_empty_database_returns_empty(self, engine) -> None:
        """Should return empty list and zero total for empty db."""
        results, total = await list_media_analysis(engine)
        assert results == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_returns_all_analyses(self, engine, sample_data) -> None:
        """Should return all media analyses."""
        results, total = await list_media_analysis(engine)
        assert total == 3
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_ordered_by_newest_first(self, engine, sample_data) -> None:
        """Should return analyses ordered by analyzed_at descending."""
        results, total = await list_media_analysis(engine)
        # Most recent should be first (media1 was analyzed 10 min ago)
        assert results[0]["id"] == "media1"
        assert results[2]["id"] == "media3"

    @pytest.mark.asyncio
    async def test_pagination_offset(self, engine, sample_data) -> None:
        """Should skip records with offset."""
        results, total = await list_media_analysis(engine, offset=1, limit=10)
        assert total == 3  # Total unchanged
        assert len(results) == 2  # Only 2 remaining

    @pytest.mark.asyncio
    async def test_pagination_limit(self, engine, sample_data) -> None:
        """Should limit number of results."""
        results, total = await list_media_analysis(engine, offset=0, limit=2)
        assert total == 3
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_result_has_expected_fields(self, engine, sample_data) -> None:
        """Results should include expected fields."""
        results, _ = await list_media_analysis(engine)
        result = results[0]
        assert "id" in result
        assert "message_id" in result
        assert "media_type" in result
        assert "filename" in result
        assert "description" in result
        assert "analyzed_at" in result
        assert "channel_id" in result
        assert "author_id" in result

    @pytest.mark.asyncio
    async def test_result_joins_message_data(self, engine, sample_data) -> None:
        """Results should include joined message data."""
        results, _ = await list_media_analysis(engine)
        # First result is media1 linked to msg0 in channel1
        assert results[0]["channel_id"] == "channel1"
        assert results[0]["author_id"] == "user0"


# =============================================================================
# Test: list_link_analysis
# =============================================================================


class TestListLinkAnalysis:
    """Tests for paginated link analysis listing."""

    @pytest.mark.asyncio
    async def test_empty_database_returns_empty(self, engine) -> None:
        """Should return empty list and zero total for empty db."""
        results, total = await list_link_analysis(engine)
        assert results == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_returns_all_analyses(self, engine, sample_data) -> None:
        """Should return all link analyses."""
        results, total = await list_link_analysis(engine)
        assert total == 5
        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_ordered_by_newest_first(self, engine, sample_data) -> None:
        """Should return analyses ordered by fetched_at descending."""
        results, total = await list_link_analysis(engine)
        # Most recent should be first (link1 fetched 1 hour ago)
        assert results[0]["id"] == "link1"

    @pytest.mark.asyncio
    async def test_filter_by_domain(self, engine, sample_data) -> None:
        """Should filter by domain."""
        results, total = await list_link_analysis(engine, domain="example.com")
        assert total == 2
        assert len(results) == 2
        for r in results:
            assert r["domain"] == "example.com"

    @pytest.mark.asyncio
    async def test_filter_by_youtube_true(self, engine, sample_data) -> None:
        """Should filter YouTube links."""
        results, total = await list_link_analysis(engine, is_youtube=True)
        assert total == 2
        for r in results:
            assert r["is_youtube"] is True

    @pytest.mark.asyncio
    async def test_filter_by_youtube_false(self, engine, sample_data) -> None:
        """Should filter non-YouTube links."""
        results, total = await list_link_analysis(engine, is_youtube=False)
        assert total == 3
        for r in results:
            assert r["is_youtube"] is False

    @pytest.mark.asyncio
    async def test_combined_filters(self, engine, sample_data) -> None:
        """Should apply both domain and YouTube filters together."""
        results, total = await list_link_analysis(
            engine, domain="youtube.com", is_youtube=True
        )
        assert total == 2
        for r in results:
            assert r["domain"] == "youtube.com"
            assert r["is_youtube"] is True

    @pytest.mark.asyncio
    async def test_pagination_offset(self, engine, sample_data) -> None:
        """Should skip records with offset."""
        results, total = await list_link_analysis(engine, offset=3, limit=10)
        assert total == 5
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_pagination_limit(self, engine, sample_data) -> None:
        """Should limit number of results."""
        results, total = await list_link_analysis(engine, offset=0, limit=2)
        assert total == 5
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_result_has_expected_fields(self, engine, sample_data) -> None:
        """Results should include expected fields."""
        results, _ = await list_link_analysis(engine)
        result = results[0]
        assert "id" in result
        assert "message_id" in result
        assert "url" in result
        assert "domain" in result
        assert "title" in result
        assert "summary" in result
        assert "is_youtube" in result
        assert "fetch_failed" in result
        assert "channel_id" in result
        assert "author_id" in result

    @pytest.mark.asyncio
    async def test_result_includes_failure_info(self, engine, sample_data) -> None:
        """Failed results should include error information."""
        # Get the failed link by filtering broken.com domain
        results, _ = await list_link_analysis(engine, domain="broken.com")
        assert len(results) == 1
        assert results[0]["fetch_failed"] is True
        assert results[0]["fetch_error"] == "Connection refused"


# =============================================================================
# Test: get_link_analyses_for_messages (batch query)
# =============================================================================


class TestGetLinkAnalysesForMessages:
    """Tests for batch link analysis query."""

    def test_empty_input_returns_empty(self, engine) -> None:
        """Should return empty dict for empty message_ids."""
        result = get_link_analyses_for_messages(engine, [])
        assert result == {}

    def test_no_matching_messages(self, engine) -> None:
        """Should return empty dict when no messages have analyses."""
        result = get_link_analyses_for_messages(engine, ["nonexistent1", "nonexistent2"])
        assert result == {}

    def test_returns_analyses_grouped_by_message(self, engine, sample_data) -> None:
        """Should return analyses grouped by message_id."""
        result = get_link_analyses_for_messages(engine, ["msg3", "msg5"])

        assert "msg3" in result
        assert "msg5" in result
        assert len(result["msg3"]) == 1
        assert len(result["msg5"]) == 1
        assert result["msg3"][0].domain == "example.com"
        assert result["msg5"][0].is_youtube is True

    def test_excludes_unrequested_messages(self, engine, sample_data) -> None:
        """Should not include analyses for unrequested messages."""
        result = get_link_analyses_for_messages(engine, ["msg3"])

        assert "msg3" in result
        assert "msg4" not in result
        assert "msg5" not in result

    def test_returns_link_analysis_objects(self, engine, sample_data) -> None:
        """Should return LinkAnalysis model instances."""
        from zos.models import LinkAnalysis

        result = get_link_analyses_for_messages(engine, ["msg3"])

        assert len(result["msg3"]) == 1
        analysis = result["msg3"][0]
        assert isinstance(analysis, LinkAnalysis)
        assert analysis.url == "https://example.com/article1"
        assert analysis.title == "First Article"
        assert analysis.content_type == ContentType.ARTICLE

    def test_handles_failed_analyses(self, engine, sample_data) -> None:
        """Should include failed analyses in results."""
        result = get_link_analyses_for_messages(engine, ["msg7"])

        assert "msg7" in result
        assert len(result["msg7"]) == 1
        assert result["msg7"][0].fetch_failed is True

    def test_batch_query_multiple_analyses_per_message(self, engine, now) -> None:
        """Should handle messages with multiple link analyses."""
        # Insert message with 2 links
        with engine.connect() as conn:
            conn.execute(
                servers.insert().prefix_with("OR IGNORE").values(
                    id="server1",
                    name="Test",
                    threads_as_topics=True,
                    created_at=now,
                )
            )
            conn.execute(
                channels.insert().prefix_with("OR IGNORE").values(
                    id="channel1",
                    server_id="server1",
                    name="test",
                    type="text",
                    created_at=now,
                )
            )
            conn.execute(
                messages.insert().values(
                    id="multi_link_msg",
                    channel_id="channel1",
                    server_id="server1",
                    author_id="user1",
                    content="Two links here",
                    created_at=now,
                    visibility_scope="public",
                    has_links=True,
                    has_media=False,
                    ingested_at=now,
                )
            )
            conn.execute(
                link_analysis.insert().values(
                    id="multi1",
                    message_id="multi_link_msg",
                    url="https://first.com/page",
                    domain="first.com",
                    content_type="article",
                    is_youtube=False,
                    fetched_at=now,
                    fetch_failed=False,
                )
            )
            conn.execute(
                link_analysis.insert().values(
                    id="multi2",
                    message_id="multi_link_msg",
                    url="https://second.com/page",
                    domain="second.com",
                    content_type="article",
                    is_youtube=False,
                    fetched_at=now,
                    fetch_failed=False,
                )
            )
            conn.commit()

        result = get_link_analyses_for_messages(engine, ["multi_link_msg"])
        assert len(result["multi_link_msg"]) == 2
        domains = {a.domain for a in result["multi_link_msg"]}
        assert domains == {"first.com", "second.com"}
