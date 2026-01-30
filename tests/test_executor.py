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
    """Test fetching messages for a subject topic using content search."""
    now = utcnow()

    # Insert messages with varying content
    with engine.connect() as conn:
        conn.execute(
            messages_table.insert().values(
                id="subj_msg_1",
                channel_id=sample_channel,
                server_id=sample_server,
                author_id="user_a",
                content="The api redesign is looking great",
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
                content="I think the redesign of our API needs work",
                created_at=now - timedelta(hours=2),
                visibility_scope="public",
                has_media=False,
                has_links=False,
                ingested_at=now,
            )
        )
        # This message only contains "api" but NOT "redesign"
        conn.execute(
            messages_table.insert().values(
                id="subj_msg_3",
                channel_id=sample_channel,
                server_id=sample_server,
                author_id="user_c",
                content="The api is slow today",
                created_at=now - timedelta(hours=3),
                visibility_scope="public",
                has_media=False,
                has_links=False,
                ingested_at=now,
            )
        )
        conn.commit()

    topic_key = f"server:{sample_server}:subject:api_redesign"
    messages = await executor._get_messages_for_topic(
        topic_key,
        since=now - timedelta(hours=48),
        limit=50,
    )

    # Should match messages containing BOTH "api" AND "redesign"
    assert len(messages) == 2
    msg_ids = {m.id for m in messages}
    assert "subj_msg_1" in msg_ids
    assert "subj_msg_2" in msg_ids
    # "subj_msg_3" only has "api", not "redesign"
    assert "subj_msg_3" not in msg_ids


@pytest.mark.asyncio
async def test_fetch_messages_for_subject_case_insensitive(
    executor: LayerExecutor,
    engine,
    sample_server,
    sample_channel,
) -> None:
    """Test that subject content search is case-insensitive."""
    now = utcnow()

    with engine.connect() as conn:
        conn.execute(
            messages_table.insert().values(
                id="subj_case_1",
                channel_id=sample_channel,
                server_id=sample_server,
                author_id="user_a",
                content="RUST is amazing for systems programming",
                created_at=now - timedelta(hours=1),
                visibility_scope="public",
                has_media=False,
                has_links=False,
                ingested_at=now,
            )
        )
        conn.commit()

    topic_key = f"server:{sample_server}:subject:rust"
    messages = await executor._get_messages_for_topic(
        topic_key,
        since=now - timedelta(hours=48),
        limit=50,
    )

    assert len(messages) == 1
    assert messages[0].id == "subj_case_1"


@pytest.mark.asyncio
async def test_fetch_messages_for_subject_excludes_other_servers(
    executor: LayerExecutor,
    engine,
    sample_server,
    sample_channel,
) -> None:
    """Test that subject message fetch is scoped to the correct server."""
    now = utcnow()

    with engine.connect() as conn:
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
        # Message in the target server
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
        # Message in a DIFFERENT server (should be excluded)
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

    topic_key = f"server:{sample_server}:subject:rust"
    messages = await executor._get_messages_for_topic(
        topic_key,
        since=now - timedelta(hours=48),
        limit=50,
    )

    assert len(messages) == 1
    assert messages[0].id == "subj_srv_1"


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
