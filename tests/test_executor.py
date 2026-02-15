"""Tests for the Sequential Layer Executor.

Covers:
- Node execution order
- Context passing between nodes
- Error handling (fail-forward)
- Dry run mode
- Layer run recording
- LLM response parsing
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zos.config import Config
from zos.database import (
    channels as channels_table,
    create_tables,
    generate_id,
    get_engine,
    insights as insights_table,
    layer_runs as layer_runs_table,
    messages as messages_table,
    reactions as reactions_table,
    servers as servers_table,
    topics as topics_table,
)
from zos.executor import (
    DEFAULT_METRICS,
    ExecutionContext,
    LayerExecutor,
)
from zos.insights import InsightRetriever
from zos.layers import Layer, LayerCategory, LayerLoader, Node, NodeType
from zos.llm import CompletionResult, ModelClient, Usage
from zos.models import (
    Insight,
    LayerRun,
    LayerRunStatus,
    Message,
    Topic,
    TopicCategory,
    VisibilityScope,
    utcnow,
)
from zos.salience import SalienceLedger
from zos.templates import TemplateEngine


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
    return templates


@pytest.fixture
def templates(templates_dir: Path, tmp_path: Path) -> TemplateEngine:
    """Create a TemplateEngine instance for testing."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return TemplateEngine(templates_dir=templates_dir, data_dir=data_dir)


