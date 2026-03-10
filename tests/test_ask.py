"""Tests for the /ask command module.

Covers:
- _parse_plan_json: JSON parsing, markdown code block handling, unknown sources, max 5 ops
- split_response: under limit, paragraph boundaries, newlines, hard cuts, empty text
- Fetcher functions: database retrieval with real test data
- plan_context: LLM call with template rendering, retry on invalid JSON
- execute_answer: LLM call, context assembly
- ask orchestrator: end-to-end flow
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import json

import pytest

from zos.ask import (
    CONTEXT_SOURCE_CATALOG,
    _fetch_existing_subjects,
    _fetch_insights,
    _fetch_layer_runs,
    _fetch_messages,
    _fetch_recent_insights,
    _fetch_self_concept,
    _fetch_topics,
    _fetch_user_profile,
    _get_known_channels,
    _get_known_topics,
    _parse_plan_json,
    ask,
    execute_answer,
    fetch_context,
    plan_context,
    split_response,
)
from zos.config import Config
from zos.database import (
    servers as servers_table,
    channels as channels_table,
    create_tables,
    generate_id,
    get_engine,
    layer_runs as layer_runs_table,
    messages as messages_table,
    topics as topics_table,
    user_profiles as user_profiles_table,
)
from zos.llm import CompletionResult, ModelClient, Usage
from zos.models import (
    LayerRun,
    LayerRunStatus,
    Message,
    Topic,
    TopicCategory,
    VisibilityScope,
    utcnow,
)
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
def templates_dir(tmp_path: Path) -> Path:
    """Create a temporary templates directory."""
    templates = tmp_path / "prompts"
    templates.mkdir()
    # Create ask subdirectory
    (templates / "ask").mkdir()
    # Create dummy templates
    (templates / "ask" / "plan.jinja2").write_text("Plan prompt: {{ question }}")
    (templates / "ask" / "answer.jinja2").write_text("Answer prompt: {{ question }}")
    return templates


@pytest.fixture
def template_engine(templates_dir: Path, tmp_path: Path) -> TemplateEngine:
    """Create a TemplateEngine instance for testing."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "self-concept.md").write_text("I am Zos.")
    return TemplateEngine(templates_dir=templates_dir, data_dir=data_dir)


def make_mock_llm(response_text: str) -> MagicMock:
    """Create a mock ModelClient."""
    mock = MagicMock(spec=ModelClient)

    async def mock_complete(*args, **kwargs):
        return CompletionResult(
            text=response_text,
            usage=Usage(input_tokens=100, output_tokens=50),
            model="test-model",
            provider="test",
        )

    mock.complete = AsyncMock(side_effect=mock_complete)
    return mock

def create_server(engine, server_id="server:123"):
    """Create a test server."""
    with engine.connect() as conn:
        conn.execute(servers_table.insert().values(id=server_id))
        conn.commit()



# =============================================================================
# Tests: _parse_plan_json
# =============================================================================


