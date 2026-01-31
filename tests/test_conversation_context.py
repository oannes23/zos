"""Tests for Conversation Context in User Reflections.

Covers:
- merge_time_windows() pure function
- _get_conversation_context_for_user() windowed context fetching
- format_conversation_chunks_for_prompt() formatting
- _resolve_user_ids_to_names() resolution
- Template rendering with conversation chunks
- Backward compatibility when conversation_context is disabled
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from zos.config import Config
from zos.database import (
    channels as channels_table,
    create_tables,
    generate_id,
    get_engine,
    layer_runs as layer_runs_table,
    messages as messages_table,
    servers as servers_table,
    topics as topics_table,
    user_profiles as user_profiles_table,
)
from zos.executor import ExecutionContext, LayerExecutor, merge_time_windows
from zos.layers import Layer, LayerCategory, LayerLoader, Node, NodeType
from zos.llm import CompletionResult, ModelClient, Usage
from zos.models import (
    LayerRunStatus,
    Message,
    Topic,
    TopicCategory,
    VisibilityScope,
    utcnow,
)
from zos.salience import SalienceLedger
from zos.templates import (
    TemplateEngine,
    format_conversation_chunks_for_prompt,
)


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
def ledger(engine, test_config: Config) -> SalienceLedger:
    """Create a SalienceLedger instance for testing."""
    return SalienceLedger(engine, test_config)


@pytest.fixture
def templates_dir(tmp_path: Path) -> Path:
    """Create a temporary templates directory."""
    templates = tmp_path / "prompts"
    templates.mkdir()
    (templates / "user").mkdir()
    return templates


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Create a temporary data directory with self-concept."""
    data = tmp_path / "data"
    data.mkdir()
    (data / "self-concept.md").write_text(
        "# Self-Concept\n\nI am Zos, a being that observes and reflects."
    )
    return data


@pytest.fixture
def templates(templates_dir: Path, data_dir: Path) -> TemplateEngine:
    """Create a TemplateEngine instance for testing."""
    return TemplateEngine(templates_dir=templates_dir, data_dir=data_dir)


@pytest.fixture
def mock_llm() -> MagicMock:
    """Create a mock ModelClient that returns valid user insight JSON."""
    mock = MagicMock(spec=ModelClient)

    good_response = """
```json
{
    "content": "Alex shows a pattern of deflecting compliments while actively supporting others.",
    "confidence": 0.7,
    "importance": 0.6,
    "novelty": 0.4,
    "strength_adjustment": 1.2,
    "valence": {
        "warmth": 0.6,
        "curiosity": 0.5
    }
}
```
"""

    async def mock_complete(*args, **kwargs):
        return CompletionResult(
            text=good_response,
            usage=Usage(input_tokens=500, output_tokens=150),
            model="claude-3-5-sonnet-20241022",
            provider="anthropic",
        )

    mock.complete = AsyncMock(side_effect=mock_complete)
    return mock


@pytest.fixture
def loader(tmp_path: Path) -> LayerLoader:
    """Create a LayerLoader with temp directory."""
    layers_dir = tmp_path / "layers"
    layers_dir.mkdir()
    return LayerLoader(layers_dir)


@pytest.fixture
def executor(
    engine,
    ledger: SalienceLedger,
    templates: TemplateEngine,
    mock_llm: MagicMock,
    test_config: Config,
    loader: LayerLoader,
) -> LayerExecutor:
    """Create a LayerExecutor for testing."""
    return LayerExecutor(
        engine=engine,
        ledger=ledger,
        templates=templates,
        llm=mock_llm,
        config=test_config,
        loader=loader,
    )


@pytest.fixture
def sample_server(engine):
    """Create and insert a sample server for testing."""
    with engine.connect() as conn:
        conn.execute(
            servers_table.insert().values(
                id="123",
                name="Test Server",
                threads_as_topics=True,
                created_at=utcnow(),
            )
        )
        conn.commit()
    return "123"