@pytest.fixture
def mock_llm(test_config: Config) -> MagicMock:
    """Create a mock ModelClient."""
    mock = MagicMock(spec=ModelClient)

    # Default completion result
    async def mock_complete(*args, **kwargs):
        return CompletionResult(
            text='{"content": "Test insight", "confidence": 0.8, "importance": 0.7, "novelty": 0.6, "valence": {"curiosity": 0.7}}',
            usage=Usage(input_tokens=100, output_tokens=50),
            model="claude-3-5-haiku-20241022",
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
def sample_layer() -> Layer:
    """Create a sample layer for testing."""
    return Layer(
        name="test-layer",
        category=LayerCategory.USER,
        description="Test layer",
        nodes=[
            Node(
                name="get_messages",
                type=NodeType.FETCH_MESSAGES,
                params={"lookback_hours": 24, "limit_per_channel": 50},
            ),
            Node(
                name="get_insights",
                type=NodeType.FETCH_INSIGHTS,
                params={"retrieval_profile": "balanced", "max_per_topic": 5},
            ),
            Node(
                name="reflect",
                type=NodeType.LLM_CALL,
                params={"prompt_template": "test.jinja2", "model": "simple"},
            ),
            Node(
                name="save",
                type=NodeType.STORE_INSIGHT,
                params={"category": "user_reflection"},
            ),
        ],
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
def sample_channel(engine, sample_server):
    """Create and insert a sample channel for testing."""
    with engine.connect() as conn:
        conn.execute(
            channels_table.insert().values(
                id="channel_1",
                server_id=sample_server,
                name="general",
                type="text",
                created_at=utcnow(),
            )
        )
        conn.commit()
    return "channel_1"


@pytest.fixture
def sample_topic(engine, sample_server) -> Topic:
    """Create and insert a sample topic for testing."""
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
def sample_messages(engine, sample_topic: Topic, sample_channel) -> list[Message]:
    """Create and insert sample messages for testing."""
    now = utcnow()
    messages = [
        Message(
            id=f"msg_{i}",
            channel_id=sample_channel,
            server_id="123",
            author_id="456",
            content=f"Test message {i}",
            created_at=now - timedelta(hours=i),
            visibility_scope=VisibilityScope.PUBLIC,
            has_media=False,
            has_links=False,
            ingested_at=now,
        )
        for i in range(3)
    ]

    with engine.connect() as conn:
        for msg in messages:
            conn.execute(
                messages_table.insert().values(
                    id=msg.id,
                    channel_id=msg.channel_id,
                    server_id=msg.server_id,
                    author_id=msg.author_id,
                    content=msg.content,
                    created_at=msg.created_at,
                    visibility_scope=msg.visibility_scope.value,
                    has_media=msg.has_media,
                    has_links=msg.has_links,
                    ingested_at=msg.ingested_at,
                )
            )
        conn.commit()

    return messages


# =============================================================================
# ExecutionContext Tests
# =============================================================================


def test_execution_context_creation(sample_topic: Topic, sample_layer: Layer) -> None:
    """Test creating an ExecutionContext."""
    ctx = ExecutionContext(
        topic=sample_topic,
        layer=sample_layer,
        run_id=generate_id(),
    )

    assert ctx.topic.key == sample_topic.key
    assert ctx.layer.name == sample_layer.name
    assert ctx.messages == []
    assert ctx.insights == []
    assert ctx.llm_response is None
    assert ctx.tokens_input == 0
    assert ctx.tokens_output == 0
    assert not ctx.dry_run


def test_execution_context_add_tokens(sample_topic: Topic, sample_layer: Layer) -> None:
    """Test adding tokens to context."""
    ctx = ExecutionContext(
        topic=sample_topic,
        layer=sample_layer,
        run_id=generate_id(),
    )

    ctx.add_tokens(100, 50)
    assert ctx.tokens_input == 100
    assert ctx.tokens_output == 50

    ctx.add_tokens(200, 100)
    assert ctx.tokens_input == 300
    assert ctx.tokens_output == 150


# =============================================================================
# Layer Execution Tests
# =============================================================================


@pytest.mark.asyncio
async def test_execute_layer_basic(
    executor: LayerExecutor,
    sample_layer: Layer,
    sample_topic: Topic,
    sample_messages: list[Message],
    templates_dir: Path,
    ledger: SalienceLedger,
) -> None:
    """Test basic layer execution."""
    # Create a test template
    (templates_dir / "test.jinja2").write_text("Reflect on {{ topic.key }}")

    # Give the topic some salience to spend
    await ledger.earn(sample_topic.key, 10.0, reason="test")

    run = await executor.execute_layer(sample_layer, [sample_topic.key])

    assert run.layer_name == "test-layer"
    assert run.status in [LayerRunStatus.SUCCESS, LayerRunStatus.DRY]
    assert run.targets_matched == 1
    assert run.targets_processed == 1
    assert run.targets_skipped == 0


@pytest.mark.asyncio
async def test_execute_layer_dry_run(
    executor: LayerExecutor,
    sample_layer: Layer,
    sample_topic: Topic,
    templates_dir: Path,
) -> None:
    """Test dry run mode skips LLM calls and DB writes."""
    (templates_dir / "test.jinja2").write_text("Test prompt")

    run = await executor.execute_layer(
        sample_layer,
        [sample_topic.key],
        dry_run=True,
    )

    assert run.status == LayerRunStatus.DRY
    assert run.targets_processed == 1
    # LLM should not have been called in dry run
    assert run.tokens_input == 0
    assert run.tokens_output == 0


@pytest.mark.asyncio
async def test_execute_layer_fail_forward(
    executor: LayerExecutor,
    sample_layer: Layer,
    sample_topic: Topic,
    engine,
    templates_dir: Path,
    ledger: SalienceLedger,
) -> None:
    """Test that errors in one topic don't stop others."""
    (templates_dir / "test.jinja2").write_text("Test prompt")

    # Create a second topic
    second_topic_key = "server:123:user:789"
    with engine.connect() as conn:
        conn.execute(
            topics_table.insert().values(
                key=second_topic_key,
                category="user",
                is_global=False,
                provisional=False,
                created_at=utcnow(),
            )
        )
        conn.commit()

    # Give both topics salience
    await ledger.earn(sample_topic.key, 10.0, reason="test")
    await ledger.earn(second_topic_key, 10.0, reason="test")

    # First topic is valid, second will be processed
    # Even if one fails, the other should still process
    run = await executor.execute_layer(
        sample_layer,
        [sample_topic.key, "nonexistent:topic", second_topic_key],
    )

    # Should have partial success (one topic not found)
    assert run.targets_matched == 3
    assert run.targets_skipped == 1  # nonexistent topic
    assert run.targets_processed == 2


@pytest.mark.asyncio
async def test_execute_layer_all_topics_fail(
    executor: LayerExecutor,
    sample_layer: Layer,
) -> None:
    """Test that all topics failing results in FAILED status."""
    run = await executor.execute_layer(
        sample_layer,
        ["nonexistent:topic:1", "nonexistent:topic:2"],
    )

    assert run.status == LayerRunStatus.FAILED
    assert run.targets_skipped == 2
    assert run.targets_processed == 0


@pytest.mark.asyncio
async def test_execute_layer_records_layer_run(
    executor: LayerExecutor,
    sample_layer: Layer,
    sample_topic: Topic,
    engine,
    templates_dir: Path,
) -> None:
    """Test that layer run is recorded in database."""
    (templates_dir / "test.jinja2").write_text("Test prompt")

    run = await executor.execute_layer(
        sample_layer,
        [sample_topic.key],
        dry_run=True,
    )

    # Check database
    with engine.connect() as conn:
        result = conn.execute(
            layer_runs_table.select().where(layer_runs_table.c.id == run.id)
        ).fetchone()

    assert result is not None
    assert result.layer_name == "test-layer"
    assert result.status == LayerRunStatus.DRY.value


# =============================================================================
# Node Execution Tests
# =============================================================================


@pytest.mark.asyncio
async def test_node_execution_order(
    executor: LayerExecutor,
    sample_topic: Topic,
    sample_messages: list[Message],
    templates_dir: Path,
    ledger: SalienceLedger,
) -> None:
    """Test that nodes execute in the correct sequence."""
    (templates_dir / "test.jinja2").write_text("{{ messages|length }} messages")

    # Create a layer with specific node order
    layer = Layer(
        name="ordered-layer",
        category=LayerCategory.USER,
        nodes=[
            Node(type=NodeType.FETCH_MESSAGES, params={"lookback_hours": 24}),
            Node(type=NodeType.LLM_CALL, params={"prompt_template": "test.jinja2"}),
        ],
    )

    await ledger.earn(sample_topic.key, 10.0)

    # Execute should work if order is correct (messages before LLM)
    run = await executor.execute_layer(layer, [sample_topic.key])
    assert run.targets_processed == 1


@pytest.mark.asyncio
async def test_context_passes_between_nodes(
    executor: LayerExecutor,
    sample_topic: Topic,
    sample_messages: list[Message],
    templates_dir: Path,
    ledger: SalienceLedger,
) -> None:
    """Test that context data passes between nodes."""
    # Template that uses messages
    (templates_dir / "test.jinja2").write_text(
        "{% for msg in messages %}{{ msg.content }}{% endfor %}"
    )

    layer = Layer(
        name="context-test",
        category=LayerCategory.USER,
        nodes=[
            Node(type=NodeType.FETCH_MESSAGES, params={"lookback_hours": 24}),
            Node(type=NodeType.LLM_CALL, params={"prompt_template": "test.jinja2"}),
        ],
    )

    await ledger.earn(sample_topic.key, 10.0)
    run = await executor.execute_layer(layer, [sample_topic.key])

    # If context didn't pass, the template render would fail
    assert run.targets_processed == 1


# =============================================================================
# LLM Response Parsing Tests
# =============================================================================


def test_parse_insight_response_json_block(executor: LayerExecutor) -> None:
    """Test parsing JSON from code block."""
    response = '''Here's the insight:

```json
{
    "content": "User shows collaborative patterns",
    "confidence": 0.85,
    "importance": 0.7,
    "novelty": 0.6,
    "valence": {"warmth": 0.8}
}
```
'''

    result = executor._parse_insight_response(response)

    assert result["content"] == "User shows collaborative patterns"
    assert result["confidence"] == 0.85
    assert result["valence"]["warmth"] == 0.8


def test_parse_insight_response_raw_json(executor: LayerExecutor) -> None:
    """Test parsing raw JSON response."""
    response = '{"content": "Test insight", "confidence": 0.9}'

    result = executor._parse_insight_response(response)

    assert result["content"] == "Test insight"
    assert result["confidence"] == 0.9


def test_parse_insight_response_fallback(executor: LayerExecutor) -> None:
    """Test fallback when JSON parsing fails."""
    response = "This is just plain text without any JSON"

    result = executor._parse_insight_response(response)

    # Should use response as content with defaults
    assert result["content"] == response
    assert result["confidence"] == DEFAULT_METRICS["confidence"]
    assert result["importance"] == DEFAULT_METRICS["importance"]


def test_parse_insight_response_partial_json(executor: LayerExecutor) -> None:
    """Test parsing with partial JSON (missing some fields)."""
    response = '{"content": "Partial insight"}'

    result = executor._parse_insight_response(response)

    assert result["content"] == "Partial insight"
    # Should have defaults for missing fields
    assert result["confidence"] == DEFAULT_METRICS["confidence"]


# =============================================================================
# Scope Determination Tests
# =============================================================================


def test_determine_scope_public(executor: LayerExecutor) -> None:
    """Test scope determination with public messages only."""
    messages = [
        Message(
            id="1",
            channel_id="ch1",
            author_id="user1",
            content="test",
            created_at=utcnow(),
            visibility_scope=VisibilityScope.PUBLIC,
        ),
    ]

    scope = executor._determine_scope(messages)
    assert scope == VisibilityScope.PUBLIC


def test_determine_scope_dm(executor: LayerExecutor) -> None:
    """Test scope determination with DM messages."""
    messages = [
        Message(
            id="1",
            channel_id="ch1",
            author_id="user1",
            content="public",
            created_at=utcnow(),
            visibility_scope=VisibilityScope.PUBLIC,
        ),
        Message(
            id="2",
            channel_id="ch2",
            author_id="user1",
            content="dm",
            created_at=utcnow(),
            visibility_scope=VisibilityScope.DM,
        ),
    ]

    scope = executor._determine_scope(messages)
    assert scope == VisibilityScope.DM


def test_determine_scope_empty(executor: LayerExecutor) -> None:
    """Test scope determination with no messages."""
    scope = executor._determine_scope([])
    assert scope == VisibilityScope.PUBLIC


# =============================================================================
# Topic Extraction Tests
# =============================================================================


def test_extract_global_topic_user(executor: LayerExecutor) -> None:
    """Test extracting global topic from server-scoped user."""
    result = executor._extract_global_topic("server:123:user:456")
    assert result == "user:456"


def test_extract_global_topic_dyad(executor: LayerExecutor) -> None:
    """Test extracting global topic from server-scoped dyad."""
    result = executor._extract_global_topic("server:123:dyad:456:789")
    assert result == "dyad:456:789"


def test_extract_global_topic_channel(executor: LayerExecutor) -> None:
    """Test that channel topics don't have global equivalents."""
    result = executor._extract_global_topic("server:123:channel:456")
    assert result is None


def test_extract_global_topic_already_global(executor: LayerExecutor) -> None:
    """Test that global topics return None."""
    result = executor._extract_global_topic("user:456")
    assert result is None


# =============================================================================
# Fetch Messages Tests
# =============================================================================


@pytest.mark.asyncio
async def test_fetch_messages_for_user_topic(
    executor: LayerExecutor,
    sample_topic: Topic,
    sample_messages: list[Message],
) -> None:
    """Test fetching messages for a user topic."""
    messages = await executor._get_messages_for_topic(
        sample_topic.key,
        since=utcnow() - timedelta(hours=48),
        limit=10,
    )

    assert len(messages) == len(sample_messages)


@pytest.mark.asyncio
async def test_fetch_messages_for_channel_topic(
    executor: LayerExecutor,
    engine,
    sample_channel,
    sample_server,
) -> None:
    """Test fetching messages for a channel topic."""
    # Create channel topic
    topic_key = f"server:{sample_server}:channel:{sample_channel}"
    with engine.connect() as conn:
        conn.execute(
            topics_table.insert().values(
                key=topic_key,
                category="channel",
                is_global=False,
                provisional=False,
                created_at=utcnow(),
            )
        )
        # Create a message in the channel
        conn.execute(
            messages_table.insert().values(
                id="channel_msg_1",
                channel_id=sample_channel,
                server_id=sample_server,
                author_id="user1",
                content="Channel message",
                created_at=utcnow(),
                visibility_scope="public",
                has_media=False,
                has_links=False,
                ingested_at=utcnow(),
            )
        )
        conn.commit()

    messages = await executor._get_messages_for_topic(
        topic_key,
        since=utcnow() - timedelta(hours=1),
        limit=10,
    )

    assert len(messages) == 1
    assert messages[0].content == "Channel message"


@pytest.fixture
def dm_setup(engine):
    """Create the DM pseudo-server and DM channels for testing."""
    now = utcnow()
    with engine.connect() as conn:
        # DM pseudo-server (mirrors observation.py _ensure_channel)
        conn.execute(
            servers_table.insert().values(
                id="dm",
                name="Direct Messages",
                threads_as_topics=False,
                created_at=now,
            )
        )
        # DM channels
        for ch_id in ["dm_ch_1", "dm_ch_2", "dm_ch_3"]:
            conn.execute(
                channels_table.insert().values(
                    id=ch_id,
                    server_id="dm",
                    name=None,
                    type="dm",
                    created_at=now,
                )
            )
        conn.commit()


@pytest.mark.asyncio
async def test_fetch_messages_for_global_user_topic(
    executor: LayerExecutor,
    engine,
    dm_setup,
) -> None:
    """Test fetching DM messages for a global user topic (user:<id>)."""
    now = utcnow()
    with engine.connect() as conn:
        for i in range(3):
            conn.execute(
                messages_table.insert().values(
                    id=f"dm_msg_{i}",
                    channel_id="dm_ch_1",
                    server_id=None,
                    author_id="456",
                    content=f"DM message {i}",
                    created_at=now - timedelta(hours=i),
                    visibility_scope=VisibilityScope.DM.value,
                    has_media=False,
                    has_links=False,
                    ingested_at=now,
                )
            )
        conn.commit()

    messages = await executor._get_messages_for_topic(
        "user:456",
        since=now - timedelta(hours=48),
        limit=10,
    )

    assert len(messages) == 3


@pytest.mark.asyncio
async def test_fetch_messages_for_global_user_topic_includes_both_sides(
    executor: LayerExecutor,
    engine,
    dm_setup,
) -> None:
    """Test that global user topic fetches both sides of a DM conversation."""
    now = utcnow()
    with engine.connect() as conn:
        conn.execute(
            messages_table.insert().values(
                id="dm_user_msg",
                channel_id="dm_ch_2",
                server_id=None,
                author_id="456",
                content="Hello Zos",
                created_at=now - timedelta(minutes=10),
                visibility_scope=VisibilityScope.DM.value,
                has_media=False,
                has_links=False,
                ingested_at=now,
            )
        )
        conn.execute(
            messages_table.insert().values(
                id="dm_bot_msg",
                channel_id="dm_ch_2",
                server_id=None,
                author_id="bot_id",
                content="Hello human",
                created_at=now - timedelta(minutes=5),
                visibility_scope=VisibilityScope.DM.value,
                has_media=False,
                has_links=False,
                ingested_at=now,
            )
        )
        conn.commit()

    messages = await executor._get_messages_for_topic(
        "user:456",
        since=now - timedelta(hours=1),
        limit=10,
    )

    assert len(messages) == 2
    authors = {m.author_id for m in messages}
    assert authors == {"456", "bot_id"}


@pytest.mark.asyncio
async def test_fetch_messages_for_global_dyad_topic(
    executor: LayerExecutor,
    engine,
    dm_setup,
) -> None:
    """Test fetching messages for a global dyad topic (dyad:<a>:<b>)."""
    now = utcnow()
    with engine.connect() as conn:
        conn.execute(
            messages_table.insert().values(
                id="dyad_msg_1",
                channel_id="dm_ch_3",
                server_id=None,
                author_id="456",
                content="Message from user A",
                created_at=now - timedelta(hours=1),
                visibility_scope=VisibilityScope.DM.value,
                has_media=False,
                has_links=False,
                ingested_at=now,
            )
        )
        conn.execute(
            messages_table.insert().values(
                id="dyad_msg_2",
                channel_id="dm_ch_3",
                server_id=None,
                author_id="789",
                content="Message from user B",
                created_at=now - timedelta(minutes=30),
                visibility_scope=VisibilityScope.DM.value,
                has_media=False,
                has_links=False,
                ingested_at=now,
            )
        )
        conn.commit()

    messages = await executor._get_messages_for_topic(
        "dyad:456:789",
        since=now - timedelta(hours=48),
        limit=10,
    )

    assert len(messages) == 2
    authors = {m.author_id for m in messages}
    assert authors == {"456", "789"}


# =============================================================================
# Layer Run Recording Tests
# =============================================================================


@pytest.mark.asyncio
async def test_layer_run_includes_model_info(
    executor: LayerExecutor,
    sample_layer: Layer,
    sample_topic: Topic,
    templates_dir: Path,
    ledger: SalienceLedger,
) -> None:
    """Test that layer run includes model information."""
    (templates_dir / "test.jinja2").write_text("Test")
    await ledger.earn(sample_topic.key, 10.0)

    run = await executor.execute_layer(sample_layer, [sample_topic.key])

    # Model info should be captured from LLM call
    if run.status == LayerRunStatus.SUCCESS:
        assert run.model_provider == "anthropic"
        assert run.model_name == "claude-3-5-haiku-20241022"


@pytest.mark.asyncio
async def test_layer_run_tracks_tokens(
    executor: LayerExecutor,
    sample_layer: Layer,
    sample_topic: Topic,
    templates_dir: Path,
    ledger: SalienceLedger,
) -> None:
    """Test that layer run tracks token usage."""
    (templates_dir / "test.jinja2").write_text("Test")
    await ledger.earn(sample_topic.key, 10.0)

    run = await executor.execute_layer(sample_layer, [sample_topic.key])

    # Tokens should be tracked from LLM call
    if run.status == LayerRunStatus.SUCCESS:
        assert run.tokens_input == 100  # From mock
        assert run.tokens_output == 50  # From mock
        assert run.tokens_total == 150


@pytest.mark.asyncio
async def test_layer_run_records_errors(
    executor: LayerExecutor,
    sample_layer: Layer,
) -> None:
    """Test that layer run records errors for failed topics."""
    run = await executor.execute_layer(
        sample_layer,
        ["nonexistent:topic:1"],
    )

    assert run.errors is not None
    assert len(run.errors) == 1
    assert run.errors[0]["topic"] == "nonexistent:topic:1"
    assert "invalid topic key format" in run.errors[0]["error"].lower()


# =============================================================================
# Node Handler Tests
# =============================================================================


@pytest.mark.asyncio
async def test_handle_reduce_collect(
    executor: LayerExecutor,
    sample_topic: Topic,
    sample_layer: Layer,
) -> None:
    """Test reduce node with collect operation."""
    ctx = ExecutionContext(
        topic=sample_topic,
        layer=sample_layer,
        run_id=generate_id(),
    )
    ctx.llm_response = "Test response"

    node = Node(
        type=NodeType.REDUCE,
        params={"operation": "collect"},
    )

    await executor._handle_reduce(node, ctx)

    assert len(ctx.reduced_results) == 1
    assert ctx.reduced_results[0] == "Test response"


@pytest.mark.asyncio
async def test_handle_output_log(
    executor: LayerExecutor,
    sample_topic: Topic,
    sample_layer: Layer,
) -> None:
    """Test output node with log destination."""
    ctx = ExecutionContext(
        topic=sample_topic,
        layer=sample_layer,
        run_id=generate_id(),
    )
    ctx.llm_response = "Output content"

    node = Node(
        type=NodeType.OUTPUT,
        params={"destination": "log"},
    )

    await executor._handle_output(node, ctx)

    assert ctx.output_content == "Output content"


@pytest.mark.asyncio
async def test_handle_update_self_concept_dry_run(
    executor: LayerExecutor,
    sample_topic: Topic,
    sample_layer: Layer,
) -> None:
    """Test that update_self_concept skips in dry run."""
    ctx = ExecutionContext(
        topic=sample_topic,
        layer=sample_layer,
        run_id=generate_id(),
        dry_run=True,
    )
    ctx.llm_response = "New self concept"

    node = Node(
        type=NodeType.UPDATE_SELF_CONCEPT,
        params={"document_path": "data/self-concept.md"},
    )

    # Should not raise in dry run
    await executor._handle_update_self_concept(node, ctx)


@pytest.mark.asyncio
async def test_handle_llm_call_requires_template(
    executor: LayerExecutor,
    sample_topic: Topic,
    sample_layer: Layer,
) -> None:
    """Test that llm_call requires prompt_template param."""
    ctx = ExecutionContext(
        topic=sample_topic,
        layer=sample_layer,
        run_id=generate_id(),
    )

    node = Node(
        type=NodeType.LLM_CALL,
        params={},  # Missing prompt_template
    )

    with pytest.raises(ValueError, match="prompt_template"):
        await executor._handle_llm_call(node, ctx)


@pytest.mark.asyncio
async def test_handle_store_insight_requires_response(
    executor: LayerExecutor,
    sample_topic: Topic,
    sample_layer: Layer,
) -> None:
    """Test that store_insight requires LLM response."""
    ctx = ExecutionContext(
        topic=sample_topic,
        layer=sample_layer,
        run_id=generate_id(),
    )
    ctx.llm_response = None  # No response

    node = Node(
        type=NodeType.STORE_INSIGHT,
        params={"category": "test"},
    )

    with pytest.raises(ValueError, match="No LLM response"):
        await executor._handle_store_insight(node, ctx)


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.asyncio
async def test_full_reflection_pipeline(
    executor: LayerExecutor,
    sample_topic: Topic,
    sample_messages: list[Message],
    templates_dir: Path,
    ledger: SalienceLedger,
    engine,
) -> None:
    """Test a complete reflection pipeline end-to-end."""
    # Create reflection template
    (templates_dir / "reflection.jinja2").write_text("""
Reflect on user {{ topic.key }}:

Messages:
{% for msg in messages %}
- {{ msg.content }}
{% endfor %}

Prior insights:
{% for insight in insights %}
- {{ insight.content }}
{% endfor %}

Generate an insight in JSON format.
""")

    # Create the layer
    layer = Layer(
        name="full-reflection",
        category=LayerCategory.USER,
        nodes=[
            Node(type=NodeType.FETCH_MESSAGES, params={"lookback_hours": 24}),
            Node(type=NodeType.FETCH_INSIGHTS, params={"max_per_topic": 3}),
            Node(type=NodeType.LLM_CALL, params={"prompt_template": "reflection.jinja2"}),
            Node(type=NodeType.STORE_INSIGHT, params={"category": "user_reflection"}),
        ],
    )

    # Give topic salience
    await ledger.earn(sample_topic.key, 10.0)

    # Execute
    run = await executor.execute_layer(layer, [sample_topic.key])

    # Verify
    assert run.status in [LayerRunStatus.SUCCESS, LayerRunStatus.DRY]
    assert run.targets_processed == 1

    # Check insight was created
    if run.status == LayerRunStatus.SUCCESS:
        with engine.connect() as conn:
            insights = conn.execute(
                insights_table.select().where(
                    insights_table.c.topic_key == sample_topic.key
                )
            ).fetchall()

        assert len(insights) >= 1


@pytest.mark.asyncio
async def test_multiple_topics_parallel_processing(
    executor: LayerExecutor,
    sample_layer: Layer,
    engine,
    templates_dir: Path,
    ledger: SalienceLedger,
    sample_server,
) -> None:
    """Test processing multiple topics in sequence."""
    (templates_dir / "test.jinja2").write_text("Test prompt for {{ topic.key }}")

    # Create multiple topics
    topic_keys = []
    for i in range(3):
        topic_key = f"server:{sample_server}:user:{1000 + i}"
        topic_keys.append(topic_key)

        with engine.connect() as conn:
            conn.execute(
                topics_table.insert().values(
                    key=topic_key,
                    category="user",
                    is_global=False,
                    provisional=False,
                    created_at=utcnow(),
                )
            )
            conn.commit()

        await ledger.earn(topic_key, 10.0)

    # Execute for all topics
    run = await executor.execute_layer(sample_layer, topic_keys)

    assert run.targets_matched == 3
    assert run.targets_processed == 3
    assert run.targets_skipped == 0


# =============================================================================
# Edge Cases
# =============================================================================


@pytest.mark.asyncio
async def test_empty_topics_list(
    executor: LayerExecutor,
    sample_layer: Layer,
) -> None:
    """Test execution with empty topics list."""
    run = await executor.execute_layer(sample_layer, [])

    assert run.targets_matched == 0
    assert run.targets_processed == 0
    # Empty execution is DRY (no insights created)
    assert run.status == LayerRunStatus.DRY


@pytest.mark.asyncio
async def test_layer_with_single_node(
    executor: LayerExecutor,
    sample_topic: Topic,
    sample_messages: list[Message],
) -> None:
    """Test layer with only one node."""
    layer = Layer(
        name="single-node",
        category=LayerCategory.USER,
        nodes=[
            Node(type=NodeType.FETCH_MESSAGES, params={"lookback_hours": 24}),
        ],
    )

    run = await executor.execute_layer(layer, [sample_topic.key])

    # Should succeed even with just fetch
    assert run.targets_processed == 1
    # But no insights created
    assert run.status == LayerRunStatus.DRY


# =============================================================================
# Subject Reflection Tests
# =============================================================================


def test_extract_subject_from_topic(executor: LayerExecutor) -> None:
    """Test extracting subject name and server_id from a subject topic key."""
    subject_name, server_id = executor._extract_subject_from_topic(
        "server:123:subject:api_redesign"
    )
    assert subject_name == "api_redesign"
    assert server_id == "123"


def test_extract_subject_from_topic_multi_word(executor: LayerExecutor) -> None:
    """Test extracting subject with colons in name."""
    subject_name, server_id = executor._extract_subject_from_topic(
        "server:123:subject:rust:vs:go"
    )
    assert subject_name == "rust:vs:go"
    assert server_id == "123"


def test_extract_subject_from_topic_invalid(executor: LayerExecutor) -> None:
    """Test that non-subject keys return (None, None)."""
    subject_name, server_id = executor._extract_subject_from_topic(
        "server:123:user:456"
    )
    assert subject_name is None
    assert server_id is None


@pytest.mark.asyncio
async def test_fetch_messages_for_subject_topic(
    executor: LayerExecutor,
    engine,
    sample_server,
    sample_channel,
) -> None:
    """Test fetching messages for a subject topic via junction table."""
    from zos.database import subject_message_sources

    now = utcnow()
    topic_key = f"server:{sample_server}:subject:api_redesign"

    # Create the subject topic
    with engine.connect() as conn:
        conn.execute(
            topics_table.insert().values(
                key=topic_key,
                category="subject",
                is_global=False,
                provisional=False,
                created_at=now,
            )
        )
        # Insert messages — content doesn't need to match keywords
        conn.execute(
            messages_table.insert().values(
                id="subj_msg_1",
                channel_id=sample_channel,
                server_id=sample_server,
                author_id="user_a",
                content="Anyone playing Elden Ring Saturday?",
                created_at=now - timedelta(hours=1),
                visibility_scope="public",
                has_media=False,
                has_links=False,
                ingested_at=now,
            )
        )
        conn.execute(
            messages_table.insert().values(
                id="subj_msg_2",
                channel_id=sample_channel,
                server_id=sample_server,
                author_id="user_b",
                content="I'm down for some co-op this weekend",
                created_at=now - timedelta(hours=2),
                visibility_scope="public",
                has_media=False,
                has_links=False,
                ingested_at=now,
            )
        )
        # Message NOT associated with the subject
        conn.execute(
            messages_table.insert().values(
                id="subj_msg_3",
                channel_id=sample_channel,
                server_id=sample_server,
                author_id="user_c",
                content="Unrelated message about cooking",
                created_at=now - timedelta(hours=3),
                visibility_scope="public",
                has_media=False,
                has_links=False,
                ingested_at=now,
            )
        )
        # Associate first two messages with the subject via junction table
        conn.execute(
            subject_message_sources.insert(),
            [
                {
                    "id": generate_id(),
                    "subject_topic_key": topic_key,
                    "message_id": "subj_msg_1",
                    "source_topic_key": f"server:{sample_server}:user:user_a",
                    "layer_run_id": "run_1",
                    "created_at": now,
                },
                {
                    "id": generate_id(),
                    "subject_topic_key": topic_key,
                    "message_id": "subj_msg_2",
                    "source_topic_key": f"server:{sample_server}:user:user_b",
                    "layer_run_id": "run_1",
                    "created_at": now,
                },
            ],
        )
        conn.commit()

    messages = await executor._get_messages_for_topic(
        topic_key,
        since=now - timedelta(hours=48),
        limit=50,
    )

    # Should return only the two associated messages
    assert len(messages) == 2
    msg_ids = {m.id for m in messages}
    assert "subj_msg_1" in msg_ids
    assert "subj_msg_2" in msg_ids
    assert "subj_msg_3" not in msg_ids


@pytest.mark.asyncio
async def test_fetch_messages_for_subject_with_source_topics(
    executor: LayerExecutor,
    engine,
    sample_server,
    sample_channel,
) -> None:
    """Test that subject fetch also retrieves recent messages from source topics."""
    from zos.database import salience_ledger, subject_message_sources

    now = utcnow()
    topic_key = f"server:{sample_server}:subject:rust"
    user_topic = f"server:{sample_server}:user:user_a"

    with engine.connect() as conn:
        # Create the subject topic
        conn.execute(
            topics_table.insert().values(
                key=topic_key,
                category="subject",
                is_global=False,
                provisional=False,
                created_at=now,
            )
        )
        # Create the user topic
        conn.execute(
            topics_table.insert().values(
                key=user_topic,
                category="user",
                is_global=False,
                provisional=False,
                created_at=now,
            )
        )
        # Old message linked via junction table
        conn.execute(
            messages_table.insert().values(
                id="subj_old_1",
                channel_id=sample_channel,
                server_id=sample_server,
                author_id="user_a",
                content="Rust ownership model is elegant",
                created_at=now - timedelta(hours=12),
                visibility_scope="public",
                has_media=False,
                has_links=False,
                ingested_at=now,
            )
        )
        conn.execute(
            subject_message_sources.insert().values(
                id=generate_id(),
                subject_topic_key=topic_key,
                message_id="subj_old_1",
                source_topic_key=user_topic,
                layer_run_id="run_1",
                created_at=now,
            )
        )
        # Newer message by same user (found via source topic re-query)
        conn.execute(
            messages_table.insert().values(
                id="subj_new_1",
                channel_id=sample_channel,
                server_id=sample_server,
                author_id="user_a",
                content="Just finished a new Rust project",
                created_at=now - timedelta(hours=1),
                visibility_scope="public",
                has_media=False,
                has_links=False,
                ingested_at=now,
            )
        )
        # Record salience ledger entry linking subject to user topic
        conn.execute(
            salience_ledger.insert().values(
                id=generate_id(),
                topic_key=topic_key,
                transaction_type="earn",
                amount=5.0,
                reason="identified:run_1",
                source_topic=user_topic,
                created_at=now,
            )
        )
        conn.commit()

    messages = await executor._get_messages_for_topic(
        topic_key,
        since=now - timedelta(hours=48),
        limit=50,
    )

    # Should include both the junction-table message and the source-topic message
    msg_ids = {m.id for m in messages}
    assert "subj_old_1" in msg_ids
    assert "subj_new_1" in msg_ids


@pytest.mark.asyncio
async def test_fetch_messages_for_subject_excludes_other_servers(
    executor: LayerExecutor,
    engine,
    sample_server,
    sample_channel,
) -> None:
    """Test that subject message fetch via junction table respects associations."""
    from zos.database import subject_message_sources

    now = utcnow()
    topic_key = f"server:{sample_server}:subject:rust"

    with engine.connect() as conn:
        # Create the subject topic
        conn.execute(
            topics_table.insert().values(
                key=topic_key,
                category="subject",
                is_global=False,
                provisional=False,
                created_at=now,
            )
        )
        # Create another server
        conn.execute(
            servers_table.insert().values(
                id="other_server",
                name="Other Server",
                threads_as_topics=True,
                created_at=utcnow(),
            )
        )
        conn.execute(
            channels_table.insert().values(
                id="other_channel",
                server_id="other_server",
                name="general",
                type="text",
                created_at=utcnow(),
            )
        )
        # Message in the target server — associated with subject
        conn.execute(
            messages_table.insert().values(
                id="subj_srv_1",
                channel_id=sample_channel,
                server_id=sample_server,
                author_id="user_a",
                content="Let's talk about rust",
                created_at=now - timedelta(hours=1),
                visibility_scope="public",
                has_media=False,
                has_links=False,
                ingested_at=now,
            )
        )
        conn.execute(
            subject_message_sources.insert().values(
                id=generate_id(),
                subject_topic_key=topic_key,
                message_id="subj_srv_1",
                source_topic_key=f"server:{sample_server}:user:user_a",
                layer_run_id="run_1",
                created_at=now,
            )
        )
        # Message in a DIFFERENT server — NOT associated
        conn.execute(
            messages_table.insert().values(
                id="subj_srv_2",
                channel_id="other_channel",
                server_id="other_server",
                author_id="user_b",
                content="Rust is great",
                created_at=now - timedelta(hours=1),
                visibility_scope="public",
                has_media=False,
                has_links=False,
                ingested_at=now,
            )
        )
        conn.commit()

    messages = await executor._get_messages_for_topic(
        topic_key,
        since=now - timedelta(hours=48),
        limit=50,
    )

    # Only the associated message should be returned
    assert len(messages) == 1
    assert messages[0].id == "subj_srv_1"


@pytest.mark.asyncio
async def test_fetch_messages_for_subject_empty_when_no_associations(
    executor: LayerExecutor,
    engine,
    sample_server,
    sample_channel,
) -> None:
    """Test that a subject with no junction rows or source topics returns empty."""
    now = utcnow()
    topic_key = f"server:{sample_server}:subject:phantom_topic"

    with engine.connect() as conn:
        conn.execute(
            topics_table.insert().values(
                key=topic_key,
                category="subject",
                is_global=False,
                provisional=False,
                created_at=now,
            )
        )
        conn.commit()

    messages = await executor._get_messages_for_topic(
        topic_key,
        since=now - timedelta(hours=48),
        limit=50,
    )

    assert messages == []


@pytest.mark.asyncio
async def test_fetch_messages_for_subject_deduplicates_phases(
    executor: LayerExecutor,
    engine,
    sample_server,
    sample_channel,
) -> None:
    """Test that messages appearing in both junction table and source topic are deduplicated."""
    from zos.database import salience_ledger, subject_message_sources

    now = utcnow()
    topic_key = f"server:{sample_server}:subject:rust"
    user_topic = f"server:{sample_server}:user:user_a"

    with engine.connect() as conn:
        conn.execute(
            topics_table.insert().values(
                key=topic_key,
                category="subject",
                is_global=False,
                provisional=False,
                created_at=now,
            )
        )
        conn.execute(
            topics_table.insert().values(
                key=user_topic,
                category="user",
                is_global=False,
                provisional=False,
                created_at=now,
            )
        )
        # Insert a message by user_a
        conn.execute(
            messages_table.insert().values(
                id="dedup_msg_1",
                channel_id=sample_channel,
                server_id=sample_server,
                author_id="user_a",
                content="Rust is great for systems programming",
                created_at=now - timedelta(hours=1),
                visibility_scope="public",
                has_media=False,
                has_links=False,
                ingested_at=now,
            )
        )
        # This message is BOTH in the junction table AND will be found
        # by the source topic re-query (since it's by user_a in the server)
        conn.execute(
            subject_message_sources.insert().values(
                id=generate_id(),
                subject_topic_key=topic_key,
                message_id="dedup_msg_1",
                source_topic_key=user_topic,
                layer_run_id="run_1",
                created_at=now,
            )
        )
        # Record salience linking subject to user topic (triggers Phase 2)
        conn.execute(
            salience_ledger.insert().values(
                id=generate_id(),
                topic_key=topic_key,
                transaction_type="earn",
                amount=5.0,
                reason="identified:run_1",
                source_topic=user_topic,
                created_at=now,
            )
        )
        conn.commit()

    messages = await executor._get_messages_for_topic(
        topic_key,
        since=now - timedelta(hours=48),
        limit=50,
    )

    # Should appear only once despite being in both phases
    assert len(messages) == 1
    assert messages[0].id == "dedup_msg_1"


# =============================================================================
# Subject Bootstrap Tests
# =============================================================================


def test_normalize_subject_name_basic(executor: LayerExecutor) -> None:
    """Test basic normalization: spaces and mixed case."""
    assert executor._normalize_subject_name("API Redesign") == "api_redesign"
    assert executor._normalize_subject_name("weekend gaming") == "weekend_gaming"
    assert executor._normalize_subject_name("Rust") == "rust"


def test_normalize_subject_name_special_chars(executor: LayerExecutor) -> None:
    """Test normalization with special characters."""
    assert executor._normalize_subject_name("C++ patterns") == "c_patterns"
    assert executor._normalize_subject_name("node.js") == "node_js"
    assert executor._normalize_subject_name("front-end dev") == "front_end_dev"
    assert executor._normalize_subject_name("api/v2") == "api_v2"


def test_normalize_subject_name_empty_and_short(executor: LayerExecutor) -> None:
    """Test that empty, whitespace, and single-char names return None."""
    assert executor._normalize_subject_name("") is None
    assert executor._normalize_subject_name("   ") is None
    assert executor._normalize_subject_name("a") is None
    assert executor._normalize_subject_name("!@#") is None


def test_normalize_subject_name_max_length(executor: LayerExecutor) -> None:
    """Test truncation at 50 characters."""
    long_name = "a" * 100
    result = executor._normalize_subject_name(long_name)
    assert result is not None
    assert len(result) == 50


def test_normalize_subject_name_collapses_underscores(executor: LayerExecutor) -> None:
    """Test that multiple separators collapse to single underscore."""
    assert executor._normalize_subject_name("api  redesign") == "api_redesign"
    assert executor._normalize_subject_name("api - redesign") == "api_redesign"
    assert executor._normalize_subject_name("  api  ") == "api"


def test_extract_server_id(executor: LayerExecutor) -> None:
    """Test extracting server ID from topic keys."""
    assert executor._extract_server_id("server:123:user:456") == "123"
    assert executor._extract_server_id("server:abc:channel:def") == "abc"
    assert executor._extract_server_id("server:999:subject:rust") == "999"


def test_extract_server_id_none(executor: LayerExecutor) -> None:
    """Test that non-server topics return None."""
    assert executor._extract_server_id("user:456") is None
    assert executor._extract_server_id("self:zos") is None
    assert executor._extract_server_id("dyad:123:456") is None


@pytest.mark.asyncio
async def test_get_existing_subjects(
    executor: LayerExecutor,
    engine,
    sample_server,
) -> None:
    """Test fetching existing subject names for a server."""
    # Insert some subject topics
    now = utcnow()
    with engine.connect() as conn:
        for name in ["api_redesign", "weekend_gaming", "rust_lang"]:
            conn.execute(
                topics_table.insert().values(
                    key=f"server:{sample_server}:subject:{name}",
                    category="subject",
                    is_global=False,
                    provisional=False,
                    created_at=now,
                )
            )
        conn.commit()

    subjects = await executor._get_existing_subjects(sample_server)

    assert set(subjects) == {"api_redesign", "weekend_gaming", "rust_lang"}


@pytest.mark.asyncio
async def test_get_existing_subjects_empty(
    executor: LayerExecutor,
    sample_server,
) -> None:
    """Test that empty list is returned when no subjects exist."""
    subjects = await executor._get_existing_subjects(sample_server)
    assert subjects == []


@pytest.mark.asyncio
async def test_process_identified_subjects_creates_topic(
    executor: LayerExecutor,
    engine,
    sample_server,
    ledger: SalienceLedger,
) -> None:
    """Test that processing subjects creates topics and earns salience."""
    await executor._process_identified_subjects(
        subjects=["API Redesign"],
        source_topic_key=f"server:{sample_server}:user:456",
        insight_importance=0.8,
        run_id="test_run",
    )

    # Verify topic was created
    with engine.connect() as conn:
        result = conn.execute(
            topics_table.select().where(
                topics_table.c.key == f"server:{sample_server}:subject:api_redesign"
            )
        ).fetchone()

    assert result is not None
    assert result.category == "subject"

    # Verify salience was earned
    balance = await ledger.get_balance(f"server:{sample_server}:subject:api_redesign")
    expected = 5.0 * (0.5 + 0.8)  # 6.5
    assert balance == pytest.approx(expected, abs=0.1)


@pytest.mark.asyncio
async def test_process_identified_subjects_reidentification(
    executor: LayerExecutor,
    engine,
    sample_server,
    ledger: SalienceLedger,
) -> None:
    """Test that re-identifying a subject increases its salience."""
    topic_key = f"server:{sample_server}:subject:rust_lang"
    source = f"server:{sample_server}:user:456"

    # First identification
    await executor._process_identified_subjects(
        subjects=["rust_lang"],
        source_topic_key=source,
        insight_importance=0.5,
        run_id="run_1",
    )
    balance_1 = await ledger.get_balance(topic_key)

    # Second identification
    await executor._process_identified_subjects(
        subjects=["rust_lang"],
        source_topic_key=source,
        insight_importance=0.7,
        run_id="run_2",
    )
    balance_2 = await ledger.get_balance(topic_key)

    assert balance_2 > balance_1


@pytest.mark.asyncio
async def test_process_identified_subjects_caps_at_three(
    executor: LayerExecutor,
    engine,
    sample_server,
    ledger: SalienceLedger,
) -> None:
    """Test that only 3 subjects are processed even if more are provided."""
    await executor._process_identified_subjects(
        subjects=["alpha", "beta", "gamma", "delta", "epsilon"],
        source_topic_key=f"server:{sample_server}:user:456",
        insight_importance=0.5,
        run_id="test_run",
    )

    # Check that only first 3 were created
    subjects = await executor._get_existing_subjects(sample_server)
    assert len(subjects) == 3
    assert set(subjects) == {"alpha", "beta", "gamma"}


@pytest.mark.asyncio
async def test_process_identified_subjects_global_topic_skipped(
    executor: LayerExecutor,
    engine,
    ledger: SalienceLedger,
) -> None:
    """Test that global (non-server) source topics skip subject creation."""
    await executor._process_identified_subjects(
        subjects=["some_topic"],
        source_topic_key="user:456",  # No server prefix
        insight_importance=0.5,
        run_id="test_run",
    )

    # No topics should be created (no server to scope to)
    with engine.connect() as conn:
        result = conn.execute(
            topics_table.select().where(
                topics_table.c.category == "subject"
            )
        ).fetchall()

    assert len(result) == 0


@pytest.mark.asyncio
async def test_process_identified_subjects_records_message_associations(
    executor: LayerExecutor,
    engine,
    sample_server,
    sample_channel,
    ledger: SalienceLedger,
) -> None:
    """Test that passing message_ids records associations in junction table."""
    from zos.database import subject_message_sources

    now = utcnow()
    source_topic = f"server:{sample_server}:user:456"

    # Create messages first (FK constraint)
    with engine.connect() as conn:
        for mid in ["msg_a", "msg_b"]:
            conn.execute(
                messages_table.insert().values(
                    id=mid,
                    channel_id=sample_channel,
                    server_id=sample_server,
                    author_id="456",
                    content=f"Message {mid}",
                    created_at=now,
                    visibility_scope="public",
                    has_media=False,
                    has_links=False,
                    ingested_at=now,
                )
            )
        conn.commit()

    await executor._process_identified_subjects(
        subjects=["rust_lang"],
        source_topic_key=source_topic,
        insight_importance=0.7,
        run_id="test_run",
        message_ids=["msg_a", "msg_b"],
    )

    # Verify junction table rows were created
    subject_key = f"server:{sample_server}:subject:rust_lang"
    with engine.connect() as conn:
        rows = conn.execute(
            subject_message_sources.select().where(
                subject_message_sources.c.subject_topic_key == subject_key
            )
        ).fetchall()

    assert len(rows) == 2
    row_msg_ids = {r.message_id for r in rows}
    assert row_msg_ids == {"msg_a", "msg_b"}
    assert all(r.source_topic_key == source_topic for r in rows)
    assert all(r.layer_run_id == "test_run" for r in rows)


@pytest.mark.asyncio
async def test_process_identified_subjects_ignores_duplicate_messages(
    executor: LayerExecutor,
    engine,
    sample_server,
    sample_channel,
    ledger: SalienceLedger,
) -> None:
    """Test that re-identifying a subject with same messages doesn't create duplicates."""
    from zos.database import subject_message_sources

    now = utcnow()
    source_topic = f"server:{sample_server}:user:456"

    with engine.connect() as conn:
        conn.execute(
            messages_table.insert().values(
                id="msg_dup",
                channel_id=sample_channel,
                server_id=sample_server,
                author_id="456",
                content="Some message",
                created_at=now,
                visibility_scope="public",
                has_media=False,
                has_links=False,
                ingested_at=now,
            )
        )
        conn.commit()

    # First identification
    await executor._process_identified_subjects(
        subjects=["rust_lang"],
        source_topic_key=source_topic,
        insight_importance=0.5,
        run_id="run_1",
        message_ids=["msg_dup"],
    )

    # Second identification with same message
    await executor._process_identified_subjects(
        subjects=["rust_lang"],
        source_topic_key=source_topic,
        insight_importance=0.7,
        run_id="run_2",
        message_ids=["msg_dup"],
    )

    # Should still be only one row (INSERT OR IGNORE)
    subject_key = f"server:{sample_server}:subject:rust_lang"
    with engine.connect() as conn:
        rows = conn.execute(
            subject_message_sources.select().where(
                subject_message_sources.c.subject_topic_key == subject_key
            )
        ).fetchall()

    assert len(rows) == 1


@pytest.mark.asyncio
async def test_store_insight_with_identified_subjects(
    executor: LayerExecutor,
    engine,
    sample_server,
    sample_topic: Topic,
    sample_layer: Layer,
    ledger: SalienceLedger,
    mock_llm: MagicMock,
) -> None:
    """Integration test: LLM response with subjects → insight stored + topics created."""
    # Configure mock to return response with identified_subjects
    async def mock_complete_with_subjects(*args, **kwargs):
        return CompletionResult(
            text='{"content": "User is passionate about Rust and API design.", "confidence": 0.8, "importance": 0.7, "novelty": 0.6, "valence": {"curiosity": 0.7}, "identified_subjects": ["rust_lang", "api_redesign"]}',
            usage=Usage(input_tokens=100, output_tokens=80),
            model="claude-3-5-haiku-20241022",
            provider="anthropic",
        )

    mock_llm.complete = AsyncMock(side_effect=mock_complete_with_subjects)

    # Give topic salience
    await ledger.earn(sample_topic.key, 10.0, reason="test")

    # Create context with LLM response already set
    ctx = ExecutionContext(
        topic=sample_topic,
        layer=sample_layer,
        run_id=generate_id(),
    )
    ctx.llm_response = '{"content": "User is passionate about Rust and API design.", "confidence": 0.8, "importance": 0.7, "novelty": 0.6, "valence": {"curiosity": 0.7}, "identified_subjects": ["rust_lang", "api_redesign"]}'
    ctx.tokens_input = 100

    # Insert a preliminary layer run so FK constraint is met
    from zos.database import layer_runs as layer_runs_table
    with engine.connect() as conn:
        conn.execute(
            layer_runs_table.insert().values(
                id=ctx.run_id,
                layer_name=sample_layer.name,
                layer_hash="test",
                started_at=utcnow(),
                status="dry",
                targets_matched=1,
                targets_processed=0,
                targets_skipped=0,
                insights_created=0,
            )
        )
        conn.commit()

    # Execute store_insight
    node = Node(
        type=NodeType.STORE_INSIGHT,
        params={"category": "user_reflection"},
    )
    await executor._handle_store_insight(node, ctx)

    # Verify insight was stored
    with engine.connect() as conn:
        insights = conn.execute(
            insights_table.select().where(
                insights_table.c.topic_key == sample_topic.key
            )
        ).fetchall()
    assert len(insights) == 1

    # Verify subject topics were created
    subjects = await executor._get_existing_subjects(sample_server)
    assert "rust_lang" in subjects
    assert "api_redesign" in subjects

    # Verify salience was earned for subjects
    rust_balance = await ledger.get_balance(f"server:{sample_server}:subject:rust_lang")
    assert rust_balance > 0


# =============================================================================
# Dyad Reaction Tests
# =============================================================================


@pytest.fixture
def dyad_topic(engine, sample_server) -> Topic:
    """Create and insert a dyad topic for testing."""
    topic = Topic(
        key="server:123:dyad:456:789",
        category=TopicCategory.DYAD,
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
def dyad_messages(engine, sample_channel) -> list[Message]:
    """Create messages authored by both dyad members."""
    now = utcnow()
    msgs = [
        Message(
            id="dmsg_1",
            channel_id=sample_channel,
            server_id="123",
            author_id="456",
            content="Check out this new API design",
            created_at=now - timedelta(hours=1),
            visibility_scope=VisibilityScope.PUBLIC,
        ),
        Message(
            id="dmsg_2",
            channel_id=sample_channel,
            server_id="123",
            author_id="789",
            content="That looks great, nice work!",
            created_at=now - timedelta(hours=2),
            visibility_scope=VisibilityScope.PUBLIC,
        ),
        Message(
            id="dmsg_3",
            channel_id=sample_channel,
            server_id="123",
            author_id="456",
            content="Thanks! Here's the follow-up",
            created_at=now - timedelta(hours=3),
            visibility_scope=VisibilityScope.PUBLIC,
        ),
    ]
    with engine.connect() as conn:
        for msg in msgs:
            conn.execute(
                messages_table.insert().values(
                    id=msg.id,
                    channel_id=msg.channel_id,
                    server_id=msg.server_id,
                    author_id=msg.author_id,
                    content=msg.content,
                    created_at=msg.created_at,
                    visibility_scope=msg.visibility_scope.value,
                    has_media=False,
                    has_links=False,
                    ingested_at=utcnow(),
                )
            )
        conn.commit()
    return msgs


@pytest.fixture
def dyad_reactions(engine, dyad_messages) -> None:
    """Insert cross-reactions between dyad members."""
    now = utcnow()
    reaction_data = [
        # 789 reacts to 456's messages (2 reactions)
        {
            "id": generate_id(),
            "message_id": "dmsg_1",  # authored by 456
            "user_id": "789",
            "emoji": "❤️",
            "is_custom": False,
            "server_id": "123",
            "created_at": now - timedelta(minutes=30),
        },
        {
            "id": generate_id(),
            "message_id": "dmsg_3",  # authored by 456
            "user_id": "789",
            "emoji": "👍",
            "is_custom": False,
            "server_id": "123",
            "created_at": now - timedelta(minutes=20),
        },
        # 456 reacts to 789's message (1 reaction)
        {
            "id": generate_id(),
            "message_id": "dmsg_2",  # authored by 789
            "user_id": "456",
            "emoji": "😄",
            "is_custom": False,
            "server_id": "123",
            "created_at": now - timedelta(minutes=10),
        },
        # Self-reaction (should be excluded)
        {
            "id": generate_id(),
            "message_id": "dmsg_1",  # authored by 456
            "user_id": "456",
            "emoji": "👀",
            "is_custom": False,
            "server_id": "123",
            "created_at": now - timedelta(minutes=5),
        },
        # Removed reaction (should be excluded)
        {
            "id": generate_id(),
            "message_id": "dmsg_2",  # authored by 789
            "user_id": "456",
            "emoji": "🔥",
            "is_custom": False,
            "server_id": "123",
            "created_at": now - timedelta(minutes=3),
            "removed_at": now - timedelta(minutes=1),
        },
    ]
    with engine.connect() as conn:
        for r in reaction_data:
            conn.execute(reactions_table.insert().values(**r))
        conn.commit()


def test_get_reactions_for_dyad(
    executor: LayerExecutor,
    engine,
    sample_server,
    sample_channel,
    dyad_messages,
    dyad_reactions,
) -> None:
    """SQL query returns cross-reactions, excludes self-reactions and removed."""
    results = executor._get_reactions_for_dyad(
        user_id_1="456",
        user_id_2="789",
        server_id="123",
        lookback_days=7,
    )

    # Should have 3 cross-reactions (not the self-reaction or removed one)
    assert len(results) == 3

    # Verify structure
    for r in results:
        assert "reactor_id" in r
        assert "message_author_id" in r
        assert "emoji" in r
        assert "message_content" in r
        # No self-reactions
        assert r["reactor_id"] != r["message_author_id"]


def test_format_dyad_reactions_directional(executor: LayerExecutor) -> None:
    """Two directional summaries with correct counts."""
    reactions = [
        {
            "reactor_id": "789",
            "message_author_id": "456",
            "emoji": "❤️",
            "is_custom": False,
            "created_at": utcnow(),
            "message_content": "Check out this new API design",
        },
        {
            "reactor_id": "789",
            "message_author_id": "456",
            "emoji": "❤️",
            "is_custom": False,
            "created_at": utcnow(),
            "message_content": "Thanks! Here's the follow-up",
        },
        {
            "reactor_id": "456",
            "message_author_id": "789",
            "emoji": "😄",
            "is_custom": False,
            "created_at": utcnow(),
            "message_content": "That looks great, nice work!",
        },
    ]

    result = executor._format_dyad_reactions(reactions, "456", "789")

    assert len(result) == 2

    # Find each direction
    dir_456_to_789 = next(d for d in result if d["reactor_id"] == "456")
    dir_789_to_456 = next(d for d in result if d["reactor_id"] == "789")

    assert dir_456_to_789["total_count"] == 1
    assert dir_456_to_789["target_id"] == "789"
    assert len(dir_456_to_789["emojis"]) == 1
    assert dir_456_to_789["emojis"][0]["emoji"] == "😄"
    assert dir_456_to_789["emojis"][0]["count"] == 1

    assert dir_789_to_456["total_count"] == 2
    assert dir_789_to_456["target_id"] == "456"
    assert len(dir_789_to_456["emojis"]) == 1
    assert dir_789_to_456["emojis"][0]["emoji"] == "❤️"
    assert dir_789_to_456["emojis"][0]["count"] == 2
    assert len(dir_789_to_456["emojis"][0]["examples"]) == 2


def test_format_dyad_reactions_empty(executor: LayerExecutor) -> None:
    """Empty input produces two zero-count entries."""
    result = executor._format_dyad_reactions([], "456", "789")

    assert len(result) == 2
    for d in result:
        assert d["total_count"] == 0
        assert d["emojis"] == []


@pytest.mark.asyncio
async def test_handle_fetch_reactions_dyad_topic(
    executor: LayerExecutor,
    engine,
    sample_server,
    sample_channel,
    dyad_topic: Topic,
    dyad_messages,
    dyad_reactions,
    sample_layer: Layer,
) -> None:
    """Full handler integration for dyad topics."""
    ctx = ExecutionContext(
        topic=dyad_topic,
        layer=sample_layer,
        run_id=generate_id(),
    )

    node = Node(
        type=NodeType.FETCH_REACTIONS,
        params={"lookback_days": 7, "min_reactions": 2},
    )

    await executor._handle_fetch_reactions(node, ctx)

    # Should have directional summaries
    assert ctx.reactions is not None
    assert len(ctx.reactions) == 2

    # Verify both directions present
    reactor_ids = {d["reactor_id"] for d in ctx.reactions}
    assert reactor_ids == {"456", "789"}


# =============================================================================
# Self-Concept Size Limit Tests
# =============================================================================


def test_render_concept_update_prompt_includes_size_constraint(
    executor: LayerExecutor,
    sample_topic: Topic,
    sample_layer: Layer,
    tmp_path: Path,
) -> None:
    """Test that _render_concept_update_prompt includes the size constraint."""
    document_path = tmp_path / "self-concept.md"
    document_path.write_text("# Self-Concept\n\nI am Zos.")

    ctx = ExecutionContext(
        topic=sample_topic,
        layer=sample_layer,
        run_id=generate_id(),
    )
    ctx.llm_response = '{"should_update": true, "suggested_changes": "Add growth"}'

    prompt = executor._render_concept_update_prompt(ctx, document_path)

    assert "must stay under 15000 characters" in prompt
    assert "condense earlier sections" in prompt


def test_render_concept_update_prompt_no_size_constraint_when_zero(
    executor: LayerExecutor,
    sample_topic: Topic,
    sample_layer: Layer,
    tmp_path: Path,
) -> None:
    """Test that size constraint is omitted when max_chars is 0 (disabled)."""
    document_path = tmp_path / "self-concept.md"
    document_path.write_text("# Self-Concept\n\nI am Zos.")

    # Temporarily set max_chars to 0
    original = executor.config.self_concept_max_chars
    executor.config.self_concept_max_chars = 0

    ctx = ExecutionContext(
        topic=sample_topic,
        layer=sample_layer,
        run_id=generate_id(),
    )
    ctx.llm_response = '{"should_update": true, "suggested_changes": "Add growth"}'

    prompt = executor._render_concept_update_prompt(ctx, document_path)

    assert "must stay under" not in prompt

    # Restore
    executor.config.self_concept_max_chars = original


@pytest.mark.asyncio
async def test_handle_update_self_concept_warns_on_oversized(
    executor: LayerExecutor,
    sample_topic: Topic,
    sample_layer: Layer,
    tmp_path: Path,
) -> None:
    """Test that _handle_update_self_concept logs a warning for oversized output."""
    document_path = tmp_path / "self-concept.md"
    document_path.write_text("# Self-Concept\n\nI am Zos.")

    # Set a low limit so the LLM "output" exceeds it
    executor.config.self_concept_max_chars = 50

    oversized_text = "x" * 200

    ctx = ExecutionContext(
        topic=sample_topic,
        layer=sample_layer,
        run_id=generate_id(),
    )
    ctx.llm_response = '{"should_update": true, "suggested_changes": "Expand"}'

    node = Node(
        type=NodeType.UPDATE_SELF_CONCEPT,
        params={"document_path": str(document_path), "conditional": True},
    )

    # Mock the LLM to return oversized content
    mock_result = CompletionResult(
        text=oversized_text,
        usage=Usage(input_tokens=100, output_tokens=50),
        provider="anthropic",
        model="test-model",
    )
    executor.llm.complete = AsyncMock(return_value=mock_result)

    with patch("zos.executor.log") as mock_log:
        await executor._handle_update_self_concept(node, ctx)

        # Verify warning was logged
        mock_log.warning.assert_any_call(
            "self_concept_update_oversized",
            content_length=200,
            max_chars=50,
        )

    # File should still be written (render-time safeguard catches overflow)
    assert document_path.read_text() == oversized_text

    # Restore
    executor.config.self_concept_max_chars = 15000


# =============================================================================
# Cross-Topic Fetch Insights Tests
# =============================================================================


@pytest.mark.asyncio
async def test_fetch_insights_with_store_as(
    executor: LayerExecutor,
    engine,
    ledger: SalienceLedger,
) -> None:
    """Test that store_as prevents overwriting ctx.insights."""
    # Create a self topic
    with engine.connect() as conn:
        conn.execute(
            topics_table.insert().values(
                key="self:zos",
                category="self",
                is_global=True,
                provisional=False,
                created_at=utcnow(),
            )
        )
        conn.commit()

    topic = Topic(
        key="self:zos",
        category=TopicCategory.SELF,
        is_global=True,
        provisional=False,
        created_at=utcnow(),
    )

    ctx = ExecutionContext(
        topic=topic,
        layer=Layer(
            name="test",
            category=LayerCategory.SELF,
            nodes=[Node(type=NodeType.FETCH_INSIGHTS)],
        ),
        run_id=generate_id(),
    )

    # First fetch populates ctx.insights normally
    node1 = Node(
        type=NodeType.FETCH_INSIGHTS,
        params={"max_per_topic": 5},
    )
    await executor._handle_fetch_insights(node1, ctx)
    assert isinstance(ctx.insights, list)

    # Second fetch with store_as should go into named_data, not overwrite ctx.insights
    node2 = Node(
        type=NodeType.FETCH_INSIGHTS,
        params={
            "topic_pattern": "*",
            "max_per_topic": 5,
            "store_as": "recent_insights",
            "categories": ["user_reflection"],
            "since_days": 14,
        },
    )
    await executor._handle_fetch_insights(node2, ctx)

    # ctx.insights should still be the original list (not overwritten)
    assert isinstance(ctx.insights, list)
    # named_data should contain the cross-topic results
    assert "recent_insights" in ctx.named_data
    assert isinstance(ctx.named_data["recent_insights"], list)


@pytest.mark.asyncio
async def test_fetch_insights_cross_topic_with_categories(
    executor: LayerExecutor,
    engine,
    ledger: SalienceLedger,
) -> None:
    """Test cross-topic retrieval filters by category."""
    # Create topics and insights
    now = utcnow()
    with engine.connect() as conn:
        conn.execute(
            topics_table.insert().values(
                key="self:zos",
                category="self",
                is_global=True,
                provisional=False,
                created_at=now,
            )
        )
        conn.execute(
            topics_table.insert().values(
                key="server:1:user:100",
                category="user",
                is_global=False,
                provisional=False,
                created_at=now,
            )
        )
        # Create a layer run for the insights
        run_id = generate_id()
        conn.execute(
            layer_runs_table.insert().values(
                id=run_id,
                layer_name="test-layer",
                layer_hash="abc",
                started_at=now,
                completed_at=now,
                status="success",
                targets_matched=1,
                targets_processed=1,
                targets_skipped=0,
                insights_created=2,
            )
        )
        # Insert a user_reflection insight
        conn.execute(
            insights_table.insert().values(
                id=generate_id(),
                topic_key="server:1:user:100",
                category="user_reflection",
                content="User is helpful",
                sources_scope_max=VisibilityScope.PUBLIC.value,
                created_at=now - timedelta(days=1),
                layer_run_id=run_id,
                salience_spent=1.0,
                strength_adjustment=1.0,
                strength=5.0,
                original_topic_salience=10.0,
                confidence=0.8,
                importance=0.7,
                novelty=0.5,
                valence_curiosity=0.6,
            )
        )
        # Insert a synthesis insight (should be excluded when filtering for user_reflection only)
        conn.execute(
            insights_table.insert().values(
                id=generate_id(),
                topic_key="server:1:user:100",
                category="synthesis",
                content="Synthesis result",
                sources_scope_max=VisibilityScope.PUBLIC.value,
                created_at=now - timedelta(days=2),
                layer_run_id=run_id,
                salience_spent=1.0,
                strength_adjustment=1.0,
                strength=5.0,
                original_topic_salience=10.0,
                confidence=0.8,
                importance=0.7,
                novelty=0.5,
                valence_curiosity=0.6,
            )
        )
        conn.commit()

    topic = Topic(
        key="self:zos",
        category=TopicCategory.SELF,
        is_global=True,
        provisional=False,
        created_at=now,
    )

    ctx = ExecutionContext(
        topic=topic,
        layer=Layer(
            name="test",
            category=LayerCategory.SELF,
            nodes=[Node(type=NodeType.FETCH_INSIGHTS)],
        ),
        run_id=generate_id(),
    )

    # Fetch only user_reflection category
    node = Node(
        type=NodeType.FETCH_INSIGHTS,
        params={
            "topic_pattern": "*",
            "max_per_topic": 10,
            "store_as": "recent_insights",
            "categories": ["user_reflection"],
            "since_days": 14,
        },
    )
    await executor._handle_fetch_insights(node, ctx)

    recent = ctx.named_data["recent_insights"]
    assert len(recent) == 1
    assert recent[0]["category"] == "user_reflection"
    assert recent[0]["content"] == "User is helpful"
    assert "topic_key" in recent[0]


@pytest.mark.asyncio
async def test_named_data_merged_into_template_context(
    executor: LayerExecutor,
    engine,
    ledger: SalienceLedger,
    templates_dir: Path,
) -> None:
    """Test that named_data entries are available in template rendering."""
    # Create a simple template that uses recent_insights
    (templates_dir / "test_named.jinja2").write_text(
        "{% if recent_insights %}found {{ recent_insights | length }}{% else %}empty{% endif %}"
    )

    now = utcnow()
    with engine.connect() as conn:
        conn.execute(
            topics_table.insert().values(
                key="self:zos",
                category="self",
                is_global=True,
                provisional=False,
                created_at=now,
            )
        )
        conn.commit()

    topic = Topic(
        key="self:zos",
        category=TopicCategory.SELF,
        is_global=True,
        provisional=False,
        created_at=now,
    )

    ctx = ExecutionContext(
        topic=topic,
        layer=Layer(
            name="test",
            category=LayerCategory.SELF,
            nodes=[Node(type=NodeType.LLM_CALL)],
        ),
        run_id=generate_id(),
    )

    # Pre-populate named_data
    ctx.named_data["recent_insights"] = [
        {"category": "user_reflection", "content": "test", "topic_key": "user:1"},
    ]

    node = Node(
        type=NodeType.LLM_CALL,
        params={"prompt_template": "test_named.jinja2", "model": "simple"},
    )

    await executor._handle_llm_call(node, ctx)

    # The LLM should have been called — verify the prompt contained our data
    call_args = executor.llm.complete.call_args
    prompt = call_args.kwargs.get("prompt", call_args.args[0] if call_args.args else "")
    assert "found 1" in prompt
