"""Tests for reaction tracking functionality.

Covers Story 2.3 acceptance criteria:
- Reactions stored with message_id, user_id, emoji
- Custom emoji distinguished from Unicode
- Only opted-in users' reactions tracked individually
- Reactions from `<chat>` users not individually tracked
- Reaction removal handled (soft delete with removed_at)
- Aggregate reaction counts updated on messages
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from zos.config import Config
from zos.database import (
    channels,
    create_tables,
    get_engine,
    messages,
    reactions,
    servers,
)
from zos.models import Message, VisibilityScope
from zos.observation import ZosBot


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
    """Create a test database engine with all tables."""
    eng = get_engine(test_config)
    create_tables(eng)
    return eng


@pytest.fixture
def bot(test_config: Config, engine):
    """Create a ZosBot with test config and engine."""
    return ZosBot(test_config, engine)


@pytest.fixture
def now():
    """Return current time in UTC (timezone-aware)."""
    return datetime.now(timezone.utc)


async def setup_test_message(bot: ZosBot, engine, now) -> dict:
    """Set up a server, channel, and message for reaction tests.

    This is a helper function, not a fixture, because pytest-asyncio
    fixtures cannot be awaited in tests.
    """
    # Create server
    mock_guild = MagicMock()
    mock_guild.id = 111111111
    mock_guild.name = "Test Server"
    await bot._ensure_server(mock_guild)

    # Create channel
    mock_channel = MagicMock(spec=['id', 'name'])
    mock_channel.id = 222222222
    mock_channel.name = "test-channel"
    await bot._ensure_channel(mock_channel, "111111111")

    # Insert a message directly
    msg = Message(
        id="444444444",
        channel_id="222222222",
        server_id="111111111",
        author_id="555555555",
        content="Test message",
        created_at=now,
        visibility_scope=VisibilityScope.PUBLIC,
        has_media=False,
        has_links=False,
    )

    with engine.connect() as conn:
        from zos.models import model_to_dict
        conn.execute(messages.insert().values(**model_to_dict(msg)))
        conn.commit()

    return {
        "server_id": "111111111",
        "channel_id": "222222222",
        "message_id": "444444444",
    }


# =============================================================================
# Emoji Serialization Tests
# =============================================================================


class TestEmojiSerialization:
    """Tests for emoji serialization."""

    def test_unicode_emoji_unchanged(self, bot: ZosBot) -> None:
        """Unicode emoji should be stored as-is."""
        result = bot._serialize_emoji("👍")
        assert result == "👍"

    def test_unicode_emoji_complex(self, bot: ZosBot) -> None:
        """Complex unicode emoji (with modifiers) should be preserved."""
        result = bot._serialize_emoji("👍🏽")
        assert result == "👍🏽"

    def test_custom_emoji_serialized(self, bot: ZosBot) -> None:
        """Custom emoji should be stored as :name:."""
        mock_emoji = MagicMock()
        mock_emoji.name = "pepe_sad"
        mock_emoji.id = 123456789

        result = bot._serialize_emoji(mock_emoji)
        assert result == ":pepe_sad:"

    def test_partial_emoji_serialized(self, bot: ZosBot) -> None:
        """Partial emoji should be stored as :name:."""
        import discord

        mock_emoji = MagicMock(spec=discord.PartialEmoji)
        mock_emoji.name = "custom_emoji"
        mock_emoji.id = 987654321

        result = bot._serialize_emoji(mock_emoji)
        assert result == ":custom_emoji:"

    def test_is_custom_emoji_detects_custom(self, bot: ZosBot) -> None:
        """Should correctly identify custom emoji strings."""
        assert bot._is_custom_emoji(":pepe_sad:") is True
        assert bot._is_custom_emoji(":custom:") is True

    def test_is_custom_emoji_rejects_unicode(self, bot: ZosBot) -> None:
        """Should correctly identify unicode emoji."""
        assert bot._is_custom_emoji("👍") is False
        assert bot._is_custom_emoji("🎉") is False

    def test_is_custom_emoji_handles_edge_cases(self, bot: ZosBot) -> None:
        """Should handle edge cases correctly."""
        assert bot._is_custom_emoji(":") is False  # Too short
        assert bot._is_custom_emoji("::") is False  # Empty name


# =============================================================================
# Reaction Storage Tests
# =============================================================================


class TestReactionStorage:
    """Tests for storing reactions."""

    @pytest.mark.asyncio
    async def test_store_unicode_reaction(
        self, bot: ZosBot, engine, now
    ) -> None:
        """Unicode emoji reaction should be stored correctly."""
        msg = await setup_test_message(bot, engine, now)

        await bot._store_reaction(
            message_id=msg["message_id"],
            user_id="666666666",
            emoji="👍",
            is_custom=False,
            server_id=msg["server_id"],
        )

        with engine.connect() as conn:
            result = conn.execute(
                select(reactions).where(
                    reactions.c.message_id == msg["message_id"]
                )
            ).fetchone()

            assert result is not None
            assert result.user_id == "666666666"
            assert result.emoji == "👍"
            assert result.is_custom is False
            assert result.removed_at is None

    @pytest.mark.asyncio
    async def test_store_custom_reaction(
        self, bot: ZosBot, engine, now
    ) -> None:
        """Custom emoji reaction should be stored correctly."""
        msg = await setup_test_message(bot, engine, now)

        await bot._store_reaction(
            message_id=msg["message_id"],
            user_id="666666666",
            emoji=":pepe_sad:",
            is_custom=True,
            server_id=msg["server_id"],
        )

        with engine.connect() as conn:
            result = conn.execute(
                select(reactions).where(
                    reactions.c.message_id == msg["message_id"]
                )
            ).fetchone()

            assert result is not None
            assert result.emoji == ":pepe_sad:"
            assert result.is_custom is True

    @pytest.mark.asyncio
    async def test_store_reaction_upsert(
        self, bot: ZosBot, engine, now
    ) -> None:
        """Re-storing same reaction should not create duplicates."""
        msg = await setup_test_message(bot, engine, now)

        # Store twice
        await bot._store_reaction(
            message_id=msg["message_id"],
            user_id="666666666",
            emoji="👍",
            is_custom=False,
            server_id=msg["server_id"],
        )
        await bot._store_reaction(
            message_id=msg["message_id"],
            user_id="666666666",
            emoji="👍",
            is_custom=False,
            server_id=msg["server_id"],
        )

        with engine.connect() as conn:
            count = conn.execute(
                select(reactions).where(
                    (reactions.c.message_id == msg["message_id"])
                    & (reactions.c.user_id == "666666666")
                    & (reactions.c.emoji == "👍")
                )
            ).fetchall()

            assert len(count) == 1  # No duplicates

    @pytest.mark.asyncio
    async def test_store_reaction_clears_removed_at(
        self, bot: ZosBot, engine, now
    ) -> None:
        """Re-adding a removed reaction should clear removed_at."""
        msg = await setup_test_message(bot, engine, now)

        # Store initial reaction
        await bot._store_reaction(
            message_id=msg["message_id"],
            user_id="666666666",
            emoji="👍",
            is_custom=False,
            server_id=msg["server_id"],
        )

        # Get the reaction ID
        with engine.connect() as conn:
            result = conn.execute(
                select(reactions.c.id).where(
                    (reactions.c.message_id == msg["message_id"])
                    & (reactions.c.user_id == "666666666")
                )
            ).fetchone()
            reaction_id = result.id

        # Mark it as removed
        bot._mark_reaction_removed(reaction_id)

        # Verify it's marked as removed
        with engine.connect() as conn:
            result = conn.execute(
                select(reactions.c.removed_at).where(
                    reactions.c.id == reaction_id
                )
            ).fetchone()
            assert result.removed_at is not None

        # Re-add the reaction
        await bot._store_reaction(
            message_id=msg["message_id"],
            user_id="666666666",
            emoji="👍",
            is_custom=False,
            server_id=msg["server_id"],
        )

        # Verify removed_at is cleared
        with engine.connect() as conn:
            result = conn.execute(
                select(reactions.c.removed_at).where(
                    reactions.c.id == reaction_id
                )
            ).fetchone()
            assert result.removed_at is None


# =============================================================================
# Reaction Removal Tests
# =============================================================================


class TestReactionRemoval:
    """Tests for reaction removal (soft delete)."""

    @pytest.mark.asyncio
    async def test_mark_reaction_removed(
        self, bot: ZosBot, engine, now
    ) -> None:
        """Marking a reaction removed should set removed_at timestamp."""
        msg = await setup_test_message(bot, engine, now)

        # Store reaction
        await bot._store_reaction(
            message_id=msg["message_id"],
            user_id="666666666",
            emoji="👍",
            is_custom=False,
            server_id=msg["server_id"],
        )

        # Get the reaction
        with engine.connect() as conn:
            result = conn.execute(
                select(reactions.c.id).where(
                    reactions.c.message_id == msg["message_id"]
                )
            ).fetchone()
            reaction_id = result.id

        # Mark as removed
        bot._mark_reaction_removed(reaction_id)

        # Verify
        with engine.connect() as conn:
            result = conn.execute(
                select(reactions).where(reactions.c.id == reaction_id)
            ).fetchone()
            assert result.removed_at is not None

    @pytest.mark.asyncio
    async def test_get_reactions_includes_removed(
        self, bot: ZosBot, engine, now
    ) -> None:
        """get_reactions_for_message should include removed reactions."""
        msg = await setup_test_message(bot, engine, now)

        # Store reaction
        await bot._store_reaction(
            message_id=msg["message_id"],
            user_id="666666666",
            emoji="👍",
            is_custom=False,
            server_id=msg["server_id"],
        )

        # Get ID and mark as removed
        stored = bot._get_reactions_for_message(msg["message_id"])
        assert len(stored) == 1
        bot._mark_reaction_removed(stored[0].id)

        # Should still be returned
        stored = bot._get_reactions_for_message(msg["message_id"])
        assert len(stored) == 1
        assert stored[0].removed_at is not None


# =============================================================================
# Privacy Gate Tests for Reactions
# =============================================================================


class TestReactionPrivacyGate:
    """Tests for privacy gate handling in reaction tracking."""

    @pytest.mark.asyncio
    async def test_anonymous_user_reactions_skipped(
        self, tmp_path: Path, engine
    ) -> None:
        """Reactions from anonymous users should not be stored individually."""
        # Create config with privacy gate
        config = Config(
            data_dir=tmp_path,
            servers={"111111111": {"privacy_gate_role": "role_id_123"}},
        )
        bot = ZosBot(config, engine)

        # Setup server and channel
        mock_guild = MagicMock()
        mock_guild.id = 111111111
        mock_guild.name = "Test Server"
        await bot._ensure_server(mock_guild)

        mock_channel = MagicMock(spec=['id', 'name'])
        mock_channel.id = 222222222
        mock_channel.name = "test-channel"
        await bot._ensure_channel(mock_channel, "111111111")

        # Insert test message
        with engine.connect() as conn:
            from zos.models import model_to_dict
            msg = Message(
                id="444444444",
                channel_id="222222222",
                server_id="111111111",
                author_id="555555555",
                content="Test message",
                created_at=datetime.now(timezone.utc),
                visibility_scope=VisibilityScope.PUBLIC,
                has_media=False,
                has_links=False,
            )
            conn.execute(messages.insert().values(**model_to_dict(msg)))
            conn.commit()

        # Create mock message with reactions
        mock_reactor = MagicMock(spec=['id', 'roles'])
        mock_reactor.id = 777777777
        mock_reactor.roles = []  # No privacy gate role

        mock_reaction = MagicMock()
        mock_reaction.emoji = "👍"
        mock_reaction.count = 1

        async def mock_users():
            yield mock_reactor

        mock_reaction.users = mock_users

        mock_message = MagicMock()
        mock_message.id = 444444444
        mock_message.reactions = [mock_reaction]

        # Sync reactions
        await bot._sync_reactions(mock_message, "111111111")

        # Verify no individual reactions stored (user is anonymous)
        with engine.connect() as conn:
            result = conn.execute(
                select(reactions).where(
                    reactions.c.message_id == "444444444"
                )
            ).fetchall()
            assert len(result) == 0

    @pytest.mark.asyncio
    async def test_opted_in_user_reactions_stored(
        self, tmp_path: Path, engine
    ) -> None:
        """Reactions from opted-in users should be stored individually."""
        # Create config with privacy gate
        config = Config(
            data_dir=tmp_path,
            servers={"111111111": {"privacy_gate_role": "111222333"}},
        )
        bot = ZosBot(config, engine)

        # Setup server and channel
        mock_guild = MagicMock()
        mock_guild.id = 111111111
        mock_guild.name = "Test Server"
        await bot._ensure_server(mock_guild)

        mock_channel = MagicMock(spec=['id', 'name'])
        mock_channel.id = 222222222
        mock_channel.name = "test-channel"
        await bot._ensure_channel(mock_channel, "111111111")

        # Insert test message
        with engine.connect() as conn:
            from zos.models import model_to_dict
            msg = Message(
                id="444444444",
                channel_id="222222222",
                server_id="111111111",
                author_id="555555555",
                content="Test message",
                created_at=datetime.now(timezone.utc),
                visibility_scope=VisibilityScope.PUBLIC,
                has_media=False,
                has_links=False,
            )
            conn.execute(messages.insert().values(**model_to_dict(msg)))
            conn.commit()

        # Create mock user with privacy gate role
        mock_role = MagicMock()
        mock_role.id = 111222333

        mock_reactor = MagicMock(spec=['id', 'roles'])
        mock_reactor.id = 777777777
        mock_reactor.roles = [mock_role]  # Has privacy gate role

        mock_reaction = MagicMock()
        mock_reaction.emoji = "👍"
        mock_reaction.count = 1

        async def mock_users():
            yield mock_reactor

        mock_reaction.users = mock_users

        mock_message = MagicMock()
        mock_message.id = 444444444
        mock_message.reactions = [mock_reaction]

        # Sync reactions
        await bot._sync_reactions(mock_message, "111111111")

        # Verify reaction was stored
        with engine.connect() as conn:
            result = conn.execute(
                select(reactions).where(
                    reactions.c.message_id == "444444444"
                )
            ).fetchall()
            assert len(result) == 1
            assert result[0].user_id == "777777777"


# =============================================================================
# Aggregate Update Tests
# =============================================================================


class TestReactionAggregate:
    """Tests for reaction aggregate updates."""

    @pytest.mark.asyncio
    async def test_update_aggregate_single_emoji(
        self, bot: ZosBot, engine, now
    ) -> None:
        """Should update aggregate with single emoji count."""
        msg = await setup_test_message(bot, engine, now)

        # Create mock message with reactions
        mock_reaction = MagicMock()
        mock_reaction.emoji = "👍"
        mock_reaction.count = 5

        mock_message = MagicMock()
        mock_message.id = int(msg["message_id"])
        mock_message.reactions = [mock_reaction]

        # Update aggregate
        await bot._update_message_reactions(mock_message)

        # Verify
        with engine.connect() as conn:
            result = conn.execute(
                select(messages.c.reactions_aggregate).where(
                    messages.c.id == msg["message_id"]
                )
            ).fetchone()

            aggregate = json.loads(result.reactions_aggregate)
            assert aggregate == {"👍": 5}

    @pytest.mark.asyncio
    async def test_update_aggregate_multiple_emoji(
        self, bot: ZosBot, engine, now
    ) -> None:
        """Should update aggregate with multiple emoji counts."""
        msg = await setup_test_message(bot, engine, now)

        # Create mock message with multiple reactions
        mock_reaction1 = MagicMock()
        mock_reaction1.emoji = "👍"
        mock_reaction1.count = 3

        mock_reaction2 = MagicMock()
        mock_reaction2.emoji = "❤️"
        mock_reaction2.count = 2

        mock_custom = MagicMock()
        mock_custom.name = "party"
        mock_custom.id = 12345

        mock_reaction3 = MagicMock()
        mock_reaction3.emoji = mock_custom
        mock_reaction3.count = 1

        mock_message = MagicMock()
        mock_message.id = int(msg["message_id"])
        mock_message.reactions = [mock_reaction1, mock_reaction2, mock_reaction3]

        # Update aggregate
        await bot._update_message_reactions(mock_message)

        # Verify
        with engine.connect() as conn:
            result = conn.execute(
                select(messages.c.reactions_aggregate).where(
                    messages.c.id == msg["message_id"]
                )
            ).fetchone()

            aggregate = json.loads(result.reactions_aggregate)
            assert aggregate["👍"] == 3
            assert aggregate["❤️"] == 2
            assert aggregate[":party:"] == 1

    @pytest.mark.asyncio
    async def test_update_aggregate_empty_reactions(
        self, bot: ZosBot, engine, now
    ) -> None:
        """Should clear aggregate when no reactions."""
        msg = await setup_test_message(bot, engine, now)

        mock_message = MagicMock()
        mock_message.id = int(msg["message_id"])
        mock_message.reactions = []

        # Update aggregate
        await bot._update_message_reactions(mock_message)

        # Verify
        with engine.connect() as conn:
            result = conn.execute(
                select(messages.c.reactions_aggregate).where(
                    messages.c.id == msg["message_id"]
                )
            ).fetchone()

            assert result.reactions_aggregate is None


# =============================================================================
# Full Sync Tests
# =============================================================================


class TestReactionSync:
    """Tests for full reaction sync functionality."""

    @pytest.mark.asyncio
    async def test_sync_adds_new_reactions(
        self, bot: ZosBot, engine, now
    ) -> None:
        """Sync should add new reactions that weren't previously stored."""
        msg = await setup_test_message(bot, engine, now)

        # Create mock user
        mock_user = MagicMock(spec=['id', 'roles'])
        mock_user.id = 666666666
        mock_user.roles = None  # No privacy gate, so tracked

        mock_reaction = MagicMock()
        mock_reaction.emoji = "👍"
        mock_reaction.count = 1

        async def mock_users():
            yield mock_user

        mock_reaction.users = mock_users

        mock_message = MagicMock()
        mock_message.id = int(msg["message_id"])
        mock_message.reactions = [mock_reaction]

        # Sync
        await bot._sync_reactions(mock_message, msg["server_id"])

        # Verify
        with engine.connect() as conn:
            result = conn.execute(
                select(reactions).where(
                    reactions.c.message_id == msg["message_id"]
                )
            ).fetchall()
            assert len(result) == 1
            assert result[0].user_id == "666666666"
            assert result[0].emoji == "👍"

    @pytest.mark.asyncio
    async def test_sync_marks_removed_reactions(
        self, bot: ZosBot, engine, now
    ) -> None:
        """Sync should mark reactions as removed when no longer present."""
        msg = await setup_test_message(bot, engine, now)

        # First, store a reaction directly
        await bot._store_reaction(
            message_id=msg["message_id"],
            user_id="666666666",
            emoji="👍",
            is_custom=False,
            server_id=msg["server_id"],
        )

        # Now sync with no reactions (simulating reaction was removed)
        mock_message = MagicMock()
        mock_message.id = int(msg["message_id"])
        mock_message.reactions = []

        await bot._sync_reactions(mock_message, msg["server_id"])

        # Verify reaction is marked as removed
        with engine.connect() as conn:
            result = conn.execute(
                select(reactions).where(
                    reactions.c.message_id == msg["message_id"]
                )
            ).fetchone()
            assert result is not None
            assert result.removed_at is not None

    @pytest.mark.asyncio
    async def test_sync_handles_multiple_users(
        self, bot: ZosBot, engine, now
    ) -> None:
        """Sync should handle multiple users reacting with same emoji."""
        msg = await setup_test_message(bot, engine, now)

        # Create mock users
        mock_user1 = MagicMock(spec=['id', 'roles'])
        mock_user1.id = 666666666
        mock_user1.roles = None

        mock_user2 = MagicMock(spec=['id', 'roles'])
        mock_user2.id = 777777777
        mock_user2.roles = None

        mock_reaction = MagicMock()
        mock_reaction.emoji = "👍"
        mock_reaction.count = 2

        async def mock_users():
            yield mock_user1
            yield mock_user2

        mock_reaction.users = mock_users

        mock_message = MagicMock()
        mock_message.id = int(msg["message_id"])
        mock_message.reactions = [mock_reaction]

        # Sync
        await bot._sync_reactions(mock_message, msg["server_id"])

        # Verify both reactions stored
        with engine.connect() as conn:
            result = conn.execute(
                select(reactions).where(
                    reactions.c.message_id == msg["message_id"]
                )
            ).fetchall()
            assert len(result) == 2
            user_ids = {r.user_id for r in result}
            assert user_ids == {"666666666", "777777777"}


