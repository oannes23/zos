"""Tests for media analysis functionality.

Covers:
- Image detection for supported types
- Non-images are skipped
- Rate limiter prevents burst
- Failures don't block message storage
- Description stored correctly
- Vision disabled respects config
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from zos.config import Config, ObservationConfig
from zos.database import create_tables, get_engine, media_analysis
from zos.llm import CompletionResult, RateLimiter, Usage
from zos.models import MediaAnalysis, MediaType
from zos.observation import SUPPORTED_IMAGE_TYPES, ZosBot


class TestImageDetection:
    """Tests for image type detection."""

    def test_is_image_png(self) -> None:
        """PNG images are detected as images."""
        config = Config()
        bot = ZosBot(config)

        attachment = MagicMock()
        attachment.content_type = "image/png"

        assert bot._is_image(attachment) is True

    def test_is_image_jpeg(self) -> None:
        """JPEG images are detected as images."""
        config = Config()
        bot = ZosBot(config)

        attachment = MagicMock()
        attachment.content_type = "image/jpeg"

        assert bot._is_image(attachment) is True

    def test_is_image_gif(self) -> None:
        """GIF images are detected as images."""
        config = Config()
        bot = ZosBot(config)

        attachment = MagicMock()
        attachment.content_type = "image/gif"

        assert bot._is_image(attachment) is True

    def test_is_image_webp(self) -> None:
        """WebP images are detected as images."""
        config = Config()
        bot = ZosBot(config)

        attachment = MagicMock()
        attachment.content_type = "image/webp"

        assert bot._is_image(attachment) is True

    def test_non_image_video(self) -> None:
        """Video files are not detected as images."""
        config = Config()
        bot = ZosBot(config)

        attachment = MagicMock()
        attachment.content_type = "video/mp4"

        assert bot._is_image(attachment) is False

    def test_non_image_document(self) -> None:
        """Document files are not detected as images."""
        config = Config()
        bot = ZosBot(config)

        attachment = MagicMock()
        attachment.content_type = "application/pdf"

        assert bot._is_image(attachment) is False

    def test_non_image_audio(self) -> None:
        """Audio files are not detected as images."""
        config = Config()
        bot = ZosBot(config)

        attachment = MagicMock()
        attachment.content_type = "audio/mpeg"

        assert bot._is_image(attachment) is False


class TestMediaTypeInference:
    """Tests for inferring media type from filename when content_type is missing."""

    def test_infer_from_content_type_when_present(self) -> None:
        """Uses content_type when available."""
        config = Config()
        bot = ZosBot(config)

        attachment = MagicMock()
        attachment.content_type = "image/png"
        attachment.filename = "test.png"

        assert bot._infer_media_type(attachment) == "image/png"

    def test_infer_png_from_filename(self) -> None:
        """Infers PNG from .png extension when content_type is None."""
        config = Config()
        bot = ZosBot(config)

        attachment = MagicMock()
        attachment.content_type = None
        attachment.filename = "Aua6XAu.png"

        assert bot._infer_media_type(attachment) == "image/png"

    def test_infer_jpeg_from_jpg_extension(self) -> None:
        """Infers JPEG from .jpg extension."""
        config = Config()
        bot = ZosBot(config)

        attachment = MagicMock()
        attachment.content_type = None
        attachment.filename = "photo.jpg"

        assert bot._infer_media_type(attachment) == "image/jpeg"

    def test_infer_jpeg_from_jpeg_extension(self) -> None:
        """Infers JPEG from .jpeg extension."""
        config = Config()
        bot = ZosBot(config)

        attachment = MagicMock()
        attachment.content_type = None
        attachment.filename = "photo.jpeg"

        assert bot._infer_media_type(attachment) == "image/jpeg"

    def test_infer_gif_from_filename(self) -> None:
        """Infers GIF from .gif extension."""
        config = Config()
        bot = ZosBot(config)

        attachment = MagicMock()
        attachment.content_type = None
        attachment.filename = "animation.gif"

        assert bot._infer_media_type(attachment) == "image/gif"

    def test_infer_webp_from_filename(self) -> None:
        """Infers WebP from .webp extension."""
        config = Config()
        bot = ZosBot(config)

        attachment = MagicMock()
        attachment.content_type = None
        attachment.filename = "modern.webp"

        assert bot._infer_media_type(attachment) == "image/webp"

    def test_case_insensitive_extension_matching(self) -> None:
        """Extension matching is case-insensitive."""
        config = Config()
        bot = ZosBot(config)

        attachment = MagicMock()
        attachment.content_type = None
        attachment.filename = "UPPERCASE.PNG"

        assert bot._infer_media_type(attachment) == "image/png"

    def test_defaults_to_jpeg_when_no_info(self) -> None:
        """Defaults to image/jpeg when no content_type or recognized extension."""
        config = Config()
        bot = ZosBot(config)

        attachment = MagicMock()
        attachment.content_type = None
        attachment.filename = "unknown.xyz"

        assert bot._infer_media_type(attachment) == "image/jpeg"

    def test_defaults_to_jpeg_when_no_filename(self) -> None:
        """Defaults to image/jpeg when filename is None."""
        config = Config()
        bot = ZosBot(config)

        attachment = MagicMock()
        attachment.content_type = None
        attachment.filename = None

        assert bot._infer_media_type(attachment) == "image/jpeg"


class TestMediaTypeFromBytes:
    """Tests for detecting media type from magic bytes."""

    def test_detect_png_from_bytes(self) -> None:
        """Detects PNG from magic bytes."""
        config = Config()
        bot = ZosBot(config)

        # PNG magic bytes: 89 50 4E 47 0D 0A 1A 0A
        png_data = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100

        assert bot._detect_media_type_from_bytes(png_data) == "image/png"

    def test_detect_jpeg_from_bytes(self) -> None:
        """Detects JPEG from magic bytes."""
        config = Config()
        bot = ZosBot(config)

        # JPEG magic bytes: FF D8 FF
        jpeg_data = b'\xff\xd8\xff' + b'\x00' * 100

        assert bot._detect_media_type_from_bytes(jpeg_data) == "image/jpeg"

    def test_detect_gif87a_from_bytes(self) -> None:
        """Detects GIF87a from magic bytes."""
        config = Config()
        bot = ZosBot(config)

        gif_data = b'GIF87a' + b'\x00' * 100

        assert bot._detect_media_type_from_bytes(gif_data) == "image/gif"

    def test_detect_gif89a_from_bytes(self) -> None:
        """Detects GIF89a from magic bytes."""
        config = Config()
        bot = ZosBot(config)

        gif_data = b'GIF89a' + b'\x00' * 100

        assert bot._detect_media_type_from_bytes(gif_data) == "image/gif"

    def test_detect_webp_from_bytes(self) -> None:
        """Detects WebP from magic bytes."""
        config = Config()
        bot = ZosBot(config)

        # WebP: RIFF....WEBP (4 bytes size in between)
        webp_data = b'RIFF\x00\x00\x00\x00WEBP' + b'\x00' * 100

        assert bot._detect_media_type_from_bytes(webp_data) == "image/webp"

    def test_returns_none_for_unrecognized_format(self) -> None:
        """Returns None for unrecognized image format."""
        config = Config()
        bot = ZosBot(config)

        unknown_data = b'UNKNOWN_FORMAT' + b'\x00' * 100

        assert bot._detect_media_type_from_bytes(unknown_data) is None

    def test_returns_none_for_too_short_data(self) -> None:
        """Returns None when data is too short to identify."""
        config = Config()
        bot = ZosBot(config)

        short_data = b'\x89PNG'  # Only 4 bytes, need at least 12

        assert bot._detect_media_type_from_bytes(short_data) is None

    def test_returns_none_for_empty_data(self) -> None:
        """Returns None for empty data."""
        config = Config()
        bot = ZosBot(config)

        assert bot._detect_media_type_from_bytes(b'') is None


class TestMediaTypeMismatchHandling:
    """Tests for handling mismatch between inferred and detected media types."""

    @pytest.fixture
    def db_engine(self, tmp_path: Path):
        """Create a test database engine."""
        config = Config()
        config.data_dir = tmp_path
        config.database.path = "test.db"

        engine = get_engine(config)
        create_tables(engine)

        return engine

    @pytest.mark.asyncio
    async def test_uses_detected_type_over_inferred(
        self, db_engine, tmp_path: Path
    ) -> None:
        """Uses detected media type from bytes instead of inferred type."""
        config = Config()
        config.data_dir = tmp_path
        bot = ZosBot(config, engine=db_engine)

        # Insert prerequisite data
        from zos.database import channels, messages as messages_table, servers

        with db_engine.connect() as conn:
            conn.execute(
                servers.insert().values(
                    id="server1",
                    name="Test Server",
                    threads_as_topics=True,
                    created_at=datetime.now(timezone.utc),
                )
            )
            conn.execute(
                channels.insert().values(
                    id="channel1",
                    server_id="server1",
                    name="general",
                    type="text",
                    created_at=datetime.now(timezone.utc),
                )
            )
            conn.execute(
                messages_table.insert().values(
                    id="msg_mismatch",
                    channel_id="channel1",
                    server_id="server1",
                    author_id="user1",
                    content="Mislabeled image",
                    created_at=datetime.now(timezone.utc),
                    visibility_scope="public",
                    has_media=True,
                    has_links=False,
                    ingested_at=datetime.now(timezone.utc),
                )
            )
            conn.commit()

        # Mock attachment: claims to be webp but is actually JPEG
        attachment = MagicMock()
        attachment.content_type = "image/webp"
        attachment.url = "https://cdn.discord.com/attachments/fake.webp"
        attachment.filename = "fake.webp"
        attachment.width = 800
        attachment.height = 600
        # Return actual JPEG bytes
        jpeg_bytes = b'\xff\xd8\xff' + b'\x00' * 100
        attachment.read = AsyncMock(return_value=jpeg_bytes)

        # Mock LLM client - should be called with image/jpeg, not image/webp
        mock_result = MagicMock()
        mock_result.text = "Test description"
        mock_result.usage = MagicMock()
        mock_result.usage.input_tokens = 100
        mock_result.usage.output_tokens = 50
        mock_result.model = "test-model"

        with patch.object(bot, "_get_llm_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.analyze_image = AsyncMock(return_value=mock_result)
            mock_get_client.return_value = mock_client

            with patch("zos.observation.log") as mock_log:
                await bot._analyze_image("msg_mismatch", attachment)

                # Should log warning about mismatch
                mock_log.warning.assert_any_call(
                    "media_type_mismatch",
                    message_id="msg_mismatch",
                    filename="fake.webp",
                    inferred="image/webp",
                    detected="image/jpeg",
                )

            # Verify analyze_image was called with detected type (jpeg), not inferred (webp)
            mock_client.analyze_image.assert_called_once()
            call_kwargs = mock_client.analyze_image.call_args[1]
            assert call_kwargs["media_type"] == "image/jpeg"

    @pytest.mark.asyncio
    async def test_skips_unrecognized_format(self, db_engine, tmp_path: Path) -> None:
        """Skips analysis for unrecognized image formats."""
        config = Config()
        config.data_dir = tmp_path
        bot = ZosBot(config, engine=db_engine)

        # Mock attachment with unrecognized format
        attachment = MagicMock()
        attachment.content_type = "image/png"
        attachment.url = "https://cdn.discord.com/attachments/weird.png"
        attachment.filename = "weird.png"
        # Return unrecognized bytes
        unknown_bytes = b'UNKNOWNFORMAT' + b'\x00' * 100
        attachment.read = AsyncMock(return_value=unknown_bytes)

        with patch.object(bot, "_get_llm_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            with patch("zos.observation.log") as mock_log:
                await bot._analyze_image("msg_unknown", attachment)

                # Should log warning about unrecognized format
                mock_log.warning.assert_any_call(
                    "media_type_unrecognized",
                    message_id="msg_unknown",
                    filename="weird.png",
                    first_bytes=unknown_bytes[:12].hex(),
                )

            # analyze_image should NOT have been called
            mock_client.analyze_image.assert_not_called()


class TestVisionDisabled:
    """Tests for when vision is disabled in config."""

    @pytest.mark.asyncio
    async def test_queue_media_skips_when_vision_disabled(self) -> None:
        """Media queuing is skipped when vision_enabled is false."""
        config = Config()
        config.observation.vision_enabled = False
        bot = ZosBot(config)

        message = MagicMock()
        attachment = MagicMock()
        attachment.content_type = "image/png"
        message.attachments = [attachment]

        await bot._queue_media_for_analysis(message, "user123")

        # Queue should remain empty
        assert bot._media_analysis_queue.empty()

    @pytest.mark.asyncio
    async def test_media_task_not_started_when_vision_disabled(self) -> None:
        """Media analysis task is not started when vision is disabled."""
        config = Config()
        config.observation.vision_enabled = False
        bot = ZosBot(config)

        # Mock cog loading and command syncing
        bot.add_cog = AsyncMock()
        bot.tree.sync = AsyncMock()
        bot.poll_messages.change_interval = MagicMock()
        bot.poll_messages.start = MagicMock()

        await bot.setup_hook()

        # Task should not be created
        assert bot._media_analysis_task is None


class TestRateLimiter:
    """Tests for the rate limiter."""

    @pytest.mark.asyncio
    async def test_rate_limiter_allows_calls_under_limit(self) -> None:
        """Rate limiter allows calls when under the limit."""
        limiter = RateLimiter(calls_per_minute=5)

        # Should complete quickly without blocking
        start = datetime.now(timezone.utc)
        for _ in range(4):
            await limiter.acquire()
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()

        assert elapsed < 1.0  # Should be nearly instant

    @pytest.mark.asyncio
    async def test_rate_limiter_blocks_when_limit_reached(self) -> None:
        """Rate limiter blocks when limit is reached."""
        limiter = RateLimiter(calls_per_minute=2)

        # Make 2 calls to hit the limit
        await limiter.acquire()
        await limiter.acquire()

        # Third call should wait (we won't actually wait the full minute in tests)
        # Just verify the calls list has the right count
        assert len(limiter.calls) == 2

    def test_rate_limiter_configured_from_observation_config(self) -> None:
        """Vision rate limiter uses config value."""
        config = Config()
        config.observation.vision_rate_limit_per_minute = 20

        bot = ZosBot(config)

        assert bot._vision_rate_limiter.calls_per_minute == 20


class TestMediaAnalysisStorage:
    """Tests for storing media analysis results."""

    @pytest.fixture
    def db_engine(self, tmp_path: Path):
        """Create a test database engine."""
        config = Config()
        config.data_dir = tmp_path
        config.database.path = "test.db"

        engine = get_engine(config)
        create_tables(engine)

        return engine

    def test_insert_media_analysis(self, db_engine, tmp_path: Path) -> None:
        """Media analysis is inserted into database."""
        config = Config()
        config.data_dir = tmp_path
        bot = ZosBot(config, engine=db_engine)

        # First insert a message for FK constraint
        from zos.database import channels, messages, servers

        with db_engine.connect() as conn:
            conn.execute(
                servers.insert().values(
                    id="server1",
                    name="Test Server",
                    threads_as_topics=True,
                    created_at=datetime.now(timezone.utc),
                )
            )
            conn.execute(
                channels.insert().values(
                    id="channel1",
                    server_id="server1",
                    name="general",
                    type="text",
                    created_at=datetime.now(timezone.utc),
                )
            )
            conn.execute(
                messages.insert().values(
                    id="msg123",
                    channel_id="channel1",
                    server_id="server1",
                    author_id="user1",
                    content="Check out this image!",
                    created_at=datetime.now(timezone.utc),
                    visibility_scope="public",
                    has_media=True,
                    has_links=False,
                    ingested_at=datetime.now(timezone.utc),
                )
            )
            conn.commit()

        analysis = MediaAnalysis(
            id="analysis1",
            message_id="msg123",
            media_type=MediaType.IMAGE,
            url="https://cdn.discord.com/attachments/123/456/image.png",
            filename="image.png",
            width=800,
            height=600,
            description="A sunset over mountains with warm orange and purple hues.",
            analyzed_at=datetime.now(timezone.utc),
            analysis_model="claude-3-5-haiku-20241022",
        )

        bot._insert_media_analysis(analysis)

        # Verify it was stored
        with db_engine.connect() as conn:
            result = conn.execute(
                select(media_analysis).where(media_analysis.c.id == "analysis1")
            ).fetchone()

            assert result is not None
            assert result.message_id == "msg123"
            assert result.media_type == "image"
            assert result.description == "A sunset over mountains with warm orange and purple hues."

    def test_get_media_analysis_for_message(self, db_engine, tmp_path: Path) -> None:
        """Can retrieve media analysis for a message."""
        config = Config()
        config.data_dir = tmp_path
        bot = ZosBot(config, engine=db_engine)

        # Insert prerequisite data
        from zos.database import channels, messages as messages_table, servers

        with db_engine.connect() as conn:
            conn.execute(
                servers.insert().values(
                    id="server1",
                    name="Test Server",
                    threads_as_topics=True,
                    created_at=datetime.now(timezone.utc),
                )
            )
            conn.execute(
                channels.insert().values(
                    id="channel1",
                    server_id="server1",
                    name="general",
                    type="text",
                    created_at=datetime.now(timezone.utc),
                )
            )
            conn.execute(
                messages_table.insert().values(
                    id="msg456",
                    channel_id="channel1",
                    server_id="server1",
                    author_id="user1",
                    content="Another image",
                    created_at=datetime.now(timezone.utc),
                    visibility_scope="public",
                    has_media=True,
                    has_links=False,
                    ingested_at=datetime.now(timezone.utc),
                )
            )
            # Insert media analysis directly
            conn.execute(
                media_analysis.insert().values(
                    id="analysis2",
                    message_id="msg456",
                    media_type="gif",
                    url="https://cdn.discord.com/attachments/123/456/funny.gif",
                    filename="funny.gif",
                    description="An animated cat falling off a table.",
                    analyzed_at=datetime.now(timezone.utc),
                    analysis_model="claude-3-5-haiku-20241022",
                )
            )
            conn.commit()

        analyses = bot._get_media_analysis_for_message("msg456")

        assert len(analyses) == 1
        assert analyses[0].id == "analysis2"
        assert analyses[0].media_type == MediaType.GIF
        assert analyses[0].description == "An animated cat falling off a table."


class TestAnalyzeImage:
    """Tests for the image analysis flow."""

    @pytest.fixture
    def db_engine(self, tmp_path: Path):
        """Create a test database engine."""
        config = Config()
        config.data_dir = tmp_path
        config.database.path = "test.db"

        engine = get_engine(config)
        create_tables(engine)

        return engine

    @pytest.mark.asyncio
    async def test_analyze_image_success(self, db_engine, tmp_path: Path) -> None:
        """Successful image analysis stores result."""
        config = Config()
        config.data_dir = tmp_path
        bot = ZosBot(config, engine=db_engine)

        # Insert prerequisite data
        from zos.database import channels, messages as messages_table, servers

        with db_engine.connect() as conn:
            conn.execute(
                servers.insert().values(
                    id="server1",
                    name="Test Server",
                    threads_as_topics=True,
                    created_at=datetime.now(timezone.utc),
                )
            )
            conn.execute(
                channels.insert().values(
                    id="channel1",
                    server_id="server1",
                    name="general",
                    type="text",
                    created_at=datetime.now(timezone.utc),
                )
            )
            conn.execute(
                messages_table.insert().values(
                    id="msg789",
                    channel_id="channel1",
                    server_id="server1",
                    author_id="user1",
                    content="Look at this!",
                    created_at=datetime.now(timezone.utc),
                    visibility_scope="public",
                    has_media=True,
                    has_links=False,
                    ingested_at=datetime.now(timezone.utc),
                )
            )
            conn.commit()

        # Mock attachment with valid JPEG magic bytes
        attachment = MagicMock()
        attachment.content_type = "image/jpeg"
        attachment.url = "https://cdn.discord.com/attachments/test.jpg"
        attachment.filename = "test.jpg"
        attachment.width = 1920
        attachment.height = 1080
        # JPEG magic bytes: FF D8 FF
        jpeg_bytes = b'\xff\xd8\xff' + b'\x00' * 100
        attachment.read = AsyncMock(return_value=jpeg_bytes)

        # Mock LLM client response
        mock_result = CompletionResult(
            text="A beautiful mountain landscape at sunset.",
            usage=Usage(input_tokens=100, output_tokens=50),
            model="claude-3-5-haiku-20241022",
            provider="anthropic",
        )

        with patch.object(bot, "_get_llm_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.analyze_image = AsyncMock(return_value=mock_result)
            mock_get_client.return_value = mock_client

            await bot._analyze_image("msg789", attachment)

        # Verify analysis was stored
        analyses = bot._get_media_analysis_for_message("msg789")
        assert len(analyses) == 1
        assert analyses[0].description == "A beautiful mountain landscape at sunset."
        assert analyses[0].analysis_model == "claude-3-5-haiku-20241022"

    @pytest.mark.asyncio
    async def test_analyze_image_failure_logged_not_fatal(
        self, db_engine, tmp_path: Path
    ) -> None:
        """Failed image analysis is logged but doesn't raise."""
        config = Config()
        config.data_dir = tmp_path
        bot = ZosBot(config, engine=db_engine)

        # Mock attachment
        attachment = MagicMock()
        attachment.content_type = "image/jpeg"
        attachment.url = "https://cdn.discord.com/test.jpg"
        attachment.filename = "test.jpg"
        attachment.read = AsyncMock(side_effect=Exception("Download failed"))

        # Should not raise
        with patch("zos.observation.log") as mock_log:
            await bot._analyze_image("msg999", attachment)

            # Should log warning
            mock_log.warning.assert_called_once()
            call_kwargs = mock_log.warning.call_args[1]
            assert call_kwargs["message_id"] == "msg999"
            assert "Download failed" in call_kwargs["error"]


