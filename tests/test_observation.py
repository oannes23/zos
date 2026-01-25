"""Tests for the observation module.

Covers:
- Bot initialization with correct intents
- CLI fails gracefully without token
- Polling task lifecycle
- Signal handlers trigger clean shutdown
- Graceful shutdown behavior
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

from zos.cli import cli
from zos.config import Config
from zos.observation import ZosBot, run_bot, setup_signal_handlers


class TestZosBotInitialization:
    """Tests for ZosBot initialization and intents."""

    def test_bot_initializes_with_correct_intents(self) -> None:
        """Bot should have message_content, reactions, and members intents enabled."""
        config = Config()
        bot = ZosBot(config)

        assert bot.intents.message_content is True
        assert bot.intents.reactions is True
        assert bot.intents.members is True
        assert bot.intents.guilds is True  # Default intent

    def test_bot_stores_config(self) -> None:
        """Bot should store the provided configuration."""
        config = Config()
        bot = ZosBot(config)

        assert bot.config is config

    def test_bot_initializes_shutdown_flag(self) -> None:
        """Bot should initialize with shutdown flag as False."""
        config = Config()
        bot = ZosBot(config)

        assert bot._shutdown_requested is False


class TestCLIObserveCommand:
    """Tests for the observe CLI command."""

    def test_observe_command_exists(self, cli_runner: CliRunner) -> None:
        """observe command should be available in CLI help."""
        result = cli_runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "observe" in result.output

    def test_observe_command_help(self, cli_runner: CliRunner) -> None:
        """observe command should have helpful description."""
        result = cli_runner.invoke(cli, ["observe", "--help"])
        assert result.exit_code == 0
        assert "Discord" in result.output
        assert "observation" in result.output.lower() or "observing" in result.output.lower()

    def test_observe_fails_without_token(self, cli_runner: CliRunner) -> None:
        """observe should fail with clear error when DISCORD_TOKEN not set."""
        # Ensure DISCORD_TOKEN is not in environment
        result = cli_runner.invoke(cli, ["observe"], env={"DISCORD_TOKEN": ""})

        assert result.exit_code == 1
        assert "DISCORD_TOKEN" in result.output

    def test_observe_fails_gracefully_with_message(
        self, cli_runner: CliRunner
    ) -> None:
        """observe failure message should be helpful."""
        result = cli_runner.invoke(cli, ["observe"], env={"DISCORD_TOKEN": ""})

        assert result.exit_code == 1
        assert "Error" in result.output or "error" in result.output.lower()


class TestZosBotCallbacks:
    """Tests for ZosBot event callbacks."""

    @pytest.mark.asyncio
    async def test_on_ready_logs_connection_info(self) -> None:
        """on_ready should log user and guild/channel counts."""
        config = Config()

        # Mock the guilds property and user by patching at the class level
        mock_guild1 = MagicMock()
        mock_guild1.text_channels = [MagicMock(), MagicMock()]  # 2 channels
        mock_guild2 = MagicMock()
        mock_guild2.text_channels = [MagicMock(), MagicMock()]  # 2 channels

        mock_user = MagicMock()
        mock_user.__str__ = MagicMock(return_value="Zos#1234")

        # Mock the log to verify it was called
        with (
            patch.object(ZosBot, "guilds", new_callable=lambda: [mock_guild1, mock_guild2]),
            patch.object(ZosBot, "user", mock_user),
            patch("zos.observation.log") as mock_log,
        ):
            bot = ZosBot(config)
            await bot.on_ready()

            mock_log.info.assert_called_once()
            call_kwargs = mock_log.info.call_args[1]
            assert call_kwargs["guilds"] == 2
            assert call_kwargs["channels"] == 4  # 2 channels * 2 guilds

    @pytest.mark.asyncio
    async def test_on_disconnect_logs_warning(self) -> None:
        """on_disconnect should log a warning."""
        config = Config()
        bot = ZosBot(config)

        with patch("zos.observation.log") as mock_log:
            await bot.on_disconnect()

            mock_log.warning.assert_called_once_with("discord_disconnected")

    @pytest.mark.asyncio
    async def test_on_resumed_logs_info(self) -> None:
        """on_resumed should log reconnection."""
        config = Config()
        bot = ZosBot(config)

        with patch("zos.observation.log") as mock_log:
            await bot.on_resumed()

            mock_log.info.assert_called_once_with("discord_resumed")


class TestPollingTask:
    """Tests for the background polling task."""

    @pytest.mark.asyncio
    async def test_poll_task_starts_after_ready(self) -> None:
        """poll_messages task should wait for bot to be ready."""
        config = Config()
        bot = ZosBot(config)

        # Verify before_poll waits for ready
        bot._ready = asyncio.Event()

        # Start the before_poll in a task
        task = asyncio.create_task(bot.before_poll())

        # Give it a moment to start waiting
        await asyncio.sleep(0.01)
        assert not task.done()

        # Set ready and verify it completes
        bot._ready.set()
        await asyncio.wait_for(task, timeout=1.0)
        assert task.done()

    @pytest.mark.asyncio
    async def test_poll_task_respects_shutdown_flag(self) -> None:
        """poll_messages should not start new work if shutdown requested."""
        config = Config()
        bot = ZosBot(config)
        bot._shutdown_requested = True

        # Mock log to verify no work is done
        with patch("zos.observation.log") as mock_log:
            await bot.poll_messages()

            # Should return early without logging poll_messages_tick
            mock_log.debug.assert_not_called()

    @pytest.mark.asyncio
    async def test_poll_interval_from_config(self) -> None:
        """Polling interval should come from configuration."""
        config = Config()
        config.discord.polling_interval_seconds = 120  # Non-default value
        bot = ZosBot(config)

        # Mock the loop's change_interval and start methods
        bot.poll_messages.change_interval = MagicMock()
        bot.poll_messages.start = MagicMock()

        # Mock cog loading and command syncing (added in Story 2.6)
        bot.add_cog = AsyncMock()
        bot.tree.sync = AsyncMock()

        with patch("zos.observation.log"):
            await bot.setup_hook()

        bot.poll_messages.change_interval.assert_called_once_with(seconds=120)


class TestGracefulShutdown:
    """Tests for graceful shutdown behavior."""

    @pytest.mark.asyncio
    async def test_graceful_shutdown_sets_flag(self) -> None:
        """graceful_shutdown should set the shutdown flag."""
        config = Config()
        bot = ZosBot(config)

        # Mock poll_messages task methods
        bot.poll_messages.is_running = MagicMock(return_value=False)

        # Mock close
        bot.close = AsyncMock()

        with patch("zos.observation.log"):
            await bot.graceful_shutdown()

        assert bot._shutdown_requested is True

    @pytest.mark.asyncio
    async def test_graceful_shutdown_cancels_polling(self) -> None:
        """graceful_shutdown should cancel the polling task."""
        config = Config()
        bot = ZosBot(config)

        # Mock poll_messages task methods
        bot.poll_messages.is_running = MagicMock(return_value=True)
        bot.poll_messages.cancel = MagicMock()

        # Mock close
        bot.close = AsyncMock()

        with patch("zos.observation.log"):
            await bot.graceful_shutdown()

        bot.poll_messages.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_graceful_shutdown_closes_connection(self) -> None:
        """graceful_shutdown should close the Discord connection."""
        config = Config()
        bot = ZosBot(config)

        # Mock poll_messages task methods
        bot.poll_messages.is_running = MagicMock(return_value=False)

        # Mock close
        bot.close = AsyncMock()

        with patch("zos.observation.log"):
            await bot.graceful_shutdown()

        bot.close.assert_called_once()


class TestSignalHandlers:
    """Tests for signal handler setup."""

    def test_signal_handlers_registered(self) -> None:
        """Signal handlers should be registered for SIGINT and SIGTERM."""
        config = Config()
        bot = ZosBot(config)
        loop = asyncio.new_event_loop()

        try:
            handlers_before = {}
            import signal

            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    handlers_before[sig] = loop._signal_handlers.get(sig)
                except AttributeError:
                    # Some event loop implementations may not expose this
                    pass

            with patch("zos.observation.log"):
                setup_signal_handlers(bot, loop)

            # Verify handlers were added (implementation detail, but important)
            for sig in (signal.SIGINT, signal.SIGTERM):
                # The loop should have a handler registered
                assert sig in loop._signal_handlers
        finally:
            loop.close()


class TestConfigIntegration:
    """Tests for configuration integration."""

    def test_bot_uses_configured_polling_interval(self, tmp_path: Path) -> None:
        """Bot should use the polling interval from config."""
        config_path = tmp_path / "config.yaml"
        config_data = {
            "data_dir": str(tmp_path),
            "discord": {"polling_interval_seconds": 90},
        }
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        config = Config.load(config_path)
        bot = ZosBot(config)

        assert bot.config.discord.polling_interval_seconds == 90

    def test_default_polling_interval(self) -> None:
        """Default polling interval should be 60 seconds."""
        config = Config()
        assert config.discord.polling_interval_seconds == 60


class TestRunBot:
    """Tests for the run_bot entry point."""

    @pytest.mark.asyncio
    async def test_run_bot_starts_with_token(self, monkeypatch) -> None:
        """run_bot should start the bot with the provided token."""
        # Set the token via environment variable
        monkeypatch.setenv("DISCORD_TOKEN", "test-token")
        config = Config()

        with (
            patch("zos.observation.ZosBot") as MockBot,
            patch("zos.observation.setup_signal_handlers"),
            patch("zos.observation.log"),
        ):
            mock_bot_instance = AsyncMock()
            mock_bot_instance.is_closed.return_value = True
            MockBot.return_value = mock_bot_instance

            # run_bot should call start with the token
            await run_bot(config)

            mock_bot_instance.start.assert_called_once_with("test-token")

    @pytest.mark.asyncio
    async def test_run_bot_closes_on_exception(self, monkeypatch) -> None:
        """run_bot should ensure bot is closed even on exception."""
        # Set the token via environment variable
        monkeypatch.setenv("DISCORD_TOKEN", "test-token")
        config = Config()

        with (
            patch("zos.observation.ZosBot") as MockBot,
            patch("zos.observation.setup_signal_handlers"),
            patch("zos.observation.log"),
        ):
            mock_bot_instance = MagicMock()
            mock_bot_instance.start = AsyncMock(side_effect=Exception("Connection failed"))
            mock_bot_instance.is_closed = MagicMock(return_value=False)
            mock_bot_instance.close = AsyncMock()
            MockBot.return_value = mock_bot_instance

            # Should raise but still close
            with pytest.raises(Exception, match="Connection failed"):
                await run_bot(config)

            mock_bot_instance.close.assert_awaited_once()