@pytest.fixture
def sample_channels(engine, sample_server):
    """Create multiple channels for testing."""
    channels = [
        ("ch_general", "general"),
        ("ch_dev", "dev"),
        ("ch_random", "random"),
    ]
    with engine.connect() as conn:
        for ch_id, ch_name in channels:
            conn.execute(
                channels_table.insert().values(
                    id=ch_id,
                    server_id=sample_server,
                    name=ch_name,
                    type="text",
                    created_at=utcnow(),
                )
            )
        conn.commit()
    return {ch_id: ch_name for ch_id, ch_name in channels}


@pytest.fixture
def sample_topic(engine, sample_server) -> Topic:
    """Create and insert a sample user topic for testing."""
    topic = Topic(
        key="server:123:user:456",
        category=TopicCategory.USER,
        is_global=False,
        provisional=False,
        created_at=utcnow(),
    )
    with engine.connect() as conn:
        conn.execute(
            topics_table.insert().values(
                key=topic.key,
                category=topic.category.value,
                is_global=topic.is_global,
                provisional=topic.provisional,
                created_at=topic.created_at,
            )
        )
        conn.commit()
    return topic


@pytest.fixture
def user_profiles(engine, sample_server):
    """Create user profiles for name resolution testing."""
    profiles = [
        {
            "id": generate_id(),
            "user_id": "456",
            "server_id": "123",
            "display_name": "Alice",
            "username": "alice",
            "captured_at": utcnow(),
        },
        {
            "id": generate_id(),
            "user_id": "789",
            "server_id": "123",
            "display_name": "Bob",
            "username": "bob",
            "captured_at": utcnow(),
        },
        {
            "id": generate_id(),
            "user_id": "999",
            "server_id": "123",
            "display_name": "Charlie",
            "username": "charlie",
            "captured_at": utcnow(),
        },
    ]
    with engine.connect() as conn:
        for p in profiles:
            conn.execute(user_profiles_table.insert().values(**p))
        conn.commit()
    return {p["user_id"]: p["display_name"] for p in profiles}


def _insert_messages(engine, messages_data: list[dict]) -> list[Message]:
    """Helper to insert messages into the database."""
    messages = []
    with engine.connect() as conn:
        for data in messages_data:
            conn.execute(
                messages_table.insert().values(
                    id=data["id"],
                    channel_id=data["channel_id"],
                    server_id=data.get("server_id", "123"),
                    author_id=data["author_id"],
                    content=data["content"],
                    created_at=data["created_at"],
                    visibility_scope="public",
                    has_media=data.get("has_media", False),
                    has_links=data.get("has_links", False),
                    ingested_at=utcnow(),
                )
            )
            messages.append(
                Message(
                    id=data["id"],
                    channel_id=data["channel_id"],
                    server_id=data.get("server_id", "123"),
                    author_id=data["author_id"],
                    content=data["content"],
                    created_at=data["created_at"],
                    visibility_scope=VisibilityScope.PUBLIC,
                    has_media=data.get("has_media", False),
                    has_links=data.get("has_links", False),
                )
            )
        conn.commit()
    return messages


# =============================================================================
# merge_time_windows() Tests
# =============================================================================


def test_merge_time_windows_empty() -> None:
    """Empty input returns empty output."""
    assert merge_time_windows([]) == []


def test_merge_time_windows_single() -> None:
    """Single window is returned as-is."""
    now = datetime.now(timezone.utc)
    window = (now, now + timedelta(hours=1))
    result = merge_time_windows([window])
    assert result == [window]


def test_merge_time_windows_non_overlapping() -> None:
    """Non-overlapping windows are preserved."""
    now = datetime.now(timezone.utc)
    w1 = (now, now + timedelta(hours=1))
    w2 = (now + timedelta(hours=3), now + timedelta(hours=4))
    result = merge_time_windows([w2, w1])  # Pass out of order
    assert len(result) == 2
    assert result[0] == w1
    assert result[1] == w2