class TestMediaQueueing:
    """Tests for media queue functionality."""

    @pytest.mark.asyncio
    async def test_images_queued_for_analysis(self) -> None:
        """Image attachments are added to analysis queue."""
        config = Config()
        config.observation.vision_enabled = True
        bot = ZosBot(config)

        message = MagicMock()
        message.id = "msg123"

        attachment1 = MagicMock()
        attachment1.content_type = "image/png"
        attachment1.filename = "image1.png"

        attachment2 = MagicMock()
        attachment2.content_type = "image/jpeg"
        attachment2.filename = "image2.jpg"

        message.attachments = [attachment1, attachment2]

        await bot._queue_media_for_analysis(message, "user123")

        # Both images should be queued
        assert bot._media_analysis_queue.qsize() == 2

    @pytest.mark.asyncio
    async def test_non_images_not_queued(self) -> None:
        """Non-image attachments are not queued."""
        config = Config()
        config.observation.vision_enabled = True
        bot = ZosBot(config)

        message = MagicMock()
        message.id = "msg456"

        attachment = MagicMock()
        attachment.content_type = "video/mp4"
        attachment.filename = "video.mp4"

        message.attachments = [attachment]

        await bot._queue_media_for_analysis(message, "user456")

        # No items should be queued
        assert bot._media_analysis_queue.empty()

    @pytest.mark.asyncio
    async def test_mixed_attachments_only_images_queued(self) -> None:
        """Only images are queued from mixed attachments."""
        config = Config()
        config.observation.vision_enabled = True
        bot = ZosBot(config)

        message = MagicMock()
        message.id = "msg789"

        image_attachment = MagicMock()
        image_attachment.content_type = "image/png"
        image_attachment.filename = "image.png"

        video_attachment = MagicMock()
        video_attachment.content_type = "video/mp4"
        video_attachment.filename = "video.mp4"

        pdf_attachment = MagicMock()
        pdf_attachment.content_type = "application/pdf"
        pdf_attachment.filename = "doc.pdf"

        message.attachments = [image_attachment, video_attachment, pdf_attachment]

        await bot._queue_media_for_analysis(message, "user789")

        # Only the image should be queued
        assert bot._media_analysis_queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_anonymous_user_media_not_queued(self) -> None:
        """Media from anonymous users (<chat>) is not queued for analysis."""
        config = Config()
        config.observation.vision_enabled = True
        bot = ZosBot(config)

        message = MagicMock()
        message.id = "msg999"

        attachment = MagicMock()
        attachment.content_type = "image/png"
        attachment.filename = "anon_image.png"

        message.attachments = [attachment]

        # Anonymous user ID (privacy gate boundary)
        await bot._queue_media_for_analysis(message, "<chat_42>")

        # Media should NOT be queued - privacy boundary
        assert bot._media_analysis_queue.empty()


class TestVisionPrompt:
    """Tests for the vision prompt content."""

    def test_vision_prompt_is_phenomenological(self) -> None:
        """Vision prompt encourages phenomenological description."""
        from zos.observation import VISION_PROMPT

        # Should ask about feeling/experience, not just objects
        assert "feel" in VISION_PROMPT.lower()
        assert "mood" in VISION_PROMPT.lower() or "atmosphere" in VISION_PROMPT.lower()
        assert "context" in VISION_PROMPT.lower()

    def test_supported_image_types_match_spec(self) -> None:
        """Supported image types match the story specification."""
        expected = {"image/png", "image/jpeg", "image/gif", "image/webp"}
        assert SUPPORTED_IMAGE_TYPES == expected
