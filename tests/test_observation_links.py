"""Tests for link analysis integration in the observation pipeline.

Covers:
- Link queue initialization
- Privacy boundary (anonymous users skipped)
- Queue behavior (put, full)
- Config disables link processing
- Background processor task lifecycle
- Graceful shutdown of link analysis task
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zos.config import Config
from zos.observation import ZosBot


class TestLinkQueueInitialization:
    """Tests for link queue setup in ZosBot.__init__."""

    def test_link_queue_created_with_configured_max_size(self) -> None:
        """Link queue uses link_queue_max_size from config."""
        config = Config()
        config.observation.link_queue_max_size = 75
        bot = ZosBot(config)

        assert bot._link_analysis_queue.maxsize == 75

    def test_link_queue_default_max_size(self) -> None:
        """Link queue has default max size of 50."""
        config = Config()
        bot = ZosBot(config)

        assert bot._link_analysis_queue.maxsize == 50

    def test_link_analysis_task_initially_none(self) -> None:
        """Link analysis task is None before setup_hook."""
        config = Config()
        bot = ZosBot(config)

        assert bot._link_analysis_task is None

    def test_link_analyzer_initially_none(self) -> None:
        """Link analyzer is None before first use."""
        config = Config()
        bot = ZosBot(config)

        assert bot._link_analyzer is None

    def test_link_rate_limiter_uses_config(self) -> None:
        """Link rate limiter uses link_rate_limit_per_minute from config."""
        config = Config()
        config.observation.link_rate_limit_per_minute = 10
        bot = ZosBot(config)

        assert bot._link_rate_limiter.calls_per_minute == 10


class TestLinkQueueing:
    """Tests for queueing links for analysis."""

    @pytest.mark.asyncio
    async def test_links_queued_from_message(self) -> None:
        """Message with links queues (message_id, content) tuple."""
        config = Config()
        config.observation.link_fetch_enabled = True
        bot = ZosBot(config)

        message = MagicMock()
        message.id = "msg123"
        message.content = "Check out https://example.com"

        await bot._queue_links_for_analysis(message, "user456")

        assert bot._link_analysis_queue.qsize() == 1
        item = bot._link_analysis_queue.get_nowait()
        assert item == ("msg123", "Check out https://example.com")

    @pytest.mark.asyncio
    async def test_anonymous_user_links_not_queued(self) -> None:
        """Links from anonymous users (<chat>) are not queued."""
        config = Config()
        config.observation.link_fetch_enabled = True
        bot = ZosBot(config)

        message = MagicMock()
        message.id = "msg789"
        message.content = "https://example.com"

        await bot._queue_links_for_analysis(message, "<chat_42>")

        assert bot._link_analysis_queue.empty()

    @pytest.mark.asyncio
    async def test_links_not_queued_when_disabled(self) -> None:
        """Links are not queued when link_fetch_enabled is False."""
        config = Config()
        config.observation.link_fetch_enabled = False
        bot = ZosBot(config)

        message = MagicMock()
        message.id = "msg101"
        message.content = "https://example.com"

        await bot._queue_links_for_analysis(message, "user123")

        assert bot._link_analysis_queue.empty()

    @pytest.mark.asyncio
    async def test_queue_full_does_not_raise(self) -> None:
        """QueueFull is handled gracefully without raising."""
        config = Config()
        config.observation.link_fetch_enabled = True
        config.observation.link_queue_max_size = 1
        bot = ZosBot(config)

        message1 = MagicMock()
        message1.id = "msg1"
        message1.content = "https://first.com"

        message2 = MagicMock()
        message2.id = "msg2"
        message2.content = "https://second.com"

        # Fill the queue
        await bot._queue_links_for_analysis(message1, "user1")
        assert bot._link_analysis_queue.qsize() == 1

        # Second should not raise despite queue being full
        await bot._queue_links_for_analysis(message2, "user2")

        # Queue should still have only 1 item
        assert bot._link_analysis_queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_queue_near_full_logs_warning(self) -> None:
        """Warning logged when queue is above 80% capacity."""
        config = Config()
        config.observation.link_fetch_enabled = True
        config.observation.link_queue_max_size = 4
        bot = ZosBot(config)

        # Pre-fill to above 80% (4 items in queue of size 4 = 100% > 80%)
        # The check triggers when qsize > max_size * 0.8, so 4 > 3.2
        for i in range(3):
            msg = MagicMock()
            msg.id = f"msg_{i}"
            msg.content = f"https://example{i}.com"
            await bot._queue_links_for_analysis(msg, f"user{i}")

        # At 3/4 = 75%, not yet above 80%. Add one more to get to 3 in queue
        # when the 4th comes in, qsize will be 3 which is < 3.2, still no warning.
        # Actually: the check runs BEFORE put_nowait. So at qsize=3, 3 > 3.2 is False.
        # Let's use max_size=3 so that at qsize=3, 3 > 2.4 triggers warning.
        config.observation.link_queue_max_size = 3
        bot = ZosBot(config)

        # Fill to above 80%: need qsize > 3 * 0.8 = 2.4, so qsize >= 3
        for i in range(2):
            msg = MagicMock()
            msg.id = f"msg_{i}"
            msg.content = f"https://example{i}.com"
            await bot._queue_links_for_analysis(msg, f"user{i}")

        # Queue is at 2, next will check at qsize=2 which is < 2.4. No warning yet.
        # We need qsize=3 before the check. Fill one more without patching.
        msg = MagicMock()
        msg.id = "msg_2"
        msg.content = "https://example2.com"
        await bot._queue_links_for_analysis(msg, "user2")

        # Now queue is full at 3/3. Next call will see qsize=3 > 2.4 -> warning
        # But queue is full so put_nowait will raise QueueFull.
        # The warning should still fire before the QueueFull.
        msg = MagicMock()
        msg.id = "msg_trigger"
        msg.content = "https://trigger.com"

        with patch("zos.observation.log") as mock_log:
            await bot._queue_links_for_analysis(msg, "user_trigger")

            # Should have logged warning about queue being near full
            warning_calls = [
                call for call in mock_log.warning.call_args_list
                if call[0][0] == "link_queue_near_full"
            ]
            assert len(warning_calls) >= 1


class TestLinkAnalysisTaskLifecycle:
    """Tests for the link analysis background task."""

    @pytest.mark.asyncio
    async def test_link_task_started_when_enabled(self) -> None:
        """Link analysis task is started in setup_hook when enabled."""
        config = Config()
        config.observation.link_fetch_enabled = True
        bot = ZosBot(config)

        # Mock dependencies for setup_hook
        bot.add_cog = AsyncMock()
        bot.tree.sync = AsyncMock()
        bot.poll_messages.change_interval = MagicMock()
        bot.poll_messages.start = MagicMock()

        await bot.setup_hook()

        assert bot._link_analysis_task is not None

        # Clean up the task
        bot._link_analysis_task.cancel()
        try:
            await bot._link_analysis_task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_link_task_not_started_when_disabled(self) -> None:
        """Link analysis task is NOT started when link_fetch_enabled is False."""
        config = Config()
        config.observation.link_fetch_enabled = False
        bot = ZosBot(config)

        # Mock dependencies for setup_hook
        bot.add_cog = AsyncMock()
        bot.tree.sync = AsyncMock()
        bot.poll_messages.change_interval = MagicMock()
        bot.poll_messages.start = MagicMock()

        await bot.setup_hook()

        assert bot._link_analysis_task is None


class TestLinkAnalyzerLazyInit:
    """Tests for lazy initialization of the link analyzer."""

    def test_get_link_analyzer_creates_instance(self) -> None:
        """_get_link_analyzer creates a LinkAnalyzer on first call."""
        config = Config()
        bot = ZosBot(config)

        # Need engine and LLM client for analyzer
        bot._engine = MagicMock()
        bot._llm_client = MagicMock()

        analyzer = bot._get_link_analyzer()

        assert analyzer is not None
        assert bot._link_analyzer is not None

    def test_get_link_analyzer_returns_same_instance(self) -> None:
        """_get_link_analyzer returns cached instance on subsequent calls."""
        config = Config()
        bot = ZosBot(config)

        bot._engine = MagicMock()
        bot._llm_client = MagicMock()

        first = bot._get_link_analyzer()
        second = bot._get_link_analyzer()

        assert first is second


class TestGracefulShutdownLinks:
    """Tests for link task cancellation during shutdown."""

    @pytest.mark.asyncio
    async def test_shutdown_cancels_link_task(self) -> None:
        """Graceful shutdown cancels the link analysis task."""
        config = Config()
        config.observation.link_fetch_enabled = True
        bot = ZosBot(config)

        # Mock dependencies for setup_hook to start the task
        bot.add_cog = AsyncMock()
        bot.tree.sync = AsyncMock()
        bot.poll_messages.change_interval = MagicMock()
        bot.poll_messages.start = MagicMock()

        await bot.setup_hook()

        # Verify task was created
        assert bot._link_analysis_task is not None

        # Mock other shutdown dependencies
        bot.poll_messages.is_running = MagicMock(return_value=False)
        bot.close = AsyncMock()

        await bot.graceful_shutdown()

        # Task should have been cancelled
        assert bot._link_analysis_task.cancelled() or bot._link_analysis_task.done()

    @pytest.mark.asyncio
    async def test_shutdown_handles_no_link_task(self) -> None:
        """Graceful shutdown works when no link task exists."""
        config = Config()
        bot = ZosBot(config)

        assert bot._link_analysis_task is None

        # Mock other shutdown dependencies
        bot.poll_messages.is_running = MagicMock(return_value=False)
        bot.close = AsyncMock()

        # Should not raise
        await bot.graceful_shutdown()