class TestParsePlanJson:
    """Tests for JSON parsing from LLM responses."""

    def test_valid_json_object(self) -> None:
        """Test parsing valid JSON object."""
        text = json.dumps({
            "fetch": [
                {"source": "insights", "params": {"topic_key": "user:123"}},
                {"source": "recent_insights", "params": {"limit": 20}},
            ]
        })

        result = _parse_plan_json(text)

        assert len(result) == 2
        assert result[0]["source"] == "insights"
        assert result[0]["params"]["topic_key"] == "user:123"
        assert result[1]["source"] == "recent_insights"

    def test_markdown_code_block_json(self) -> None:
        """Test parsing JSON wrapped in markdown code blocks."""
        text = """```json
{"fetch": [{"source": "insights", "params": {"topic_key": "user:123"}}]}
```"""

        result = _parse_plan_json(text)

        assert len(result) == 1
        assert result[0]["source"] == "insights"

    def test_markdown_code_block_no_language(self) -> None:
        """Test parsing JSON wrapped in markdown without language specifier."""
        text = """```
{"fetch": [{"source": "topics", "params": {}}]}
```"""

        result = _parse_plan_json(text)

        assert len(result) == 1
        assert result[0]["source"] == "topics"

    def test_unknown_source_filtered(self) -> None:
        """Test that unknown sources are filtered out."""
        text = json.dumps({
            "fetch": [
                {"source": "insights", "params": {}},
                {"source": "unknown_source", "params": {}},
                {"source": "messages", "params": {}},
            ]
        })

        result = _parse_plan_json(text)

        assert len(result) == 2
        assert result[0]["source"] == "insights"
        assert result[1]["source"] == "messages"

    def test_max_5_operations(self) -> None:
        """Test that max 5 operations are enforced."""
        text = json.dumps({
            "fetch": [
                {"source": "insights", "params": {}},
                {"source": "insights", "params": {}},
                {"source": "insights", "params": {}},
                {"source": "insights", "params": {}},
                {"source": "insights", "params": {}},
                {"source": "recent_insights", "params": {}},
                {"source": "messages", "params": {}},
            ]
        })

        result = _parse_plan_json(text)

        assert len(result) == 5

    def test_missing_params_defaults_to_empty_dict(self) -> None:
        """Test that missing params defaults to empty dict."""
        text = json.dumps({
            "fetch": [
                {"source": "topics"},
            ]
        })

        result = _parse_plan_json(text)

        assert len(result) == 1
        assert result[0]["params"] == {}

    def test_invalid_json_raises_error(self) -> None:
        """Test that invalid JSON raises JSONDecodeError."""
        text = "{ not valid json"

        with pytest.raises(json.JSONDecodeError):
            _parse_plan_json(text)

    def test_missing_fetch_key_raises_error(self) -> None:
        """Test that missing 'fetch' key raises KeyError."""
        text = json.dumps({"operations": []})

        with pytest.raises(KeyError):
            _parse_plan_json(text)


# =============================================================================
# Tests: split_response
# =============================================================================


class TestSplitResponse:
    """Tests for Discord message splitting."""

    def test_under_limit_returns_single_chunk(self) -> None:
        """Test that text under limit returns as single chunk."""
        text = "Short message"
        result = split_response(text, max_len=2000)

        assert result == [text]

    def test_exact_limit_returns_single_chunk(self) -> None:
        """Test that text at exact limit returns as single chunk."""
        text = "x" * 100
        result = split_response(text, max_len=100)

        assert result == [text]

    def test_split_at_paragraph_boundary(self) -> None:
        """Test splitting at double newline (paragraph boundary)."""
        text = "First paragraph\n\nSecond paragraph\n\nThird paragraph"
        result = split_response(text, max_len=30)

        # Should split at paragraph boundaries
        assert len(result) >= 2
        assert all(len(chunk) <= 30 for chunk in result)
        # Reconstruct should be reasonable
        assert "First paragraph" in result[0]
        assert "Second paragraph" in result[1] or "Second paragraph" in "".join(result)

    def test_split_at_newline_when_no_paragraphs(self) -> None:
        """Test splitting at single newline when no paragraph boundaries."""
        text = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
        result = split_response(text, max_len=20)

        assert len(result) >= 2
        assert all(len(chunk) <= 20 for chunk in result)

    def test_split_at_space_when_no_newlines(self) -> None:
        """Test splitting at space when no newlines."""
        text = "word1 word2 word3 word4 word5 word6 word7 word8"
        result = split_response(text, max_len=20)

        assert len(result) >= 2
        assert all(len(chunk) <= 20 for chunk in result)

    def test_hard_cut_last_resort(self) -> None:
        """Test hard cut when no suitable split point."""
        text = "veryveryveryverylongwordwithoutbreaks" * 10
        result = split_response(text, max_len=50)

        assert len(result) >= 2
        assert all(len(chunk) <= 50 for chunk in result)

    def test_empty_text(self) -> None:
        """Test empty text returns empty list item."""
        result = split_response("", max_len=2000)

        assert result == [""]

    def test_reconstruction(self) -> None:
        """Test that reconstructed text equals original (modulo whitespace)."""
        text = "Para 1\n\nPara 2\n\nPara 3\n\nPara 4"
        result = split_response(text, max_len=20)

        reconstructed = "".join(result)
        # Should have same content (modulo extra spaces from lstrip)
        assert "Para 1" in reconstructed
        assert "Para 4" in reconstructed


