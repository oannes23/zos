"""Tests for Discord client event handlers."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from zos.config import DiscordConfig
from zos.discord.client import ZosDiscordClient
from zos.discord.repository import MessageRepository


class TestShouldProcessMessage:
    """Tests for message filtering logic."""

    def test_ignores_bot_messages(self, message_repository: MessageRepository):
        """Test that bot messages are ignored."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(config=config, repository=message_repository)

        message = MagicMock()
        message.author.bot = True

        assert client._should_process_message(message) is False

    def test_processes_user_messages(self, message_repository: MessageRepository):
        """Test that user messages are processed."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(config=config, repository=message_repository)

        message = MagicMock()
        message.author.bot = False
        message.guild = None
        message.channel.id = 123

        assert client._should_process_message(message) is True

    def test_filters_by_guild(self, message_repository: MessageRepository):
        """Test guild filtering."""
        config = DiscordConfig(token="test", guild_ids=[111])
        client = ZosDiscordClient(config=config, repository=message_repository)

        message = MagicMock()
        message.author.bot = False
        message.guild.id = 222
        message.channel.id = 123

        assert client._should_process_message(message) is False

    def test_allows_configured_guild(self, message_repository: MessageRepository):
        """Test that configured guilds are allowed."""
        config = DiscordConfig(token="test", guild_ids=[111])
        client = ZosDiscordClient(config=config, repository=message_repository)

        message = MagicMock()
        message.author.bot = False
        message.guild.id = 111
        message.channel.id = 123

        assert client._should_process_message(message) is True

    def test_filters_by_channel(self, message_repository: MessageRepository):
        """Test channel filtering."""
        config = DiscordConfig(token="test", watched_channel_ids=[111])
        client = ZosDiscordClient(config=config, repository=message_repository)

        message = MagicMock()
        message.author.bot = False
        message.guild = None
        message.channel.id = 222

        assert client._should_process_message(message) is False

    def test_allows_configured_channel(self, message_repository: MessageRepository):
        """Test that configured channels are allowed."""
        config = DiscordConfig(token="test", watched_channel_ids=[111])
        client = ZosDiscordClient(config=config, repository=message_repository)

        message = MagicMock()
        message.author.bot = False
        message.guild = None
        message.channel.id = 111

        assert client._should_process_message(message) is True

    def test_dms_always_processed_regardless_of_guild_filter(
        self, message_repository: MessageRepository
    ):
        """Test that DMs bypass guild filtering."""
        config = DiscordConfig(token="test", guild_ids=[111])
        client = ZosDiscordClient(config=config, repository=message_repository)

        message = MagicMock()
        message.author.bot = False
        message.guild = None  # DM
        message.channel.id = 999

        # DMs should still be processed despite guild filter
        # (unless there's a channel filter)
        assert client._should_process_message(message) is True


class TestOnMessage:
    """Tests for on_message event handler."""

    @pytest.mark.asyncio
    async def test_stores_message(
        self, message_repository: MessageRepository, mock_discord_message: MagicMock
    ):
        """Test that valid messages are stored."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(config=config, repository=message_repository)

        await client.on_message(mock_discord_message)

        assert message_repository.message_exists(mock_discord_message.id)

    @pytest.mark.asyncio
    async def test_ignores_bot_message(
        self, message_repository: MessageRepository, mock_discord_message: MagicMock
    ):
        """Test that bot messages are not stored."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(config=config, repository=message_repository)

        mock_discord_message.author.bot = True
        await client.on_message(mock_discord_message)

        assert not message_repository.message_exists(mock_discord_message.id)

    @pytest.mark.asyncio
    async def test_stores_dm_as_dm_scope(
        self, message_repository: MessageRepository, mock_discord_message: MagicMock
    ):
        """Test that DMs are stored with dm visibility scope."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(config=config, repository=message_repository)

        mock_discord_message.guild = None  # DM
        await client.on_message(mock_discord_message)

        result = message_repository.db.execute(
            "SELECT visibility_scope FROM messages WHERE message_id = ?",
            (mock_discord_message.id,),
        ).fetchone()
        assert result["visibility_scope"] == "dm"

    @pytest.mark.asyncio
    async def test_stores_guild_message_as_public(
        self, message_repository: MessageRepository, mock_discord_message: MagicMock
    ):
        """Test that guild messages are stored with public visibility scope."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(config=config, repository=message_repository)

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
        self, message_repository: MessageRepository, mock_discord_message: MagicMock
    ):
        """Test that edited messages update content."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(config=config, repository=message_repository)

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
        self, message_repository: MessageRepository, mock_discord_message: MagicMock
    ):
        """Test that deleted messages are soft deleted."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(config=config, repository=message_repository)

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
        mock_discord_message: MagicMock,
        mock_discord_reaction: MagicMock,
        mock_discord_user: MagicMock,
    ):
        """Test that reactions are added."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(config=config, repository=message_repository)

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
        mock_discord_message: MagicMock,
        mock_discord_reaction: MagicMock,
        mock_discord_user: MagicMock,
    ):
        """Test that reactions are marked as removed."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(config=config, repository=message_repository)

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
        mock_discord_message: MagicMock,
        mock_discord_reaction: MagicMock,
        mock_discord_user: MagicMock,
    ):
        """Test that bot reactions are ignored."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(config=config, repository=message_repository)

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
        self, message_repository: MessageRepository, mock_discord_message: MagicMock
    ):
        """Test that member roles are captured."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(config=config, repository=message_repository)

        import discord

        # Make the author a Member (not just User)
        mock_discord_message.author.__class__ = discord.Member

        roles_json = client._get_roles_snapshot(mock_discord_message)
        # Should contain role ID 111 but not 222 (@everyone)
        assert "111" in roles_json
        assert "222" not in roles_json

    def test_returns_empty_for_non_member(
        self, message_repository: MessageRepository, mock_discord_message: MagicMock
    ):
        """Test that non-members get empty role list."""
        config = DiscordConfig(token="test")
        client = ZosDiscordClient(config=config, repository=message_repository)

        import discord

        # Make the author a User (not Member)
        mock_discord_message.author.__class__ = discord.User

        roles_json = client._get_roles_snapshot(mock_discord_message)
        assert roles_json == "[]"