# =============================================================================
# Integration with Polling Tests
# =============================================================================


class TestReactionPollingIntegration:
    """Tests for reaction handling during polling."""

    @pytest.mark.asyncio
    async def test_poll_channel_syncs_reactions(
        self, bot: ZosBot, engine
    ) -> None:
        """Polling a channel should sync reactions on messages."""
        # Setup server
        mock_guild = MagicMock()
        mock_guild.id = 111111111
        mock_guild.name = "Test Server"
        await bot._ensure_server(mock_guild)

        # Create mock channel with history
        mock_user = MagicMock(spec=['id', 'roles'])
        mock_user.id = 555555555
        mock_user.roles = None

        mock_reactor = MagicMock(spec=['id', 'roles'])
        mock_reactor.id = 666666666
        mock_reactor.roles = None

        mock_reaction = MagicMock()
        mock_reaction.emoji = "🎉"
        mock_reaction.count = 1

        async def mock_users():
            yield mock_reactor

        mock_reaction.users = mock_users

        mock_message = MagicMock()
        mock_message.id = 444444444
        mock_message.channel = MagicMock()
        mock_message.channel.id = 222222222
        mock_message.author = mock_user
        mock_message.content = "Celebrate!"
        mock_message.created_at = datetime.now(timezone.utc)
        mock_message.attachments = []
        mock_message.embeds = []
        mock_message.reference = None
        mock_message.thread = None
        mock_message.reactions = [mock_reaction]

        mock_channel = MagicMock()
        mock_channel.id = 222222222
        mock_channel.name = "test-channel"
        mock_channel.guild = mock_guild

        async def mock_history(**kwargs):
            yield mock_message

        mock_channel.history = mock_history
        mock_channel.permissions_for = MagicMock(
            return_value=MagicMock(read_message_history=True)
        )

        # Poll the channel
        count = await bot._poll_channel(mock_channel, "111111111")

        assert count == 1

        # Verify reaction was stored
        with engine.connect() as conn:
            result = conn.execute(
                select(reactions).where(
                    reactions.c.message_id == "444444444"
                )
            ).fetchall()
            assert len(result) == 1
            assert result[0].emoji == "🎉"

            # Verify aggregate was updated
            msg_result = conn.execute(
                select(messages.c.reactions_aggregate).where(
                    messages.c.id == "444444444"
                )
            ).fetchone()
            aggregate = json.loads(msg_result.reactions_aggregate)
            assert aggregate == {"🎉": 1}