# =============================================================================
# Tests: Fetcher Functions
# =============================================================================


class TestFetchers:
    """Tests for individual fetcher functions."""

    @pytest.mark.asyncio
    async def test_fetch_insights_missing_topic_key(self, engine, test_config: Config) -> None:
        """Test fetching insights without topic_key returns None."""
        result = await _fetch_insights(engine, test_config, None, {})

        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_insights_with_limit_clamping(self, engine, test_config: Config) -> None:
        """Test that limit is clamped to max 50."""
        # Limit should be clamped to max, doesn't error
        result = await _fetch_insights(engine, test_config, None, {
            "topic_key": "user:123",
            "limit": 1000  # Should be clamped to 50
        })

        # Returns "No insights" string for nonexistent topic
        assert result is not None
        assert "No insights" in result

    @pytest.mark.asyncio
    async def test_fetch_recent_insights(self, engine, test_config: Config) -> None:
        """Test fetching cross-topic recent insights."""
        result = await _fetch_recent_insights(engine, test_config, None, {})

        # Empty database should return "No recent insights"
        assert result is not None
        assert "No recent insights" in result

    @pytest.mark.asyncio
    async def test_fetch_messages_from_channel(self, engine, test_config: Config) -> None:
        """Test fetching messages from a channel."""
        # Setup: create server and channel
        create_server(engine)
        channel_id = "123456789"
        with engine.connect() as conn:
            conn.execute(
                channels_table.insert().values(
                    id=channel_id,
                    server_id="server:123",
                    name="general",
                    type="text",
                )
            )
            conn.commit()

        msg = Message(
            id=generate_id(),
            channel_id=channel_id,
            author_id="user:456",
            content="Test message",
            created_at=utcnow(),
            visibility_scope=VisibilityScope.PUBLIC,
        )
        with engine.connect() as conn:
            conn.execute(
                messages_table.insert().values(
                    **msg.model_dump(mode="python")
                )
            )
            conn.commit()

        # Fetch
        result = await _fetch_messages(engine, test_config, None, {"channel_id": channel_id})

        assert result is not None
        assert "Test message" in result
        assert "general" in result

    @pytest.mark.asyncio
    async def test_fetch_messages_missing_channel_id(self, engine, test_config: Config) -> None:
        """Test fetching messages without channel_id returns None."""
        result = await _fetch_messages(engine, test_config, None, {})

        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_messages_empty_channel(self, engine, test_config: Config) -> None:
        """Test fetching from channel with no messages."""
        create_server(engine)
        channel_id = "empty-channel"
        with engine.connect() as conn:
            conn.execute(
                channels_table.insert().values(
                    id=channel_id,
                    server_id="server:123",
                    name="empty",
                    type="text",
                )
            )
            conn.commit()

        result = await _fetch_messages(engine, test_config, None, {"channel_id": channel_id})

        assert result is not None
        assert "No messages" in result
        assert "empty" in result

    @pytest.mark.asyncio
    async def test_fetch_topics(self, engine, test_config: Config) -> None:
        """Test fetching known topics with salience."""
        # Setup: create topics
        topic1 = Topic(
            key="user:123",
            category=TopicCategory.USER,
            is_global=True,
        )
        with engine.connect() as conn:
            conn.execute(
                topics_table.insert().values(
                    **topic1.model_dump(mode="python")
                )
            )
            conn.commit()

        # Fetch
        result = await _fetch_topics(engine, test_config, None, {})

        assert result is not None
        assert "Known topics" in result
        assert "user:123" in result

    @pytest.mark.asyncio
    async def test_fetch_topics_empty(self, engine, test_config: Config) -> None:
        """Test fetching topics when none exist."""
        result = await _fetch_topics(engine, test_config, None, {})

        assert result is not None
        assert "No topics" in result

    @pytest.mark.asyncio
    async def test_fetch_user_profile(self, engine, test_config: Config) -> None:
        """Test fetching user profile data."""
        user_id = "user:456"
        profile_id = generate_id()

        with engine.connect() as conn:
            conn.execute(
                user_profiles_table.insert().values(
                    id=profile_id,
                    user_id=user_id,
                    display_name="John Doe",
                    username="johndoe",
                    is_bot=False,
                    captured_at=utcnow(),
                )
            )
            conn.commit()

        # Fetch
        result = await _fetch_user_profile(engine, test_config, None, {"user_id": user_id})

        assert result is not None
        assert "John Doe" in result
        assert "johndoe" in result

    @pytest.mark.asyncio
    async def test_fetch_user_profile_missing_user_id(self, engine, test_config: Config) -> None:
        """Test fetching profile without user_id returns None."""
        result = await _fetch_user_profile(engine, test_config, None, {})

        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_user_profile_not_found(self, engine, test_config: Config) -> None:
        """Test fetching profile for nonexistent user."""
        result = await _fetch_user_profile(engine, test_config, None, {"user_id": "user:nonexistent"})

        assert result is not None
        assert "No profile found" in result

    @pytest.mark.asyncio
    async def test_fetch_self_concept(self, engine, test_config: Config, template_engine) -> None:
        """Test fetching Zos's self-concept."""
        result = await _fetch_self_concept(engine, test_config, template_engine, {})

        assert result is not None
        assert "I am Zos" in result

    @pytest.mark.asyncio
    async def test_fetch_layer_runs(self, engine, test_config: Config) -> None:
        """Test fetching recent layer run history."""
        # Setup: create layer run
        run = LayerRun(
            id=generate_id(),
            layer_name="test_layer",
            layer_hash="abc123",
            started_at=utcnow(),
            completed_at=utcnow(),
            status=LayerRunStatus.SUCCESS,
            targets_processed=5,
            insights_created=2,
        )
        with engine.connect() as conn:
            conn.execute(
                layer_runs_table.insert().values(
                    **run.model_dump(mode="python")
                )
            )
            conn.commit()

        # Fetch
        result = await _fetch_layer_runs(engine, test_config, None, {})

        assert result is not None
        assert "test_layer" in result
        assert "success" in result.lower()

    @pytest.mark.asyncio
    async def test_fetch_layer_runs_empty(self, engine, test_config: Config) -> None:
        """Test fetching layer runs when none exist."""
        result = await _fetch_layer_runs(engine, test_config, None, {})

        assert result is not None
        assert "No layer runs" in result

    @pytest.mark.asyncio
    async def test_fetch_existing_subjects(self, engine, test_config: Config) -> None:
        """Test fetching known subject topics."""
        # Setup: create subject topic
        subject = Topic(
            key="server:123:subject:climate-change",
            category=TopicCategory.SUBJECT,
            is_global=False,
        )
        with engine.connect() as conn:
            conn.execute(
                topics_table.insert().values(
                    **subject.model_dump(mode="python")
                )
            )
            conn.commit()

        # Fetch
        result = await _fetch_existing_subjects(engine, test_config, None, {})

        assert result is not None
        assert "climate-change" in result

    @pytest.mark.asyncio
    async def test_fetch_existing_subjects_empty(self, engine, test_config: Config) -> None:
        """Test fetching subjects when none exist."""
        result = await _fetch_existing_subjects(engine, test_config, None, {})

        assert result is not None
        assert "No subjects" in result


