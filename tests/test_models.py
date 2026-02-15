"""Tests for the Pydantic models.

Covers serialization, validation, from_attributes mode, and edge cases
for all models representing Zos's understanding of the world.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from zos.models import (
    Channel,
    ChannelType,
    ChattinessEntry,
    ChattinessTransactionType,
    ConversationLogEntry,
    ContentType,
    DraftHistoryEntry,
    ImpulsePool,
    Insight,
    LayerRun,
    LayerRunStatus,
    LinkAnalysis,
    LLMCall,
    LLMCallType,
    MediaAnalysis,
    MediaType,
    Message,
    PollState,
    Reaction,
    SalienceEntry,
    Server,
    SpeechPressure,
    Topic,
    TopicCategory,
    TransactionType,
    User,
    UserServerTracking,
    VisibilityScope,
    generate_id,
    model_to_dict,
    row_to_model,
    utcnow,
)


def test_generate_id() -> None:
    """Test ULID generation."""
    id1 = generate_id()
    id2 = generate_id()

    # Should be 26 characters (ULID length)
    assert len(id1) == 26
    assert len(id2) == 26

    # Should be unique
    assert id1 != id2


def test_utcnow() -> None:
    """Test UTC timestamp generation."""
    now = utcnow()

    assert isinstance(now, datetime)
    assert now.tzinfo is not None
    assert now.tzinfo == timezone.utc


class TestServer:
    """Tests for Server model."""

    def test_create_minimal(self) -> None:
        """Test creating server with minimal fields."""
        server = Server(id="123456789")

        assert server.id == "123456789"
        assert server.name is None
        assert server.threads_as_topics is True

    def test_create_full(self) -> None:
        """Test creating server with all fields."""
        server = Server(
            id="123",
            name="Test Server",
            privacy_gate_role="456",
            disabled_layers=["layer1", "layer2"],
            threads_as_topics=False,
            chattiness_config={"threshold_min": 30},
        )

        assert server.name == "Test Server"
        assert server.privacy_gate_role == "456"
        assert server.threads_as_topics is False

    def test_serialization_round_trip(self) -> None:
        """Test server serialization and deserialization."""
        original = Server(
            id="123",
            name="Test Server",
            privacy_gate_role="456",
            disabled_layers=["layer1"],
            chattiness_config={"threshold_min": 30},
        )
        d = model_to_dict(original)
        restored = Server(**d)

        assert restored.id == original.id
        assert restored.name == original.name
        assert restored.privacy_gate_role == original.privacy_gate_role
        assert restored.disabled_layers == original.disabled_layers
        assert restored.chattiness_config == original.chattiness_config

    def test_from_attributes_mode(self) -> None:
        """Test creating server from SQLAlchemy row."""
        row = MagicMock()
        row._mapping = {
            "id": "123",
            "name": "Test Server",
            "privacy_gate_role": "456",
            "disabled_layers": ["layer1"],
            "threads_as_topics": False,
            "chattiness_config": {"threshold_min": 30},
            "created_at": utcnow(),
        }
        server = row_to_model(row, Server)

        assert server.id == "123"
        assert server.name == "Test Server"


class TestUser:
    """Tests for User model."""

    def test_create_minimal(self) -> None:
        """Test creating user with minimal fields."""
        user = User(id="987654321")

        assert user.id == "987654321"
        assert user.first_dm_acknowledged is False
        assert user.first_dm_at is None

    def test_create_acknowledged(self) -> None:
        """Test creating user that has been acknowledged."""
        now = utcnow()
        user = User(id="123", first_dm_acknowledged=True, first_dm_at=now)

        assert user.first_dm_acknowledged is True
        assert user.first_dm_at == now

    def test_serialization_round_trip(self) -> None:
        """Test user serialization and deserialization."""
        now = utcnow()
        original = User(id="123", first_dm_acknowledged=True, first_dm_at=now)
        d = model_to_dict(original)
        restored = User(**d)

        assert restored.id == original.id
        assert restored.first_dm_acknowledged is True
        assert restored.first_dm_at == now


class TestUserServerTracking:
    """Tests for UserServerTracking model."""

    def test_create_tracking(self) -> None:
        """Test creating user server tracking entry."""
        tracking = UserServerTracking(user_id="user123", server_id="server456")

        assert tracking.user_id == "user123"
        assert tracking.server_id == "server456"
        assert isinstance(tracking.first_seen_at, datetime)

    def test_serialization_round_trip(self) -> None:
        """Test serialization and deserialization."""
        now = utcnow()
        original = UserServerTracking(
            user_id="user123", server_id="server456", first_seen_at=now
        )
        d = model_to_dict(original)
        restored = UserServerTracking(**d)

        assert restored.user_id == original.user_id
        assert restored.server_id == original.server_id
        assert restored.first_seen_at == now


class TestChannel:
    """Tests for Channel model."""

    def test_create_text_channel(self) -> None:
        """Test creating a text channel."""
        channel = Channel(
            id="chan123",
            server_id="server456",
            name="general",
            type=ChannelType.TEXT,
        )

        assert channel.id == "chan123"
        assert channel.server_id == "server456"
        assert channel.name == "general"
        assert channel.type == ChannelType.TEXT
        assert channel.parent_id is None

    def test_create_thread_channel(self) -> None:
        """Test creating a thread channel with parent."""
        channel = Channel(
            id="thread123",
            server_id="server456",
            name="Discussion",
            type=ChannelType.THREAD,
            parent_id="chan123",
        )

        assert channel.type == ChannelType.THREAD
        assert channel.parent_id == "chan123"

    def test_all_channel_types(self) -> None:
        """Test all channel types are valid."""
        for ch_type in ChannelType:
            channel = Channel(
                id="chan_" + ch_type.value,
                server_id="server456",
                type=ch_type,
            )
            assert channel.type == ch_type

    def test_serialization_round_trip(self) -> None:
        """Test channel serialization."""
        original = Channel(
            id="chan123",
            server_id="server456",
            name="general",
            type=ChannelType.TEXT,
        )
        d = model_to_dict(original)
        restored = Channel(**d)

        assert restored.id == original.id
        assert restored.server_id == original.server_id
        assert restored.name == original.name
        assert restored.type == original.type


class TestMessage:
    """Tests for Message model."""

    def test_create_public_message(self) -> None:
        """Test creating a public message."""
        msg = Message(
            id="msg123",
            channel_id="chan456",
            server_id="serv789",
            author_id="user111",
            content="Hello world",
            created_at=utcnow(),
            visibility_scope=VisibilityScope.PUBLIC,
        )

        assert msg.id == "msg123"
        assert msg.visibility_scope == VisibilityScope.PUBLIC
        assert msg.has_media is False
        assert msg.has_links is False

    def test_create_dm_message(self) -> None:
        """Test creating a DM message."""
        msg = Message(
            id="msg123",
            channel_id="dm_chan",
            author_id="user111",
            content="Private message",
            created_at=utcnow(),
            visibility_scope=VisibilityScope.DM,
        )

        assert msg.server_id is None
        assert msg.visibility_scope == VisibilityScope.DM

    def test_create_message_with_media_and_links(self) -> None:
        """Test creating message with media and links."""
        msg = Message(
            id="msg123",
            channel_id="chan456",
            server_id="serv789",
            author_id="user111",
            content="Check this out https://example.com with image",
            created_at=utcnow(),
            visibility_scope=VisibilityScope.PUBLIC,
            has_media=True,
            has_links=True,
        )

        assert msg.has_media is True
        assert msg.has_links is True

    def test_create_message_with_reply(self) -> None:
        """Test creating a message that replies to another."""
        msg = Message(
            id="msg456",
            channel_id="chan123",
            server_id="serv789",
            author_id="user111",
            content="Response",
            created_at=utcnow(),
            visibility_scope=VisibilityScope.PUBLIC,
            reply_to_id="msg123",
        )

        assert msg.reply_to_id == "msg123"

    def test_message_soft_delete(self) -> None:
        """Test creating a deleted message tombstone."""
        now = utcnow()
        msg = Message(
            id="msg123",
            channel_id="chan456",
            server_id="serv789",
            author_id="user111",
            content="Original content",
            created_at=now,
            visibility_scope=VisibilityScope.PUBLIC,
            deleted_at=now,
        )

        assert msg.deleted_at == now

    def test_serialization_round_trip(self) -> None:
        """Test message serialization."""
        now = utcnow()
        original = Message(
            id="msg123",
            channel_id="chan456",
            server_id="serv789",
            author_id="user111",
            content="Hello",
            created_at=now,
            visibility_scope=VisibilityScope.PUBLIC,
            has_media=True,
            has_links=False,
            reactions_aggregate={"thumbsup": 3, "heart": 1},
            reply_to_id="msg111",
            thread_id="thread123",
        )
        d = model_to_dict(original)
        restored = Message(**d)

        assert restored.id == original.id
        assert restored.reactions_aggregate == original.reactions_aggregate
        assert restored.reply_to_id == original.reply_to_id
        assert restored.thread_id == original.thread_id


class TestTopic:
    """Tests for Topic model."""

    def test_valid_global_user_topic(self) -> None:
        """Test valid global user topic."""
        topic = Topic(
            key="user:123456789",
            category=TopicCategory.USER,
            is_global=True,
        )

        assert topic.key == "user:123456789"
        assert topic.is_global is True

    def test_valid_global_dyad_topic(self) -> None:
        """Test valid global dyad topic."""
        topic = Topic(
            key="dyad:123:456",
            category=TopicCategory.DYAD,
            is_global=True,
        )

        assert topic.key == "dyad:123:456"

    def test_valid_global_self_topic(self) -> None:
        """Test valid global self topic."""
        topic = Topic(
            key="self:zos",
            category=TopicCategory.SELF,
            is_global=True,
        )

        assert topic.key == "self:zos"

    def test_valid_self_aspect_topic(self) -> None:
        """Test valid self aspect topic."""
        topic = Topic(
            key="self:social_patterns",
            category=TopicCategory.SELF,
            is_global=True,
        )

        assert topic.key == "self:social_patterns"

    def test_valid_server_user_topic(self) -> None:
        """Test valid server-scoped user topic."""
        topic = Topic(
            key="server:111:user:222",
            category=TopicCategory.USER,
            is_global=False,
        )

        assert topic.key == "server:111:user:222"
        assert topic.is_global is False

    def test_valid_server_channel_topic(self) -> None:
        """Test valid server-scoped channel topic."""
        topic = Topic(
            key="server:111:channel:333",
            category=TopicCategory.CHANNEL,
            is_global=False,
        )

        assert topic.key == "server:111:channel:333"

    def test_valid_server_thread_topic(self) -> None:
        """Test valid server-scoped thread topic."""
        topic = Topic(
            key="server:111:thread:444",
            category=TopicCategory.THREAD,
            is_global=False,
        )

        assert topic.key == "server:111:thread:444"

    def test_valid_server_role_topic(self) -> None:
        """Test valid server-scoped role topic."""
        topic = Topic(
            key="server:111:role:555",
            category=TopicCategory.ROLE,
            is_global=False,
        )

        assert topic.key == "server:111:role:555"

    def test_valid_server_dyad_topic(self) -> None:
        """Test valid server-scoped dyad topic."""
        topic = Topic(
            key="server:111:dyad:222:333",
            category=TopicCategory.DYAD,
            is_global=False,
        )

        assert topic.key == "server:111:dyad:222:333"

    def test_valid_server_user_in_channel_topic(self) -> None:
        """Test valid server user_in_channel topic."""
        topic = Topic(
            key="server:111:user_in_channel:333:222",
            category=TopicCategory.USER_IN_CHANNEL,
            is_global=False,
        )

        assert topic.key == "server:111:user_in_channel:333:222"

    def test_valid_server_dyad_in_channel_topic(self) -> None:
        """Test valid server dyad_in_channel topic."""
        topic = Topic(
            key="server:111:dyad_in_channel:333:222:444",
            category=TopicCategory.DYAD_IN_CHANNEL,
            is_global=False,
        )

        assert topic.key == "server:111:dyad_in_channel:333:222:444"

    def test_valid_server_subject_topic(self) -> None:
        """Test valid server subject topic."""
        topic = Topic(
            key="server:111:subject:philosophy",
            category=TopicCategory.SUBJECT,
            is_global=False,
        )

        assert topic.key == "server:111:subject:philosophy"

    def test_valid_server_emoji_topic(self) -> None:
        """Test valid server emoji topic."""
        topic = Topic(
            key="server:111:emoji:custom_emoji_123",
            category=TopicCategory.EMOJI,
            is_global=False,
        )

        assert topic.key == "server:111:emoji:custom_emoji_123"

    def test_valid_server_self_topic(self) -> None:
        """Test valid server-scoped self topic."""
        topic = Topic(
            key="server:111:self:zos",
            category=TopicCategory.SELF,
            is_global=False,
        )

        assert topic.key == "server:111:self:zos"

    def test_invalid_topic_key(self) -> None:
        """Test that invalid topic key is rejected."""
        with pytest.raises(ValueError, match="Invalid topic key format"):
            Topic(
                key="invalid_key",
                category=TopicCategory.USER,
                is_global=True,
            )

    def test_server_scoped_keys_accepted(self) -> None:
        """Test that any server-prefixed key is currently accepted."""
        # The validator currently accepts any key starting with 'server:'
        topic = Topic(
            key="server:111:anything:goes",
            category=TopicCategory.USER,
            is_global=False,
        )

        assert topic.key == "server:111:anything:goes"

    def test_topic_with_metadata(self) -> None:
        """Test topic with metadata."""
        topic = Topic(
            key="user:123",
            category=TopicCategory.USER,
            is_global=True,
            metadata={"last_message_id": "msg123", "sentiment": 0.75},
        )

        assert topic.metadata == {"last_message_id": "msg123", "sentiment": 0.75}

    def test_topic_provisional_flag(self) -> None:
        """Test topic provisional flag."""
        topic = Topic(
            key="user:123",
            category=TopicCategory.USER,
            is_global=True,
            provisional=True,
        )

        assert topic.provisional is True

    def test_topic_with_activity(self) -> None:
        """Test topic with last activity timestamp."""
        now = utcnow()
        topic = Topic(
            key="user:123",
            category=TopicCategory.USER,
            is_global=True,
            last_activity_at=now,
        )

        assert topic.last_activity_at == now

    def test_serialization_round_trip(self) -> None:
        """Test topic serialization."""
        now = utcnow()
        original = Topic(
            key="server:111:user:222",
            category=TopicCategory.USER,
            is_global=False,
            provisional=True,
            last_activity_at=now,
            metadata={"context": "test"},
        )
        d = model_to_dict(original)
        restored = Topic(**d)

        assert restored.key == original.key
        assert restored.category == original.category
        assert restored.is_global == original.is_global
        assert restored.provisional == original.provisional
        assert restored.metadata == original.metadata


class TestSalienceEntry:
    """Tests for SalienceEntry model."""

    def test_create_earn_entry(self) -> None:
        """Test creating an earn transaction."""
        entry = SalienceEntry(
            topic_key="user:123",
            transaction_type=TransactionType.EARN,
            amount=5.0,
            reason="message",
        )

        assert entry.amount == 5.0
        assert entry.transaction_type == TransactionType.EARN

    def test_create_spend_entry(self) -> None:
        """Test creating a spend transaction."""
        entry = SalienceEntry(
            topic_key="user:123",
            transaction_type=TransactionType.SPEND,
            amount=-3.0,
            reason="reflection",
        )

        assert entry.amount == -3.0

    def test_all_transaction_types(self) -> None:
        """Test all transaction types are valid."""
        for tx_type in TransactionType:
            entry = SalienceEntry(
                topic_key="user:123",
                transaction_type=tx_type,
                amount=1.0,
            )
            assert entry.transaction_type == tx_type

    def test_salience_entry_with_source(self) -> None:
        """Test salience entry with source topic (propagation)."""
        entry = SalienceEntry(
            topic_key="user:123",
            transaction_type=TransactionType.PROPAGATE,
            amount=2.5,
            source_topic="dyad:123:456",
        )

        assert entry.source_topic == "dyad:123:456"

    def test_serialization_round_trip(self) -> None:
        """Test salience entry serialization."""
        original = SalienceEntry(
            topic_key="user:123",
            transaction_type=TransactionType.EARN,
            amount=5.0,
            reason="message",
            source_topic="channel:456",
        )
        d = model_to_dict(original)
        restored = SalienceEntry(**d)

        assert restored.topic_key == original.topic_key
        assert restored.transaction_type == original.transaction_type
        assert restored.amount == original.amount
        assert restored.reason == original.reason
        assert restored.source_topic == original.source_topic


class TestInsight:
    """Tests for Insight model."""

    def test_create_with_single_valence(self) -> None:
        """Test creating insight with one valence."""
        insight = Insight(
            topic_key="user:123",
            category="user_reflection",
            content="Test insight content",
            sources_scope_max=VisibilityScope.PUBLIC,
            created_at=utcnow(),
            layer_run_id=generate_id(),
            salience_spent=5.0,
            strength_adjustment=1.0,
            strength=5.0,
            original_topic_salience=10.0,
            confidence=0.8,
            importance=0.7,
            novelty=0.5,
            valence_curiosity=0.9,
        )

        assert insight.valence_curiosity == 0.9
        assert insight.valence_joy is None

    def test_create_with_multiple_valences(self) -> None:
        """Test creating insight with multiple valences."""
        insight = Insight(
            topic_key="user:123",
            category="user_reflection",
            content="Test insight",
            sources_scope_max=VisibilityScope.PUBLIC,
            created_at=utcnow(),
            layer_run_id=generate_id(),
            salience_spent=5.0,
            strength_adjustment=1.0,
            strength=5.0,
            original_topic_salience=10.0,
            confidence=0.8,
            importance=0.7,
            novelty=0.5,
            valence_joy=0.3,
            valence_warmth=0.8,
        )

        assert insight.valence_joy == 0.3
        assert insight.valence_warmth == 0.8

    def test_all_valence_types(self) -> None:
        """Test that all valence types can be set independently."""
        now = utcnow()
        run_id = generate_id()

        valences = [
            ("valence_joy", 0.5),
            ("valence_concern", 0.6),
            ("valence_curiosity", 0.7),
            ("valence_warmth", 0.8),
            ("valence_tension", 0.4),
        ]

        for valence_name, value in valences:
            kwargs = {
                "topic_key": "user:123",
                "category": "test",
                "content": "Test",
                "sources_scope_max": VisibilityScope.PUBLIC,
                "created_at": now,
                "layer_run_id": run_id,
                "salience_spent": 5.0,
                "strength_adjustment": 1.0,
                "strength": 5.0,
                "original_topic_salience": 10.0,
                "confidence": 0.8,
                "importance": 0.7,
                "novelty": 0.5,
                valence_name: value,
            }
            insight = Insight(**kwargs)
            assert getattr(insight, valence_name) == value

    def test_requires_at_least_one_valence(self) -> None:
        """Test that insight requires at least one valence."""
        with pytest.raises(ValueError, match="At least one valence"):
            Insight(
                topic_key="user:123",
                category="user_reflection",
                content="Test insight",
                sources_scope_max=VisibilityScope.PUBLIC,
                created_at=utcnow(),
                layer_run_id=generate_id(),
                salience_spent=5.0,
                strength_adjustment=1.0,
                strength=5.0,
                original_topic_salience=10.0,
                confidence=0.8,
                importance=0.7,
                novelty=0.5,
                # No valence fields set
            )

    def test_valence_range_validation(self) -> None:
        """Test that valence values are validated to 0.0-1.0."""
        with pytest.raises(ValueError):
            Insight(
                topic_key="user:123",
                category="user_reflection",
                content="Test insight",
                sources_scope_max=VisibilityScope.PUBLIC,
                created_at=utcnow(),
                layer_run_id=generate_id(),
                salience_spent=5.0,
                strength_adjustment=1.0,
                strength=5.0,
                original_topic_salience=10.0,
                confidence=0.8,
                importance=0.7,
                novelty=0.5,
                valence_joy=1.5,  # Out of range
            )

    def test_valence_negative_validation(self) -> None:
        """Test that negative valence values are rejected."""
        with pytest.raises(ValueError):
            Insight(
                topic_key="user:123",
                category="user_reflection",
                content="Test insight",
                sources_scope_max=VisibilityScope.PUBLIC,
                created_at=utcnow(),
                layer_run_id=generate_id(),
                salience_spent=5.0,
                strength_adjustment=1.0,
                strength=5.0,
                original_topic_salience=10.0,
                confidence=0.8,
                importance=0.7,
                novelty=0.5,
                valence_joy=-0.1,  # Negative
            )

    def test_strength_adjustment_range(self) -> None:
        """Test strength adjustment range validation."""
        # Valid range
        insight = Insight(
            topic_key="user:123",
            category="test",
            content="Test",
            sources_scope_max=VisibilityScope.PUBLIC,
            created_at=utcnow(),
            layer_run_id=generate_id(),
            salience_spent=5.0,
            strength_adjustment=5.0,
            strength=25.0,
            original_topic_salience=10.0,
            confidence=0.8,
            importance=0.7,
            novelty=0.5,
            valence_curiosity=0.5,
        )
        assert insight.strength_adjustment == 5.0

        # Out of range (too high)
        with pytest.raises(ValueError):
            Insight(
                topic_key="user:123",
                category="test",
                content="Test",
                sources_scope_max=VisibilityScope.PUBLIC,
                created_at=utcnow(),
                layer_run_id=generate_id(),
                salience_spent=5.0,
                strength_adjustment=15.0,  # > 10
                strength=75.0,
                original_topic_salience=10.0,
                confidence=0.8,
                importance=0.7,
                novelty=0.5,
                valence_curiosity=0.5,
            )

        # Out of range (too low)
        with pytest.raises(ValueError):
            Insight(
                topic_key="user:123",
                category="test",
                content="Test",
                sources_scope_max=VisibilityScope.PUBLIC,
                created_at=utcnow(),
                layer_run_id=generate_id(),
                salience_spent=5.0,
                strength_adjustment=0.05,  # < 0.1
                strength=0.25,
                original_topic_salience=10.0,
                confidence=0.8,
                importance=0.7,
                novelty=0.5,
                valence_curiosity=0.5,
            )

    def test_confidence_importance_novelty_range(self) -> None:
        """Test confidence, importance, novelty validation."""
        # Valid ranges
        insight = Insight(
            topic_key="user:123",
            category="test",
            content="Test",
            sources_scope_max=VisibilityScope.PUBLIC,
            created_at=utcnow(),
            layer_run_id=generate_id(),
            salience_spent=5.0,
            strength_adjustment=1.0,
            strength=5.0,
            original_topic_salience=10.0,
            confidence=0.0,  # Min
            importance=1.0,  # Max
            novelty=0.5,
            valence_curiosity=0.5,
        )
        assert insight.confidence == 0.0
        assert insight.importance == 1.0

    def test_insight_with_context(self) -> None:
        """Test insight with context links."""
        insight = Insight(
            topic_key="user:123",
            category="user_reflection",
            content="Test insight",
            sources_scope_max=VisibilityScope.PUBLIC,
            created_at=utcnow(),
            layer_run_id=generate_id(),
            salience_spent=5.0,
            strength_adjustment=1.0,
            strength=5.0,
            original_topic_salience=10.0,
            confidence=0.8,
            importance=0.7,
            novelty=0.5,
            valence_joy=0.5,
            context_channel="server:111:channel:222",
            context_thread="server:111:thread:333",
            subject="server:111:subject:philosophy",
            participants=["user:123", "user:456", "user:789"],
        )

        assert insight.context_channel == "server:111:channel:222"
        assert insight.context_thread == "server:111:thread:333"
        assert insight.subject == "server:111:subject:philosophy"
        assert len(insight.participants) == 3

    def test_insight_with_conflict_tracking(self) -> None:
        """Test insight conflict tracking."""
        conflict_ids = [generate_id(), generate_id()]
        insight = Insight(
            topic_key="user:123",
            category="user_reflection",
            content="Test insight",
            sources_scope_max=VisibilityScope.PUBLIC,
            created_at=utcnow(),
            layer_run_id=generate_id(),
            salience_spent=5.0,
            strength_adjustment=1.0,
            strength=5.0,
            original_topic_salience=10.0,
            confidence=0.8,
            importance=0.7,
            novelty=0.5,
            valence_joy=0.5,
            conflicts_with=conflict_ids,
            conflict_resolved=False,
        )

        assert insight.conflicts_with == conflict_ids
        assert insight.conflict_resolved is False

    def test_insight_with_synthesis_tracking(self) -> None:
        """Test insight synthesis source tracking."""
        source_ids = [generate_id(), generate_id(), generate_id()]
        insight = Insight(
            topic_key="user:123",
            category="synthesis",
            content="Synthesized insight",
            sources_scope_max=VisibilityScope.PUBLIC,
            created_at=utcnow(),
            layer_run_id=generate_id(),
            salience_spent=10.0,
            strength_adjustment=2.0,
            strength=20.0,
            original_topic_salience=30.0,
            confidence=0.9,
            importance=0.85,
            novelty=0.6,
            valence_warmth=0.7,
            synthesis_source_ids=source_ids,
        )

        assert insight.synthesis_source_ids == source_ids

    def test_insight_supersession(self) -> None:
        """Test insight supersession tracking."""
        previous_id = generate_id()
        insight = Insight(
            topic_key="user:123",
            category="user_reflection",
            content="Updated insight",
            sources_scope_max=VisibilityScope.PUBLIC,
            created_at=utcnow(),
            layer_run_id=generate_id(),
            salience_spent=5.0,
            strength_adjustment=1.0,
            strength=5.0,
            original_topic_salience=10.0,
            confidence=0.8,
            importance=0.7,
            novelty=0.5,
            valence_joy=0.5,
            supersedes=previous_id,
        )

        assert insight.supersedes == previous_id

    def test_insight_quarantine_flag(self) -> None:
        """Test insight quarantine flag."""
        insight = Insight(
            topic_key="user:123",
            category="user_reflection",
            content="Test insight",
            sources_scope_max=VisibilityScope.PUBLIC,
            created_at=utcnow(),
            layer_run_id=generate_id(),
            salience_spent=5.0,
            strength_adjustment=1.0,
            strength=5.0,
            original_topic_salience=10.0,
            confidence=0.8,
            importance=0.7,
            novelty=0.5,
            valence_joy=0.5,
            quarantined=True,
        )

        assert insight.quarantined is True

    def test_serialization_round_trip(self) -> None:
        """Test insight serialization and deserialization."""
        now = utcnow()
        run_id = generate_id()
        original = Insight(
            topic_key="user:123",
            category="user_reflection",
            content="Test insight",
            sources_scope_max=VisibilityScope.PUBLIC,
            created_at=now,
            layer_run_id=run_id,
            salience_spent=5.0,
            strength_adjustment=1.5,
            strength=7.5,
            original_topic_salience=10.0,
            confidence=0.8,
            importance=0.7,
            novelty=0.5,
            valence_joy=0.3,
            valence_warmth=0.6,
            context_channel="server:111:channel:222",
            participants=["user:123", "user:456"],
        )
        d = model_to_dict(original)
        restored = Insight(**d)

        assert restored.id == original.id
        assert restored.topic_key == original.topic_key
        assert restored.category == original.category
        assert restored.valence_joy == 0.3
        assert restored.valence_warmth == 0.6
        assert restored.context_channel == original.context_channel


class TestLayerRun:
    """Tests for LayerRun model."""

    def test_create_successful_run(self) -> None:
        """Test creating a successful layer run."""
        run = LayerRun(
            layer_name="user_reflection",
            layer_hash="abc123",
            started_at=utcnow(),
            status=LayerRunStatus.SUCCESS,
            targets_matched=10,
            targets_processed=10,
            insights_created=8,
        )

        assert run.status == LayerRunStatus.SUCCESS
        assert run.targets_skipped == 0

    def test_create_dry_run(self) -> None:
        """Test creating a dry run."""
        run = LayerRun(
            layer_name="test_layer",
            layer_hash="def456",
            started_at=utcnow(),
            status=LayerRunStatus.DRY,
        )

        assert run.status == LayerRunStatus.DRY
        assert run.insights_created == 0

    def test_create_partial_run(self) -> None:
        """Test creating a partial run."""
        run = LayerRun(
            layer_name="test_layer",
            layer_hash="def456",
            started_at=utcnow(),
            status=LayerRunStatus.PARTIAL,
            targets_matched=10,
            targets_processed=8,
            targets_skipped=2,
            insights_created=5,
        )

        assert run.status == LayerRunStatus.PARTIAL
        assert run.targets_skipped == 2

    def test_create_failed_run(self) -> None:
        """Test creating a failed layer run."""
        errors = [
            {"topic_key": "user:123", "error": "Timeout"},
            {"topic_key": "user:456", "error": "Invalid input"},
        ]
        run = LayerRun(
            layer_name="test_layer",
            layer_hash="def456",
            started_at=utcnow(),
            status=LayerRunStatus.FAILED,
            errors=errors,
        )

        assert run.status == LayerRunStatus.FAILED
        assert len(run.errors) == 2

    def test_layer_run_with_model_info(self) -> None:
        """Test layer run with model information."""
        run = LayerRun(
            layer_name="user_reflection",
            layer_hash="abc123",
            started_at=utcnow(),
            status=LayerRunStatus.SUCCESS,
            targets_matched=10,
            targets_processed=10,
            insights_created=8,
            model_profile="moderate",
            model_provider="anthropic",
            model_name="claude-sonnet-4-20250514",
            tokens_input=5000,
            tokens_output=2000,
            tokens_total=7000,
            estimated_cost_usd=0.042,
        )

        assert run.model_profile == "moderate"
        assert run.tokens_total == 7000

    def test_layer_run_with_completion_time(self) -> None:
        """Test layer run with completion timestamp."""
        start = utcnow()
        end = utcnow()
        run = LayerRun(
            layer_name="test_layer",
            layer_hash="abc123",
            started_at=start,
            completed_at=end,
            status=LayerRunStatus.SUCCESS,
        )

        assert run.completed_at == end

    def test_serialization_round_trip(self) -> None:
        """Test layer run serialization."""
        start = utcnow()
        original = LayerRun(
            layer_name="user_reflection",
            layer_hash="abc123",
            started_at=start,
            status=LayerRunStatus.SUCCESS,
            targets_matched=10,
            targets_processed=10,
            insights_created=8,
            model_profile="moderate",
            tokens_total=7000,
        )
        d = model_to_dict(original)
        restored = LayerRun(**d)

        assert restored.id == original.id
        assert restored.layer_name == original.layer_name
        assert restored.tokens_total == original.tokens_total


class TestReaction:
    """Tests for Reaction model."""

    def test_create_unicode_reaction(self) -> None:
        """Test creating a Unicode emoji reaction."""
        reaction = Reaction(
            message_id="msg123",
            user_id="user456",
            emoji="thumbsup",
            is_custom=False,
        )

        assert reaction.is_custom is False
        assert reaction.removed_at is None

    def test_create_custom_reaction(self) -> None:
        """Test creating a custom emoji reaction."""
        reaction = Reaction(
            message_id="msg123",
            user_id="user456",
            emoji="pepe_happy",
            is_custom=True,
            server_id="server789",
        )

        assert reaction.is_custom is True
        assert reaction.server_id == "server789"

    def test_reaction_removal(self) -> None:
        """Test reaction removal timestamp."""
        removed_at = utcnow()
        reaction = Reaction(
            message_id="msg123",
            user_id="user456",
            emoji="heart",
            is_custom=False,
            removed_at=removed_at,
        )

        assert reaction.removed_at == removed_at

    def test_reaction_ulid_validation(self) -> None:
        """Test that reaction ID is a valid ULID."""
        reaction = Reaction(
            message_id="msg123",
            user_id="user456",
            emoji="smile",
            is_custom=False,
        )

        assert len(reaction.id) == 26  # ULID length

    def test_serialization_round_trip(self) -> None:
        """Test reaction serialization."""
        original = Reaction(
            message_id="msg123",
            user_id="user456",
            emoji="heart",
            is_custom=False,
            server_id="server789",
        )
        d = model_to_dict(original)
        restored = Reaction(**d)

        assert restored.id == original.id
        assert restored.message_id == original.message_id
        assert restored.emoji == original.emoji


class TestPollState:
    """Tests for PollState model."""

    def test_create_poll_state(self) -> None:
        """Test creating a poll state entry."""
        now = utcnow()
        poll = PollState(
            channel_id="chan123",
            last_polled_at=now,
        )

        assert poll.channel_id == "chan123"
        assert poll.last_polled_at == now
        assert poll.last_message_at is None

    def test_poll_state_with_message_time(self) -> None:
        """Test poll state with last message timestamp."""
        msg_time = utcnow()
        poll_time = utcnow()
        poll = PollState(
            channel_id="chan123",
            last_message_at=msg_time,
            last_polled_at=poll_time,
        )

        assert poll.last_message_at == msg_time
        assert poll.last_polled_at == poll_time

    def test_serialization_round_trip(self) -> None:
        """Test poll state serialization."""
        now = utcnow()
        original = PollState(
            channel_id="chan123",
            last_message_at=now,
            last_polled_at=now,
        )
        d = model_to_dict(original)
        restored = PollState(**d)

        assert restored.channel_id == original.channel_id
        assert restored.last_polled_at == original.last_polled_at


class TestMediaAnalysis:
    """Tests for MediaAnalysis model."""

    def test_create_image_analysis(self) -> None:
        """Test creating image analysis."""
        media = MediaAnalysis(
            message_id="msg123",
            media_type=MediaType.IMAGE,
            url="https://example.com/image.jpg",
            width=1920,
            height=1080,
            description="A serene landscape with mountains",
        )

        assert media.media_type == MediaType.IMAGE
        assert media.width == 1920
        assert media.height == 1080
        assert media.duration_seconds is None

    def test_create_video_analysis(self) -> None:
        """Test creating video analysis."""
        media = MediaAnalysis(
            message_id="msg123",
            media_type=MediaType.VIDEO,
            url="https://example.com/video.mp4",
            filename="presentation.mp4",
            width=1280,
            height=720,
            duration_seconds=600,
            description="Technical presentation on systems design",
            analysis_model="claude-opus-vision",
        )

        assert media.media_type == MediaType.VIDEO
        assert media.duration_seconds == 600

    def test_create_gif_analysis(self) -> None:
        """Test creating GIF analysis."""
        media = MediaAnalysis(
            message_id="msg123",
            media_type=MediaType.GIF,
            url="https://example.com/reaction.gif",
            duration_seconds=3,
            description="Excited celebration reaction",
        )

        assert media.media_type == MediaType.GIF
        assert media.duration_seconds == 3

    def test_all_media_types(self) -> None:
        """Test all media types are valid."""
        for media_type in MediaType:
            media = MediaAnalysis(
                message_id="msg123",
                media_type=media_type,
                url="https://example.com/media",
                description="Test",
            )
            assert media.media_type == media_type

    def test_serialization_round_trip(self) -> None:
        """Test media analysis serialization."""
        original = MediaAnalysis(
            message_id="msg123",
            media_type=MediaType.IMAGE,
            url="https://example.com/image.jpg",
            filename="photo.jpg",
            width=1920,
            height=1080,
            description="A test image",
            analysis_model="vision-model-v1",
        )
        d = model_to_dict(original)
        restored = MediaAnalysis(**d)

        assert restored.id == original.id
        assert restored.message_id == original.message_id
        assert restored.media_type == original.media_type
        assert restored.width == original.width


class TestLinkAnalysis:
    """Tests for LinkAnalysis model."""

    def test_create_article_link(self) -> None:
        """Test creating article link analysis."""
        link = LinkAnalysis(
            message_id="msg123",
            url="https://example.com/article",
            domain="example.com",
            content_type=ContentType.ARTICLE,
            title="Interesting Article",
            summary="This article discusses...",
        )

        assert link.content_type == ContentType.ARTICLE
        assert link.is_youtube is False

    def test_create_youtube_link(self) -> None:
        """Test creating YouTube link analysis."""
        link = LinkAnalysis(
            message_id="msg123",
            url="https://youtube.com/watch?v=abc123",
            domain="youtube.com",
            content_type=ContentType.VIDEO,
            title="Educational Video",
            is_youtube=True,
            duration_seconds=1800,
            transcript_available=True,
        )

        assert link.is_youtube is True
        assert link.duration_seconds == 1800
        assert link.transcript_available is True

    def test_create_failed_link_fetch(self) -> None:
        """Test creating a failed link fetch."""
        link = LinkAnalysis(
            message_id="msg123",
            url="https://example.com/broken",
            domain="example.com",
            content_type=ContentType.OTHER,
            fetch_failed=True,
            fetch_error="Connection timeout",
        )

        assert link.fetch_failed is True
        assert link.fetch_error == "Connection timeout"

    def test_all_content_types(self) -> None:
        """Test all content types are valid."""
        for content_type in ContentType:
            link = LinkAnalysis(
                message_id="msg123",
                url="https://example.com/link",
                domain="example.com",
                content_type=content_type,
            )
            assert link.content_type == content_type

    def test_link_with_fetch_time(self) -> None:
        """Test link analysis with fetch timestamp."""
        now = utcnow()
        link = LinkAnalysis(
            message_id="msg123",
            url="https://example.com/article",
            domain="example.com",
            content_type=ContentType.ARTICLE,
            fetched_at=now,
        )

        assert link.fetched_at == now

    def test_serialization_round_trip(self) -> None:
        """Test link analysis serialization."""
        now = utcnow()
        original = LinkAnalysis(
            message_id="msg123",
            url="https://example.com/article",
            domain="example.com",
            content_type=ContentType.ARTICLE,
            title="Article Title",
            summary="Article summary",
            fetched_at=now,
        )
        d = model_to_dict(original)
        restored = LinkAnalysis(**d)

        assert restored.id == original.id
        assert restored.message_id == original.message_id
        assert restored.title == original.title


class TestChattinessEntry:
    """Tests for ChattinessEntry model."""

    def test_create_earn_entry(self) -> None:
        """Test creating a chattiness earn entry."""
        entry = ChattinessEntry(
            pool=ImpulsePool.ADDRESS,
            channel_id="chan123",
            transaction_type=ChattinessTransactionType.EARN,
            amount=5.0,
            trigger="direct_ping",
        )

        assert entry.pool == ImpulsePool.ADDRESS
        assert entry.amount == 5.0

    def test_create_flood_entry(self) -> None:
        """Test creating a flood entry (overwhelming trigger)."""
        entry = ChattinessEntry(
            pool=ImpulsePool.ADDRESS,
            transaction_type=ChattinessTransactionType.FLOOD,
            amount=100.0,
        )

        assert entry.transaction_type == ChattinessTransactionType.FLOOD

    def test_all_impulse_pools(self) -> None:
        """Test all impulse pools are valid."""
        for pool in ImpulsePool:
            entry = ChattinessEntry(
                pool=pool,
                transaction_type=ChattinessTransactionType.EARN,
                amount=1.0,
            )
            assert entry.pool == pool

    def test_all_chattiness_transaction_types(self) -> None:
        """Test all chattiness transaction types."""
        for tx_type in ChattinessTransactionType:
            entry = ChattinessEntry(
                pool=ImpulsePool.ADDRESS,
                transaction_type=tx_type,
                amount=1.0,
            )
            assert entry.transaction_type == tx_type

    def test_chattiness_entry_with_topic(self) -> None:
        """Test chattiness entry with topic scope."""
        entry = ChattinessEntry(
            pool=ImpulsePool.INSIGHT,
            channel_id="chan123",
            topic_key="user:456",
            transaction_type=ChattinessTransactionType.SPEND,
            amount=-3.5,
        )

        assert entry.topic_key == "user:456"

    def test_serialization_round_trip(self) -> None:
        """Test chattiness entry serialization."""
        original = ChattinessEntry(
            pool=ImpulsePool.ADDRESS,
            channel_id="chan123",
            transaction_type=ChattinessTransactionType.EARN,
            amount=5.0,
            trigger="direct_ping",
        )
        d = model_to_dict(original)
        restored = ChattinessEntry(**d)

        assert restored.id == original.id
        assert restored.pool == original.pool
        assert restored.amount == original.amount


class TestSpeechPressure:
    """Tests for SpeechPressure model."""

    def test_create_speech_pressure(self) -> None:
        """Test creating a speech pressure entry."""
        pressure = SpeechPressure(
            amount=25.0,
            trigger="response_generated",
        )

        assert pressure.amount == 25.0
        assert pressure.trigger == "response_generated"

    def test_speech_pressure_per_server(self) -> None:
        """Test speech pressure with server scope."""
        pressure = SpeechPressure(
            amount=15.0,
            trigger="response_generated",
            server_id="server789",
        )

        assert pressure.server_id == "server789"

    def test_serialization_round_trip(self) -> None:
        """Test speech pressure serialization."""
        original = SpeechPressure(
            amount=25.0,
            trigger="response_generated",
            server_id="server789",
        )
        d = model_to_dict(original)
        restored = SpeechPressure(**d)

        assert restored.id == original.id
        assert restored.amount == original.amount
        assert restored.server_id == original.server_id


class TestConversationLogEntry:
    """Tests for ConversationLogEntry model."""

    def test_create_conversation_log_entry(self) -> None:
        """Test creating a conversation log entry."""
        entry = ConversationLogEntry(
            message_id="zos_msg_123",
            channel_id="chan456",
            server_id="server789",
            content="Hello, I'm responding to your message",
            layer_name="conversational",
            trigger_type="message_reply",
            impulse_pool=ImpulsePool.CONVERSATIONAL,
            impulse_spent=3.5,
        )

        assert entry.message_id == "zos_msg_123"
        assert entry.content == "Hello, I'm responding to your message"
        assert entry.priority_flagged is False

    def test_conversation_log_dm(self) -> None:
        """Test conversation log for DM."""
        entry = ConversationLogEntry(
            message_id="zos_msg_456",
            channel_id="dm_chan",
            content="Direct message response",
            layer_name="conversational",
            trigger_type="dm",
            impulse_pool=ImpulsePool.ADDRESS,
            impulse_spent=5.0,
        )

        assert entry.server_id is None

    def test_conversation_log_priority_flagged(self) -> None:
        """Test priority-flagged conversation log entry."""
        entry = ConversationLogEntry(
            message_id="zos_msg_789",
            channel_id="chan456",
            server_id="server789",
            content="Important response",
            layer_name="conversational",
            trigger_type="direct_ping",
            impulse_pool=ImpulsePool.ADDRESS,
            impulse_spent=10.0,
            priority_flagged=True,
        )

        assert entry.priority_flagged is True

    def test_serialization_round_trip(self) -> None:
        """Test conversation log entry serialization."""
        original = ConversationLogEntry(
            message_id="zos_msg_123",
            channel_id="chan456",
            server_id="server789",
            content="Response content",
            layer_name="conversational",
            trigger_type="message_reply",
            impulse_pool=ImpulsePool.CONVERSATIONAL,
            impulse_spent=3.5,
            priority_flagged=False,
        )
        d = model_to_dict(original)
        restored = ConversationLogEntry(**d)

        assert restored.id == original.id
        assert restored.message_id == original.message_id
        assert restored.content == original.content


class TestDraftHistoryEntry:
    """Tests for DraftHistoryEntry model."""

    def test_create_draft_entry(self) -> None:
        """Test creating a draft history entry."""
        draft = DraftHistoryEntry(
            channel_id="chan123",
            content="This is a draft response I almost sent",
            layer_name="conversational",
        )

        assert draft.channel_id == "chan123"
        assert draft.content == "This is a draft response I almost sent"
        assert draft.thread_id is None

    def test_draft_in_thread(self) -> None:
        """Test draft in a thread context."""
        draft = DraftHistoryEntry(
            channel_id="chan123",
            thread_id="thread456",
            content="Threaded draft",
            layer_name="conversational",
        )

        assert draft.thread_id == "thread456"

    def test_draft_with_discard_reason(self) -> None:
        """Test draft with discard reason."""
        draft = DraftHistoryEntry(
            channel_id="chan123",
            content="Off-topic response",
            layer_name="conversational",
            discard_reason="Content outside conversation scope",
        )

        assert draft.discard_reason == "Content outside conversation scope"

    def test_serialization_round_trip(self) -> None:
        """Test draft history entry serialization."""
        original = DraftHistoryEntry(
            channel_id="chan123",
            thread_id="thread456",
            content="Draft response content",
            layer_name="conversational",
            discard_reason="Off-topic",
        )
        d = model_to_dict(original)
        restored = DraftHistoryEntry(**d)

        assert restored.id == original.id
        assert restored.channel_id == original.channel_id
        assert restored.content == original.content
        assert restored.discard_reason == original.discard_reason


class TestLLMCall:
    """Tests for LLMCall model."""

    def test_create_successful_call(self) -> None:
        """Test creating a successful LLM call."""
        call = LLMCall(
            call_type=LLMCallType.REFLECTION,
            model_profile="moderate",
            model_provider="anthropic",
            model_name="claude-sonnet-4",
            prompt="Test prompt",
            response="Test response",
            tokens_input=100,
            tokens_output=50,
            tokens_total=150,
            latency_ms=500,
        )

        assert call.success is True
        assert call.error_message is None

    def test_create_failed_call(self) -> None:
        """Test creating a failed LLM call."""
        call = LLMCall(
            call_type=LLMCallType.VISION,
            model_profile="vision",
            model_provider="anthropic",
            model_name="claude-sonnet-4",
            prompt="Analyze image",
            response="",
            tokens_input=0,
            tokens_output=0,
            tokens_total=0,
            success=False,
            error_message="Rate limit exceeded",
        )

        assert call.success is False
        assert call.error_message == "Rate limit exceeded"

    def test_llm_call_with_layer_run(self) -> None:
        """Test LLM call linked to layer run."""
        run_id = generate_id()
        call = LLMCall(
            call_type=LLMCallType.REFLECTION,
            model_profile="moderate",
            model_provider="anthropic",
            model_name="claude-sonnet-4",
            prompt="Reflect",
            response="Reflection result",
            tokens_input=100,
            tokens_output=50,
            tokens_total=150,
            layer_run_id=run_id,
        )

        assert call.layer_run_id == run_id

    def test_llm_call_with_topic(self) -> None:
        """Test LLM call linked to topic."""
        call = LLMCall(
            call_type=LLMCallType.REFLECTION,
            model_profile="moderate",
            model_provider="anthropic",
            model_name="claude-sonnet-4",
            prompt="Reflect on user",
            response="User analysis",
            tokens_input=100,
            tokens_output=50,
            tokens_total=150,
            topic_key="user:123",
        )

        assert call.topic_key == "user:123"

    def test_llm_call_all_types(self) -> None:
        """Test all LLM call types."""
        for call_type in LLMCallType:
            call = LLMCall(
                call_type=call_type,
                model_profile="test",
                model_provider="anthropic",
                model_name="test-model",
                prompt="Test",
                response="Result",
                tokens_input=10,
                tokens_output=10,
                tokens_total=20,
            )
            assert call.call_type == call_type

    def test_llm_call_with_cost(self) -> None:
        """Test LLM call with estimated cost."""
        call = LLMCall(
            call_type=LLMCallType.REFLECTION,
            model_profile="moderate",
            model_provider="anthropic",
            model_name="claude-sonnet-4",
            prompt="Expensive call",
            response="Expensive response",
            tokens_input=5000,
            tokens_output=2000,
            tokens_total=7000,
            estimated_cost_usd=0.042,
            latency_ms=1500,
        )

        assert call.estimated_cost_usd == 0.042
        assert call.latency_ms == 1500

    def test_serialization_round_trip(self) -> None:
        """Test LLM call serialization."""
        original = LLMCall(
            call_type=LLMCallType.REFLECTION,
            model_profile="moderate",
            model_provider="anthropic",
            model_name="claude-sonnet-4",
            prompt="Test prompt",
            response="Test response",
            tokens_input=100,
            tokens_output=50,
            tokens_total=150,
            estimated_cost_usd=0.009,
            latency_ms=500,
        )
        d = model_to_dict(original)
        restored = LLMCall(**d)

        assert restored.id == original.id
        assert restored.call_type == original.call_type
        assert restored.tokens_total == original.tokens_total


class TestModelConversion:
    """Tests for model conversion helpers."""

    def test_model_to_dict(self) -> None:
        """Test converting model to dict."""
        server = Server(id="123", name="Test")
        d = model_to_dict(server)

        assert d["id"] == "123"
        assert d["name"] == "Test"
        assert "created_at" in d

    def test_model_to_dict_exclude_none(self) -> None:
        """Test converting model to dict excluding None."""
        server = Server(id="123")
        d = model_to_dict(server, exclude_none=True)

        assert d["id"] == "123"
        assert "name" not in d

    def test_row_to_model_conversion(self) -> None:
        """Test converting SQLAlchemy row to model."""
        row = MagicMock()
        row._mapping = {
            "id": "msg123",
            "channel_id": "chan456",
            "server_id": "serv789",
            "author_id": "user111",
            "content": "Hello",
            "created_at": utcnow(),
            "visibility_scope": VisibilityScope.PUBLIC.value,
            "reactions_aggregate": None,
            "reply_to_id": None,
            "thread_id": None,
            "has_media": False,
            "has_links": False,
            "ingested_at": utcnow(),
            "deleted_at": None,
        }
        msg = row_to_model(row, Message)

        assert msg.id == "msg123"
        assert msg.channel_id == "chan456"
        assert msg.visibility_scope == VisibilityScope.PUBLIC


class TestEnums:
    """Tests for enum types."""

    def test_visibility_scope_values(self) -> None:
        """Test visibility scope enum values."""
        assert VisibilityScope.PUBLIC.value == "public"
        assert VisibilityScope.DM.value == "dm"

    def test_channel_type_values(self) -> None:
        """Test channel type enum values."""
        expected = {"text", "voice", "dm", "group_dm", "thread"}
        actual = {t.value for t in ChannelType}
        assert actual == expected

    def test_topic_category_values(self) -> None:
        """Test topic category enum values."""
        expected = {
            "user",
            "channel",
            "thread",
            "role",
            "dyad",
            "user_in_channel",
            "dyad_in_channel",
            "subject",
            "emoji",
            "self",
        }
        actual = {t.value for t in TopicCategory}
        assert actual == expected

    def test_layer_run_status_values(self) -> None:
        """Test layer run status enum values."""
        assert LayerRunStatus.SUCCESS.value == "success"
        assert LayerRunStatus.PARTIAL.value == "partial"
        assert LayerRunStatus.FAILED.value == "failed"
        assert LayerRunStatus.DRY.value == "dry"

    def test_transaction_type_values(self) -> None:
        """Test transaction type enum values."""
        expected = {"earn", "spend", "reset", "retain", "decay", "propagate", "spillover", "warm"}
        actual = {t.value for t in TransactionType}
        assert actual == expected

    def test_impulse_pool_values(self) -> None:
        """Test impulse pool enum values."""
        expected = {"address", "insight", "conversational", "curiosity", "reaction"}
        actual = {p.value for p in ImpulsePool}
        assert actual == expected

    def test_chattiness_transaction_type_values(self) -> None:
        """Test chattiness transaction type values."""
        expected = {"earn", "spend", "decay", "flood", "reset"}
        actual = {t.value for t in ChattinessTransactionType}
        assert actual == expected

    def test_media_type_values(self) -> None:
        """Test media type enum values."""
        expected = {"image", "video", "gif", "embed"}
        actual = {t.value for t in MediaType}
        assert actual == expected

    def test_content_type_values(self) -> None:
        """Test content type enum values."""
        expected = {"article", "video", "image", "audio", "other"}
        actual = {t.value for t in ContentType}
        assert actual == expected

    def test_llm_call_type_values(self) -> None:
        """Test LLM call type enum values."""
        expected = {"reflection", "vision", "conversation", "filter", "synthesis", "other"}
        actual = {t.value for t in LLMCallType}
        assert actual == expected
