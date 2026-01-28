"""Tests for the operator commands module.

Covers:
- Operator check (user ID and role based)
- All 8 slash commands
- Ephemeral responses
- Logging of command usage
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from zos.commands import OperatorCommands
from zos.config import Config, DiscordConfig, OperatorsConfig


class MockInteraction:
    """Mock Discord interaction for testing."""

    def __init__(
        self,
        user_id: str = "123456",
        user_name: str = "TestUser",
        role_ids: list[str] | None = None,
        in_guild: bool = True,
        command_name: str = "test",
    ) -> None:
        """Initialize mock interaction.

        Args:
            user_id: The user's Discord ID.
            user_name: The user's display name.
            role_ids: List of role IDs the user has.
            in_guild: Whether the interaction is in a guild.
            command_name: Name of the command being invoked.
        """
        self.user = MagicMock()
        self.user.id = int(user_id)
        self.user.__str__ = MagicMock(return_value=f"{user_name}#{user_id[:4]}")

        if in_guild and role_ids is not None:
            # Make user a Member with roles
            self.user.roles = [
                MagicMock(id=int(role_id)) for role_id in role_ids
            ]
            self.guild = MagicMock()
        else:
            self.guild = MagicMock() if in_guild else None

        self.command = MagicMock()
        self.command.name = command_name

        self.response = MagicMock()
        self.response.send_message = AsyncMock()
        self.response.defer = AsyncMock()

        self.followup = MagicMock()
        self.followup.send = AsyncMock()


class MockZosBot:
    """Mock ZosBot for testing commands."""

    def __init__(
        self,
        operator_user_ids: list[str] | None = None,
        operator_role_id: str | None = None,
    ) -> None:
        """Initialize mock bot.

        Args:
            operator_user_ids: List of operator user IDs.
            operator_role_id: Role ID that grants operator access.
        """
        self.config = Config(
            discord=DiscordConfig(
                operators=OperatorsConfig(
                    user_ids=operator_user_ids or [],
                    role_id=operator_role_id,
                )
            )
        )
        self.is_silenced = False
        self.dev_mode = False
        self.engine = None  # No database in mock by default
        self.scheduler = None  # No scheduler in mock by default


class TestOperatorCheck:
    """Tests for operator access control."""

    def test_operator_check_by_user_id(self) -> None:
        """User ID in operator list should pass check."""
        bot = MockZosBot(operator_user_ids=["123456"])
        cog = OperatorCommands(bot)  # type: ignore[arg-type]
        interaction = MockInteraction(user_id="123456")

        assert cog.is_operator(interaction) is True  # type: ignore[arg-type]

    def test_operator_check_user_not_in_list(self) -> None:
        """User ID not in operator list should fail check."""
        bot = MockZosBot(operator_user_ids=["999999"])
        cog = OperatorCommands(bot)  # type: ignore[arg-type]
        interaction = MockInteraction(user_id="123456")

        assert cog.is_operator(interaction) is False  # type: ignore[arg-type]

    def test_operator_check_by_role(self) -> None:
        """User with operator role should pass check."""
        bot = MockZosBot(operator_role_id="111111")
        cog = OperatorCommands(bot)  # type: ignore[arg-type]
        interaction = MockInteraction(user_id="123456", role_ids=["111111", "222222"])

        # Need to make user a Member for role check
        interaction.user = MagicMock(spec=discord.Member)
        interaction.user.id = 123456
        interaction.user.roles = [
            MagicMock(id=111111),
            MagicMock(id=222222),
        ]

        assert cog.is_operator(interaction) is True  # type: ignore[arg-type]

    def test_operator_check_role_not_present(self) -> None:
        """User without operator role should fail check."""
        bot = MockZosBot(operator_role_id="111111")
        cog = OperatorCommands(bot)  # type: ignore[arg-type]
        interaction = MockInteraction(user_id="123456", role_ids=["222222", "333333"])

        # Need to make user a Member for role check
        interaction.user = MagicMock(spec=discord.Member)
        interaction.user.id = 123456
        interaction.user.roles = [
            MagicMock(id=222222),
            MagicMock(id=333333),
        ]

        assert cog.is_operator(interaction) is False  # type: ignore[arg-type]

    def test_operator_check_no_guild_for_role(self) -> None:
        """Role check should fail if not in a guild."""
        bot = MockZosBot(operator_role_id="111111")
        cog = OperatorCommands(bot)  # type: ignore[arg-type]
        interaction = MockInteraction(user_id="123456", in_guild=False)

        assert cog.is_operator(interaction) is False  # type: ignore[arg-type]

    def test_operator_check_empty_config(self) -> None:
        """Empty operator config should deny everyone."""
        bot = MockZosBot()
        cog = OperatorCommands(bot)  # type: ignore[arg-type]
        interaction = MockInteraction(user_id="123456")

        assert cog.is_operator(interaction) is False  # type: ignore[arg-type]


class TestPingCommand:
    """Tests for /ping command."""

    @pytest.mark.asyncio
    async def test_ping_responds_pong(self) -> None:
        """Ping should respond with pong."""
        bot = MockZosBot(operator_user_ids=["123456"])
        cog = OperatorCommands(bot)  # type: ignore[arg-type]
        interaction = MockInteraction(user_id="123456", command_name="ping")

        with patch("zos.commands.log"):
            # Access the callback directly since it's wrapped by app_commands
            await cog.ping.callback(cog, interaction)  # type: ignore[arg-type]

        interaction.response.send_message.assert_called_once_with("pong", ephemeral=True)

    @pytest.mark.asyncio
    async def test_ping_rejected_for_non_operator(self) -> None:
        """Non-operator should get rejection message."""
        bot = MockZosBot(operator_user_ids=["999999"])
        cog = OperatorCommands(bot)  # type: ignore[arg-type]
        interaction = MockInteraction(user_id="123456", command_name="ping")

        with patch("zos.commands.log"):
            await cog.ping.callback(cog, interaction)  # type: ignore[arg-type]

        interaction.response.send_message.assert_called_once()
        call_kwargs = interaction.response.send_message.call_args[1]
        assert call_kwargs["ephemeral"] is True
        assert "restricted" in interaction.response.send_message.call_args[0][0].lower()


class TestStatusCommand:
    """Tests for /status command."""

    @pytest.mark.asyncio
    async def test_status_shows_silenced_state(self) -> None:
        """Status should show whether observation is silenced."""
        bot = MockZosBot(operator_user_ids=["123456"])
        bot.is_silenced = True
        cog = OperatorCommands(bot)  # type: ignore[arg-type]
        interaction = MockInteraction(user_id="123456", command_name="status")

        with patch("zos.commands.log"):
            await cog.status.callback(cog, interaction)  # type: ignore[arg-type]

        interaction.response.defer.assert_called_once_with(ephemeral=True)
        interaction.followup.send.assert_called_once()

        response_text = interaction.followup.send.call_args[0][0]
        assert "Yes" in response_text  # Silenced: Yes

    @pytest.mark.asyncio
    async def test_status_shows_dev_mode(self) -> None:
        """Status should show dev mode state."""
        bot = MockZosBot(operator_user_ids=["123456"])
        bot.dev_mode = True
        cog = OperatorCommands(bot)  # type: ignore[arg-type]
        interaction = MockInteraction(user_id="123456", command_name="status")

        with patch("zos.commands.log"):
            await cog.status.callback(cog, interaction)  # type: ignore[arg-type]

        response_text = interaction.followup.send.call_args[0][0]
        assert "Enabled" in response_text  # Dev Mode: Enabled


class TestSilenceCommand:
    """Tests for /silence command."""

    @pytest.mark.asyncio
    async def test_silence_toggles_on(self) -> None:
        """Silence should toggle from off to on."""
        bot = MockZosBot(operator_user_ids=["123456"])
        bot.is_silenced = False
        cog = OperatorCommands(bot)  # type: ignore[arg-type]
        interaction = MockInteraction(user_id="123456", command_name="silence")

        with patch("zos.commands.log"):
            await cog.silence.callback(cog, interaction)  # type: ignore[arg-type]

        assert bot.is_silenced is True
        assert "paused" in interaction.response.send_message.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_silence_toggles_off(self) -> None:
        """Silence should toggle from on to off."""
        bot = MockZosBot(operator_user_ids=["123456"])
        bot.is_silenced = True
        cog = OperatorCommands(bot)  # type: ignore[arg-type]
        interaction = MockInteraction(user_id="123456", command_name="silence")

        with patch("zos.commands.log"):
            await cog.silence.callback(cog, interaction)  # type: ignore[arg-type]

        assert bot.is_silenced is False
        assert "resumed" in interaction.response.send_message.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_silence_logs_toggle(self) -> None:
        """Silence toggle should be logged."""
        bot = MockZosBot(operator_user_ids=["123456"])
        cog = OperatorCommands(bot)  # type: ignore[arg-type]
        interaction = MockInteraction(user_id="123456", command_name="silence")

        with patch("zos.commands.log") as mock_log:
            await cog.silence.callback(cog, interaction)  # type: ignore[arg-type]

            mock_log.info.assert_called_with(
                "silence_toggled",
                state="paused",
                user=str(interaction.user),
            )


class TestDevModeCommand:
    """Tests for /dev-mode command."""

    @pytest.mark.asyncio
    async def test_dev_mode_toggles_on(self) -> None:
        """Dev mode should toggle from off to on."""
        bot = MockZosBot(operator_user_ids=["123456"])
        bot.dev_mode = False
        cog = OperatorCommands(bot)  # type: ignore[arg-type]
        interaction = MockInteraction(user_id="123456", command_name="dev-mode")

        with patch("zos.commands.log"):
            await cog.dev_mode.callback(cog, interaction)  # type: ignore[arg-type]

        assert bot.dev_mode is True
        response_text = interaction.response.send_message.call_args[0][0]
        assert "enabled" in response_text.lower()
        assert "available" in response_text.lower()

    @pytest.mark.asyncio
    async def test_dev_mode_toggles_off(self) -> None:
        """Dev mode should toggle from on to off."""
        bot = MockZosBot(operator_user_ids=["123456"])
        bot.dev_mode = True
        cog = OperatorCommands(bot)  # type: ignore[arg-type]
        interaction = MockInteraction(user_id="123456", command_name="dev-mode")

        with patch("zos.commands.log"):
            await cog.dev_mode.callback(cog, interaction)  # type: ignore[arg-type]

        assert bot.dev_mode is False
        response_text = interaction.response.send_message.call_args[0][0]
        assert "disabled" in response_text.lower()
        assert "restricted" in response_text.lower()


class TestPlaceholderCommands:
    """Tests for commands that are placeholders for future epics."""

    @pytest.mark.asyncio
    async def test_reflect_now_placeholder(self) -> None:
        """Reflect-now should show reflection unavailable when no scheduler."""
        bot = MockZosBot(operator_user_ids=["123456"])
        cog = OperatorCommands(bot)  # type: ignore[arg-type]
        interaction = MockInteraction(user_id="123456", command_name="reflect-now")

        with patch("zos.commands.log"):
            await cog.reflect_now.callback(cog, interaction)  # type: ignore[arg-type]

        response_text = interaction.followup.send.call_args[0][0]
        assert "reflection not available" in response_text.lower()

    @pytest.mark.asyncio
    async def test_insights_placeholder(self) -> None:
        """Insights should show database unavailable when no engine."""
        bot = MockZosBot(operator_user_ids=["123456"])
        cog = OperatorCommands(bot)  # type: ignore[arg-type]
        interaction = MockInteraction(user_id="123456", command_name="insights")

        with patch("zos.commands.log"):
            await cog.insights.callback(cog, interaction, topic="server:123:user:456")  # type: ignore[arg-type]

        response_text = interaction.followup.send.call_args[0][0]
        assert "database not available" in response_text.lower()

    @pytest.mark.asyncio
    async def test_topics_placeholder(self) -> None:
        """Topics should show database unavailable when no engine."""
        bot = MockZosBot(operator_user_ids=["123456"])
        cog = OperatorCommands(bot)  # type: ignore[arg-type]
        interaction = MockInteraction(user_id="123456", command_name="topics")

        with patch("zos.commands.log"):
            await cog.topics.callback(cog, interaction)  # type: ignore[arg-type]

        response_text = interaction.followup.send.call_args[0][0]
        assert "database not available" in response_text.lower()

    @pytest.mark.asyncio
    async def test_layer_run_placeholder(self) -> None:
        """Layer-run should show scheduler unavailable when no scheduler."""
        bot = MockZosBot(operator_user_ids=["123456"])
        cog = OperatorCommands(bot)  # type: ignore[arg-type]
        interaction = MockInteraction(user_id="123456", command_name="layer-run")

        with patch("zos.commands.log"):
            await cog.layer_run.callback(cog, interaction, layer_name="user_reflection")  # type: ignore[arg-type]

        response_text = interaction.followup.send.call_args[0][0]
        assert "scheduler not available" in response_text.lower()


class TestEphemeralResponses:
    """Tests ensuring all commands respond ephemerally."""

    @pytest.mark.asyncio
    async def test_all_commands_respond_ephemeral(self) -> None:
        """All commands should send ephemeral responses."""
        bot = MockZosBot(operator_user_ids=["123456"])
        cog = OperatorCommands(bot)  # type: ignore[arg-type]

        # Test each command individually to access callback properly
        commands_and_args: list[tuple[str, list]] = [
            ("ping", []),
            ("status", []),
            ("silence", []),
            ("reflect_now", []),
            ("insights", ["test:topic"]),
            ("topics", []),
            ("layer_run", ["test_layer"]),
            ("dev_mode", []),
        ]

        for cmd_name, args in commands_and_args:
            interaction = MockInteraction(user_id="123456", command_name=cmd_name)

            with patch("zos.commands.log"):
                cmd = getattr(cog, cmd_name)
                # Access the callback from the command
                await cmd.callback(cog, interaction, *args)  # type: ignore[arg-type]

            # Check that response is ephemeral (either via send_message or defer)
            if interaction.response.send_message.called:
                call_kwargs = interaction.response.send_message.call_args[1]
                assert call_kwargs.get("ephemeral") is True, f"{cmd_name} response not ephemeral"
            elif interaction.response.defer.called:
                call_kwargs = interaction.response.defer.call_args[1]
                assert call_kwargs.get("ephemeral") is True, f"{cmd_name} defer not ephemeral"

                # Also check followup is ephemeral
                if interaction.followup.send.called:
                    call_kwargs = interaction.followup.send.call_args[1]
                    assert call_kwargs.get("ephemeral") is True, f"{cmd_name} followup not ephemeral"


class TestCommandLogging:
    """Tests for command usage logging."""

    @pytest.mark.asyncio
    async def test_ping_logs_usage(self) -> None:
        """Ping command should log usage."""
        bot = MockZosBot(operator_user_ids=["123456"])
        cog = OperatorCommands(bot)  # type: ignore[arg-type]
        interaction = MockInteraction(user_id="123456", command_name="ping")

        with patch("zos.commands.log") as mock_log:
            await cog.ping.callback(cog, interaction)  # type: ignore[arg-type]

            mock_log.info.assert_called_with("ping_command", user=str(interaction.user))

    @pytest.mark.asyncio
    async def test_rejected_command_logs(self) -> None:
        """Rejected commands should log the rejection."""
        bot = MockZosBot(operator_user_ids=["999999"])
        cog = OperatorCommands(bot)  # type: ignore[arg-type]
        interaction = MockInteraction(user_id="123456", command_name="ping")

        with patch("zos.commands.log") as mock_log:
            await cog.ping.callback(cog, interaction)  # type: ignore[arg-type]

            mock_log.info.assert_called()
            call_kwargs = mock_log.info.call_args[1]
            assert call_kwargs["reason"] == "not_operator"