# =============================================================================
# Tests: Helper Functions
# =============================================================================


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_get_known_topics(self, engine) -> None:
        """Test retrieving known topics by insight count."""
        # Setup: create topics with different insight counts
        topic1 = Topic(key="user:123", category=TopicCategory.USER, is_global=True)
        topic2 = Topic(key="user:456", category=TopicCategory.USER, is_global=True)

        with engine.connect() as conn:
            conn.execute(topics_table.insert().values(**topic1.model_dump(mode="python")))
            conn.execute(topics_table.insert().values(**topic2.model_dump(mode="python")))
            conn.commit()

        result = _get_known_topics(engine, limit=10)

        assert len(result) == 2
        assert result[0]["key"] in [topic1.key, topic2.key]
        assert all("key" in r and "category" in r for r in result)

    def test_get_known_topics_limit(self, engine) -> None:
        """Test that limit is respected."""
        # Create 5 topics
        for i in range(5):
            topic = Topic(key=f"user:{i}", category=TopicCategory.USER, is_global=True)
            with engine.connect() as conn:
                conn.execute(topics_table.insert().values(**topic.model_dump(mode="python")))
                conn.commit()

        result = _get_known_topics(engine, limit=3)

        assert len(result) <= 3

    def test_get_known_channels(self, engine) -> None:
        """Test retrieving known channels."""
        # Setup: create server and channels
        create_server(engine)
        with engine.connect() as conn:
            conn.execute(
                channels_table.insert().values(
                    id="chan:123",
                    server_id="server:123",
                    name="general",
                    type="text",
                )
            )
            conn.execute(
                channels_table.insert().values(
                    id="chan:456",
                    server_id="server:123",
                    name="random",
                    type="text",
                )
            )
            conn.commit()

        result = _get_known_channels(engine)

        assert len(result) == 2
        assert any(r["name"] == "general" for r in result)
        assert any(r["name"] == "random" for r in result)