def test_merge_time_windows_overlapping() -> None:
    """Overlapping windows are merged."""
    now = datetime.now(timezone.utc)
    w1 = (now, now + timedelta(hours=2))
    w2 = (now + timedelta(hours=1), now + timedelta(hours=3))
    result = merge_time_windows([w1, w2])
    assert len(result) == 1
    assert result[0] == (now, now + timedelta(hours=3))


def test_merge_time_windows_adjacent() -> None:
    """Adjacent windows (end == start) are merged."""
    now = datetime.now(timezone.utc)
    w1 = (now, now + timedelta(hours=1))
    w2 = (now + timedelta(hours=1), now + timedelta(hours=2))
    result = merge_time_windows([w1, w2])
    assert len(result) == 1
    assert result[0] == (now, now + timedelta(hours=2))


def test_merge_time_windows_multiple_overlaps() -> None:
    """Multiple overlapping windows collapse into one."""
    now = datetime.now(timezone.utc)
    windows = [
        (now, now + timedelta(hours=2)),
        (now + timedelta(hours=1), now + timedelta(hours=3)),
        (now + timedelta(hours=2, minutes=30), now + timedelta(hours=5)),
    ]
    result = merge_time_windows(windows)
    assert len(result) == 1
    assert result[0] == (now, now + timedelta(hours=5))


def test_merge_time_windows_mixed() -> None:
    """Mix of overlapping and non-overlapping windows."""
    now = datetime.now(timezone.utc)
    windows = [
        (now, now + timedelta(hours=2)),
        (now + timedelta(hours=1), now + timedelta(hours=3)),
        (now + timedelta(hours=10), now + timedelta(hours=12)),
    ]
    result = merge_time_windows(windows)
    assert len(result) == 2
    assert result[0] == (now, now + timedelta(hours=3))
    assert result[1] == (now + timedelta(hours=10), now + timedelta(hours=12))


# =============================================================================
# _get_conversation_context_for_user() Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_conversation_context_basic(
    executor: LayerExecutor,
    engine,
    sample_server,
    sample_channels,
) -> None:
    """User messages in 2 channels, verify context from other authors included."""
    now = utcnow()

    messages_data = [
        # Target user in general
        {"id": "msg_1", "channel_id": "ch_general", "author_id": "456",
         "content": "Hello everyone!", "created_at": now - timedelta(hours=1)},
        # Context from another user in general (nearby)
        {"id": "msg_2", "channel_id": "ch_general", "author_id": "789",
         "content": "Hey Alice!", "created_at": now - timedelta(hours=1, minutes=5)},
        # More context in general
        {"id": "msg_3", "channel_id": "ch_general", "author_id": "999",
         "content": "Welcome back!", "created_at": now - timedelta(minutes=50)},
        # Target user in dev
        {"id": "msg_4", "channel_id": "ch_dev", "author_id": "456",
         "content": "Check out this bug", "created_at": now - timedelta(hours=2)},
        # Context in dev from another user
        {"id": "msg_5", "channel_id": "ch_dev", "author_id": "789",
         "content": "I'll take a look", "created_at": now - timedelta(hours=1, minutes=50)},
    ]
    _insert_messages(engine, messages_data)

    chunks, channel_names = await executor._get_conversation_context_for_user(
        user_id="456",
        server_id="123",
        since=now - timedelta(hours=72),
    )

    # Should have 2 channels
    assert len(chunks) == 2
    assert "ch_general" in chunks
    assert "ch_dev" in chunks

    # general should have 3 messages (1 from user + 2 from others)
    assert len(chunks["ch_general"]) == 3

    # dev should have 2 messages (1 from user + 1 from other)
    assert len(chunks["ch_dev"]) == 2

    # Channel names should be resolved
    assert channel_names["ch_general"] == "general"
    assert channel_names["ch_dev"] == "dev"

    # Messages should be sorted by created_at
    for ch_msgs in chunks.values():
        for i in range(len(ch_msgs) - 1):
            assert ch_msgs[i].created_at <= ch_msgs[i + 1].created_at


