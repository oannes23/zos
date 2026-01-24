"""Tests for the database module.

Comprehensive test coverage for all 19 tables, foreign key constraints,
derived views, indexes, and edge cases.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from zos.config import Config
from zos.database import (
    channels,
    chattiness_ledger,
    conversation_log,
    create_tables,
    draft_history,
    generate_id,
    get_engine,
    insights,
    layer_runs,
    link_analysis,
    llm_calls,
    media_analysis,
    messages,
    metadata,
    poll_state,
    reactions,
    salience_ledger,
    servers,
    speech_pressure,
    topics,
    user_server_tracking,
    users,
)


# ============================================================================
# Fixtures
# ============================================================================


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
def now():
    """Return current time in UTC (timezone-aware)."""
    return datetime.now(timezone.utc)


@pytest.fixture
def setup_server(engine, now):
    """Create a server for tests requiring relationships."""
    with engine.connect() as conn:
        conn.execute(
            servers.insert().values(
                id="server1",
                name="Test Server",
                threads_as_topics=True,
                created_at=now,
            )
        )
        conn.commit()
    return "server1"


@pytest.fixture
def setup_channel(engine, setup_server, now):
    """Create a channel for tests requiring relationships."""
    with engine.connect() as conn:
        conn.execute(
            channels.insert().values(
                id="channel1",
                server_id=setup_server,
                name="test-channel",
                type="text",
                created_at=now,
            )
        )
        conn.commit()
    return "channel1"


@pytest.fixture
def setup_message(engine, setup_channel, setup_server, now):
    """Create a message for tests requiring relationships."""
    with engine.connect() as conn:
        conn.execute(
            messages.insert().values(
                id="msg1",
                channel_id=setup_channel,
                server_id=setup_server,
                author_id="author1",
                content="Test message",
                created_at=now,
                visibility_scope="public",
                has_media=False,
                has_links=False,
                ingested_at=now,
            )
        )
        conn.commit()
    return "msg1"


@pytest.fixture
def setup_topic(engine, now):
    """Create a topic for tests requiring relationships."""
    with engine.connect() as conn:
        conn.execute(
            topics.insert().values(
                key="user:123456789",
                category="user",
                is_global=True,
                provisional=False,
                created_at=now,
            )
        )
        conn.commit()
    return "user:123456789"


@pytest.fixture
def setup_layer_run(engine, now):
    """Create a layer run for tests requiring relationships."""
    layer_id = generate_id()
    with engine.connect() as conn:
        conn.execute(
            layer_runs.insert().values(
                id=layer_id,
                layer_name="test_layer",
                layer_hash="abc123def456",
                started_at=now,
                status="success",
            )
        )
        conn.commit()
    return layer_id


# ============================================================================
# Core Functionality Tests
# ============================================================================


def test_generate_id() -> None:
    """Test ULID generation."""
    id1 = generate_id()
    id2 = generate_id()

    # Should be 26 characters (ULID length)
    assert len(id1) == 26
    assert len(id2) == 26

    # Should be unique
    assert id1 != id2

    # Should be sortable (later ID > earlier ID)
    assert id2 > id1


def test_engine_wal_mode(engine) -> None:
    """Test that WAL mode is enabled."""
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA journal_mode")).scalar()
        assert result.lower() == "wal"


def test_engine_foreign_keys(engine) -> None:
    """Test that foreign keys are enabled."""
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA foreign_keys")).scalar()
        assert result == 1


def test_all_tables_created(engine) -> None:
    """Test that all 19 tables are created."""
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    expected_tables = {
        "servers",
        "users",
        "user_server_tracking",
        "channels",
        "messages",
        "reactions",
        "poll_state",
        "media_analysis",
        "link_analysis",
        "topics",
        "salience_ledger",
        "insights",
        "layer_runs",
        "llm_calls",
        "chattiness_ledger",
        "speech_pressure",
        "conversation_log",
        "draft_history",
        "_schema_version",
    }

    assert expected_tables.issubset(table_names)


def test_database_path_created(test_config: Config) -> None:
    """Test that database file is created."""
    engine = get_engine(test_config)
    create_tables(engine)

    assert test_config.database_path.exists()


# ============================================================================
# Table 1: Servers
# ============================================================================


def test_insert_server(engine, now) -> None:
    """Test inserting a server."""
    with engine.connect() as conn:
        conn.execute(
            servers.insert().values(
                id="123456789",
                name="Test Server",
                threads_as_topics=True,
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(select(servers).where(servers.c.id == "123456789")).fetchone()
        assert result is not None
        assert result.name == "Test Server"
        assert result.threads_as_topics is True


def test_server_nullable_fields(engine, now) -> None:
    """Test server with minimal required fields."""
    with engine.connect() as conn:
        conn.execute(
            servers.insert().values(
                id="minimal_server",
                threads_as_topics=False,
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(servers).where(servers.c.id == "minimal_server")
        ).fetchone()
        assert result is not None
        assert result.name is None
        assert result.privacy_gate_role is None
        assert result.disabled_layers is None
        assert result.chattiness_config is None


def test_server_with_json_config(engine, now) -> None:
    """Test server with JSON fields."""
    config = {
        "threshold_min": 30,
        "threshold_max": 80,
        "pools_enabled": {"address": True, "insight": False},
    }
    with engine.connect() as conn:
        conn.execute(
            servers.insert().values(
                id="json_server",
                disabled_layers=["layer1", "layer2"],
                chattiness_config=config,
                threads_as_topics=True,
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(servers).where(servers.c.id == "json_server")
        ).fetchone()
        assert result is not None
        assert result.disabled_layers == ["layer1", "layer2"]
        assert result.chattiness_config == config


# ============================================================================
# Table 2: Users
# ============================================================================


def test_insert_user(engine) -> None:
    """Test inserting a user."""
    with engine.connect() as conn:
        conn.execute(
            users.insert().values(
                id="987654321",
                first_dm_acknowledged=False,
            )
        )
        conn.commit()

        result = conn.execute(select(users).where(users.c.id == "987654321")).fetchone()
        assert result is not None
        assert result.first_dm_acknowledged is False
        assert result.first_dm_at is None


def test_user_with_dm_timestamp(engine, now) -> None:
    """Test user with DM acknowledgment timestamp."""
    with engine.connect() as conn:
        conn.execute(
            users.insert().values(
                id="user_with_dm",
                first_dm_acknowledged=True,
                first_dm_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(users).where(users.c.id == "user_with_dm")
        ).fetchone()
        assert result is not None
        assert result.first_dm_acknowledged is True
        # SQLite returns naive datetimes, just verify it's set
        assert result.first_dm_at is not None


# ============================================================================
# Table 3: UserServerTracking
# ============================================================================


def test_insert_user_server_tracking(engine, now) -> None:
    """Test inserting user-server tracking."""
    with engine.connect() as conn:
        # Create server and user first
        conn.execute(
            servers.insert().values(
                id="track_server",
                threads_as_topics=True,
                created_at=now,
            )
        )
        conn.execute(
            users.insert().values(
                id="track_user",
                first_dm_acknowledged=False,
            )
        )

        # Insert tracking
        conn.execute(
            user_server_tracking.insert().values(
                user_id="track_user",
                server_id="track_server",
                first_seen_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(user_server_tracking).where(
                user_server_tracking.c.user_id == "track_user"
            )
        ).fetchone()
        assert result is not None
        assert result.server_id == "track_server"
        # SQLite returns naive datetimes, just verify it's set
        assert result.first_seen_at is not None


def test_user_server_tracking_unique_composite_key(engine, now) -> None:
    """Test that user-server tracking has unique composite key."""
    with engine.connect() as conn:
        # Create prerequisites
        conn.execute(
            servers.insert().values(
                id="unique_server",
                threads_as_topics=True,
                created_at=now,
            )
        )
        conn.execute(
            users.insert().values(
                id="unique_user",
                first_dm_acknowledged=False,
            )
        )

        # Insert first tracking
        conn.execute(
            user_server_tracking.insert().values(
                user_id="unique_user",
                server_id="unique_server",
                first_seen_at=now,
            )
        )
        conn.commit()

        # Try to insert duplicate - should fail
        with pytest.raises(IntegrityError):
            conn.execute(
                user_server_tracking.insert().values(
                    user_id="unique_user",
                    server_id="unique_server",
                    first_seen_at=now,
                )
            )
            conn.commit()


# ============================================================================
# Table 4: Channels
# ============================================================================


def test_insert_channel(engine, setup_server, now) -> None:
    """Test inserting a channel."""
    with engine.connect() as conn:
        conn.execute(
            channels.insert().values(
                id="chan1",
                server_id=setup_server,
                name="general",
                type="text",
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(select(channels).where(channels.c.id == "chan1")).fetchone()
        assert result is not None
        assert result.name == "general"
        assert result.type == "text"


def test_channel_requires_server(engine, now) -> None:
    """Test that channel requires valid server FK."""
    with engine.connect() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(
                channels.insert().values(
                    id="orphan_channel",
                    server_id="nonexistent_server",
                    type="text",
                    created_at=now,
                )
            )
            conn.commit()


def test_channel_thread_with_parent(engine, setup_server, now) -> None:
    """Test thread channel with parent_id."""
    with engine.connect() as conn:
        # Create parent channel
        conn.execute(
            channels.insert().values(
                id="parent_chan",
                server_id=setup_server,
                type="text",
                created_at=now,
            )
        )

        # Create thread channel
        conn.execute(
            channels.insert().values(
                id="thread_chan",
                server_id=setup_server,
                type="thread",
                parent_id="parent_chan",
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(channels).where(channels.c.id == "thread_chan")
        ).fetchone()
        assert result is not None
        assert result.type == "thread"
        assert result.parent_id == "parent_chan"


# ============================================================================
# Table 5: Messages
# ============================================================================


def test_insert_message(engine, setup_channel, setup_server, now) -> None:
    """Test inserting a message."""
    with engine.connect() as conn:
        conn.execute(
            messages.insert().values(
                id="msg1",
                channel_id=setup_channel,
                server_id=setup_server,
                author_id="author1",
                content="Hello world",
                created_at=now,
                visibility_scope="public",
                has_media=False,
                has_links=False,
                ingested_at=now,
            )
        )
        conn.commit()

        result = conn.execute(select(messages).where(messages.c.id == "msg1")).fetchone()
        assert result is not None
        assert result.content == "Hello world"


def test_message_requires_channel(engine, setup_server, now) -> None:
    """Test that message requires valid channel FK."""
    with engine.connect() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(
                messages.insert().values(
                    id="orphan_msg",
                    channel_id="nonexistent_channel",
                    server_id=setup_server,
                    author_id="author1",
                    content="Test",
                    created_at=now,
                    visibility_scope="public",
                    has_media=False,
                    has_links=False,
                    ingested_at=now,
                )
            )
            conn.commit()


def test_message_dm_without_server_id(engine, setup_channel, now) -> None:
    """Test DM message without server_id (channel still needs one)."""
    with engine.connect() as conn:
        # Create a message with NULL server_id (for DMs)
        conn.execute(
            messages.insert().values(
                id="dm_msg",
                channel_id=setup_channel,
                server_id=None,  # Nullable for DMs
                author_id="dm_user",
                content="DM content",
                created_at=now,
                visibility_scope="dm",
                has_media=False,
                has_links=False,
                ingested_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(messages).where(messages.c.id == "dm_msg")
        ).fetchone()
        assert result is not None
        assert result.server_id is None
        assert result.visibility_scope == "dm"


def test_message_with_media_and_links(engine, setup_channel, setup_server, now) -> None:
    """Test message with media and links flags."""
    with engine.connect() as conn:
        conn.execute(
            messages.insert().values(
                id="rich_msg",
                channel_id=setup_channel,
                server_id=setup_server,
                author_id="author1",
                content="Check out https://example.com and this image!",
                created_at=now,
                visibility_scope="public",
                has_media=True,
                has_links=True,
                ingested_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(messages).where(messages.c.id == "rich_msg")
        ).fetchone()
        assert result.has_media is True
        assert result.has_links is True


def test_message_soft_delete(engine, setup_message, now) -> None:
    """Test message soft delete with deleted_at."""
    with engine.connect() as conn:
        # Verify message exists
        result = conn.execute(
            select(messages).where(messages.c.id == setup_message)
        ).fetchone()
        assert result.deleted_at is None

        # Soft delete
        delete_time = datetime.now(timezone.utc)
        conn.execute(
            messages.update().where(messages.c.id == setup_message).values(deleted_at=delete_time)
        )
        conn.commit()

        # Verify soft delete
        result = conn.execute(
            select(messages).where(messages.c.id == setup_message)
        ).fetchone()
        assert result.deleted_at is not None


def test_message_with_reply_and_thread(engine, setup_channel, setup_server, now) -> None:
    """Test message with reply_to and thread context."""
    with engine.connect() as conn:
        # Create original message
        conn.execute(
            messages.insert().values(
                id="original",
                channel_id=setup_channel,
                server_id=setup_server,
                author_id="author1",
                content="Original message",
                created_at=now,
                visibility_scope="public",
                has_media=False,
                has_links=False,
                ingested_at=now,
            )
        )

        # Create reply in thread
        conn.execute(
            messages.insert().values(
                id="reply_msg",
                channel_id=setup_channel,
                server_id=setup_server,
                author_id="author2",
                content="Reply to original",
                created_at=datetime.now(timezone.utc),
                visibility_scope="public",
                has_media=False,
                has_links=False,
                ingested_at=datetime.now(timezone.utc),
                reply_to_id="original",
                thread_id="thread123",
            )
        )
        conn.commit()

        result = conn.execute(
            select(messages).where(messages.c.id == "reply_msg")
        ).fetchone()
        assert result.reply_to_id == "original"
        assert result.thread_id == "thread123"


def test_message_reactions_aggregate_json(engine, setup_message, now) -> None:
    """Test message with reactions_aggregate JSON field."""
    reactions_agg = {
        "👍": 5,
        "❤️": 3,
        "custom_emoji_123": 2,
    }
    with engine.connect() as conn:
        conn.execute(
            messages.update()
            .where(messages.c.id == setup_message)
            .values(reactions_aggregate=reactions_agg)
        )
        conn.commit()

        result = conn.execute(
            select(messages).where(messages.c.id == setup_message)
        ).fetchone()
        assert result.reactions_aggregate == reactions_agg


# ============================================================================
# Table 6: Reactions
# ============================================================================


def test_insert_reaction(engine, setup_message, now) -> None:
    """Test inserting a reaction."""
    with engine.connect() as conn:
        reaction_id = generate_id()
        conn.execute(
            reactions.insert().values(
                id=reaction_id,
                message_id=setup_message,
                user_id="reactor1",
                emoji="👍",
                is_custom=False,
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(reactions).where(reactions.c.id == reaction_id)
        ).fetchone()
        assert result is not None
        assert result.emoji == "👍"
        assert result.is_custom is False


def test_reaction_requires_message(engine, now) -> None:
    """Test that reaction requires valid message FK."""
    with engine.connect() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(
                reactions.insert().values(
                    id=generate_id(),
                    message_id="nonexistent_msg",
                    user_id="user1",
                    emoji="👍",
                    is_custom=False,
                    created_at=now,
                )
            )
            conn.commit()


def test_reaction_soft_delete(engine, setup_message, now) -> None:
    """Test reaction soft delete with removed_at."""
    with engine.connect() as conn:
        reaction_id = generate_id()
        conn.execute(
            reactions.insert().values(
                id=reaction_id,
                message_id=setup_message,
                user_id="reactor1",
                emoji="❤️",
                is_custom=False,
                created_at=now,
            )
        )

        # Soft delete
        remove_time = datetime.now(timezone.utc)
        conn.execute(
            reactions.update()
            .where(reactions.c.id == reaction_id)
            .values(removed_at=remove_time)
        )
        conn.commit()

        result = conn.execute(
            select(reactions).where(reactions.c.id == reaction_id)
        ).fetchone()
        assert result.removed_at is not None


def test_reaction_custom_emoji_with_server(engine, setup_message, setup_server, now) -> None:
    """Test custom emoji reaction with server_id."""
    with engine.connect() as conn:
        reaction_id = generate_id()
        conn.execute(
            reactions.insert().values(
                id=reaction_id,
                message_id=setup_message,
                user_id="reactor1",
                emoji="custom_emoji_123",
                is_custom=True,
                server_id=setup_server,
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(reactions).where(reactions.c.id == reaction_id)
        ).fetchone()
        assert result.is_custom is True
        assert result.server_id == setup_server


# ============================================================================
# Table 7: PollState
# ============================================================================


def test_insert_poll_state(engine, setup_channel, now) -> None:
    """Test inserting poll state."""
    with engine.connect() as conn:
        conn.execute(
            poll_state.insert().values(
                channel_id=setup_channel,
                last_message_at=now,
                last_polled_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(poll_state).where(poll_state.c.channel_id == setup_channel)
        ).fetchone()
        assert result is not None
        # SQLite returns naive datetimes
        assert result.last_message_at is not None
        assert result.last_polled_at is not None


def test_poll_state_nullable_message_at(engine, setup_channel, now) -> None:
    """Test poll state with null last_message_at."""
    with engine.connect() as conn:
        conn.execute(
            poll_state.insert().values(
                channel_id=setup_channel,
                last_message_at=None,
                last_polled_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(poll_state).where(poll_state.c.channel_id == setup_channel)
        ).fetchone()
        assert result.last_message_at is None


# ============================================================================
# Table 8: MediaAnalysis
# ============================================================================


def test_insert_media_analysis(engine, setup_message, now) -> None:
    """Test inserting media analysis."""
    with engine.connect() as conn:
        media_id = generate_id()
        conn.execute(
            media_analysis.insert().values(
                id=media_id,
                message_id=setup_message,
                media_type="image",
                url="https://example.com/image.jpg",
                filename="image.jpg",
                width=1920,
                height=1080,
                description="I see a beautiful landscape photo",
                analyzed_at=now,
                analysis_model="vision-v1",
            )
        )
        conn.commit()

        result = conn.execute(
            select(media_analysis).where(media_analysis.c.id == media_id)
        ).fetchone()
        assert result is not None
        assert result.media_type == "image"
        assert result.width == 1920


def test_media_analysis_requires_message(engine, now) -> None:
    """Test that media analysis requires valid message FK."""
    with engine.connect() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(
                media_analysis.insert().values(
                    id=generate_id(),
                    message_id="nonexistent",
                    media_type="image",
                    url="https://example.com/image.jpg",
                    description="Test",
                    analyzed_at=now,
                )
            )
            conn.commit()


def test_media_analysis_video_with_duration(engine, setup_message, now) -> None:
    """Test video media with duration."""
    with engine.connect() as conn:
        media_id = generate_id()
        conn.execute(
            media_analysis.insert().values(
                id=media_id,
                message_id=setup_message,
                media_type="video",
                url="https://example.com/video.mp4",
                duration_seconds=120,
                description="I see a 2-minute video",
                analyzed_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(media_analysis).where(media_analysis.c.id == media_id)
        ).fetchone()
        assert result.duration_seconds == 120


# ============================================================================
# Table 9: LinkAnalysis
# ============================================================================


def test_insert_link_analysis(engine, setup_message, now) -> None:
    """Test inserting link analysis."""
    with engine.connect() as conn:
        link_id = generate_id()
        conn.execute(
            link_analysis.insert().values(
                id=link_id,
                message_id=setup_message,
                url="https://example.com/article",
                domain="example.com",
                content_type="article",
                title="Example Article",
                summary="A brief summary",
                fetched_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(link_analysis).where(link_analysis.c.id == link_id)
        ).fetchone()
        assert result is not None
        assert result.domain == "example.com"
        assert result.content_type == "article"


def test_link_analysis_requires_message(engine, now) -> None:
    """Test that link analysis requires valid message FK."""
    with engine.connect() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(
                link_analysis.insert().values(
                    id=generate_id(),
                    message_id="nonexistent",
                    url="https://example.com",
                    domain="example.com",
                    content_type="article",
                )
            )
            conn.commit()


def test_link_analysis_youtube(engine, setup_message, now) -> None:
    """Test YouTube link with transcript."""
    with engine.connect() as conn:
        link_id = generate_id()
        conn.execute(
            link_analysis.insert().values(
                id=link_id,
                message_id=setup_message,
                url="https://youtube.com/watch?v=dQw4w9WgXcQ",
                domain="youtube.com",
                content_type="video",
                is_youtube=True,
                title="Example Video",
                duration_seconds=184,
                transcript_available=True,
                fetched_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(link_analysis).where(link_analysis.c.id == link_id)
        ).fetchone()
        assert result.is_youtube is True
        assert result.transcript_available is True


def test_link_analysis_fetch_failure(engine, setup_message, now) -> None:
    """Test link analysis with failed fetch."""
    with engine.connect() as conn:
        link_id = generate_id()
        conn.execute(
            link_analysis.insert().values(
                id=link_id,
                message_id=setup_message,
                url="https://example.com/broken",
                domain="example.com",
                content_type="other",
                fetch_failed=True,
                fetch_error="Timeout after 30 seconds",
            )
        )
        conn.commit()

        result = conn.execute(
            select(link_analysis).where(link_analysis.c.id == link_id)
        ).fetchone()
        assert result.fetch_failed is True
        assert result.fetch_error == "Timeout after 30 seconds"


# ============================================================================
# Table 10: Topics
# ============================================================================


def test_insert_topic(engine, now) -> None:
    """Test inserting a topic."""
    with engine.connect() as conn:
        conn.execute(
            topics.insert().values(
                key="user:123456789",
                category="user",
                is_global=True,
                provisional=False,
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(topics).where(topics.c.key == "user:123456789")
        ).fetchone()
        assert result is not None
        assert result.category == "user"
        assert result.is_global is True


def test_topic_server_scoped(engine, now) -> None:
    """Test server-scoped topic."""
    with engine.connect() as conn:
        conn.execute(
            topics.insert().values(
                key="server:111:user:222",
                category="user",
                is_global=False,
                provisional=False,
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(topics).where(topics.c.key == "server:111:user:222")
        ).fetchone()
        assert result.is_global is False


def test_topic_provisional(engine, now) -> None:
    """Test provisional topic."""
    with engine.connect() as conn:
        conn.execute(
            topics.insert().values(
                key="server:111:subject:weather",
                category="subject",
                is_global=False,
                provisional=True,
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(topics).where(topics.c.key == "server:111:subject:weather")
        ).fetchone()
        assert result.provisional is True


def test_topic_with_metadata_and_activity(engine, now) -> None:
    """Test topic with metadata and activity tracking."""
    metadata_json = {"context": "important", "source": "observation"}
    activity_time = datetime.now(timezone.utc)
    with engine.connect() as conn:
        conn.execute(
            topics.insert().values(
                key="dyad:123:456",
                category="dyad",
                is_global=True,
                provisional=False,
                created_at=now,
                last_activity_at=activity_time,
                metadata=metadata_json,
            )
        )
        conn.commit()

        result = conn.execute(
            select(topics).where(topics.c.key == "dyad:123:456")
        ).fetchone()
        assert result.metadata == metadata_json
        # SQLite returns naive datetimes
        assert result.last_activity_at is not None


# ============================================================================
# Table 11: SalienceLedger
# ============================================================================


def test_insert_salience_entry(engine, setup_topic, now) -> None:
    """Test inserting a salience ledger entry."""
    with engine.connect() as conn:
        entry_id = generate_id()
        conn.execute(
            salience_ledger.insert().values(
                id=entry_id,
                topic_key=setup_topic,
                transaction_type="earn",
                amount=5.0,
                reason="message",
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(salience_ledger).where(salience_ledger.c.id == entry_id)
        ).fetchone()
        assert result is not None
        assert result.amount == 5.0
        assert result.transaction_type == "earn"


def test_salience_requires_topic(engine, now) -> None:
    """Test that salience requires valid topic FK."""
    with engine.connect() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(
                salience_ledger.insert().values(
                    id=generate_id(),
                    topic_key="nonexistent:topic",
                    transaction_type="earn",
                    amount=5.0,
                    created_at=now,
                )
            )
            conn.commit()


def test_salience_spend_transaction(engine, setup_topic, now) -> None:
    """Test negative spending transaction."""
    with engine.connect() as conn:
        entry_id = generate_id()
        conn.execute(
            salience_ledger.insert().values(
                id=entry_id,
                topic_key=setup_topic,
                transaction_type="spend",
                amount=-3.0,
                reason="insight_creation",
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(salience_ledger).where(salience_ledger.c.id == entry_id)
        ).fetchone()
        assert result.amount == -3.0
        assert result.transaction_type == "spend"


def test_salience_propagate_with_source(engine, setup_topic, now) -> None:
    """Test propagation transaction with source_topic."""
    with engine.connect() as conn:
        # Create source topic
        conn.execute(
            topics.insert().values(
                key="user:999",
                category="user",
                is_global=True,
                provisional=False,
                created_at=now,
            )
        )

        # Propagate from source
        entry_id = generate_id()
        conn.execute(
            salience_ledger.insert().values(
                id=entry_id,
                topic_key=setup_topic,
                transaction_type="propagate",
                amount=2.0,
                source_topic="user:999",
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(salience_ledger).where(salience_ledger.c.id == entry_id)
        ).fetchone()
        assert result.source_topic == "user:999"


# ============================================================================
# Table 12: Insights
# ============================================================================


def test_insert_insight_with_valence(engine, setup_topic, setup_layer_run, now) -> None:
    """Test that insight with valence succeeds."""
    with engine.connect() as conn:
        insight_id = generate_id()
        conn.execute(
            insights.insert().values(
                id=insight_id,
                topic_key=setup_topic,
                category="user_reflection",
                content="Test insight",
                sources_scope_max="public",
                created_at=now,
                layer_run_id=setup_layer_run,
                salience_spent=5.0,
                strength_adjustment=1.0,
                strength=5.0,
                original_topic_salience=10.0,
                confidence=0.8,
                importance=0.7,
                novelty=0.5,
                valence_curiosity=0.9,
            )
        )
        conn.commit()

        result = conn.execute(
            select(insights).where(insights.c.id == insight_id)
        ).fetchone()
        assert result is not None
        assert result.valence_curiosity == 0.9


def test_insert_insight_requires_valence(engine, setup_topic, setup_layer_run, now) -> None:
    """Test that insight requires at least one valence field."""
    with engine.connect() as conn:
        # Try to insert insight without any valence - should fail
        with pytest.raises(IntegrityError):
            conn.execute(
                insights.insert().values(
                    id=generate_id(),
                    topic_key=setup_topic,
                    category="user_reflection",
                    content="Test insight without valence",
                    sources_scope_max="public",
                    created_at=now,
                    layer_run_id=setup_layer_run,
                    salience_spent=5.0,
                    strength_adjustment=1.0,
                    strength=5.0,
                    original_topic_salience=10.0,
                    confidence=0.8,
                    importance=0.7,
                    novelty=0.5,
                    # No valence fields set
                )
            )
            conn.commit()


def test_insight_requires_topic(engine, setup_layer_run, now) -> None:
    """Test that insight requires valid topic FK."""
    with engine.connect() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(
                insights.insert().values(
                    id=generate_id(),
                    topic_key="nonexistent:topic",
                    category="user_reflection",
                    content="Test",
                    sources_scope_max="public",
                    created_at=now,
                    layer_run_id=setup_layer_run,
                    salience_spent=5.0,
                    strength_adjustment=1.0,
                    strength=5.0,
                    original_topic_salience=10.0,
                    confidence=0.8,
                    importance=0.7,
                    novelty=0.5,
                    valence_joy=0.5,
                )
            )
            conn.commit()


def test_insight_requires_layer_run(engine, setup_topic, now) -> None:
    """Test that insight requires valid layer_run FK."""
    with engine.connect() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(
                insights.insert().values(
                    id=generate_id(),
                    topic_key=setup_topic,
                    category="user_reflection",
                    content="Test",
                    sources_scope_max="public",
                    created_at=now,
                    layer_run_id="nonexistent_layer_run",
                    salience_spent=5.0,
                    strength_adjustment=1.0,
                    strength=5.0,
                    original_topic_salience=10.0,
                    confidence=0.8,
                    importance=0.7,
                    novelty=0.5,
                    valence_joy=0.5,
                )
            )
            conn.commit()


def test_insight_multiple_valences(engine, setup_topic, setup_layer_run, now) -> None:
    """Test insight with multiple valence fields."""
    with engine.connect() as conn:
        insight_id = generate_id()
        conn.execute(
            insights.insert().values(
                id=insight_id,
                topic_key=setup_topic,
                category="dyad_observation",
                content="Complex relationship dynamics",
                sources_scope_max="public",
                created_at=now,
                layer_run_id=setup_layer_run,
                salience_spent=8.0,
                strength_adjustment=1.5,
                strength=12.0,
                original_topic_salience=15.0,
                confidence=0.9,
                importance=0.85,
                novelty=0.6,
                valence_warmth=0.7,
                valence_tension=0.5,
                valence_concern=0.3,
            )
        )
        conn.commit()

        result = conn.execute(
            select(insights).where(insights.c.id == insight_id)
        ).fetchone()
        assert result.valence_warmth == 0.7
        assert result.valence_tension == 0.5
        assert result.valence_concern == 0.3


def test_insight_quarantine_and_supersede(
    engine, setup_topic, setup_layer_run, now
) -> None:
    """Test quarantine status and supersede references."""
    with engine.connect() as conn:
        # Create first insight
        first_id = generate_id()
        conn.execute(
            insights.insert().values(
                id=first_id,
                topic_key=setup_topic,
                category="user_reflection",
                content="Initial understanding",
                sources_scope_max="public",
                created_at=now,
                layer_run_id=setup_layer_run,
                salience_spent=5.0,
                strength_adjustment=1.0,
                strength=5.0,
                original_topic_salience=10.0,
                confidence=0.7,
                importance=0.6,
                novelty=0.4,
                valence_joy=0.6,
                quarantined=False,
            )
        )

        # Create updated insight
        second_id = generate_id()
        conn.execute(
            insights.insert().values(
                id=second_id,
                topic_key=setup_topic,
                category="user_reflection",
                content="Refined understanding",
                sources_scope_max="public",
                created_at=datetime.now(timezone.utc),
                layer_run_id=setup_layer_run,
                salience_spent=6.0,
                strength_adjustment=1.2,
                strength=7.2,
                original_topic_salience=12.0,
                confidence=0.85,
                importance=0.8,
                novelty=0.5,
                valence_joy=0.7,
                supersedes=first_id,
                quarantined=False,
            )
        )
        conn.commit()

        result = conn.execute(
            select(insights).where(insights.c.id == second_id)
        ).fetchone()
        assert result.supersedes == first_id
        assert result.quarantined is False


def test_insight_synthesis_and_conflict(
    engine, setup_topic, setup_layer_run, now
) -> None:
    """Test synthesis source tracking and conflict markers."""
    with engine.connect() as conn:
        # Create source insights
        source_ids = [generate_id(), generate_id()]
        for source_id in source_ids:
            conn.execute(
                insights.insert().values(
                    id=source_id,
                    topic_key=setup_topic,
                    category="user_reflection",
                    content="Source insight",
                    sources_scope_max="public",
                    created_at=now,
                    layer_run_id=setup_layer_run,
                    salience_spent=3.0,
                    strength_adjustment=1.0,
                    strength=3.0,
                    original_topic_salience=6.0,
                    confidence=0.6,
                    importance=0.5,
                    novelty=0.3,
                    valence_joy=0.5,
                )
            )

        # Create synthesis insight
        synthesis_id = generate_id()
        conn.execute(
            insights.insert().values(
                id=synthesis_id,
                topic_key=setup_topic,
                category="synthesis",
                content="Synthesized understanding",
                sources_scope_max="public",
                created_at=datetime.now(timezone.utc),
                layer_run_id=setup_layer_run,
                salience_spent=10.0,
                strength_adjustment=2.0,
                strength=20.0,
                original_topic_salience=25.0,
                confidence=0.9,
                importance=0.9,
                novelty=0.7,
                valence_joy=0.8,
                synthesis_source_ids=source_ids,
                conflicts_with=[],
                conflict_resolved=False,
            )
        )
        conn.commit()

        result = conn.execute(
            select(insights).where(insights.c.id == synthesis_id)
        ).fetchone()
        assert result.synthesis_source_ids == source_ids
        assert result.category == "synthesis"


def test_insight_context_and_participants(
    engine, setup_topic, setup_layer_run, now
) -> None:
    """Test context fields and participants JSON."""
    with engine.connect() as conn:
        insight_id = generate_id()
        participants = ["user:111", "user:222", "user:333"]
        conn.execute(
            insights.insert().values(
                id=insight_id,
                topic_key=setup_topic,
                category="dyad_observation",
                content="Interaction patterns",
                sources_scope_max="public",
                created_at=now,
                layer_run_id=setup_layer_run,
                salience_spent=5.0,
                strength_adjustment=1.0,
                strength=5.0,
                original_topic_salience=10.0,
                confidence=0.8,
                importance=0.7,
                novelty=0.5,
                valence_warmth=0.6,
                context_channel="server:999:channel:888",
                context_thread="server:999:thread:777",
                subject="server:999:subject:gaming",
                participants=participants,
            )
        )
        conn.commit()

        result = conn.execute(
            select(insights).where(insights.c.id == insight_id)
        ).fetchone()
        assert result.context_channel == "server:999:channel:888"
        assert result.context_thread == "server:999:thread:777"
        assert result.subject == "server:999:subject:gaming"
        assert result.participants == participants


# ============================================================================
# Table 13: LayerRuns
# ============================================================================


def test_insert_layer_run(engine, now) -> None:
    """Test inserting a layer run."""
    with engine.connect() as conn:
        layer_id = generate_id()
        conn.execute(
            layer_runs.insert().values(
                id=layer_id,
                layer_name="user_reflection",
                layer_hash="hash123",
                started_at=now,
                status="success",
            )
        )
        conn.commit()

        result = conn.execute(
            select(layer_runs).where(layer_runs.c.id == layer_id)
        ).fetchone()
        assert result is not None
        assert result.layer_name == "user_reflection"
        assert result.status == "success"


def test_layer_run_with_model_info(engine, now) -> None:
    """Test layer run with model information."""
    with engine.connect() as conn:
        layer_id = generate_id()
        conn.execute(
            layer_runs.insert().values(
                id=layer_id,
                layer_name="synthesis",
                layer_hash="hash456",
                started_at=now,
                completed_at=datetime.now(timezone.utc),
                status="success",
                targets_matched=10,
                targets_processed=9,
                targets_skipped=1,
                insights_created=3,
                model_profile="complex",
                model_provider="anthropic",
                model_name="claude-opus-4-20250515",
                tokens_input=5000,
                tokens_output=2000,
                tokens_total=7000,
                estimated_cost_usd=0.15,
            )
        )
        conn.commit()

        result = conn.execute(
            select(layer_runs).where(layer_runs.c.id == layer_id)
        ).fetchone()
        assert result.model_profile == "complex"
        assert result.tokens_total == 7000


def test_layer_run_with_errors(engine, now) -> None:
    """Test layer run with error tracking."""
    with engine.connect() as conn:
        layer_id = generate_id()
        errors = [
            {"topic": "user:999", "error": "Invalid topic format"},
            {"topic": "user:888", "error": "Insufficient salience"},
        ]
        conn.execute(
            layer_runs.insert().values(
                id=layer_id,
                layer_name="reflection",
                layer_hash="hash789",
                started_at=now,
                status="partial",
                targets_matched=10,
                targets_processed=8,
                targets_skipped=2,
                insights_created=5,
                errors=errors,
            )
        )
        conn.commit()

        result = conn.execute(
            select(layer_runs).where(layer_runs.c.id == layer_id)
        ).fetchone()
        assert result.status == "partial"
        assert len(result.errors) == 2


# ============================================================================
# Table 14: LLMCalls
# ============================================================================


def test_insert_llm_call(engine, setup_layer_run, now) -> None:
    """Test inserting an LLM call record."""
    with engine.connect() as conn:
        call_id = generate_id()
        conn.execute(
            llm_calls.insert().values(
                id=call_id,
                layer_run_id=setup_layer_run,
                call_type="reflection",
                model_profile="complex",
                model_provider="anthropic",
                model_name="claude-opus-4-20250515",
                prompt="Analyze this user's patterns...",
                response="Based on the data, I observe...",
                tokens_input=1000,
                tokens_output=500,
                tokens_total=1500,
                estimated_cost_usd=0.03,
                latency_ms=2500,
                success=True,
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(llm_calls).where(llm_calls.c.id == call_id)
        ).fetchone()
        assert result is not None
        assert result.call_type == "reflection"
        assert result.success is True


def test_llm_call_without_layer_run(engine, now) -> None:
    """Test LLM call without layer_run (conversation call)."""
    with engine.connect() as conn:
        call_id = generate_id()
        conn.execute(
            llm_calls.insert().values(
                id=call_id,
                layer_run_id=None,
                call_type="conversation",
                model_profile="moderate",
                model_provider="anthropic",
                model_name="claude-sonnet-4-20250514",
                prompt="User: Hello!",
                response="Zos: Hi there!",
                tokens_input=50,
                tokens_output=30,
                tokens_total=80,
                estimated_cost_usd=0.001,
                success=True,
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(llm_calls).where(llm_calls.c.id == call_id)
        ).fetchone()
        assert result.layer_run_id is None


def test_llm_call_failure(engine, now) -> None:
    """Test LLM call with failure."""
    with engine.connect() as conn:
        call_id = generate_id()
        conn.execute(
            llm_calls.insert().values(
                id=call_id,
                layer_run_id=None,
                call_type="vision",
                model_profile="simple",
                model_provider="openai",
                model_name="gpt-4-vision",
                prompt="Analyze image...",
                response="",
                tokens_input=500,
                tokens_output=0,
                tokens_total=500,
                estimated_cost_usd=0.01,
                success=False,
                error_message="API rate limit exceeded",
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(llm_calls).where(llm_calls.c.id == call_id)
        ).fetchone()
        assert result.success is False
        assert result.error_message == "API rate limit exceeded"


# ============================================================================
# Table 15: ChattinessLedger
# ============================================================================


def test_insert_chattiness_entry(engine, setup_channel, setup_topic, now) -> None:
    """Test inserting chattiness ledger entry."""
    with engine.connect() as conn:
        entry_id = generate_id()
        conn.execute(
            chattiness_ledger.insert().values(
                id=entry_id,
                pool="address",
                channel_id=setup_channel,
                topic_key=setup_topic,
                transaction_type="earn",
                amount=10.0,
                trigger="message",
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(chattiness_ledger).where(chattiness_ledger.c.id == entry_id)
        ).fetchone()
        assert result is not None
        assert result.pool == "address"
        assert result.amount == 10.0


def test_chattiness_pool_channel_level(engine, setup_channel, now) -> None:
    """Test chattiness at pool-channel level (no topic)."""
    with engine.connect() as conn:
        entry_id = generate_id()
        conn.execute(
            chattiness_ledger.insert().values(
                id=entry_id,
                pool="presence",
                channel_id=setup_channel,
                topic_key=None,
                transaction_type="spend",
                amount=-5.0,
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(chattiness_ledger).where(chattiness_ledger.c.id == entry_id)
        ).fetchone()
        assert result.topic_key is None


def test_chattiness_global_pool_level(engine, now) -> None:
    """Test chattiness at global pool level (no channel or topic)."""
    with engine.connect() as conn:
        entry_id = generate_id()
        conn.execute(
            chattiness_ledger.insert().values(
                id=entry_id,
                pool="insight",
                channel_id=None,
                topic_key=None,
                transaction_type="decay",
                amount=-2.0,
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(chattiness_ledger).where(chattiness_ledger.c.id == entry_id)
        ).fetchone()
        assert result.channel_id is None
        assert result.topic_key is None


def test_chattiness_flood_transaction(engine, setup_channel, now) -> None:
    """Test flood transaction (high impulse event)."""
    with engine.connect() as conn:
        entry_id = generate_id()
        conn.execute(
            chattiness_ledger.insert().values(
                id=entry_id,
                pool="address",
                channel_id=setup_channel,
                transaction_type="flood",
                amount=50.0,
                trigger="direct_mention",
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(chattiness_ledger).where(chattiness_ledger.c.id == entry_id)
        ).fetchone()
        assert result.transaction_type == "flood"


# ============================================================================
# Table 16: SpeechPressure
# ============================================================================


def test_insert_speech_pressure(engine, setup_server, now) -> None:
    """Test inserting speech pressure."""
    with engine.connect() as conn:
        pressure_id = generate_id()
        conn.execute(
            speech_pressure.insert().values(
                id=pressure_id,
                amount=10.0,
                trigger="response_generation",
                server_id=setup_server,
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(speech_pressure).where(speech_pressure.c.id == pressure_id)
        ).fetchone()
        assert result is not None
        assert result.amount == 10.0


def test_speech_pressure_global(engine, now) -> None:
    """Test global speech pressure (no server)."""
    with engine.connect() as conn:
        pressure_id = generate_id()
        conn.execute(
            speech_pressure.insert().values(
                id=pressure_id,
                amount=5.0,
                trigger="dm_response",
                server_id=None,
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(speech_pressure).where(speech_pressure.c.id == pressure_id)
        ).fetchone()
        assert result.server_id is None


# ============================================================================
# Table 17: ConversationLog
# ============================================================================


def test_insert_conversation_log(engine, setup_channel, now) -> None:
    """Test inserting conversation log."""
    with engine.connect() as conn:
        log_id = generate_id()
        conn.execute(
            conversation_log.insert().values(
                id=log_id,
                message_id="zos_msg_123",
                channel_id=setup_channel,
                server_id="server1",
                content="I thought about that too...",
                layer_name="conversation",
                trigger_type="impulse",
                impulse_pool="address",
                impulse_spent=15.0,
                priority_flagged=False,
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(conversation_log).where(conversation_log.c.id == log_id)
        ).fetchone()
        assert result is not None
        assert result.impulse_spent == 15.0


def test_conversation_log_priority_flagged(engine, setup_channel, now) -> None:
    """Test conversation log with priority flag."""
    with engine.connect() as conn:
        log_id = generate_id()
        conn.execute(
            conversation_log.insert().values(
                id=log_id,
                message_id="zos_msg_456",
                channel_id=setup_channel,
                server_id=None,
                content="Important reflection needed",
                layer_name="self_reflection",
                trigger_type="conflict_detected",
                impulse_pool="conversational",
                impulse_spent=25.0,
                priority_flagged=True,
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(conversation_log).where(conversation_log.c.id == log_id)
        ).fetchone()
        assert result.priority_flagged is True


# ============================================================================
# Table 18: DraftHistory
# ============================================================================


def test_insert_draft_history(engine, setup_channel, now) -> None:
    """Test inserting draft history."""
    with engine.connect() as conn:
        draft_id = generate_id()
        conn.execute(
            draft_history.insert().values(
                id=draft_id,
                channel_id=setup_channel,
                thread_id=None,
                content="First draft response...",
                layer_name="conversation",
                discard_reason=None,
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(draft_history).where(draft_history.c.id == draft_id)
        ).fetchone()
        assert result is not None


def test_draft_with_thread_context(engine, setup_channel, now) -> None:
    """Test draft with thread context."""
    with engine.connect() as conn:
        draft_id = generate_id()
        conn.execute(
            draft_history.insert().values(
                id=draft_id,
                channel_id=setup_channel,
                thread_id="thread_456",
                content="Discarded response",
                layer_name="conversation",
                discard_reason="self_censored - too direct",
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(draft_history).where(draft_history.c.id == draft_id)
        ).fetchone()
        assert result.thread_id == "thread_456"
        assert result.discard_reason == "self_censored - too direct"


# ============================================================================
# Index Tests
# ============================================================================


def test_indexes_exist(engine) -> None:
    """Test that all important indexes are created."""
    inspector = inspect(engine)

    # Messages indexes
    message_indexes = {idx["name"] for idx in inspector.get_indexes("messages")}
    assert "ix_messages_channel_created" in message_indexes
    assert "ix_messages_author_created" in message_indexes
    assert "ix_messages_server_created" in message_indexes

    # Insights indexes
    insight_indexes = {idx["name"] for idx in inspector.get_indexes("insights")}
    assert "ix_insights_topic_created" in insight_indexes
    assert "ix_insights_quarantined" in insight_indexes
    assert "ix_insights_layer_run" in insight_indexes

    # Layer run indexes
    layer_run_indexes = {idx["name"] for idx in inspector.get_indexes("layer_runs")}
    assert "ix_layer_runs_name_started" in layer_run_indexes
    assert "ix_layer_runs_status" in layer_run_indexes

    # Salience indexes
    salience_indexes = {idx["name"] for idx in inspector.get_indexes("salience_ledger")}
    assert "ix_salience_ledger_topic_created" in salience_indexes

    # Reaction indexes
    reaction_indexes = {idx["name"] for idx in inspector.get_indexes("reactions")}
    assert "ix_reactions_message" in reaction_indexes
    assert "ix_reactions_emoji_server" in reaction_indexes

    # LLM call indexes
    llm_indexes = {idx["name"] for idx in inspector.get_indexes("llm_calls")}
    assert "ix_llm_calls_layer_run" in llm_indexes
    assert "ix_llm_calls_created" in llm_indexes

    # Chattiness indexes
    chattiness_indexes = {idx["name"] for idx in inspector.get_indexes("chattiness_ledger")}
    assert "ix_chattiness_ledger_pool_channel_created" in chattiness_indexes
    assert "ix_chattiness_ledger_pool_topic_created" in chattiness_indexes


# ============================================================================
# Edge Cases & NULL Handling
# ============================================================================


def test_message_empty_content_allowed(engine, setup_channel, setup_server, now) -> None:
    """Test that empty message content is allowed (valid use case)."""
    with engine.connect() as conn:
        # Empty content is technically valid (e.g., message with just media)
        conn.execute(
            messages.insert().values(
                id="empty_msg",
                channel_id=setup_channel,
                server_id=setup_server,
                author_id="author1",
                content="",  # Empty but allowed
                created_at=now,
                visibility_scope="public",
                has_media=True,  # Has media instead
                has_links=False,
                ingested_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(messages).where(messages.c.id == "empty_msg")
        ).fetchone()
        assert result.content == ""


def test_insight_null_optional_fields(engine, setup_topic, setup_layer_run, now) -> None:
    """Test insight with many optional fields as NULL."""
    with engine.connect() as conn:
        insight_id = generate_id()
        conn.execute(
            insights.insert().values(
                id=insight_id,
                topic_key=setup_topic,
                category="self_reflection",
                content="Simple insight",
                sources_scope_max="derived",
                created_at=now,
                layer_run_id=setup_layer_run,
                salience_spent=1.0,
                strength_adjustment=1.0,
                strength=1.0,
                original_topic_salience=2.0,
                confidence=0.5,
                importance=0.5,
                novelty=0.5,
                valence_joy=0.5,
                # Optional fields left NULL
                supersedes=None,
                context_channel=None,
                context_thread=None,
                subject=None,
                participants=None,
                conflicts_with=None,
                conflict_resolved=None,
                synthesis_source_ids=None,
            )
        )
        conn.commit()

        result = conn.execute(
            select(insights).where(insights.c.id == insight_id)
        ).fetchone()
        assert result.supersedes is None
        assert result.participants is None


def test_topic_metadata_null_vs_empty(engine, now) -> None:
    """Test topic with NULL vs empty metadata."""
    with engine.connect() as conn:
        # NULL metadata
        conn.execute(
            topics.insert().values(
                key="null_meta_topic",
                category="subject",
                is_global=False,
                provisional=False,
                created_at=now,
                metadata=None,
            )
        )

        # Empty dict metadata
        conn.execute(
            topics.insert().values(
                key="empty_meta_topic",
                category="subject",
                is_global=False,
                provisional=False,
                created_at=now,
                metadata={},
            )
        )
        conn.commit()

        result_null = conn.execute(
            select(topics).where(topics.c.key == "null_meta_topic")
        ).fetchone()
        result_empty = conn.execute(
            select(topics).where(topics.c.key == "empty_meta_topic")
        ).fetchone()

        assert result_null.metadata is None
        assert result_empty.metadata == {}


def test_llm_call_optional_cost_field(engine, now) -> None:
    """Test LLM call with NULL estimated cost."""
    with engine.connect() as conn:
        call_id = generate_id()
        conn.execute(
            llm_calls.insert().values(
                id=call_id,
                layer_run_id=None,
                call_type="other",
                model_profile="simple",
                model_provider="ollama",
                model_name="mistral",
                prompt="Test",
                response="Response",
                tokens_input=100,
                tokens_output=50,
                tokens_total=150,
                estimated_cost_usd=None,  # Local model, no cost
                success=True,
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(llm_calls).where(llm_calls.c.id == call_id)
        ).fetchone()
        assert result.estimated_cost_usd is None


# ============================================================================
# Data Type Tests
# ============================================================================


def test_float_precision_salience(engine, setup_topic, now) -> None:
    """Test float precision in salience amounts."""
    with engine.connect() as conn:
        entry_id = generate_id()
        precise_amount = 3.14159265
        conn.execute(
            salience_ledger.insert().values(
                id=entry_id,
                topic_key=setup_topic,
                transaction_type="earn",
                amount=precise_amount,
                created_at=now,
            )
        )
        conn.commit()

        result = conn.execute(
            select(salience_ledger).where(salience_ledger.c.id == entry_id)
        ).fetchone()
        # Float comparison - should be very close
        assert abs(result.amount - precise_amount) < 0.00001


def test_integer_fields_layer_run(engine, now) -> None:
    """Test integer field constraints in layer run."""
    with engine.connect() as conn:
        layer_id = generate_id()
        conn.execute(
            layer_runs.insert().values(
                id=layer_id,
                layer_name="test",
                layer_hash="hash",
                started_at=now,
                status="success",
                targets_matched=0,  # Can be zero
                targets_processed=0,
                targets_skipped=0,
                insights_created=0,
            )
        )
        conn.commit()

        result = conn.execute(
            select(layer_runs).where(layer_runs.c.id == layer_id)
        ).fetchone()
        assert result.targets_matched == 0


# ============================================================================
# Cross-Table Relationship Tests
# ============================================================================


def test_cascade_integrity_channels_require_server(engine, now) -> None:
    """Test that channels properly reference servers."""
    with engine.connect() as conn:
        # Create a server
        server_id = "server_with_channels"
        conn.execute(
            servers.insert().values(
                id=server_id,
                threads_as_topics=True,
                created_at=now,
            )
        )

        # Add multiple channels
        for i in range(3):
            conn.execute(
                channels.insert().values(
                    id=f"channel_{i}",
                    server_id=server_id,
                    type="text",
                    created_at=now,
                )
            )

        conn.commit()

        # Verify all channels reference correct server
        results = conn.execute(
            select(channels).where(channels.c.server_id == server_id)
        ).fetchall()
        assert len(results) == 3


def test_message_topic_audit_trail(engine, setup_message, setup_topic, now) -> None:
    """Test tracing a message to topics to insights."""
    with engine.connect() as conn:
        # Create an insight about the topic
        layer_id = generate_id()
        conn.execute(
            layer_runs.insert().values(
                id=layer_id,
                layer_name="message_analysis",
                layer_hash="hash",
                started_at=now,
                status="success",
            )
        )

        insight_id = generate_id()
        conn.execute(
            insights.insert().values(
                id=insight_id,
                topic_key=setup_topic,
                category="user_reflection",
                content="Insight about the topic",
                sources_scope_max="public",
                created_at=now,
                layer_run_id=layer_id,
                salience_spent=3.0,
                strength_adjustment=1.0,
                strength=3.0,
                original_topic_salience=6.0,
                confidence=0.7,
                importance=0.6,
                novelty=0.4,
                valence_joy=0.5,
            )
        )
        conn.commit()

        # Verify the chain
        msg = conn.execute(
            select(messages).where(messages.c.id == setup_message)
        ).fetchone()
        topic = conn.execute(
            select(topics).where(topics.c.key == setup_topic)
        ).fetchone()
        insight = conn.execute(
            select(insights).where(insights.c.id == insight_id)
        ).fetchone()

        assert msg is not None
        assert topic is not None
        assert insight is not None
        assert insight.topic_key == setup_topic
