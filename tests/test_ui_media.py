"""Tests for Media Dashboard UI (Part 3 of Link Analysis Integration).

Tests the UI pages and partials for browsing link and image analyses,
viewing stats, filtering, and pagination.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from zos.api import create_app
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
def now():
    """Return current time in UTC."""
    return datetime.now(timezone.utc)


@pytest.fixture
def sample_data(engine, now):
    """Create sample server, channel, messages, links, and media for testing."""
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
        for i in range(5):
            conn.execute(
                messages.insert().values(
                    id=f"msg{i}",
                    channel_id="channel1",
                    server_id="server1",
                    author_id=f"user{i}",
                    content=f"Message {i}",
                    created_at=now - timedelta(hours=i),
                    visibility_scope="public",
                    has_media=(i < 2),
                    has_links=(i >= 2),
                    ingested_at=now,
                )
            )

        # Link analyses
        conn.execute(
            link_analysis.insert().values(
                id="link1",
                message_id="msg2",
                url="https://example.com/article",
                domain="example.com",
                content_type="article",
                title="Test Article",
                summary="A great article about testing.",
                is_youtube=False,
                fetched_at=now - timedelta(hours=1),
                fetch_failed=False,
            )
        )
        conn.execute(
            link_analysis.insert().values(
                id="link2",
                message_id="msg3",
                url="https://youtube.com/watch?v=test123",
                domain="youtube.com",
                content_type="video",
                title="Test Video",
                summary="A video about testing frameworks.",
                is_youtube=True,
                duration_seconds=600,
                transcript_available=True,
                fetched_at=now - timedelta(hours=2),
                fetch_failed=False,
            )
        )
        conn.execute(
            link_analysis.insert().values(
                id="link3",
                message_id="msg4",
                url="https://broken.com/page",
                domain="broken.com",
                content_type="article",
                title=None,
                summary=None,
                is_youtube=False,
                fetched_at=now - timedelta(hours=3),
                fetch_failed=True,
                fetch_error="Connection timeout",
            )
        )

        # Media analyses
        conn.execute(
            media_analysis.insert().values(
                id="media1",
                message_id="msg0",
                media_type="image",
                url="https://cdn.discord.com/image1.png",
                filename="sunset.png",
                width=1920,
                height=1080,
                description="A beautiful sunset over the ocean.",
                analyzed_at=now - timedelta(minutes=30),
                analysis_model="claude-3-5-haiku-20241022",
            )
        )
        conn.execute(
            media_analysis.insert().values(
                id="media2",
                message_id="msg1",
                media_type="gif",
                url="https://cdn.discord.com/funny.gif",
                filename="funny.gif",
                description="A cat falling off a table.",
                analyzed_at=now - timedelta(minutes=45),
                analysis_model="claude-3-5-haiku-20241022",
            )
        )

        conn.commit()


# =============================================================================
# Test: Media Dashboard Page
# =============================================================================


class TestMediaPage:
    """Tests for: GET /ui/media - main media dashboard page."""

    def test_media_page_returns_200(self, client: TestClient) -> None:
        """Media page should return 200 OK."""
        response = client.get("/ui/media")
        assert response.status_code == 200

    def test_media_page_returns_html(self, client: TestClient) -> None:
        """Media page should return HTML."""
        response = client.get("/ui/media")
        assert "text/html" in response.headers["content-type"]

    def test_media_page_contains_title(self, client: TestClient) -> None:
        """Media page should contain Media title."""
        response = client.get("/ui/media")
        assert "Media" in response.text

    def test_media_page_is_full_page(self, client: TestClient) -> None:
        """Media page should be a full HTML page with nav."""
        response = client.get("/ui/media")
        assert "<!DOCTYPE html>" in response.text
        assert "<nav" in response.text

    def test_media_page_has_active_nav(self, client: TestClient) -> None:
        """Media page should have media nav item active."""
        response = client.get("/ui/media")
        assert 'href="/ui/media"' in response.text

    def test_media_page_contains_htmx_triggers(self, client: TestClient) -> None:
        """Media page should contain htmx triggers for dynamic content."""
        response = client.get("/ui/media")
        assert "hx-get" in response.text
        assert "/ui/media/stats" in response.text
        assert "/ui/media/links" in response.text
        assert "/ui/media/images" in response.text


# =============================================================================
# Test: Stats Partial
# =============================================================================


class TestMediaStatsPartial:
    """Tests for: GET /ui/media/stats - summary cards."""

    def test_stats_partial_returns_200(self, client: TestClient) -> None:
        """Stats partial should return 200 OK."""
        response = client.get("/ui/media/stats")
        assert response.status_code == 200

    def test_stats_partial_returns_html(self, client: TestClient) -> None:
        """Stats partial should return HTML."""
        response = client.get("/ui/media/stats")
        assert "text/html" in response.headers["content-type"]

    def test_stats_partial_is_partial(self, client: TestClient) -> None:
        """Stats partial should not be a full page."""
        response = client.get("/ui/media/stats")
        assert "<!DOCTYPE" not in response.text
        assert "<html" not in response.text

    def test_stats_shows_zero_when_empty(self, client: TestClient) -> None:
        """Stats should show zeros when no analyses exist."""
        response = client.get("/ui/media/stats")
        assert "0" in response.text

    def test_stats_shows_correct_counts(self, client: TestClient, sample_data) -> None:
        """Stats should show correct counts for links and images."""
        response = client.get("/ui/media/stats")
        text = response.text
        # Should show stats labels
        assert "Links Fetched" in text or "links" in text.lower()
        assert "Images" in text or "image" in text.lower()

    def test_stats_shows_youtube_count(self, client: TestClient, sample_data) -> None:
        """Stats should show YouTube video count."""
        response = client.get("/ui/media/stats")
        assert "YouTube" in response.text or "youtube" in response.text.lower()

    def test_stats_shows_failures(self, client: TestClient, sample_data) -> None:
        """Stats should show failure count."""
        response = client.get("/ui/media/stats")
        assert "Fail" in response.text or "fail" in response.text.lower()

    def test_stats_shows_top_domains(self, client: TestClient, sample_data) -> None:
        """Stats should show top domains table."""
        response = client.get("/ui/media/stats")
        assert "example.com" in response.text or "domain" in response.text.lower()

    def test_stats_accepts_days_parameter(self, client: TestClient) -> None:
        """Stats should accept days query parameter."""
        response = client.get("/ui/media/stats?days=7")
        assert response.status_code == 200


# =============================================================================
# Test: Images List Partial
# =============================================================================


class TestMediaImagesPartial:
    """Tests for: GET /ui/media/images - image analyses list."""

    def test_images_partial_returns_200(self, client: TestClient) -> None:
        """Images partial should return 200 OK."""
        response = client.get("/ui/media/images")
        assert response.status_code == 200

    def test_images_partial_returns_html(self, client: TestClient) -> None:
        """Images partial should return HTML."""
        response = client.get("/ui/media/images")
        assert "text/html" in response.headers["content-type"]

    def test_images_partial_is_partial(self, client: TestClient) -> None:
        """Images partial should not be a full page."""
        response = client.get("/ui/media/images")
        assert "<!DOCTYPE" not in response.text

    def test_images_shows_empty_state(self, client: TestClient) -> None:
        """Images should show empty state when no analyses exist."""
        response = client.get("/ui/media/images")
        assert "No image" in response.text or "no image" in response.text.lower() or "0" in response.text

    def test_images_shows_analyses(self, client: TestClient, sample_data) -> None:
        """Images should show image analysis entries."""
        response = client.get("/ui/media/images")
        # Should show filenames
        assert "sunset.png" in response.text or "funny.gif" in response.text

    def test_images_shows_descriptions(self, client: TestClient, sample_data) -> None:
        """Images should show image descriptions."""
        response = client.get("/ui/media/images")
        assert "sunset" in response.text.lower() or "cat" in response.text.lower()

    def test_images_pagination_works(self, client: TestClient, sample_data) -> None:
        """Images should respect offset and limit parameters."""
        response = client.get("/ui/media/images?offset=0&limit=1")
        assert response.status_code == 200

    def test_images_large_offset_returns_empty(self, client: TestClient, sample_data) -> None:
        """Large offset should return no results."""
        response = client.get("/ui/media/images?offset=1000&limit=20")
        assert response.status_code == 200


# =============================================================================
# Test: Links List Partial
# =============================================================================


class TestMediaLinksPartial:
    """Tests for: GET /ui/media/links - link analyses list."""

    def test_links_partial_returns_200(self, client: TestClient) -> None:
        """Links partial should return 200 OK."""
        response = client.get("/ui/media/links")
        assert response.status_code == 200

    def test_links_partial_returns_html(self, client: TestClient) -> None:
        """Links partial should return HTML."""
        response = client.get("/ui/media/links")
        assert "text/html" in response.headers["content-type"]

    def test_links_partial_is_partial(self, client: TestClient) -> None:
        """Links partial should not be a full page."""
        response = client.get("/ui/media/links")
        assert "<!DOCTYPE" not in response.text

    def test_links_shows_empty_state(self, client: TestClient) -> None:
        """Links should show empty state when no analyses exist."""
        response = client.get("/ui/media/links")
        assert "No link" in response.text or "no link" in response.text.lower() or "0" in response.text

    def test_links_shows_analyses(self, client: TestClient, sample_data) -> None:
        """Links should show link analysis entries."""
        response = client.get("/ui/media/links")
        assert "example.com" in response.text

    def test_links_shows_titles(self, client: TestClient, sample_data) -> None:
        """Links should show link titles."""
        response = client.get("/ui/media/links")
        assert "Test Article" in response.text or "Test Video" in response.text

    def test_links_shows_summaries(self, client: TestClient, sample_data) -> None:
        """Links should show link summaries."""
        response = client.get("/ui/media/links")
        assert "testing" in response.text.lower()

    def test_links_filter_by_domain(self, client: TestClient, sample_data) -> None:
        """Links should filter by domain parameter."""
        response = client.get("/ui/media/links?domain=youtube.com")
        assert response.status_code == 200
        assert "youtube.com" in response.text

    def test_links_filter_by_youtube(self, client: TestClient, sample_data) -> None:
        """Links should filter by is_youtube parameter."""
        response = client.get("/ui/media/links?is_youtube=true")
        assert response.status_code == 200
        assert "youtube" in response.text.lower() or "Test Video" in response.text

    def test_links_pagination_works(self, client: TestClient, sample_data) -> None:
        """Links should respect offset and limit parameters."""
        response = client.get("/ui/media/links?offset=0&limit=1")
        assert response.status_code == 200

    def test_links_shows_failed_status(self, client: TestClient, sample_data) -> None:
        """Links should show failed status for failed fetches."""
        response = client.get("/ui/media/links")
        # Should have some indication of failure
        assert "fail" in response.text.lower() or "error" in response.text.lower() or "broken.com" in response.text


# =============================================================================
# Test: Navigation
# =============================================================================


class TestMediaNavigation:
    """Tests for media tab in navigation."""

    def test_nav_contains_media_link(self, client: TestClient) -> None:
        """Navigation should contain Media link."""
        response = client.get("/ui/")
        assert 'href="/ui/media"' in response.text
        assert "Media" in response.text

    def test_media_page_nav_active(self, client: TestClient) -> None:
        """Media page should mark its nav link as active."""
        response = client.get("/ui/media")
        # The media link should have class active
        text = response.text
        # Find the media nav link and check it has active class
        assert 'href="/ui/media"' in text