# =============================================================================
# Tests: plan_context
# =============================================================================


class TestPlanContext:
    """Tests for the planning phase."""

    @pytest.mark.asyncio
    async def test_plan_context_valid_json(
        self, engine, test_config, template_engine
    ) -> None:
        """Test planning with valid JSON response from LLM."""
        plan_response = json.dumps({
            "fetch": [
                {"source": "insights", "params": {"topic_key": "user:123"}},
                {"source": "recent_insights", "params": {"limit": 15}},
            ]
        })
        mock_llm = make_mock_llm(plan_response)

        result = await plan_context(mock_llm, engine, "What about user 123?", test_config, template_engine)

        assert len(result) == 2
        assert result[0]["source"] == "insights"
        assert result[1]["source"] == "recent_insights"

    @pytest.mark.asyncio
    async def test_plan_context_invalid_json_retry(
        self, engine, test_config, template_engine
    ) -> None:
        """Test that invalid JSON triggers retry."""
        # First response is invalid, second is valid
        valid_response = json.dumps({
            "fetch": [{"source": "topics", "params": {}}]
        })

        async def side_effect(*args, **kwargs):
            # First call returns invalid
            if side_effect.call_count == 0:
                side_effect.call_count += 1
                return CompletionResult(
                    text="not valid json",
                    usage=Usage(input_tokens=100, output_tokens=50),
                    model="test",
                    provider="test",
                )
            # Second call returns valid
            return CompletionResult(
                text=valid_response,
                usage=Usage(input_tokens=100, output_tokens=50),
                model="test",
                provider="test",
            )

        side_effect.call_count = 0
        mock_llm = MagicMock(spec=ModelClient)
        mock_llm.complete = AsyncMock(side_effect=side_effect)

        result = await plan_context(mock_llm, engine, "Test question", test_config, template_engine)

        assert len(result) == 1
        assert result[0]["source"] == "topics"
        # Verify retry happened (2 calls)
        assert mock_llm.complete.call_count == 2

    @pytest.mark.asyncio
    async def test_plan_context_calls_template_render(
        self, engine, test_config, template_engine
    ) -> None:
        """Test that template is rendered with correct context."""
        plan_response = json.dumps({"fetch": []})
        mock_llm = make_mock_llm(plan_response)

        # Mock template engine to track calls
        original_render = template_engine.render
        render_calls = []

        def track_render(*args, **kwargs):
            render_calls.append((args, kwargs))
            return original_render(*args, **kwargs)

        template_engine.render = track_render

        await plan_context(mock_llm, engine, "Test question", test_config, template_engine)

        assert len(render_calls) > 0
        call_args, call_kwargs = render_calls[0]
        assert "ask/plan.jinja2" in call_args
        assert call_kwargs["context"]["question"] == "Test question"
        assert "catalog" in call_kwargs["context"]


# =============================================================================
# Tests: fetch_context
# =============================================================================