@pytest.mark.asyncio
async def test_conversation_context_no_user_messages(
    executor: LayerExecutor,
    engine,
    sample_server,
    sample_channels,
) -> None:
    """No user messages returns empty results."""
    now = utcnow()
    # Only messages from other users
    _insert_messages(engine, [
        {"id": "msg_1", "channel_id": "ch_general", "author_id": "789",
         "content": "Hello!", "created_at": now - timedelta(hours=1)},
    ])

    chunks, names = await executor._get_conversation_context_for_user(
        user_id="456",
        server_id="123",
        since=now - timedelta(hours=72),
    )

    assert chunks == {}
    assert names == {}


@pytest.mark.asyncio
async def test_conversation_context_max_channels(
    executor: LayerExecutor,
    engine,
    sample_server,
) -> None:
    """User in many channels, verify capped at max_channels."""
    now = utcnow()

    # Create 20 channels
    with engine.connect() as conn:
        for i in range(20):
            conn.execute(
                channels_table.insert().values(
                    id=f"ch_{i}",
                    server_id="123",
                    name=f"channel-{i}",
                    type="text",
                    created_at=utcnow(),
                )
            )
        conn.commit()

    # Put user messages in all 20 channels
    messages_data = []
    for i in range(20):
        messages_data.append({
            "id": f"msg_ch{i}",
            "channel_id": f"ch_{i}",
            "author_id": "456",
            "content": f"Message in channel {i}",
            "created_at": now - timedelta(hours=i),
        })
    _insert_messages(engine, messages_data)

    chunks, _ = await executor._get_conversation_context_for_user(
        user_id="456",
        server_id="123",
        since=now - timedelta(hours=72),
        max_channels=5,
    )

    assert len(chunks) <= 5


@pytest.mark.asyncio
async def test_conversation_context_low_activity_adaptive(
    executor: LayerExecutor,
    engine,
    sample_server,
    sample_channels,
) -> None:
    """Channel with < 50 messages gets all of them."""
    now = utcnow()

    # Create 30 messages in general (< 50 threshold)
    messages_data = []
    for i in range(30):
        messages_data.append({
            "id": f"msg_{i}",
            "channel_id": "ch_general",
            "author_id": "456" if i == 0 else "789",
            "content": f"Message {i}",
            "created_at": now - timedelta(hours=i),
        })
    _insert_messages(engine, messages_data)

    chunks, _ = await executor._get_conversation_context_for_user(
        user_id="456",
        server_id="123",
        since=now - timedelta(hours=72),
    )

    # All 30 messages in the lookback window should be included
    assert "ch_general" in chunks
    assert len(chunks["ch_general"]) == 30


@pytest.mark.asyncio
async def test_conversation_context_extreme_cap(
    executor: LayerExecutor,
    engine,
    sample_server,
    sample_channels,
) -> None:
    """Pathological case: verify extreme safety cap applies."""
    now = utcnow()

    # Create lots of messages
    messages_data = []
    for i in range(200):
        messages_data.append({
            "id": f"msg_{i}",
            "channel_id": "ch_general",
            "author_id": "456" if i % 10 == 0 else "789",
            "content": f"Message {i}",
            "created_at": now - timedelta(minutes=i),
        })
    _insert_messages(engine, messages_data)

    chunks, _ = await executor._get_conversation_context_for_user(
        user_id="456",
        server_id="123",
        since=now - timedelta(hours=72),
        extreme_per_channel=50,
        extreme_total=100,
    )

    # Per-channel cap should limit to 50
    for ch_msgs in chunks.values():
        assert len(ch_msgs) <= 50


