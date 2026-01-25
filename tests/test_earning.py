"""Tests for salience earning coordinator.

Tests the earning rules from Story 3.2: Topic Earning.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from zos.config import Config
from zos.database import create_tables, get_engine, messages
from zos.models import Message, Reaction, VisibilityScope
from zos.salience import EarningCoordinator, SalienceLedger


@pytest.fixture
def config() -> Config:
    """Create a test configuration."""
    return Config()


@pytest.fixture
def engine(tmp_path, config):
    """Create a test database engine."""
    config.data_dir = tmp_path
    config.database.path = "test.db"
    engine = get_engine(config)
    create_tables(engine)
    return engine


@pytest.fixture
def ledger(engine, config) -> SalienceLedger:
    """Create a salience ledger for testing."""
    return SalienceLedger(engine, config)


@pytest.fixture
def earning(ledger, config) -> EarningCoordinator:
    """Create an earning coordinator for testing."""
    return EarningCoordinator(ledger, config)


def create_message(
    id: str = "msg1",
    channel_id: str = "ch1",
    server_id: str | None = "srv1",
    author_id: str = "user1",
    content: str = "Hello world",
    has_media: bool = False,
    has_links: bool = False,
    reply_to_id: str | None = None,
) -> Message:
    """Create a test message."""
    return Message(
        id=id,
        channel_id=channel_id,
        server_id=server_id,
        author_id=author_id,
        content=content,
        created_at=datetime.now(timezone.utc),
        visibility_scope=VisibilityScope.DM if server_id is None else VisibilityScope.PUBLIC,
        reply_to_id=reply_to_id,
        thread_id=None,
        has_media=has_media,
        has_links=has_links,
    )


def create_reaction(
    message_id: str = "msg1",
    user_id: str = "user2",
    emoji: str = ":thumbsup:",
    is_custom: bool = False,
    server_id: str | None = "srv1",
) -> Reaction:
    """Create a test reaction."""
    return Reaction(
        message_id=message_id,
        user_id=user_id,
        emoji=emoji,
        is_custom=is_custom,
        server_id=server_id,
    )


class TestMessageEarning:
    """Tests for message earning."""

    @pytest.mark.asyncio
    async def test_message_earns_for_author(self, earning: EarningCoordinator):
        """Message earns salience for author topic."""
        msg = create_message(author_id="user123", server_id="srv1")

        topics = await earning.process_message(msg)

        assert "server:srv1:user:user123" in topics
        balance = await earning.ledger.get_balance("server:srv1:user:user123")
        assert balance == earning.weights.message

    @pytest.mark.asyncio
    async def test_message_earns_for_channel(self, earning: EarningCoordinator):
        """Message earns salience for channel topic."""
        msg = create_message(channel_id="ch456", server_id="srv1")

        topics = await earning.process_message(msg)

        assert "server:srv1:channel:ch456" in topics
        balance = await earning.ledger.get_balance("server:srv1:channel:ch456")
        assert balance == earning.weights.message

    @pytest.mark.asyncio
    async def test_message_with_media_earns_boosted(self, earning: EarningCoordinator):
        """Message with media earns boosted amount."""
        msg = create_message(author_id="user1", server_id="srv1", has_media=True)

        await earning.process_message(msg)

        balance = await earning.ledger.get_balance("server:srv1:user:user1")
        expected = earning.weights.message * earning.weights.media_boost_factor
        assert balance == expected

    @pytest.mark.asyncio
    async def test_message_with_links_earns_boosted(self, earning: EarningCoordinator):
        """Message with links earns boosted amount."""
        msg = create_message(author_id="user1", server_id="srv1", has_links=True)

        await earning.process_message(msg)

        balance = await earning.ledger.get_balance("server:srv1:user:user1")
        expected = earning.weights.message * earning.weights.media_boost_factor
        assert balance == expected

    @pytest.mark.asyncio
    async def test_anonymous_user_no_individual_earning(self, earning: EarningCoordinator):
        """Anonymous users (<chat*) don't earn individual salience."""
        msg = create_message(author_id="<chat_123>", server_id="srv1", channel_id="ch1")

        topics = await earning.process_message(msg)

        # No user topic earned
        assert "server:srv1:user:<chat_123>" not in topics
        balance = await earning.ledger.get_balance("server:srv1:user:<chat_123>")
        assert balance == 0

    @pytest.mark.asyncio
    async def test_channel_earns_from_anonymous(self, earning: EarningCoordinator):
        """Channel still earns from anonymous user messages."""
        msg = create_message(author_id="<chat_123>", server_id="srv1", channel_id="ch1")

        await earning.process_message(msg)

        # Channel topic should still earn
        balance = await earning.ledger.get_balance("server:srv1:channel:ch1")
        assert balance == earning.weights.message


