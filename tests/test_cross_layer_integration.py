"""Tests for cross-layer integration infrastructure.

Tests the layer filter and topic_category_override functionality
added to FetchInsightsConfig and related components.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from zos.config import DatabaseConfig
from zos.db import Database
from zos.discord.repository import MessageRepository
from zos.insights import InsightRepository
from zos.layer.nodes import create_node
from zos.layer.nodes.fetch_insights import FetchInsightsNode
from zos.layer.nodes.fetch_messages import FetchMessagesNode
from zos.layer.schema import FetchInsightsConfig, FetchMessagesConfig
from zos.topics.topic_key import TopicKey


# --- Fixtures ---


@pytest.fixture
def test_db(tmp_path: Path) -> Generator[Database, None, None]:
    """Create a test database with initialized schema."""
    config = DatabaseConfig(path=tmp_path / "test.db")
    db = Database(config)
    db.initialize()
    yield db
    db.close()


@pytest.fixture
def insight_repo(test_db: Database) -> InsightRepository:
    """Create an insight repository."""
    return InsightRepository(test_db)


@pytest.fixture
def message_repo(test_db: Database) -> MessageRepository:
    """Create a message repository."""
    return MessageRepository(test_db)


@pytest.fixture
def sample_insights(insight_repo: InsightRepository) -> list[dict[str, str]]:
    """Create sample insights from different layers and topics."""
    # Note: We don't pass run_id to avoid foreign key constraint issues
    # since we don't have runs in the test database

    # User profile insights
    insight_repo.store(
        TopicKey.user(1001),
        "User 1001 is a software developer who enjoys Python.",
        layer="user_profile",
        sources_scope_max="public",
    )
    insight_repo.store(
        TopicKey.user(1002),
        "User 1002 is a designer who prefers visual communication.",
        layer="user_profile",
        sources_scope_max="public",
    )

    # Channel digest insights
    insight_repo.store(
        TopicKey.channel(2001),
        "Channel 2001 had active discussions about AI.",
        layer="channel_digest",
        sources_scope_max="public",
    )
    insight_repo.store(
        TopicKey.channel(2002),
        "Channel 2002 focused on project planning.",
        layer="channel_digest",
        sources_scope_max="public",
    )

    # Social dynamics insight
    insight_repo.store(
        TopicKey.dyad(1001, 1002),
        "User 1001 and 1002 collaborate frequently.",
        layer="social_dynamics",
        sources_scope_max="public",
    )

    return [
        {"topic": "user:1001", "layer": "user_profile"},
        {"topic": "user:1002", "layer": "user_profile"},
        {"topic": "channel:2001", "layer": "channel_digest"},
        {"topic": "channel:2002", "layer": "channel_digest"},
        {"topic": "dyad:1001:1002", "layer": "social_dynamics"},
    ]


@pytest.fixture
def mock_context(test_db: Database, message_repo: MessageRepository) -> MagicMock:
    """Create a mock pipeline context."""
    context = MagicMock()
    context.db = test_db
    context.message_repo = message_repo
    context.current_topic = TopicKey.user(1001)
    context.run_start = datetime.now(UTC)
    context.window_start = None

    # Track context.set calls
    context_data: dict[str, object] = {}

    def set_fn(key: str, value: object) -> None:
        context_data[key] = value

    def get_fn(key: str, default: object = None) -> object:
        return context_data.get(key, default)

    context.set = MagicMock(side_effect=set_fn)
    context.get = MagicMock(side_effect=get_fn)
    context._data = context_data

    return context


# --- InsightRepository Tests ---


class TestInsightRepositoryLayerFilter:
    """Tests for InsightRepository layer filtering."""

    def test_get_insights_single_layer_filter(
        self,
        insight_repo: InsightRepository,
        sample_insights: list[dict[str, str]],
    ) -> None:
        """Test filtering insights by a single layer."""
        topic = TopicKey.user(1001)

        # Get only user_profile insights for this topic
        insights = insight_repo.get_insights(
            topic,
            limit=10,
            layer="user_profile",
        )

        assert len(insights) == 1
        assert insights[0].layer == "user_profile"
        assert "software developer" in insights[0].summary

    def test_get_insights_multiple_layer_filter(
        self,
        insight_repo: InsightRepository,
        sample_insights: list[dict[str, str]],
    ) -> None:
        """Test filtering insights by multiple layers."""
        # Create an additional insight for user 1001 from a different layer
        insight_repo.store(
            TopicKey.user(1001),
            "Additional insight from another layer.",
            layer="other_layer",
            sources_scope_max="public",
        )

        topic = TopicKey.user(1001)

        # Get insights from both user_profile and other_layer
        insights = insight_repo.get_insights(
            topic,
            limit=10,
            layer=["user_profile", "other_layer"],
        )

        assert len(insights) == 2
        layers = {i.layer for i in insights}
        assert layers == {"user_profile", "other_layer"}

    def test_get_insights_layer_filter_no_match(
        self,
        insight_repo: InsightRepository,
        sample_insights: list[dict[str, str]],
    ) -> None:
        """Test layer filter with no matching insights."""
        topic = TopicKey.user(1001)

        insights = insight_repo.get_insights(
            topic,
            limit=10,
            layer="nonexistent_layer",
        )

        assert len(insights) == 0


class TestInsightRepositoryCategoryQuery:
    """Tests for InsightRepository category-based queries."""

    def test_get_insights_by_category(
        self,
        insight_repo: InsightRepository,
        sample_insights: list[dict[str, str]],
    ) -> None:
        """Test fetching insights by topic category."""
        # Get all user insights
        insights = insight_repo.get_insights_by_category(
            "user",
            limit=10,
        )

        assert len(insights) == 2
        for insight in insights:
            assert insight.topic_key.startswith("user:")

    def test_get_insights_by_category_with_layer(
        self,
        insight_repo: InsightRepository,
        sample_insights: list[dict[str, str]],
    ) -> None:
        """Test category query with layer filter."""
        insights = insight_repo.get_insights_by_category(
            "channel",
            limit=10,
            layer="channel_digest",
        )

        assert len(insights) == 2
        for insight in insights:
            assert insight.topic_key.startswith("channel:")
            assert insight.layer == "channel_digest"

    def test_get_insights_by_category_with_scope(
        self,
        insight_repo: InsightRepository,
        sample_insights: list[dict[str, str]],
    ) -> None:
        """Test category query with scope filter."""
        # Add a DM-scoped insight
        insight_repo.store(
            TopicKey.user(1003),
            "Private insight.",
            layer="user_profile",
            sources_scope_max="dm",
        )

        # Get only public user insights
        insights = insight_repo.get_insights_by_category(
            "user",
            limit=10,
            scope="public",
        )

        # Should not include the DM-scoped insight
        assert all(i.sources_scope_max == "public" for i in insights)

    def test_get_insights_by_category_empty(
        self,
        insight_repo: InsightRepository,
        sample_insights: list[dict[str, str]],
    ) -> None:
        """Test category query with no results."""
        insights = insight_repo.get_insights_by_category(
            "user_in_channel",
            limit=10,
        )

        assert len(insights) == 0


# --- FetchInsightsNode Tests ---


class TestFetchInsightsNodeLayerFilter:
    """Tests for FetchInsightsNode layer filtering."""

    @pytest.mark.asyncio
    async def test_execute_with_layer_filter(
        self,
        mock_context: MagicMock,
        sample_insights: list[dict[str, str]],
    ) -> None:
        """Test fetching insights with layer filter."""
        config = FetchInsightsConfig(
            type="fetch_insights",
            name="get_prior_profile",
            max_insights=10,
            layer="user_profile",
        )
        node = FetchInsightsNode(config=config)

        result = await node.execute(mock_context)

        assert result.success is True
        assert len(result.data) == 1
        assert result.data[0]["layer"] == "user_profile"

        # Check context key is based on node name
        mock_context.set.assert_called()
        call_args = [call[0] for call in mock_context.set.call_args_list]
        assert ("prior_profile", result.data) in call_args

    @pytest.mark.asyncio
    async def test_execute_with_multiple_layers(
        self,
        mock_context: MagicMock,
        insight_repo: InsightRepository,
    ) -> None:
        """Test fetching insights from multiple layers."""
        # Create insights
        insight_repo.store(
            TopicKey.user(1001),
            "Profile insight.",
            layer="user_profile",
        )
        insight_repo.store(
            TopicKey.user(1001),
            "Social insight.",
            layer="social_dynamics",
        )

        config = FetchInsightsConfig(
            type="fetch_insights",
            name="get_context",
            max_insights=10,
            layer=["user_profile", "social_dynamics"],
        )
        node = FetchInsightsNode(config=config)

        result = await node.execute(mock_context)

        assert result.success is True
        assert len(result.data) == 2
        layers = {d["layer"] for d in result.data}
        assert layers == {"user_profile", "social_dynamics"}


class TestFetchInsightsNodeCategoryOverride:
    """Tests for FetchInsightsNode topic_category_override."""

    @pytest.mark.asyncio
    async def test_execute_with_category_override(
        self,
        mock_context: MagicMock,
        sample_insights: list[dict[str, str]],
    ) -> None:
        """Test fetching insights with topic_category_override."""
        # Current topic is user:1001, but we want channel insights
        config = FetchInsightsConfig(
            type="fetch_insights",
            name="get_channel_context",
            max_insights=10,
            topic_category_override="channel",
        )
        node = FetchInsightsNode(config=config)

        result = await node.execute(mock_context)

        assert result.success is True
        assert len(result.data) == 2
        for insight in result.data:
            assert insight["topic_key"].startswith("channel:")

        # Verify context key
        call_args = [call[0] for call in mock_context.set.call_args_list]
        assert ("channel_context", result.data) in call_args

    @pytest.mark.asyncio
    async def test_execute_category_override_with_layer(
        self,
        mock_context: MagicMock,
        sample_insights: list[dict[str, str]],
    ) -> None:
        """Test category override combined with layer filter."""
        config = FetchInsightsConfig(
            type="fetch_insights",
            name="get_user_profiles",
            max_insights=10,
            topic_category_override="user",
            layer="user_profile",
        )
        node = FetchInsightsNode(config=config)

        result = await node.execute(mock_context)

        assert result.success is True
        assert len(result.data) == 2
        for insight in result.data:
            assert insight["topic_key"].startswith("user:")
            assert insight["layer"] == "user_profile"

    @pytest.mark.asyncio
    async def test_execute_category_override_no_topic_needed(
        self,
        mock_context: MagicMock,
        sample_insights: list[dict[str, str]],
    ) -> None:
        """Test that category_override works even without current topic."""
        mock_context.current_topic = None

        config = FetchInsightsConfig(
            type="fetch_insights",
            name="get_all_channels",
            max_insights=10,
            topic_category_override="channel",
        )
        node = FetchInsightsNode(config=config)

        result = await node.execute(mock_context)

        assert result.success is True
        assert len(result.data) == 2


class TestFetchInsightsNodeContextKey:
    """Tests for FetchInsightsNode context key generation."""

    @pytest.mark.asyncio
    async def test_context_key_from_node_name(
        self,
        mock_context: MagicMock,
        sample_insights: list[dict[str, str]],
    ) -> None:
        """Test context key is derived from node name."""
        config = FetchInsightsConfig(
            type="fetch_insights",
            name="get_prior_analysis",
            max_insights=10,
        )
        node = FetchInsightsNode(config=config)

        await node.execute(mock_context)

        # Should strip "get_" prefix
        call_args = [call[0][0] for call in mock_context.set.call_args_list]
        assert "prior_analysis" in call_args

    @pytest.mark.asyncio
    async def test_context_key_default(
        self,
        mock_context: MagicMock,
        sample_insights: list[dict[str, str]],
    ) -> None:
        """Test default context key when no name provided."""
        config = FetchInsightsConfig(
            type="fetch_insights",
            max_insights=10,
        )
        node = FetchInsightsNode(config=config)

        await node.execute(mock_context)

        call_args = [call[0][0] for call in mock_context.set.call_args_list]
        assert "insights" in call_args


# --- FetchMessagesNode Reactions Tests ---


class TestFetchMessagesNodeReactions:
    """Tests for FetchMessagesNode reaction inclusion."""

    @pytest.fixture
    def messages_with_reactions(
        self, message_repo: MessageRepository
    ) -> list[dict[str, object]]:
        """Create test messages with reactions."""
        now = datetime.now(UTC)

        # Create messages
        message_repo.upsert_message(
            message_id=101,
            guild_id=1,
            guild_name="Test Guild",
            channel_id=2001,
            channel_name="test-channel",
            thread_id=None,
            parent_channel_id=None,
            author_id=1001,
            author_name="User1",
            author_roles_snapshot="role1,role2",
            content="First message",
            created_at=now - timedelta(hours=1),
            visibility_scope="public",
        )
        message_repo.upsert_message(
            message_id=102,
            guild_id=1,
            guild_name="Test Guild",
            channel_id=2001,
            channel_name="test-channel",
            thread_id=None,
            parent_channel_id=None,
            author_id=1002,
            author_name="User2",
            author_roles_snapshot="role1",
            content="Second message",
            created_at=now - timedelta(minutes=30),
            visibility_scope="public",
        )

        # Add reactions
        message_repo.add_reaction(101, "👍", 1002, "User2", now - timedelta(minutes=50))
        message_repo.add_reaction(101, "👍", 1003, "User3", now - timedelta(minutes=45))
        message_repo.add_reaction(101, "❤️", 1002, "User2", now - timedelta(minutes=40))
        message_repo.add_reaction(102, "🎉", 1001, "User1", now - timedelta(minutes=20))

        return []

    @pytest.mark.asyncio
    async def test_execute_includes_reactions(
        self,
        mock_context: MagicMock,
        messages_with_reactions: list[dict[str, object]],
    ) -> None:
        """Test that reactions are included when configured."""
        mock_context.current_topic = TopicKey.channel(2001)
        mock_context.run_start = datetime.now(UTC)

        config = FetchMessagesConfig(
            type="fetch_messages",
            lookback_hours=24,
            max_messages=100,
            include_reactions=True,
        )
        node = FetchMessagesNode(config=config)

        result = await node.execute(mock_context)

        assert result.success is True
        assert len(result.data) == 2

        # Check reactions are attached
        msg1 = next(m for m in result.data if m["message_id"] == 101)
        assert "reactions" in msg1
        assert len(msg1["reactions"]) == 3

        msg2 = next(m for m in result.data if m["message_id"] == 102)
        assert "reactions" in msg2
        assert len(msg2["reactions"]) == 1

    @pytest.mark.asyncio
    async def test_execute_reaction_summary(
        self,
        mock_context: MagicMock,
        messages_with_reactions: list[dict[str, object]],
    ) -> None:
        """Test that reaction summary is stored in context."""
        mock_context.current_topic = TopicKey.channel(2001)
        mock_context.run_start = datetime.now(UTC)

        config = FetchMessagesConfig(
            type="fetch_messages",
            lookback_hours=24,
            max_messages=100,
            include_reactions=True,
        )
        node = FetchMessagesNode(config=config)

        await node.execute(mock_context)

        # Check reaction_summary was set
        set_calls = {call[0][0]: call[0][1] for call in mock_context.set.call_args_list}
        assert "reaction_summary" in set_calls
        assert "reaction_counts" in set_calls

        reaction_counts = set_calls["reaction_counts"]
        assert reaction_counts["👍"] == 2
        assert reaction_counts["❤️"] == 1
        assert reaction_counts["🎉"] == 1

    @pytest.mark.asyncio
    async def test_execute_without_reactions(
        self,
        mock_context: MagicMock,
        messages_with_reactions: list[dict[str, object]],
    ) -> None:
        """Test that reactions are not included by default."""
        mock_context.current_topic = TopicKey.channel(2001)
        mock_context.run_start = datetime.now(UTC)

        config = FetchMessagesConfig(
            type="fetch_messages",
            lookback_hours=24,
            max_messages=100,
            include_reactions=False,  # Default
        )
        node = FetchMessagesNode(config=config)

        result = await node.execute(mock_context)

        assert result.success is True
        # Messages should not have reactions key
        for msg in result.data:
            assert "reactions" not in msg


# --- MessageRepository Reactions Tests ---


class TestMessageRepositoryReactions:
    """Tests for MessageRepository reaction fetching."""

    def test_get_reactions_for_messages(
        self, message_repo: MessageRepository, test_db: Database
    ) -> None:
        """Test fetching reactions for multiple messages."""
        now = datetime.now(UTC)

        # Create a message
        message_repo.upsert_message(
            message_id=201,
            guild_id=1,
            guild_name="Test",
            channel_id=100,
            channel_name="test",
            thread_id=None,
            parent_channel_id=None,
            author_id=1,
            author_name="User",
            author_roles_snapshot="",
            content="Test",
            created_at=now,
            visibility_scope="public",
        )

        # Add reactions
        message_repo.add_reaction(201, "👍", 2, "User2", now)
        message_repo.add_reaction(201, "❤️", 3, "User3", now)

        reactions = message_repo.get_reactions_for_messages([201])

        assert 201 in reactions
        assert len(reactions[201]) == 2
        emojis = {r["emoji"] for r in reactions[201]}
        assert emojis == {"👍", "❤️"}

    def test_get_reactions_excludes_removed(
        self, message_repo: MessageRepository, test_db: Database
    ) -> None:
        """Test that removed reactions are excluded."""
        now = datetime.now(UTC)

        message_repo.upsert_message(
            message_id=202,
            guild_id=1,
            guild_name="Test",
            channel_id=100,
            channel_name="test",
            thread_id=None,
            parent_channel_id=None,
            author_id=1,
            author_name="User",
            author_roles_snapshot="",
            content="Test",
            created_at=now,
            visibility_scope="public",
        )

        message_repo.add_reaction(202, "👍", 2, "User2", now)
        message_repo.add_reaction(202, "❤️", 3, "User3", now)
        message_repo.remove_reaction(202, "👍", 2)

        reactions = message_repo.get_reactions_for_messages([202])

        assert len(reactions[202]) == 1
        assert reactions[202][0]["emoji"] == "❤️"

    def test_get_reactions_empty_list(
        self, message_repo: MessageRepository
    ) -> None:
        """Test with empty message ID list."""
        reactions = message_repo.get_reactions_for_messages([])
        assert reactions == {}

    def test_get_reactions_no_reactions(
        self, message_repo: MessageRepository, test_db: Database
    ) -> None:
        """Test message with no reactions."""
        now = datetime.now(UTC)

        message_repo.upsert_message(
            message_id=203,
            guild_id=1,
            guild_name="Test",
            channel_id=100,
            channel_name="test",
            thread_id=None,
            parent_channel_id=None,
            author_id=1,
            author_name="User",
            author_roles_snapshot="",
            content="Test",
            created_at=now,
            visibility_scope="public",
        )

        reactions = message_repo.get_reactions_for_messages([203])

        # Message ID should not be in result if no reactions
        assert 203 not in reactions