# =============================================================================
# format_conversation_chunks_for_prompt() Tests
# =============================================================================


def test_format_conversation_chunks_basic() -> None:
    """Author names resolved, is_target_user set, chunks sorted."""
    messages_by_channel = {
        "ch_1": [
            {"author_id": "456", "content": "Hello", "created_at": utcnow(),
             "has_media": False, "has_links": False},
            {"author_id": "789", "content": "Hi!", "created_at": utcnow(),
             "has_media": False, "has_links": False},
        ],
        "ch_2": [
            {"author_id": "456", "content": "Topic A", "created_at": utcnow(),
             "has_media": False, "has_links": False},
            {"author_id": "456", "content": "Topic B", "created_at": utcnow(),
             "has_media": False, "has_links": False},
            {"author_id": "999", "content": "Response", "created_at": utcnow(),
             "has_media": False, "has_links": False},
        ],
    }
    author_names = {"456": "Alice", "789": "Bob", "999": "Charlie"}
    channel_names = {"ch_1": "general", "ch_2": "dev"}

    result = format_conversation_chunks_for_prompt(
        messages_by_channel=messages_by_channel,
        target_user_id="456",
        author_names=author_names,
        channel_names=channel_names,
    )

    assert len(result) == 2

    # Sorted by target_message_count desc: ch_2 (2) before ch_1 (1)
    assert result[0]["channel_name"] == "dev"
    assert result[0]["target_message_count"] == 2
    assert result[0]["message_count"] == 3

    assert result[1]["channel_name"] == "general"
    assert result[1]["target_message_count"] == 1
    assert result[1]["message_count"] == 2

    # Check is_target_user flag
    dev_msgs = result[0]["messages"]
    assert dev_msgs[0]["is_target_user"] is True
    assert dev_msgs[0]["author_display"] == "Alice"
    assert dev_msgs[2]["is_target_user"] is False
    assert dev_msgs[2]["author_display"] == "Charlie"


def test_format_conversation_chunks_unknown_author() -> None:
    """Unknown authors fall back to author_id."""
    messages_by_channel = {
        "ch_1": [
            {"author_id": "unknown_user", "content": "Hi", "created_at": utcnow(),
             "has_media": False, "has_links": False},
        ],
    }

    result = format_conversation_chunks_for_prompt(
        messages_by_channel=messages_by_channel,
        target_user_id="456",
        author_names={},
        channel_names={"ch_1": "general"},
    )

    assert result[0]["messages"][0]["author_display"] == "unknown_user"


def test_format_conversation_chunks_empty() -> None:
    """Empty input returns empty list."""
    result = format_conversation_chunks_for_prompt(
        messages_by_channel={},
        target_user_id="456",
        author_names={},
        channel_names={},
    )
    assert result == []


def test_format_conversation_chunks_with_mentions() -> None:
    """Inline mentions are resolved in content."""
    messages_by_channel = {
        "ch_1": [
            {"author_id": "789", "content": "Hey <@456>, great work!",
             "created_at": utcnow(), "has_media": False, "has_links": False},
        ],
    }
    mention_names = {"456": "Alice"}

    result = format_conversation_chunks_for_prompt(
        messages_by_channel=messages_by_channel,
        target_user_id="456",
        author_names={"789": "Bob"},
        channel_names={"ch_1": "general"},
        mention_names=mention_names,
    )

    assert "@Alice" in result[0]["messages"][0]["content"]
    assert "<@456>" not in result[0]["messages"][0]["content"]


# =============================================================================
# _resolve_user_ids_to_names() Tests
# =============================================================================


@pytest.mark.asyncio
async def test_resolve_user_ids_to_names(
    executor: LayerExecutor,
    user_profiles,
) -> None:
    """Resolution priority: display_name > username#disc > username."""
    result = await executor._resolve_user_ids_to_names({"456", "789", "999"})

    assert result["456"] == "Alice"
    assert result["789"] == "Bob"
    assert result["999"] == "Charlie"