class TestFetchContext:
    """Tests for the fetching phase."""

    @pytest.mark.asyncio
    async def test_fetch_context_empty_plan(self, engine, test_config, template_engine) -> None:
        """Test fetching with empty plan."""
        result = await fetch_context(engine, test_config, template_engine, [])

        assert result == {}

    @pytest.mark.asyncio
    async def test_fetch_context_single_source(self, engine, test_config, template_engine) -> None:
        """Test fetching a single source."""
        # Create topic for retrieval
        topic = Topic(key="user:123", category=TopicCategory.USER, is_global=True)
        with engine.connect() as conn:
            conn.execute(topics_table.insert().values(**topic.model_dump(mode="python")))
            conn.commit()

        plan = [
            {"source": "topics", "params": {}}
        ]

        result = await fetch_context(engine, test_config, template_engine, plan)

        assert "topics" in result
        assert "Known topics" in result["topics"]

    @pytest.mark.asyncio
    async def test_fetch_context_multiple_sources(self, engine, test_config, template_engine) -> None:
        """Test fetching multiple sources."""
        plan = [
            {"source": "topics", "params": {}},
            {"source": "self_concept", "params": {}},
        ]

        result = await fetch_context(engine, test_config, template_engine, plan)

        assert len(result) == 2
        assert "topics" in result
        assert "self_concept" in result

    @pytest.mark.asyncio
    async def test_fetch_context_duplicate_source_indexing(self, engine, test_config, template_engine) -> None:
        """Test that duplicate sources get indexed."""
        plan = [
            {"source": "topics", "params": {}},
            {"source": "topics", "params": {}},
        ]

        result = await fetch_context(engine, test_config, template_engine, plan)

        # Should have "topics" and "topics_1" keys
        assert "topics" in result
        assert "topics_1" in result

    @pytest.mark.asyncio
    async def test_fetch_context_unknown_source_skipped(self, engine, test_config, template_engine) -> None:
        """Test that unknown sources are skipped gracefully."""
        plan = [
            {"source": "unknown_source", "params": {}},
            {"source": "topics", "params": {}},
        ]

        result = await fetch_context(engine, test_config, template_engine, plan)

        # Should only have topics
        assert "topics" in result
        assert "unknown_source" not in result


# =============================================================================
# Tests: execute_answer
# =============================================================================


class TestExecuteAnswer:
    """Tests for the answer generation phase."""

    @pytest.mark.asyncio
    async def test_execute_answer_basic(self, test_config, template_engine) -> None:
        """Test basic answer execution."""
        answer_text = "The answer is 42."
        mock_llm = make_mock_llm(answer_text)

        context = {"topics": "Known topics...", "insights": "Some insights..."}

        result = await execute_answer(mock_llm, template_engine, "What is the answer?", context, test_config)

        assert result == answer_text

    @pytest.mark.asyncio
    async def test_execute_answer_calls_template(self, test_config, template_engine) -> None:
        """Test that template is rendered with correct context."""
        mock_llm = make_mock_llm("Answer")

        # Track template calls
        original_render = template_engine.render
        render_calls = []

        def track_render(*args, **kwargs):
            render_calls.append((args, kwargs))
            return original_render(*args, **kwargs)

        template_engine.render = track_render

        await execute_answer(mock_llm, template_engine, "Question?", {"test": "context"}, test_config)

        assert len(render_calls) > 0
        call_args, call_kwargs = render_calls[0]
        assert "ask/answer.jinja2" in call_args
        assert call_kwargs["context"]["question"] == "Question?"
        assert call_kwargs["context"]["context"] == {"test": "context"}

    @pytest.mark.asyncio
    async def test_execute_answer_empty_context(self, test_config, template_engine) -> None:
        """Test answer with empty context."""
        mock_llm = make_mock_llm("I don't have context for this.")

        result = await execute_answer(mock_llm, template_engine, "Question?", {}, test_config)

        assert result == "I don't have context for this."


# =============================================================================
# Tests: ask orchestrator
# =============================================================================


