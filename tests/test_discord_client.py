"""Tests for Discord client event handlers."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from zos.config import DiscordConfig
from zos.discord.client import ZosDiscordClient
from zos.discord.repository import MessageRepository
from zos.salience.earner import SalienceEarner


class TestShouldProcessMessage:
    """Tests for message filtering logic."""

    def test_ignores_bot_messages(
        self, message_repository: MessageRepository, salience_earner: SalienceEarner
    ):
        """Test that bot messages are ignored."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(
            config=config, repository=message_repository, salience_earner=salience_earner
        )

        message = MagicMock()
        message.author.bot = True

        assert client._should_process_message(message) is False

    def test_processes_user_messages(
        self, message_repository: MessageRepository, salience_earner: SalienceEarner
    ):
        """Test that user messages are processed."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(
            config=config, repository=message_repository, salience_earner=salience_earner
        )

        message = MagicMock()
        message.author.bot = False
        message.guild = None
        message.channel.name = None  # DM channels have no name

        assert client._should_process_message(message) is True

    def test_filters_by_guild(
        self, message_repository: MessageRepository, salience_earner: SalienceEarner
    ):
        """Test guild filtering by ID."""
        config = DiscordConfig(token="test", guilds=[111111111111111111])
        client = ZosDiscordClient(
            config=config, repository=message_repository, salience_earner=salience_earner
        )

        message = MagicMock()
        message.author.bot = False
        message.guild.id = 222222222222222222  # Different guild
        message.channel.id = 333333333333333333

        assert client._should_process_message(message) is False

    def test_allows_configured_guild(
        self, message_repository: MessageRepository, salience_earner: SalienceEarner
    ):
        """Test that configured guilds are allowed."""
        config = DiscordConfig(token="test", guilds=[111111111111111111])
        client = ZosDiscordClient(
            config=config, repository=message_repository, salience_earner=salience_earner
        )

        message = MagicMock()
        message.author.bot = False
        message.guild.id = 111111111111111111  # Configured guild
        message.channel.id = 333333333333333333

        assert client._should_process_message(message) is True

    def test_excludes_channel_by_id(
        self, message_repository: MessageRepository, salience_earner: SalienceEarner
    ):
        """Test channel exclusion by ID (opt-out)."""
        config = DiscordConfig(token="test", excluded_channels=[444444444444444444])
        client = ZosDiscordClient(
            config=config, repository=message_repository, salience_earner=salience_earner
        )

        message = MagicMock()
        message.author.bot = False
        message.guild = None
        message.channel.id = 444444444444444444  # Excluded channel

        assert client._should_process_message(message) is False

    def test_allows_non_excluded_channel(
        self, message_repository: MessageRepository, salience_earner: SalienceEarner
    ):
        """Test that non-excluded channels are allowed (opt-out default)."""
        config = DiscordConfig(token="test", excluded_channels=[444444444444444444])
        client = ZosDiscordClient(
            config=config, repository=message_repository, salience_earner=salience_earner
        )

        message = MagicMock()
        message.author.bot = False
        message.guild = None
        message.channel.id = 555555555555555555  # Not excluded

        assert client._should_process_message(message) is True

    def test_dms_always_processed_regardless_of_guild_filter(
        self, message_repository: MessageRepository, salience_earner: SalienceEarner
    ):
        """Test that DMs bypass guild filtering."""
        config = DiscordConfig(token="test", guilds=[111111111111111111])
        client = ZosDiscordClient(
            config=config, repository=message_repository, salience_earner=salience_earner
        )

        message = MagicMock()
        message.author.bot = False
        message.guild = None  # DM
        message.channel.id = 666666666666666666  # DM channel ID

        # DMs should still be processed despite guild filter
        assert client._should_process_message(message) is True


class TestUserTracking:
    """Tests for user opt-in tracking functionality."""

    def test_dm_always_tracked(
        self, message_repository: MessageRepository, salience_earner: SalienceEarner
    ):
        """Test that DMs are always tracked (initiation implies consent)."""
        config = DiscordConfig(token="test", tracking_opt_in_role="Zos Participant")
        client = ZosDiscordClient(
            config=config, repository=message_repository, salience_earner=salience_earner
        )

        message = MagicMock()
        message.guild = None  # DM

        assert client._is_user_tracked(message) is True

    def test_no_role_configured_everyone_tracked(
        self, message_repository: MessageRepository, salience_earner: SalienceEarner
    ):
        """Test that everyone is tracked when no role is configured."""
        config = DiscordConfig(token="test", tracking_opt_in_role=None)
        client = ZosDiscordClient(
            config=config, repository=message_repository, salience_earner=salience_earner
        )

        message = MagicMock()
        message.guild = MagicMock()

        assert client._is_user_tracked(message) is True

    def test_user_with_role_is_tracked(
        self, message_repository: MessageRepository, salience_earner: SalienceEarner
    ):
        """Test that users with the tracking role are tracked."""
        import discord

        config = DiscordConfig(token="test", tracking_opt_in_role="Zos Participant")
        client = ZosDiscordClient(
            config=config, repository=message_repository, salience_earner=salience_earner
        )

        role = MagicMock()
        role.name = "Zos Participant"

        member = MagicMock(spec=discord.Member)
        member.roles = [role]

        message = MagicMock()
        message.guild = MagicMock()
        message.author = member

        assert client._is_user_tracked(message) is True

    def test_user_without_role_not_tracked(
        self, message_repository: MessageRepository, salience_earner: SalienceEarner
    ):
        """Test that users without the tracking role are not tracked."""
        import discord

        config = DiscordConfig(token="test", tracking_opt_in_role="Zos Participant")
        client = ZosDiscordClient(
            config=config, repository=message_repository, salience_earner=salience_earner
        )

        other_role = MagicMock()
        other_role.name = "Other Role"

        member = MagicMock(spec=discord.Member)
        member.roles = [other_role]

        message = MagicMock()
        message.guild = MagicMock()
        message.author = member

        assert client._is_user_tracked(message) is False


class TestOnMessage:
    """Tests for on_message event handler."""

    @pytest.mark.asyncio
    async def test_stores_message(
        self,
        message_repository: MessageRepository,
        salience_earner: SalienceEarner,
        mock_discord_message: MagicMock,
    ):
        """Test that valid messages are stored."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(
            config=config, repository=message_repository, salience_earner=salience_earner
        )

        await client.on_message(mock_discord_message)

        assert message_repository.message_exists(mock_discord_message.id)

    @pytest.mark.asyncio
    async def test_ignores_bot_message(
        self,
        message_repository: MessageRepository,
        salience_earner: SalienceEarner,
        mock_discord_message: MagicMock,
    ):
        """Test that bot messages are not stored."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(
            config=config, repository=message_repository, salience_earner=salience_earner
        )

        mock_discord_message.author.bot = True
        await client.on_message(mock_discord_message)

        assert not message_repository.message_exists(mock_discord_message.id)

    @pytest.mark.asyncio
    async def test_stores_dm_as_dm_scope(
        self,
        message_repository: MessageRepository,
        salience_earner: SalienceEarner,
        mock_discord_message: MagicMock,
    ):
        """Test that DMs are stored with dm visibility scope."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(
            config=config, repository=message_repository, salience_earner=salience_earner
        )

        mock_discord_message.guild = None  # DM
        await client.on_message(mock_discord_message)

        result = message_repository.db.execute(
            "SELECT visibility_scope FROM messages WHERE message_id = ?",
            (mock_discord_message.id,),
        ).fetchone()
        assert result["visibility_scope"] == "dm"

    @pytest.mark.asyncio
    async def test_stores_guild_message_as_public(
        self,
        message_repository: MessageRepository,
        salience_earner: SalienceEarner,
        mock_discord_message: MagicMock,
    ):
        """Test that guild messages are stored with public visibility scope."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(
            config=config, repository=message_repository, salience_earner=salience_earner
        )

        await client.on_message(mock_discord_message)

        result = message_repository.db.execute(
            "SELECT visibility_scope FROM messages WHERE message_id = ?",
            (mock_discord_message.id,),
        ).fetchone()
        assert result["visibility_scope"] == "public"


class TestOnMessageEdit:
    """Tests for on_message_edit event handler."""

    @pytest.mark.asyncio
    async def test_updates_content(
        self,
        message_repository: MessageRepository,
        salience_earner: SalienceEarner,
        mock_discord_message: MagicMock,
    ):
        """Test that edited messages update content."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(
            config=config, repository=message_repository, salience_earner=salience_earner
        )

        # First store the original
        await client.on_message(mock_discord_message)

        # Create edited version
        before = mock_discord_message
        after = MagicMock()
        after.id = mock_discord_message.id
        after.content = "Edited content"
        after.author = mock_discord_message.author
        after.channel = mock_discord_message.channel
        after.guild = mock_discord_message.guild
        after.edited_at = datetime.now(UTC)

        await client.on_message_edit(before, after)

        result = message_repository.db.execute(
            "SELECT content FROM messages WHERE message_id = ?",
            (mock_discord_message.id,),
        ).fetchone()
        assert result["content"] == "Edited content"