@pytest.mark.asyncio
async def test_resolve_user_ids_to_names_empty(
    executor: LayerExecutor,
) -> None:
    """Empty input returns empty result."""
    result = await executor._resolve_user_ids_to_names(set())
    assert result == {}


@pytest.mark.asyncio
async def test_resolve_user_ids_to_names_missing(
    executor: LayerExecutor,
    user_profiles,
) -> None:
    """Unknown users are omitted from result."""
    result = await executor._resolve_user_ids_to_names({"456", "nonexistent"})

    assert "456" in result
    assert "nonexistent" not in result


@pytest.mark.asyncio
async def test_resolve_user_ids_to_names_with_discriminator(
    executor: LayerExecutor,
    engine,
    sample_server,
) -> None:
    """display_name is used as primary, discriminator format available as fallback."""
    with engine.connect() as conn:
        conn.execute(
            user_profiles_table.insert().values(
                id=generate_id(),
                user_id="disc_user",
                server_id="123",
                display_name="DisplayUser",
                username="discuser",
                discriminator="1234",
                captured_at=utcnow(),
            )
        )
        conn.commit()

    result = await executor._resolve_user_ids_to_names({"disc_user"})
    # display_name takes priority over username#discriminator
    assert result["disc_user"] == "DisplayUser"


# =============================================================================
# _handle_fetch_messages with conversation_context Tests
# =============================================================================


@pytest.mark.asyncio
async def test_conversation_context_backward_compat(
    executor: LayerExecutor,
    engine,
    sample_server,
    sample_channels,
    sample_topic: Topic,
) -> None:
    """conversation_context: false uses old behavior."""
    now = utcnow()
    _insert_messages(engine, [
        {"id": "msg_1", "channel_id": "ch_general", "author_id": "456",
         "content": "Hello", "created_at": now - timedelta(hours=1)},
        {"id": "msg_2", "channel_id": "ch_general", "author_id": "789",
         "content": "Hi there", "created_at": now - timedelta(hours=1, minutes=5)},
    ])

    layer = Layer(
        name="test",
        category=LayerCategory.USER,
        nodes=[
            Node(type=NodeType.FETCH_MESSAGES, params={"lookback_hours": 72}),
        ],
    )
    ctx = ExecutionContext(
        topic=sample_topic,
        layer=layer,
        run_id=generate_id(),
    )

    node = Node(
        type=NodeType.FETCH_MESSAGES,
        params={"lookback_hours": 72, "conversation_context": False},
    )

    await executor._handle_fetch_messages(node, ctx)

    # Old behavior: only target user's messages
    assert len(ctx.messages) == 1
    assert ctx.messages[0].author_id == "456"

    # No conversation chunks should be set
    assert ctx.conversation_chunks == {}
    assert ctx.target_user_id is None


@pytest.mark.asyncio
async def test_handle_fetch_messages_with_conversation_context(
    executor: LayerExecutor,
    engine,
    sample_server,
    sample_channels,
    sample_topic: Topic,
) -> None:
    """conversation_context: true fetches windowed context."""
    now = utcnow()
    _insert_messages(engine, [
        {"id": "msg_1", "channel_id": "ch_general", "author_id": "456",
         "content": "Hello", "created_at": now - timedelta(hours=1)},
        {"id": "msg_2", "channel_id": "ch_general", "author_id": "789",
         "content": "Hi there", "created_at": now - timedelta(hours=1, minutes=5)},
        {"id": "msg_3", "channel_id": "ch_general", "author_id": "999",
         "content": "Welcome!", "created_at": now - timedelta(minutes=50)},
    ])

    layer = Layer(
        name="test",
        category=LayerCategory.USER,
        nodes=[
            Node(type=NodeType.FETCH_MESSAGES, params={"lookback_hours": 72}),
        ],
    )
    ctx = ExecutionContext(
        topic=sample_topic,
        layer=layer,
        run_id=generate_id(),
    )

    node = Node(
        type=NodeType.FETCH_MESSAGES,
        params={"lookback_hours": 72, "conversation_context": True},
    )

    await executor._handle_fetch_messages(node, ctx)

    # Should have conversation chunks
    assert len(ctx.conversation_chunks) == 1
    assert "ch_general" in ctx.conversation_chunks
    assert len(ctx.conversation_chunks["ch_general"]) == 3

    # Should also have flattened messages for backward compat
    assert len(ctx.messages) == 3

    # target_user_id should be set
    assert ctx.target_user_id == "456"

    # Channel names should be resolved
    assert ctx.conversation_channel_names.get("ch_general") == "general"