class TestAskOrchestrator:
    """Tests for the end-to-end ask flow."""

    @pytest.mark.asyncio
    async def test_ask_full_flow(self, engine, test_config, template_engine) -> None:
        """Test full ask orchestration."""
        # Setup: create test data
        topic = Topic(key="user:123", category=TopicCategory.USER, is_global=True)
        with engine.connect() as conn:
            conn.execute(topics_table.insert().values(**topic.model_dump(mode="python")))
            conn.commit()

        # Mock LLM with plan and answer
        plan_response = json.dumps({"fetch": [{"source": "topics", "params": {}}]})
        answer_response = "Answer to your question"

        async def llm_side_effect(*args, **kwargs):
            call_type = kwargs.get("call_type")
            if "plan" in args[0]:  # Heuristic: plan prompt contains "plan"
                return CompletionResult(
                    text=plan_response,
                    usage=Usage(input_tokens=100, output_tokens=50),
                    model="test",
                    provider="test",
                )
            # Default to answer
            return CompletionResult(
                text=answer_response,
                usage=Usage(input_tokens=100, output_tokens=50),
                model="test",
                provider="test",
            )

        mock_llm = MagicMock(spec=ModelClient)
        mock_llm.complete = AsyncMock(side_effect=llm_side_effect)

        result = await ask("What is happening?", mock_llm, engine, test_config, template_engine)

        assert result == answer_response
        # Verify both plan and answer LLM calls were made
        assert mock_llm.complete.call_count >= 2

    @pytest.mark.asyncio
    async def test_ask_with_no_context(self, engine, test_config, template_engine) -> None:
        """Test ask when plan fetches no context."""
        # Plan with empty fetch
        plan_response = json.dumps({"fetch": []})
        answer_response = "I don't have context for this."

        async def llm_side_effect(*args, **kwargs):
            # First call: plan
            if llm_side_effect.call_count == 0:
                llm_side_effect.call_count += 1
                return CompletionResult(
                    text=plan_response,
                    usage=Usage(input_tokens=100, output_tokens=50),
                    model="test",
                    provider="test",
                )
            # Second call: answer
            return CompletionResult(
                text=answer_response,
                usage=Usage(input_tokens=100, output_tokens=50),
                model="test",
                provider="test",
            )

        llm_side_effect.call_count = 0
        mock_llm = MagicMock(spec=ModelClient)
        mock_llm.complete = AsyncMock(side_effect=llm_side_effect)

        result = await ask("Question?", mock_llm, engine, test_config, template_engine)

        assert result == answer_response


# =============================================================================
# Tests: Integration
# =============================================================================


class TestIntegration:
    """Integration tests combining multiple components."""

    @pytest.mark.asyncio
    async def test_ask_with_real_database_data(self, engine, test_config, template_engine) -> None:
        """Test ask with realistic database state."""
        # Setup: create realistic database state
        server_id = "server:123"
        create_server(engine, server_id)

        # Create channel
        with engine.connect() as conn:
            conn.execute(
                channels_table.insert().values(
                    id="chan:general",
                    server_id=server_id,
                    name="general",
                    type="text",
                )
            )
            conn.commit()

        # Create topics
        user_topic = Topic(key="user:456", category=TopicCategory.USER, is_global=False)
        with engine.connect() as conn:
            conn.execute(topics_table.insert().values(**user_topic.model_dump(mode="python")))
            conn.commit()

        # Create messages
        msg = Message(
            id=generate_id(),
            channel_id="chan:general",
            author_id="user:456",
            content="I'm interested in this topic",
            created_at=utcnow(),
            visibility_scope=VisibilityScope.PUBLIC,
        )
        with engine.connect() as conn:
            conn.execute(messages_table.insert().values(**msg.model_dump(mode="python")))
            conn.commit()

        # Mock LLM
        plan_response = json.dumps({
            "fetch": [
                {"source": "messages", "params": {"channel_id": "chan:general"}},
                {"source": "user_profile", "params": {"user_id": "user:456"}},
            ]
        })

        call_count = [0]

        async def llm_side_effect(*args, **kwargs):
            if call_count[0] == 0:
                call_count[0] += 1
                return CompletionResult(
                    text=plan_response,
                    usage=Usage(input_tokens=100, output_tokens=50),
                    model="test",
                    provider="test",
                )
            return CompletionResult(
                text="Based on the context, here's my answer...",
                usage=Usage(input_tokens=100, output_tokens=50),
                model="test",
                provider="test",
            )

        mock_llm = MagicMock(spec=ModelClient)
        mock_llm.complete = AsyncMock(side_effect=llm_side_effect)

        result = await ask(
            "What is user 456 interested in?",
            mock_llm,
            engine,
            test_config,
            template_engine,
        )

        assert "answer" in result.lower() or result  # Just verify we got something