class TestDMEarning:
    """Tests for DM earning."""

    @pytest.mark.asyncio
    async def test_dm_earns_for_global_topic(self, earning: EarningCoordinator):
        """DMs earn for global user topic."""
        msg = create_message(
            author_id="user123",
            server_id=None,  # DM has no server
        )

        topics = await earning.process_message(msg)

        # Should earn for global topic, not server-scoped
        assert "user:user123" in topics
        balance = await earning.ledger.get_balance("user:user123")
        # DM activity warms global topic (initial_global_warmth) + message earning
        initial_warmth = earning.config.salience.initial_global_warmth
        assert balance == initial_warmth + earning.weights.message

    @pytest.mark.asyncio
    async def test_dm_no_channel_topic(self, earning: EarningCoordinator):
        """DMs don't create channel topics."""
        msg = create_message(
            author_id="user123",
            server_id=None,
            channel_id="dm_ch",
        )

        topics = await earning.process_message(msg)

        # Should not have any channel topic
        assert not any("channel:" in t for t in topics)

    @pytest.mark.asyncio
    async def test_process_dm_method(self, earning: EarningCoordinator):
        """process_dm specifically earns for global topic with dm weight."""
        msg = create_message(
            author_id="user123",
            server_id=None,
        )

        topics = await earning.process_dm(msg)

        assert "user:user123" in topics
        balance = await earning.ledger.get_balance("user:user123")
        # DM activity warms global topic (initial_global_warmth) + dm_message earning
        initial_warmth = earning.config.salience.initial_global_warmth
        assert balance == initial_warmth + earning.weights.dm_message

    @pytest.mark.asyncio
    async def test_dm_with_media_boosted(self, earning: EarningCoordinator):
        """DM with media gets boost multiplier."""
        msg = create_message(
            author_id="user123",
            server_id=None,
            has_media=True,
        )

        await earning.process_dm(msg)

        balance = await earning.ledger.get_balance("user:user123")
        # DM activity warms global topic (initial_global_warmth) + boosted dm_message
        initial_warmth = earning.config.salience.initial_global_warmth
        expected = initial_warmth + (earning.weights.dm_message * earning.weights.media_boost_factor)
        assert balance == expected


class TestReactionEarning:
    """Tests for reaction earning."""

    @pytest.mark.asyncio
    async def test_reaction_earns_for_author(self, earning: EarningCoordinator):
        """Reaction earns salience for message author."""
        msg = create_message(author_id="author1", server_id="srv1")
        reaction = create_reaction(user_id="reactor1", server_id="srv1")

        topics = await earning.process_reaction(reaction, msg)

        assert "server:srv1:user:author1" in topics
        balance = await earning.ledger.get_balance("server:srv1:user:author1")
        assert balance == earning.weights.reaction

    @pytest.mark.asyncio
    async def test_reaction_earns_for_reactor(self, earning: EarningCoordinator):
        """Reaction earns salience for reactor."""
        msg = create_message(author_id="author1", server_id="srv1")
        reaction = create_reaction(user_id="reactor1", server_id="srv1")

        topics = await earning.process_reaction(reaction, msg)

        assert "server:srv1:user:reactor1" in topics
        balance = await earning.ledger.get_balance("server:srv1:user:reactor1")
        assert balance == earning.weights.reaction

    @pytest.mark.asyncio
    async def test_reaction_earns_for_dyad(self, earning: EarningCoordinator):
        """Reaction earns salience for dyad between author and reactor."""
        msg = create_message(author_id="author1", server_id="srv1")
        reaction = create_reaction(user_id="reactor1", server_id="srv1")

        topics = await earning.process_reaction(reaction, msg)

        # Dyad uses sorted IDs
        dyad_topic = "server:srv1:dyad:author1:reactor1"
        assert dyad_topic in topics
        balance = await earning.ledger.get_balance(dyad_topic)
        assert balance == earning.weights.reaction

    @pytest.mark.asyncio
    async def test_custom_emoji_earns_for_emoji_topic(self, earning: EarningCoordinator):
        """Custom emoji reaction earns for emoji topic."""
        msg = create_message(author_id="author1", server_id="srv1")
        reaction = create_reaction(
            user_id="reactor1",
            emoji=":pepe_sad:",
            is_custom=True,
            server_id="srv1",
        )

        topics = await earning.process_reaction(reaction, msg)

        emoji_topic = "server:srv1:emoji::pepe_sad:"
        assert emoji_topic in topics
        balance = await earning.ledger.get_balance(emoji_topic)
        assert balance == earning.weights.reaction

    @pytest.mark.asyncio
    async def test_anonymous_reactor_no_earning(self, earning: EarningCoordinator):
        """Anonymous reactors don't earn any salience."""
        msg = create_message(author_id="author1", server_id="srv1")
        reaction = create_reaction(user_id="<chat_123>", server_id="srv1")

        topics = await earning.process_reaction(reaction, msg)

        # No topics earned
        assert len(topics) == 0

    @pytest.mark.asyncio
    async def test_reaction_to_anonymous_author(self, earning: EarningCoordinator):
        """Reaction to anonymous author still earns for reactor and no dyad."""
        msg = create_message(author_id="<chat_123>", server_id="srv1")
        reaction = create_reaction(user_id="reactor1", server_id="srv1")

        topics = await earning.process_reaction(reaction, msg)

        # Reactor earns
        assert "server:srv1:user:reactor1" in topics
        # No author or dyad
        assert "server:srv1:user:<chat_123>" not in topics
        assert not any("dyad:" in t for t in topics)