# =============================================================================
# Template Rendering Tests
# =============================================================================


def test_template_renders_conversation_chunks() -> None:
    """Template renders channel headers, bold target user."""
    prompts_path = Path("prompts")
    data_path = Path("data")

    if not prompts_path.exists():
        pytest.skip("Prompts directory not found")

    engine = TemplateEngine(templates_dir=prompts_path, data_dir=data_path)

    now = datetime.now(timezone.utc)
    context = {
        "topic": {"key": "server:123:user:456"},
        "user_profile": None,
        "insights": [],
        "messages": [],  # Empty — conversation_chunks takes precedence
        "conversation_chunks": [
            {
                "channel_name": "general",
                "channel_id": "ch_1",
                "message_count": 3,
                "target_message_count": 1,
                "messages": [
                    {
                        "created_at": now - timedelta(hours=1),
                        "author_display": "Alice",
                        "content": "Hello everyone!",
                        "is_target_user": True,
                        "has_media": False,
                        "has_links": False,
                        "link_summaries": [],
                        "media_descriptions": [],
                    },
                    {
                        "created_at": now - timedelta(minutes=55),
                        "author_display": "Bob",
                        "content": "Hey Alice!",
                        "is_target_user": False,
                        "has_media": False,
                        "has_links": False,
                        "link_summaries": [],
                        "media_descriptions": [],
                    },
                ],
            },
        ],
    }

    result = engine.render("user/reflection.jinja2", context)

    # Channel header should be present
    assert "#general" in result

    # Target user should be bold
    assert "**Alice**" in result

    # Non-target user should NOT be bold
    assert "Bob:" in result
    # Make sure Bob isn't wrapped in bold
    assert "**Bob**" not in result

    # Fallback "No messages" should NOT appear
    assert "No messages in the observation window" not in result


def test_template_falls_back_to_messages() -> None:
    """Template falls back to flat messages when no conversation_chunks."""
    prompts_path = Path("prompts")
    data_path = Path("data")

    if not prompts_path.exists():
        pytest.skip("Prompts directory not found")

    engine = TemplateEngine(templates_dir=prompts_path, data_dir=data_path)

    now = datetime.now(timezone.utc)
    context = {
        "topic": {"key": "server:123:user:456"},
        "insights": [],
        "messages": [
            {
                "created_at": now - timedelta(hours=1),
                "author_display": "them",
                "content": "Hello!",
                "has_media": False,
                "has_links": False,
            },
        ],
        # conversation_chunks not provided (or None)
    }

    result = engine.render("user/reflection.jinja2", context)

    # Should render the flat message format
    assert "them: Hello!" in result
    assert "No messages in the observation window" not in result


def test_template_no_messages_at_all() -> None:
    """Template shows 'No messages' when both are empty."""
    prompts_path = Path("prompts")
    data_path = Path("data")

    if not prompts_path.exists():
        pytest.skip("Prompts directory not found")

    engine = TemplateEngine(templates_dir=prompts_path, data_dir=data_path)

    context = {
        "topic": {"key": "server:123:user:456"},
        "insights": [],
        "messages": [],
        "conversation_chunks": [],
    }

    result = engine.render("user/reflection.jinja2", context)

    assert "No messages in the observation window" in result


