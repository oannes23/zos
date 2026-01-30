"""Tests for link analysis module.

Covers:
- URL extraction from various message formats
- YouTube URL detection and video ID extraction
- robots.txt respect
- Transcript fetching (mocked)
- Duration threshold (TLDW) behavior
- Failure handling
- Database operations
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zos.config import Config
from zos.database import channels, create_tables, get_engine, link_analysis, messages, servers
from zos.links import (
    LinkAnalyzer,
    extract_domain,
    extract_urls,
    extract_video_id,
    get_link_analysis_for_message,
    insert_link_analysis,
    is_youtube_url,
)
from zos.models import ContentType, LinkAnalysis


def create_test_message(engine, message_id: str, server_id: str = "test-server") -> None:
    """Helper to create a test message with required parent records."""
    now = datetime.now(timezone.utc)
    channel_id = f"channel-{message_id}"

    with engine.connect() as conn:
        # Insert server if not exists
        conn.execute(
            servers.insert().prefix_with("OR IGNORE").values(
                id=server_id,
                name="Test Server",
                threads_as_topics=True,
                created_at=now,
            )
        )
        # Insert channel if not exists
        conn.execute(
            channels.insert().prefix_with("OR IGNORE").values(
                id=channel_id,
                server_id=server_id,
                name="test-channel",
                type="text",
                created_at=now,
            )
        )
        # Insert message
        conn.execute(
            messages.insert().prefix_with("OR IGNORE").values(
                id=message_id,
                channel_id=channel_id,
                server_id=server_id,
                author_id="test-author",
                content="Test message content",
                created_at=now,
                visibility_scope="public",
                has_media=False,
                has_links=True,
                ingested_at=now,
            )
        )
        conn.commit()


class TestURLExtraction:
    """Tests for URL extraction from message content."""

    def test_extract_single_url(self) -> None:
        """Should extract a single URL from content."""
        content = "Check out https://example.com/page"
        urls = extract_urls(content)
        assert urls == ["https://example.com/page"]

    def test_extract_multiple_urls(self) -> None:
        """Should extract multiple URLs from content."""
        content = "Links: https://example.com and https://test.org/page"
        urls = extract_urls(content)
        assert len(urls) == 2
        assert "https://example.com" in urls
        assert "https://test.org/page" in urls

    def test_extract_url_with_path_and_query(self) -> None:
        """Should extract URLs with paths and query parameters."""
        content = "Visit https://example.com/path/to/page?foo=bar&baz=qux"
        urls = extract_urls(content)
        assert len(urls) == 1
        assert "foo=bar" in urls[0]
        assert "baz=qux" in urls[0]

    def test_extract_no_urls(self) -> None:
        """Should return empty list for content without URLs."""
        content = "Just a regular message without links"
        urls = extract_urls(content)
        assert urls == []

    def test_extract_http_and_https(self) -> None:
        """Should extract both HTTP and HTTPS URLs."""
        content = "http://insecure.com https://secure.com"
        urls = extract_urls(content)
        assert len(urls) == 2

    def test_extract_urls_with_special_characters(self) -> None:
        """Should handle URLs with special characters in path."""
        content = "https://example.com/path-with-dashes/and_underscores"
        urls = extract_urls(content)
        assert len(urls) == 1

    def test_extract_urls_ignores_angle_brackets(self) -> None:
        """Should not include angle brackets in extracted URLs."""
        content = "Link: <https://example.com>"
        urls = extract_urls(content)
        assert urls == ["https://example.com"]


class TestYouTubeURLDetection:
    """Tests for YouTube URL detection."""

    def test_youtube_com_url(self) -> None:
        """Should detect youtube.com URLs."""
        assert is_youtube_url("https://youtube.com/watch?v=abc123")
        assert is_youtube_url("https://www.youtube.com/watch?v=abc123")

    def test_youtu_be_url(self) -> None:
        """Should detect youtu.be short URLs."""
        assert is_youtube_url("https://youtu.be/abc123")

    def test_mobile_youtube_url(self) -> None:
        """Should detect mobile YouTube URLs."""
        assert is_youtube_url("https://m.youtube.com/watch?v=abc123")

    def test_non_youtube_url(self) -> None:
        """Should not detect non-YouTube URLs."""
        assert not is_youtube_url("https://example.com")
        assert not is_youtube_url("https://vimeo.com/123456")

    def test_malformed_url(self) -> None:
        """Should handle malformed URLs gracefully."""
        assert not is_youtube_url("not a url")
        assert not is_youtube_url("")


class TestVideoIDExtraction:
    """Tests for YouTube video ID extraction."""

    def test_standard_watch_url(self) -> None:
        """Should extract ID from standard watch URL."""
        url = "https://youtube.com/watch?v=dQw4w9WgXcQ"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_short_url(self) -> None:
        """Should extract ID from youtu.be short URL."""
        url = "https://youtu.be/dQw4w9WgXcQ"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_embed_url(self) -> None:
        """Should extract ID from embed URL."""
        url = "https://youtube.com/embed/dQw4w9WgXcQ"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_shorts_url(self) -> None:
        """Should extract ID from shorts URL."""
        url = "https://youtube.com/shorts/dQw4w9WgXcQ"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_url_with_extra_params(self) -> None:
        """Should extract ID even with extra query parameters."""
        url = "https://youtube.com/watch?v=dQw4w9WgXcQ&t=120s&list=PLtest"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_invalid_url_returns_none(self) -> None:
        """Should return None for non-YouTube URLs."""
        assert extract_video_id("https://example.com") is None
        assert extract_video_id("https://youtube.com/channel/UCtest") is None


class TestDomainExtraction:
    """Tests for domain extraction."""

    def test_extract_simple_domain(self) -> None:
        """Should extract simple domain."""
        assert extract_domain("https://example.com/page") == "example.com"

    def test_extract_subdomain(self) -> None:
        """Should include subdomain."""
        assert extract_domain("https://www.example.com/page") == "www.example.com"

    def test_extract_domain_lowercase(self) -> None:
        """Should return lowercase domain."""
        assert extract_domain("https://EXAMPLE.COM/page") == "example.com"

    def test_extract_domain_with_port(self) -> None:
        """Should include port in domain."""
        assert extract_domain("https://example.com:8080/page") == "example.com:8080"


class TestLinkAnalyzer:
    """Tests for LinkAnalyzer class."""

    @pytest.fixture
    def config(self, tmp_path) -> Config:
        """Provide a test configuration."""
        config = Config(data_dir=tmp_path)
        config.observation.link_fetch_enabled = True
        config.observation.youtube_transcript_enabled = True
        config.observation.video_duration_threshold_minutes = 30
        return config

    @pytest.fixture
    def engine(self, config):
        """Provide a test database engine."""
        engine = get_engine(config)
        create_tables(engine)
        return engine

    @pytest.fixture
    def mock_llm_client(self):
        """Provide a mock LLM client."""
        client = MagicMock()
        client.complete = AsyncMock(
            return_value=MagicMock(text="Summary of the content")
        )
        return client

    @pytest.fixture
    def analyzer(self, config, engine, mock_llm_client):
        """Provide a LinkAnalyzer instance."""
        from zos.llm import RateLimiter

        return LinkAnalyzer(
            config=config,
            engine=engine,
            llm_client=mock_llm_client,
            link_rate_limiter=RateLimiter(calls_per_minute=100),
        )

    @pytest.mark.asyncio
    async def test_process_links_disabled(self, config, engine, mock_llm_client) -> None:
        """Should not process links when disabled in config."""
        config.observation.link_fetch_enabled = False
        from zos.llm import RateLimiter

        analyzer = LinkAnalyzer(
            config=config,
            engine=engine,
            llm_client=mock_llm_client,
            link_rate_limiter=RateLimiter(calls_per_minute=100),
        )

        count = await analyzer.process_links("msg123", "https://example.com")
        assert count == 0

    @pytest.mark.asyncio
    async def test_process_links_no_urls(self, analyzer) -> None:
        """Should return 0 for content without URLs."""
        count = await analyzer.process_links("msg123", "Just regular text")
        assert count == 0

    @pytest.mark.asyncio
    async def test_process_webpage_success(self, analyzer, engine) -> None:
        """Should fetch and summarize webpage content."""
        # Create parent records for foreign key constraint
        create_test_message(engine, "msg123")

        html_content = """
        <html>
            <head><title>Test Page</title></head>
            <body><p>This is test content.</p></body>
        </html>
        """

        with patch("zos.links.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = html_content
            mock_response.headers = {"content-type": "text/html"}
            mock_response.raise_for_status = MagicMock()

            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock()
            mock_client.return_value = mock_client_instance

            # Mock robots.txt check
            with patch.object(analyzer, "_can_fetch", return_value=True):
                await analyzer._process_webpage("msg123", "https://example.com/test")

        # Check that result was stored
        analyses = get_link_analysis_for_message(engine, "msg123")
        assert len(analyses) == 1
        assert analyses[0].url == "https://example.com/test"
        assert analyses[0].domain == "example.com"
        assert analyses[0].title == "Test Page"
        assert analyses[0].summary is not None
        assert not analyses[0].fetch_failed

    @pytest.mark.asyncio
    async def test_process_youtube_short_video(self, analyzer, engine) -> None:
        """Should fetch transcript for videos under threshold."""
        # Create parent records for foreign key constraint
        create_test_message(engine, "msg123")

        # Mock metadata fetch
        mock_metadata = {"title": "Test Video", "duration_seconds": 600}  # 10 minutes

        # Mock transcript
        mock_transcript = [
            {"text": "Hello everyone", "start": 0, "duration": 5},
            {"text": "Welcome to the video", "start": 5, "duration": 5},
        ]

        with (
            patch.object(analyzer, "_get_video_metadata", return_value=mock_metadata),
            patch.object(analyzer, "_fetch_transcript", return_value="Hello everyone Welcome to the video"),
        ):
            await analyzer._process_youtube("msg123", "https://youtube.com/watch?v=test123")

        # Check result
        analyses = get_link_analysis_for_message(engine, "msg123")
        assert len(analyses) == 1
        assert analyses[0].is_youtube is True
        assert analyses[0].title == "Test Video"
        assert analyses[0].duration_seconds == 600
        assert analyses[0].transcript_available is True
        assert "Summary" in analyses[0].summary

    @pytest.mark.asyncio
    async def test_process_youtube_long_video_tldw(self, analyzer, engine) -> None:
        """Should not fetch transcript for videos over threshold (TLDW)."""
        # Create parent records for foreign key constraint
        create_test_message(engine, "msg123")

        # Mock metadata for long video (45 minutes)
        mock_metadata = {"title": "Long Video", "duration_seconds": 2700}

        with patch.object(analyzer, "_get_video_metadata", return_value=mock_metadata):
            await analyzer._process_youtube("msg123", "https://youtube.com/watch?v=long123")

        # Check result
        analyses = get_link_analysis_for_message(engine, "msg123")
        assert len(analyses) == 1
        assert analyses[0].is_youtube is True
        assert analyses[0].transcript_available is False
        assert "TLDW" in analyses[0].summary
        assert "45 minutes" in analyses[0].summary

    @pytest.mark.asyncio
    async def test_process_youtube_no_transcript(self, analyzer, engine) -> None:
        """Should handle videos without available transcripts."""
        # Create parent records for foreign key constraint
        create_test_message(engine, "msg123")

        mock_metadata = {"title": "No Transcript Video", "duration_seconds": 300}

        with (
            patch.object(analyzer, "_get_video_metadata", return_value=mock_metadata),
            patch.object(analyzer, "_fetch_transcript", return_value=None),
        ):
            await analyzer._process_youtube("msg123", "https://youtube.com/watch?v=notrans")

        analyses = get_link_analysis_for_message(engine, "msg123")
        assert len(analyses) == 1
        assert analyses[0].transcript_available is False
        assert "unavailable" in analyses[0].summary.lower()

    @pytest.mark.asyncio
    async def test_robots_txt_respected(self, analyzer) -> None:
        """Should respect robots.txt disallow rules."""
        robots_content = """