class TestDyadEarning:
    """Tests for dyad earning."""

    @pytest.mark.asyncio
    async def test_dyad_canonical_ordering(self, earning: EarningCoordinator):
        """Dyad uses sorted IDs for canonical ordering."""
        # user_z comes after user_a alphabetically
        dyad1 = await earning.earn_dyad("srv1", "user_z", "user_a", 1.0, "test")
        dyad2 = await earning.earn_dyad("srv1", "user_a", "user_z", 1.0, "test")

        # Both should create the same topic
        assert dyad1 == dyad2 == "server:srv1:dyad:user_a:user_z"

        # Balance should be 2.0 (earned twice)
        balance = await earning.ledger.get_balance("server:srv1:dyad:user_a:user_z")
        assert balance == 2.0

    @pytest.mark.asyncio
    async def test_no_self_dyad(self, earning: EarningCoordinator):
        """Self-dyads are not created."""
        dyad = await earning.earn_dyad("srv1", "user1", "user1", 1.0, "test")

        assert dyad is None

    @pytest.mark.asyncio
    async def test_global_dyad(self, earning: EarningCoordinator):
        """Global dyads have no server prefix."""
        dyad = await earning.earn_dyad(None, "user_a", "user_b", 1.0, "test")

        assert dyad == "dyad:user_a:user_b"


class TestMentionEarning:
    """Tests for mention earning."""

    @pytest.mark.asyncio
    async def test_mention_earns_boosted(self, earning: EarningCoordinator):
        """Mentions earn boosted amount."""
        msg = create_message(
            author_id="author1",
            server_id="srv1",
            content="Hey <@123456789> check this out",
        )

        topics = await earning.process_message(msg)

        assert "server:srv1:user:123456789" in topics
        balance = await earning.ledger.get_balance("server:srv1:user:123456789")
        assert balance == earning.weights.mention

    @pytest.mark.asyncio
    async def test_multiple_mentions(self, earning: EarningCoordinator):
        """Multiple mentions all earn."""
        msg = create_message(
            author_id="author1",
            server_id="srv1",
            content="<@111> and <@222> and <@333>",
        )

        topics = await earning.process_message(msg)

        assert "server:srv1:user:111" in topics
        assert "server:srv1:user:222" in topics
        assert "server:srv1:user:333" in topics

    @pytest.mark.asyncio
    async def test_mention_with_nickname_format(self, earning: EarningCoordinator):
        """Mentions with nickname format (<@!id>) are detected."""
        msg = create_message(
            author_id="author1",
            server_id="srv1",
            content="Hello <@!999888777>",
        )

        topics = await earning.process_message(msg)

        assert "server:srv1:user:999888777" in topics

    def test_extract_mentions(self, earning: EarningCoordinator):
        """extract_mentions correctly parses Discord mention format."""
        content = "Hey <@123> and <@!456> check this"

        mentions = earning.extract_mentions(content)

        assert mentions == ["123", "456"]


class TestReplyEarning:
    """Tests for reply earning."""

    @pytest.mark.asyncio
    async def test_reply_creates_dyad(self, earning: EarningCoordinator, engine):
        """Reply to message creates dyad earning."""
        from zos.database import servers, channels
        from zos.models import model_to_dict
        from datetime import datetime, timezone

        # First, create server and channel (required by foreign keys)
        now = datetime.now(timezone.utc)
        with engine.connect() as conn:
            conn.execute(servers.insert().values(
                id="srv1",
                name="Test Server",
                threads_as_topics=True,
                created_at=now,
            ))
            conn.execute(channels.insert().values(
                id="ch1",
                server_id="srv1",
                name="test-channel",
                type="text",
                created_at=now,
            ))
            conn.commit()

        # Now store the original message in the database
        original_msg = create_message(id="original", author_id="original_author")
        with engine.connect() as conn:
            msg_dict = model_to_dict(original_msg)
            # Convert enum to string for database
            msg_dict["visibility_scope"] = original_msg.visibility_scope.value
            conn.execute(messages.insert().values(**msg_dict))
            conn.commit()

        # Create reply message
        reply_msg = create_message(
            id="reply",
            author_id="replier",
            server_id="srv1",
            reply_to_id="original",
        )

        topics = await earning.process_message(reply_msg)

        # Should have dyad between replier and original author
        dyad_topic = "server:srv1:dyad:original_author:replier"
        assert dyad_topic in topics
        balance = await earning.ledger.get_balance(dyad_topic)
        assert balance == earning.weights.reply


