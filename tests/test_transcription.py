"""Tests for audio/video transcription functionality.

Covers:
- Transcribable type detection (audio and video)
- Extension fallback for voice messages
- Config defaults for transcription fields
- Queueing: enabled/disabled, file size limits, mixed attachments, privacy
- Transcription flow: mocked Whisper, empty results, failures, local save
- MediaType correctness (audio vs video)
- [Transcription] prefix in description
- LLM call audit records
- Queue dispatch: image → _analyze_image, audio → _transcribe_audio
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from zos.config import Config, ObservationConfig
from zos.database import create_tables, get_engine, llm_calls, media_analysis
from zos.llm import CompletionResult, RateLimiter, Usage
from zos.models import LLMCallType, MediaAnalysis, MediaType
from zos.observation import (
    SUPPORTED_AUDIO_TYPES,
    SUPPORTED_VIDEO_TYPES,
    TRANSCRIBABLE_EXTENSIONS,
    TRANSCRIBABLE_TYPES,
    ZosBot,
)


# =========================================================================
# Detection Tests
# =========================================================================


class TestIsTranscribable:
    """Tests for _is_transcribable() detection."""

    def _make_attachment(self, content_type: str | None, filename: str = "file") -> MagicMock:
        att = MagicMock()
        att.content_type = content_type
        att.filename = filename
        return att

    def test_ogg_audio(self) -> None:
        bot = ZosBot(Config())
        assert bot._is_transcribable(self._make_attachment("audio/ogg", "voice.ogg")) is True

    def test_mp3_audio(self) -> None:
        bot = ZosBot(Config())
        assert bot._is_transcribable(self._make_attachment("audio/mpeg", "song.mp3")) is True

    def test_wav_audio(self) -> None:
        bot = ZosBot(Config())
        assert bot._is_transcribable(self._make_attachment("audio/wav", "clip.wav")) is True

    def test_flac_audio(self) -> None:
        bot = ZosBot(Config())
        assert bot._is_transcribable(self._make_attachment("audio/flac", "lossless.flac")) is True

    def test_mp4_video(self) -> None:
        bot = ZosBot(Config())
        assert bot._is_transcribable(self._make_attachment("video/mp4", "clip.mp4")) is True

    def test_webm_video(self) -> None:
        bot = ZosBot(Config())
        assert bot._is_transcribable(self._make_attachment("video/webm", "clip.webm")) is True

    def test_quicktime_video(self) -> None:
        bot = ZosBot(Config())
        assert bot._is_transcribable(self._make_attachment("video/quicktime", "clip.mov")) is True

    def test_rejects_images(self) -> None:
        bot = ZosBot(Config())
        assert bot._is_transcribable(self._make_attachment("image/png", "pic.png")) is False

    def test_rejects_pdf(self) -> None:
        bot = ZosBot(Config())
        assert bot._is_transcribable(self._make_attachment("application/pdf", "doc.pdf")) is False

    def test_extension_fallback_ogg(self) -> None:
        """Voice messages may lack content_type; fallback to extension."""
        bot = ZosBot(Config())
        assert bot._is_transcribable(self._make_attachment(None, "voice-message.ogg")) is True

    def test_extension_fallback_mp3(self) -> None:
        bot = ZosBot(Config())
        assert bot._is_transcribable(self._make_attachment(None, "track.mp3")) is True

    def test_extension_fallback_mp4(self) -> None:
        bot = ZosBot(Config())
        assert bot._is_transcribable(self._make_attachment(None, "video.mp4")) is True

    def test_no_extension_no_content_type(self) -> None:
        bot = ZosBot(Config())
        assert bot._is_transcribable(self._make_attachment(None, "noext")) is False


# =========================================================================
# Config Tests
# =========================================================================


class TestTranscriptionConfig:
    """Tests for transcription config defaults."""

    def test_transcription_enabled_default(self) -> None:
        config = ObservationConfig()
        assert config.transcription_enabled is True

    def test_transcription_rate_limit_default(self) -> None:
        config = ObservationConfig()
        assert config.transcription_rate_limit_per_minute == 10

    def test_transcription_max_file_size_default(self) -> None:
        config = ObservationConfig()
        assert config.transcription_max_file_size_mb == 25


# =========================================================================
# Queueing Tests
# =========================================================================


class TestTranscriptionQueueing:
    """Tests for queueing audio/video for transcription."""

    @pytest.mark.asyncio
    async def test_audio_queued_when_enabled(self) -> None:
        """Audio attachment is queued when transcription is enabled."""
        config = Config()
        config.observation.transcription_enabled = True
        bot = ZosBot(config)

        message = MagicMock()
        message.id = "msg100"

        attachment = MagicMock()
        attachment.content_type = "audio/ogg"
        attachment.filename = "voice.ogg"
        attachment.size = 1024 * 100  # 100KB

        message.attachments = [attachment]

        await bot._queue_media_for_analysis(message, "user1")

        assert bot._media_analysis_queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_audio_not_queued_when_disabled(self) -> None:
        """Audio attachment is NOT queued when transcription is disabled."""
        config = Config()
        config.observation.vision_enabled = False
        config.observation.transcription_enabled = False
        bot = ZosBot(config)

        message = MagicMock()
        message.id = "msg101"

        attachment = MagicMock()
        attachment.content_type = "audio/ogg"
        attachment.filename = "voice.ogg"

        message.attachments = [attachment]

        await bot._queue_media_for_analysis(message, "user1")

        assert bot._media_analysis_queue.empty()

    @pytest.mark.asyncio
    async def test_large_files_skipped(self) -> None:
        """Files over the size limit are not queued."""
        config = Config()
        config.observation.transcription_enabled = True
        config.observation.transcription_max_file_size_mb = 1  # 1MB limit
        bot = ZosBot(config)

        message = MagicMock()
        message.id = "msg102"

        attachment = MagicMock()
        attachment.content_type = "audio/ogg"
        attachment.filename = "huge.ogg"
        attachment.size = 2 * 1024 * 1024  # 2MB — over limit

        message.attachments = [attachment]

        await bot._queue_media_for_analysis(message, "user1")

        assert bot._media_analysis_queue.empty()

    @pytest.mark.asyncio
    async def test_mixed_attachments_image_and_audio(self) -> None:
        """Both image and audio are queued from mixed attachments."""
        config = Config()
        config.observation.vision_enabled = True
        config.observation.transcription_enabled = True
        bot = ZosBot(config)

        message = MagicMock()
        message.id = "msg103"

        image_att = MagicMock()
        image_att.content_type = "image/png"
        image_att.filename = "pic.png"

        audio_att = MagicMock()
        audio_att.content_type = "audio/ogg"
        audio_att.filename = "voice.ogg"
        audio_att.size = 50000

        pdf_att = MagicMock()
        pdf_att.content_type = "application/pdf"
        pdf_att.filename = "doc.pdf"

        message.attachments = [image_att, audio_att, pdf_att]

        await bot._queue_media_for_analysis(message, "user1")

        # Image + audio queued, PDF not
        assert bot._media_analysis_queue.qsize() == 2

    @pytest.mark.asyncio
    async def test_anonymous_user_media_not_queued(self) -> None:
        """Media from anonymous users is not queued."""
        config = Config()
        config.observation.transcription_enabled = True
        bot = ZosBot(config)

        message = MagicMock()
        message.id = "msg104"

        attachment = MagicMock()
        attachment.content_type = "audio/ogg"
        attachment.filename = "voice.ogg"
        attachment.size = 1024

        message.attachments = [attachment]

        await bot._queue_media_for_analysis(message, "<chat_42>")

        assert bot._media_analysis_queue.empty()

    @pytest.mark.asyncio
    async def test_media_task_starts_with_only_transcription_enabled(self) -> None:
        """Media analysis task starts even if vision is off but transcription is on."""
        config = Config()
        config.observation.vision_enabled = False
        config.observation.transcription_enabled = True
        bot = ZosBot(config)

        # Mock cog loading and command syncing
        bot.add_cog = AsyncMock()
        bot.tree.sync = AsyncMock()
        bot.poll_messages.change_interval = MagicMock()
        bot.poll_messages.start = MagicMock()

        await bot.setup_hook()

        # Task should be created
        assert bot._media_analysis_task is not None

        # Clean up
        bot._media_analysis_task.cancel()
        try:
            await bot._media_analysis_task
        except asyncio.CancelledError:
            pass


# =========================================================================
# Transcription Flow Tests
# =========================================================================


class TestTranscribeAudio:
    """Tests for the _transcribe_audio flow."""

    @pytest.fixture
    def db_engine(self, tmp_path: Path):
        config = Config()
        config.data_dir = tmp_path
        config.database.path = "test.db"

        engine = get_engine(config)
        create_tables(engine)

        return engine

    def _insert_message(self, engine, message_id: str = "msg200") -> None:
        from zos.database import channels, messages as messages_table, servers

        with engine.connect() as conn:
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
                    id=message_id,
                    channel_id="channel1",
                    server_id="server1",
                    author_id="user1",
                    content="Check this out",
                    created_at=datetime.now(timezone.utc),
                    visibility_scope="public",
                    has_media=True,
                    has_links=False,
                    ingested_at=datetime.now(timezone.utc),
                )
            )
            conn.commit()

    @pytest.mark.asyncio
    async def test_successful_transcription(self, db_engine, tmp_path: Path) -> None:
        """Successful transcription stores result with [Transcription] prefix."""
        config = Config()
        config.data_dir = tmp_path
        bot = ZosBot(config, engine=db_engine)
        self._insert_message(db_engine, "msg200")

        attachment = MagicMock()
        attachment.content_type = "audio/ogg"
        attachment.url = "https://cdn.discord.com/attachments/voice.ogg"
        attachment.filename = "voice.ogg"
        attachment.read = AsyncMock(return_value=b"\x00" * 1000)

        mock_result = CompletionResult(
            text="Hello world, this is a test message.",
            usage=Usage(input_tokens=0, output_tokens=9),
            model="whisper-1",
            provider="openai",
        )

        with patch.object(bot, "_get_llm_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.transcribe_audio = AsyncMock(return_value=mock_result)
            mock_get_client.return_value = mock_client

            await bot._transcribe_audio("msg200", attachment)

        # Verify stored
        analyses = bot._get_media_analysis_for_message("msg200")
        assert len(analyses) == 1
        assert analyses[0].description == "[Transcription] Hello world, this is a test message."
        assert analyses[0].media_type == MediaType.AUDIO
        assert analyses[0].analysis_model == "whisper-1"

    @pytest.mark.asyncio
    async def test_video_gets_video_media_type(self, db_engine, tmp_path: Path) -> None:
        """Video attachments are stored with MediaType.VIDEO."""
        config = Config()
        config.data_dir = tmp_path
        bot = ZosBot(config, engine=db_engine)
        self._insert_message(db_engine, "msg201")

        attachment = MagicMock()
        attachment.content_type = "video/mp4"
        attachment.url = "https://cdn.discord.com/attachments/clip.mp4"
        attachment.filename = "clip.mp4"
        attachment.read = AsyncMock(return_value=b"\x00" * 500)

        mock_result = CompletionResult(
            text="A person speaking about Python.",
            usage=Usage(input_tokens=0, output_tokens=6),
            model="whisper-1",
            provider="openai",
        )

        with patch.object(bot, "_get_llm_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.transcribe_audio = AsyncMock(return_value=mock_result)
            mock_get_client.return_value = mock_client

            await bot._transcribe_audio("msg201", attachment)

        analyses = bot._get_media_analysis_for_message("msg201")
        assert len(analyses) == 1
        assert analyses[0].media_type == MediaType.VIDEO

    @pytest.mark.asyncio
    async def test_empty_transcription_skipped(self, db_engine, tmp_path: Path) -> None:
        """Empty transcription result is not stored."""
        config = Config()
        config.data_dir = tmp_path
        bot = ZosBot(config, engine=db_engine)

        attachment = MagicMock()
        attachment.content_type = "audio/ogg"
        attachment.url = "https://cdn.discord.com/attachments/silence.ogg"
        attachment.filename = "silence.ogg"
        attachment.read = AsyncMock(return_value=b"\x00" * 100)

        mock_result = CompletionResult(
            text="   ",
            usage=Usage(input_tokens=0, output_tokens=0),
            model="whisper-1",
            provider="openai",
        )

        with patch.object(bot, "_get_llm_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.transcribe_audio = AsyncMock(return_value=mock_result)
            mock_get_client.return_value = mock_client

            await bot._transcribe_audio("msg_empty", attachment)

        # Nothing should be stored
        analyses = bot._get_media_analysis_for_message("msg_empty")
        assert len(analyses) == 0

    @pytest.mark.asyncio
    async def test_failure_logged_not_fatal(self, db_engine, tmp_path: Path) -> None:
        """Transcription failure is logged but doesn't raise."""
        config = Config()
        config.data_dir = tmp_path
        bot = ZosBot(config, engine=db_engine)

        attachment = MagicMock()
        attachment.content_type = "audio/ogg"
        attachment.url = "https://cdn.discord.com/test.ogg"
        attachment.filename = "test.ogg"
        attachment.read = AsyncMock(side_effect=Exception("Download failed"))

        with patch("zos.observation.log") as mock_log:
            await bot._transcribe_audio("msg_fail", attachment)

            mock_log.warning.assert_called_once()
            call_kwargs = mock_log.warning.call_args[1]
            assert call_kwargs["message_id"] == "msg_fail"
            assert "Download failed" in call_kwargs["error"]

    @pytest.mark.asyncio
    async def test_local_file_saved(self, db_engine, tmp_path: Path) -> None:
        """Transcribed audio is saved to data/media/ directory."""
        config = Config()
        config.data_dir = tmp_path
        bot = ZosBot(config, engine=db_engine)
        self._insert_message(db_engine, "msg203")

        audio_bytes = b"\x00" * 500
        attachment = MagicMock()
        attachment.content_type = "audio/ogg"
        attachment.url = "https://cdn.discord.com/attachments/voice.ogg"
        attachment.filename = "voice.ogg"
        attachment.read = AsyncMock(return_value=audio_bytes)

        mock_result = CompletionResult(
            text="Test transcription",
            usage=Usage(input_tokens=0, output_tokens=4),
            model="whisper-1",
            provider="openai",
        )

        with patch.object(bot, "_get_llm_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.transcribe_audio = AsyncMock(return_value=mock_result)
            mock_get_client.return_value = mock_client

            await bot._transcribe_audio("msg203", attachment)

        # Check local file
        analyses = bot._get_media_analysis_for_message("msg203")
        assert len(analyses) == 1
        assert analyses[0].local_path is not None
        assert analyses[0].local_path.endswith(".ogg")

        local_path = tmp_path / "media" / analyses[0].local_path
        assert local_path.exists()
        assert local_path.read_bytes() == audio_bytes

    @pytest.mark.asyncio
    async def test_file_size_enforced_after_download(self, db_engine, tmp_path: Path) -> None:
        """File size is checked after download as a second guard."""
        config = Config()
        config.data_dir = tmp_path
        config.observation.transcription_max_file_size_mb = 1  # 1MB
        bot = ZosBot(config, engine=db_engine)

        # Return data larger than limit
        attachment = MagicMock()
        attachment.content_type = "audio/ogg"
        attachment.url = "https://cdn.discord.com/huge.ogg"
        attachment.filename = "huge.ogg"
        attachment.read = AsyncMock(return_value=b"\x00" * (2 * 1024 * 1024))

        with patch.object(bot, "_get_llm_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            await bot._transcribe_audio("msg_big", attachment)

            # transcribe_audio should NOT be called
            mock_client.transcribe_audio.assert_not_called()


# =========================================================================
# LLM Call Audit Tests
# =========================================================================


class TestTranscriptionAudit:
    """Tests for LLM call audit recording."""

    @pytest.fixture
    def db_engine(self, tmp_path: Path):
        config = Config()
        config.data_dir = tmp_path
        config.database.path = "test.db"

        engine = get_engine(config)
        create_tables(engine)

        return engine

    @pytest.mark.asyncio
    async def test_successful_call_recorded(self, db_engine, tmp_path: Path) -> None:
        """Successful transcription records an LLM call."""
        from zos.llm import ModelClient

        config = Config()
        config.data_dir = tmp_path
        client = ModelClient(config, engine=db_engine)

        mock_response = MagicMock()
        mock_response.text = "Hello world"

        with patch("openai.AsyncOpenAI") as MockOpenAI:
            mock_openai = MagicMock()
            mock_openai.audio.transcriptions.create = AsyncMock(return_value=mock_response)
            MockOpenAI.return_value = mock_openai

            with patch.object(client, "_get_api_key", return_value="test-key"):
                result = await client.transcribe_audio(
                    audio_data=b"\x00" * 100,
                    filename="test.ogg",
                )

        assert result.text == "Hello world"
        assert result.model == "whisper-1"

        # Check audit record
        with db_engine.connect() as conn:
            rows = conn.execute(
                select(llm_calls).where(llm_calls.c.call_type == "transcription")
            ).fetchall()

        assert len(rows) == 1
        assert rows[0].success is True
        assert rows[0].model_name == "whisper-1"
        assert rows[0].model_provider == "openai"

    @pytest.mark.asyncio
    async def test_failed_call_recorded(self, db_engine, tmp_path: Path) -> None:
        """Failed transcription records an error LLM call."""
        from zos.llm import ModelClient

        config = Config()
        config.data_dir = tmp_path
        client = ModelClient(config, engine=db_engine)

        with patch("openai.AsyncOpenAI") as MockOpenAI:
            mock_openai = MagicMock()
            mock_openai.audio.transcriptions.create = AsyncMock(
                side_effect=Exception("API error")
            )
            MockOpenAI.return_value = mock_openai

            with patch.object(client, "_get_api_key", return_value="test-key"):
                with pytest.raises(Exception, match="API error"):
                    await client.transcribe_audio(
                        audio_data=b"\x00" * 100,
                        filename="test.ogg",
                    )

        # Check error audit record
        with db_engine.connect() as conn:
            rows = conn.execute(
                select(llm_calls).where(llm_calls.c.call_type == "transcription")
            ).fetchall()

        assert len(rows) == 1
        assert rows[0].success is False
        assert "API error" in rows[0].error_message


# =========================================================================
# Queue Dispatch Tests
# =========================================================================


class TestQueueDispatch:
    """Tests for dispatch in _process_media_queue."""

    @pytest.mark.asyncio
    async def test_image_dispatches_to_analyze_image(self) -> None:
        """Image attachment dispatches to _analyze_image."""
        config = Config()
        config.observation.vision_enabled = True
        config.observation.transcription_enabled = True
        bot = ZosBot(config)

        attachment = MagicMock()
        attachment.content_type = "image/png"
        attachment.filename = "pic.png"

        with patch.object(bot, "_analyze_image", new_callable=AsyncMock) as mock_analyze, \
             patch.object(bot, "_transcribe_audio", new_callable=AsyncMock) as mock_transcribe:
            # Simulate what _process_media_queue does
            if bot._is_transcribable(attachment):
                await bot._transcribe_audio("msg1", attachment)
            else:
                await bot._analyze_image("msg1", attachment)

            mock_analyze.assert_called_once_with("msg1", attachment)
            mock_transcribe.assert_not_called()

    @pytest.mark.asyncio
    async def test_audio_dispatches_to_transcribe_audio(self) -> None:
        """Audio attachment dispatches to _transcribe_audio."""
        config = Config()
        config.observation.vision_enabled = True
        config.observation.transcription_enabled = True
        bot = ZosBot(config)

        attachment = MagicMock()
        attachment.content_type = "audio/ogg"
        attachment.filename = "voice.ogg"

        with patch.object(bot, "_analyze_image", new_callable=AsyncMock) as mock_analyze, \
             patch.object(bot, "_transcribe_audio", new_callable=AsyncMock) as mock_transcribe:
            if bot._is_transcribable(attachment):
                await bot._transcribe_audio("msg2", attachment)
            else:
                await bot._analyze_image("msg2", attachment)

            mock_transcribe.assert_called_once_with("msg2", attachment)
            mock_analyze.assert_not_called()

    @pytest.mark.asyncio
    async def test_video_dispatches_to_transcribe_audio(self) -> None:
        """Video attachment dispatches to _transcribe_audio."""
        config = Config()
        bot = ZosBot(config)

        attachment = MagicMock()
        attachment.content_type = "video/mp4"
        attachment.filename = "clip.mp4"

        with patch.object(bot, "_analyze_image", new_callable=AsyncMock) as mock_analyze, \
             patch.object(bot, "_transcribe_audio", new_callable=AsyncMock) as mock_transcribe:
            if bot._is_transcribable(attachment):
                await bot._transcribe_audio("msg3", attachment)
            else:
                await bot._analyze_image("msg3", attachment)

            mock_transcribe.assert_called_once_with("msg3", attachment)
            mock_analyze.assert_not_called()


# =========================================================================
# Rate Limiter Configuration Tests
# =========================================================================


class TestTranscriptionRateLimiter:
    """Tests for transcription rate limiter setup."""

    def test_rate_limiter_configured_from_config(self) -> None:
        """Transcription rate limiter uses config value."""
        config = Config()
        config.observation.transcription_rate_limit_per_minute = 5

        bot = ZosBot(config)

        assert bot._transcription_rate_limiter.calls_per_minute == 5

    def test_rate_limiter_default(self) -> None:
        """Default transcription rate limit is 10/min."""
        config = Config()
        bot = ZosBot(config)

        assert bot._transcription_rate_limiter.calls_per_minute == 10