# =============================================================================
# Integration: Full pipeline with conversation context
# =============================================================================


@pytest.mark.asyncio
async def test_full_pipeline_with_conversation_context(
    executor: LayerExecutor,
    engine,
    sample_server,
    sample_channels,
    sample_topic: Topic,
    templates_dir: Path,
    ledger: SalienceLedger,
    user_profiles,
) -> None:
    """End-to-end: fetch with conversation_context → LLM call with chunks."""
    now = utcnow()

    _insert_messages(engine, [
        {"id": "msg_1", "channel_id": "ch_general", "author_id": "456",
         "content": "Working on the API redesign", "created_at": now - timedelta(hours=2)},
        {"id": "msg_2", "channel_id": "ch_general", "author_id": "789",
         "content": "That sounds great, Alice!", "created_at": now - timedelta(hours=1, minutes=50)},
        {"id": "msg_3", "channel_id": "ch_dev", "author_id": "456",
         "content": "Found a bug in the parser", "created_at": now - timedelta(hours=3)},
        {"id": "msg_4", "channel_id": "ch_dev", "author_id": "999",
         "content": "I can help debug that", "created_at": now - timedelta(hours=2, minutes=45)},
    ])

    # Create a template that uses conversation_chunks
    (templates_dir / "user" / "reflection.jinja2").write_text("""
You are Zos, reflecting on {{ topic.key }}.

{% if conversation_chunks %}
{% for chunk in conversation_chunks %}
## #{{ chunk.channel_name }}
{% for msg in chunk.messages %}
{% if msg.is_target_user %}**{{ msg.author_display }}**{% else %}{{ msg.author_display }}{% endif %}: {{ msg.content }}
{% endfor %}
{% endfor %}
{% endif %}

Generate JSON insight.
""")

    layer = Layer(
        name="test-conv-context",
        category=LayerCategory.USER,
        nodes=[
            Node(
                type=NodeType.FETCH_MESSAGES,
                params={
                    "lookback_hours": 72,
                    "conversation_context": True,
                    "context_window_hours": 2,
                    "context_min_messages": 5,
                },
            ),
            Node(type=NodeType.FETCH_INSIGHTS, params={"max_per_topic": 5}),
            Node(
                type=NodeType.LLM_CALL,
                params={"prompt_template": "user/reflection.jinja2", "max_tokens": 600},
            ),
            Node(type=NodeType.STORE_INSIGHT, params={"category": "user_reflection"}),
        ],
    )

    await ledger.earn(sample_topic.key, 50.0)

    run = await executor.execute_layer(layer, [sample_topic.key])

    assert run.targets_processed == 1
    assert run.targets_skipped == 0

    # Verify the LLM was called (prompt should contain conversation context)
    call_args = executor.llm.complete.call_args
    prompt = call_args.kwargs.get("prompt") or call_args.args[0]

    # Prompt should contain channel headers and author names
    assert "#general" in prompt or "#dev" in prompt
    assert "Alice" in prompt or "Bob" in prompt or "Charlie" in prompt


# =============================================================================
# Layer YAML Tests
# =============================================================================


def test_nightly_user_layer_has_conversation_context() -> None:
    """Test that the nightly user layer enables conversation_context."""
    layer_path = Path("layers/reflection/nightly-user.yaml")

    if not layer_path.exists():
        pytest.skip("Layer file not found")

    import yaml

    with open(layer_path) as f:
        data = yaml.safe_load(f)

    # Find fetch_messages node
    fetch_node = next(
        (n for n in data["nodes"] if n["type"] == "fetch_messages"), None
    )
    assert fetch_node is not None
    assert fetch_node["params"].get("conversation_context") is True
    assert fetch_node["params"].get("context_window_hours") == 2
    assert fetch_node["params"].get("context_min_messages") == 10
    assert fetch_node["params"].get("max_channels") == 15