class TestThreadCreationEarning:
    """Tests for thread creation earning."""

    @pytest.mark.asyncio
    async def test_thread_creator_earns_boosted(self, earning: EarningCoordinator):
        """Thread creator earns boosted amount."""
        topics = await earning.process_thread_creation(
            thread_id="thread1",
            channel_id="ch1",
            creator_id="creator1",
            server_id="srv1",
        )

        assert "server:srv1:user:creator1" in topics
        balance = await earning.ledger.get_balance("server:srv1:user:creator1")
        assert balance == earning.weights.thread_create

    @pytest.mark.asyncio
    async def test_thread_topic_created(self, earning: EarningCoordinator):
        """Thread topic is created and earns."""
        topics = await earning.process_thread_creation(
            thread_id="thread1",
            channel_id="ch1",
            creator_id="creator1",
            server_id="srv1",
        )

        assert "server:srv1:thread:thread1" in topics
        balance = await earning.ledger.get_balance("server:srv1:thread:thread1")
        assert balance == earning.weights.thread_create

    @pytest.mark.asyncio
    async def test_anonymous_thread_creator_no_earning(self, earning: EarningCoordinator):
        """Anonymous thread creators don't earn."""
        topics = await earning.process_thread_creation(
            thread_id="thread1",
            channel_id="ch1",
            creator_id="<chat_999>",
            server_id="srv1",
        )

        assert len(topics) == 0


class TestWeightsConfiguration:
    """Tests that weights are correctly applied from config."""

    @pytest.mark.asyncio
    async def test_default_weights_applied(self, earning: EarningCoordinator):
        """Default weights from config are applied."""
        assert earning.weights.message == 1.0
        assert earning.weights.reaction == 0.5
        assert earning.weights.mention == 2.0
        assert earning.weights.reply == 1.5
        assert earning.weights.thread_create == 2.0
        assert earning.weights.dm_message == 1.5
        assert earning.weights.media_boost_factor == 1.2

    @pytest.mark.asyncio
    async def test_custom_weights(self, engine):
        """Custom weights can be configured."""
        config = Config()
        config.salience.weights.message = 2.0
        config.salience.weights.reaction = 1.0

        ledger = SalienceLedger(engine, config)
        earning = EarningCoordinator(ledger, config)

        msg = create_message(author_id="user1", server_id="srv1")
        await earning.process_message(msg)

        balance = await earning.ledger.get_balance("server:srv1:user:user1")
        assert balance == 2.0  # Custom message weight


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_content_no_mentions(self, earning: EarningCoordinator):
        """Empty content has no mentions."""
        msg = create_message(content="")
        mentions = earning.extract_mentions(msg.content)
        assert mentions == []

    @pytest.mark.asyncio
    async def test_content_with_no_mentions(self, earning: EarningCoordinator):
        """Content without mentions extracts empty list."""
        msg = create_message(content="Hello world no mentions here")
        mentions = earning.extract_mentions(msg.content)
        assert mentions == []

    @pytest.mark.asyncio
    async def test_numeric_ids_handled(self, earning: EarningCoordinator):
        """Numeric Discord IDs are handled correctly."""
        msg = create_message(
            author_id="123456789012345678",  # Real Discord snowflake
            server_id="987654321098765432",
        )

        topics = await earning.process_message(msg)

        assert "server:987654321098765432:user:123456789012345678" in topics

    @pytest.mark.asyncio
    async def test_dm_reaction_no_emoji_topic(self, earning: EarningCoordinator):
        """DM reactions with custom emoji don't create server emoji topics."""
        msg = create_message(author_id="author1", server_id=None)  # DM
        reaction = create_reaction(
            user_id="reactor1",
            emoji=":custom:",
            is_custom=True,
            server_id=None,  # DM has no server
        )

        topics = await earning.process_reaction(reaction, msg)

        # No emoji topic (requires server_id)
        assert not any("emoji:" in t for t in topics)