class TestOnMessageDelete:
    """Tests for on_message_delete event handler."""

    @pytest.mark.asyncio
    async def test_soft_deletes_message(
        self,
        message_repository: MessageRepository,
        salience_earner: SalienceEarner,
        mock_discord_message: MagicMock,
    ):
        """Test that deleted messages are soft deleted."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(
            config=config, repository=message_repository, salience_earner=salience_earner
        )

        # First store the message
        await client.on_message(mock_discord_message)

        # Delete it
        await client.on_message_delete(mock_discord_message)

        result = message_repository.db.execute(
            "SELECT is_deleted FROM messages WHERE message_id = ?",
            (mock_discord_message.id,),
        ).fetchone()
        assert result["is_deleted"] == 1


class TestOnReaction:
    """Tests for reaction event handlers."""

    @pytest.mark.asyncio
    async def test_adds_reaction(
        self,
        message_repository: MessageRepository,
        salience_earner: SalienceEarner,
        mock_discord_message: MagicMock,
        mock_discord_reaction: MagicMock,
        mock_discord_user: MagicMock,
    ):
        """Test that reactions are added."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(
            config=config, repository=message_repository, salience_earner=salience_earner
        )

        # First store the message
        await client.on_message(mock_discord_message)

        # Add reaction
        await client.on_reaction_add(mock_discord_reaction, mock_discord_user)

        result = message_repository.db.execute(
            "SELECT emoji, user_id FROM reactions WHERE message_id = ?",
            (mock_discord_message.id,),
        ).fetchone()
        assert result is not None
        assert result["user_id"] == mock_discord_user.id

    @pytest.mark.asyncio
    async def test_removes_reaction(
        self,
        message_repository: MessageRepository,
        salience_earner: SalienceEarner,
        mock_discord_message: MagicMock,
        mock_discord_reaction: MagicMock,
        mock_discord_user: MagicMock,
    ):
        """Test that reactions are marked as removed."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(
            config=config, repository=message_repository, salience_earner=salience_earner
        )

        # First store the message
        await client.on_message(mock_discord_message)

        # Add then remove reaction
        await client.on_reaction_add(mock_discord_reaction, mock_discord_user)
        await client.on_reaction_remove(mock_discord_reaction, mock_discord_user)

        result = message_repository.db.execute(
            "SELECT is_removed FROM reactions WHERE message_id = ?",
            (mock_discord_message.id,),
        ).fetchone()
        assert result["is_removed"] == 1

    @pytest.mark.asyncio
    async def test_ignores_bot_reactions(
        self,
        message_repository: MessageRepository,
        salience_earner: SalienceEarner,
        mock_discord_message: MagicMock,
        mock_discord_reaction: MagicMock,
        mock_discord_user: MagicMock,
    ):
        """Test that bot reactions are ignored."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(
            config=config, repository=message_repository, salience_earner=salience_earner
        )

        # First store the message
        await client.on_message(mock_discord_message)

        # Bot adds reaction
        mock_discord_user.bot = True
        await client.on_reaction_add(mock_discord_reaction, mock_discord_user)

        result = message_repository.db.execute(
            "SELECT COUNT(*) FROM reactions WHERE message_id = ?",
            (mock_discord_message.id,),
        ).fetchone()
        assert result[0] == 0


class TestRolesSnapshot:
    """Tests for role snapshot functionality."""

    def test_gets_roles_for_member(
        self,
        message_repository: MessageRepository,
        salience_earner: SalienceEarner,
        mock_discord_message: MagicMock,
    ):
        """Test that member roles are captured."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(
            config=config, repository=message_repository, salience_earner=salience_earner
        )

        import discord

        # Make the author a Member (not just User)
        mock_discord_message.author.__class__ = discord.Member

        roles_json = client._get_roles_snapshot(mock_discord_message)
        # Should contain role ID 111 but not 222 (@everyone)
        assert "111" in roles_json
        assert "222" not in roles_json

    def test_returns_empty_for_non_member(
        self,
        message_repository: MessageRepository,
        salience_earner: SalienceEarner,
        mock_discord_message: MagicMock,
    ):
        """Test that non-members get empty role list."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(
            config=config, repository=message_repository, salience_earner=salience_earner
        )

        import discord

        # Make the author a User (not Member)
        mock_discord_message.author.__class__ = discord.User

        roles_json = client._get_roles_snapshot(mock_discord_message)
        assert roles_json == "[]"