User-agent: *
Disallow: /private/

User-agent: Zos
Disallow: /secret/
"""
        with patch("zos.links.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = robots_content

            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock()
            mock_client.return_value = mock_client_instance

            # Should be blocked by wildcard rule
            result = await analyzer._can_fetch("https://example.com/private/page")
            assert result is False

    @pytest.mark.asyncio
    async def test_robots_txt_allows_when_no_file(self, analyzer) -> None:
        """Should allow fetching when robots.txt doesn't exist."""
        with patch("zos.links.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 404

            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock()
            mock_client.return_value = mock_client_instance

            result = await analyzer._can_fetch("https://example.com/page")
            assert result is True

    @pytest.mark.asyncio
    async def test_fetch_failure_does_not_block(self, analyzer, engine) -> None:
        """Should log failure but not block processing of other links."""
        # Create parent records for foreign key constraint
        create_test_message(engine, "msg123")

        # Mock _fetch_page to return failure
        with patch.object(analyzer, "_fetch_page", return_value=(None, None)):
            # Should not raise
            await analyzer._process_webpage("msg123", "https://example.com/fail")

        # Should have stored failure record
        analyses = get_link_analysis_for_message(engine, "msg123")
        assert len(analyses) == 1
        assert analyses[0].fetch_failed is True

    @pytest.mark.asyncio
    async def test_summary_error_stored_when_llm_fails(self, config, engine) -> None:
        """Should store summary_error when LLM summarization fails.

        When page fetch succeeds but LLM call fails, the error should be
        captured in summary_error rather than silently producing NULL summary.
        """
        # Create parent records for foreign key constraint
        create_test_message(engine, "msg-llm-fail")

        # Create analyzer with LLM client that raises
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(side_effect=Exception("LLM connection timeout"))

        from zos.llm import RateLimiter

        analyzer = LinkAnalyzer(
            config=config,
            engine=engine,
            llm_client=mock_llm,
            link_rate_limiter=RateLimiter(calls_per_minute=100),
        )

        html_content = """
        <html>
            <head><title>Good Page</title></head>
            <body><p>Content fetched successfully.</p></body>
        </html>
        """

        with patch("zos.links.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = html_content
            mock_response.headers = {"content-type": "text/html"}
            mock_response.raise_for_status = MagicMock()

            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock()
            mock_client.return_value = mock_client_instance

            with patch.object(analyzer, "_can_fetch", return_value=True):
                await analyzer._process_webpage("msg-llm-fail", "https://example.com/page")

        # Verify: page fetched OK, but summary failed with error captured
        analyses = get_link_analysis_for_message(engine, "msg-llm-fail")
        assert len(analyses) == 1
        assert analyses[0].fetch_failed is False  # Page was fetched successfully
        assert analyses[0].summary is None  # LLM failed, no summary
        assert analyses[0].summary_error == "LLM connection timeout"
        assert analyses[0].title == "Good Page"


class TestDatabaseOperations:
    """Tests for database operations."""

    @pytest.fixture
    def engine(self, tmp_path):
        """Provide a test database engine."""
        config = Config(data_dir=tmp_path)
        engine = get_engine(config)
        create_tables(engine)
        return engine

    def test_insert_link_analysis(self, engine) -> None:
        """Should insert link analysis record."""
        # Create parent records for foreign key constraint
        create_test_message(engine, "msg456")

        analysis = LinkAnalysis(
            id="test-id-123",
            message_id="msg456",
            url="https://example.com/page",
            domain="example.com",
            content_type=ContentType.ARTICLE,
            title="Test Page",
            summary="A summary of the page",
            is_youtube=False,
            fetched_at=datetime.now(timezone.utc),
            fetch_failed=False,
        )

        insert_link_analysis(engine, analysis)

        # Verify it was stored
        analyses = get_link_analysis_for_message(engine, "msg456")
        assert len(analyses) == 1
        assert analyses[0].id == "test-id-123"
        assert analyses[0].title == "Test Page"

    def test_get_link_analysis_for_message_empty(self, engine) -> None:
        """Should return empty list for message with no analyses."""
        analyses = get_link_analysis_for_message(engine, "nonexistent")
        assert analyses == []

    def test_get_multiple_analyses_for_message(self, engine) -> None:
        """Should return all analyses for a message."""
        # Create parent records for foreign key constraint
        create_test_message(engine, "msg789")

        for i in range(3):
            analysis = LinkAnalysis(
                id=f"test-id-{i}",
                message_id="msg789",
                url=f"https://example{i}.com",
                domain=f"example{i}.com",
                content_type=ContentType.ARTICLE,
                is_youtube=False,
                fetch_failed=False,
            )
            insert_link_analysis(engine, analysis)

        analyses = get_link_analysis_for_message(engine, "msg789")
        assert len(analyses) == 3


class TestContentTypeInference:
    """Tests for content type inference."""

    @pytest.fixture
    def analyzer(self, tmp_path):
        """Provide a basic analyzer for testing."""
        config = Config(data_dir=tmp_path)
        engine = get_engine(config)
        create_tables(engine)
        mock_llm = MagicMock()
        from zos.llm import RateLimiter

        return LinkAnalyzer(
            config=config,
            engine=engine,
            llm_client=mock_llm,
            link_rate_limiter=RateLimiter(calls_per_minute=100),
        )

    def test_infer_video_from_domain(self, analyzer) -> None:
        """Should infer video type from video hosting domains."""
        assert analyzer._infer_content_type("https://vimeo.com/123", "") == ContentType.VIDEO

    def test_infer_audio_from_domain(self, analyzer) -> None:
        """Should infer audio type from audio hosting domains."""
        assert analyzer._infer_content_type("https://spotify.com/track/abc", "") == ContentType.AUDIO

    def test_infer_image_from_extension(self, analyzer) -> None:
        """Should infer image type from file extension."""
        assert analyzer._infer_content_type("https://example.com/photo.jpg", "") == ContentType.IMAGE
        assert analyzer._infer_content_type("https://example.com/image.png", "") == ContentType.IMAGE

    def test_infer_article_as_default(self, analyzer) -> None:
        """Should default to article for unknown content."""
        assert analyzer._infer_content_type("https://example.com/page", "") == ContentType.ARTICLE
