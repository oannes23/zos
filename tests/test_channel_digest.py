"""End-to-end integration tests for the channel_digest layer.

Phase 9 validation tests that verify the complete reflection pipeline works:
- Layer definition loading and validation
- Message fetching and context assembly
- Jinja2 prompt rendering
- LLM call execution (mocked)
- Insight storage and retrieval
- RunManager integration
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from zos.budget.models import AllocationPlan, CategoryAllocation, TopicAllocation
from zos.config import BudgetConfig, CategoryWeights, DatabaseConfig, ZosConfig
from zos.db import Database
from zos.insights import InsightRepository
from zos.layer.executor import PipelineExecutor
from zos.layer.loader import LayerLoader
from zos.salience.repository import SalienceRepository
from zos.scheduler.models import Run, RunStatus, TriggerType
from zos.scheduler.repository import RunRepository
from zos.scheduler.run_manager import RunManager
from zos.topics.topic_key import TopicCategory, TopicKey

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def layers_dir() -> Path:
    """Get the actual layers directory."""
    return Path(__file__).parent.parent / "layers"


@pytest.fixture
def layer_loader(layers_dir: Path) -> LayerLoader:
    """Create a layer loader with the actual layers directory."""
    return LayerLoader(layers_dir)


@pytest.fixture
def test_db_with_messages(tmp_path: Path) -> Database:
    """Create a test database with sample messages."""
    config = DatabaseConfig(path=tmp_path / "test.db")
    db = Database(config)
    db.initialize()

    # Insert sample messages for testing
    now = datetime.now(UTC)
    messages = [
        {
            "message_id": 1001,
            "guild_id": 12345,
            "channel_id": 123456,
            "author_id": 100,
            "author_name": "Alice",
            "author_roles_snapshot": "Member",
            "content": "Hey everyone! I just finished that Python tutorial.",
            "created_at": (now - timedelta(hours=2)).isoformat(),
            "visibility_scope": "public",
        },
        {
            "message_id": 1002,
            "guild_id": 12345,
            "channel_id": 123456,
            "author_id": 101,
            "author_name": "Bob",
            "author_roles_snapshot": "Member",
            "content": "Nice! What did you think about the asyncio section?",
            "created_at": (now - timedelta(hours=1, minutes=45)).isoformat(),
            "visibility_scope": "public",
        },
        {
            "message_id": 1003,
            "guild_id": 12345,
            "channel_id": 123456,
            "author_id": 100,
            "author_name": "Alice",
            "author_roles_snapshot": "Member",
            "content": "It was tricky but really helpful. Still wrapping my head around await.",
            "created_at": (now - timedelta(hours=1, minutes=30)).isoformat(),
            "visibility_scope": "public",
        },
        {
            "message_id": 1004,
            "guild_id": 12345,
            "channel_id": 123456,
            "author_id": 102,
            "author_name": "Charlie",
            "author_roles_snapshot": "Admin",
            "content": "Don't forget we have the weekly sync tomorrow at 3pm!",
            "created_at": (now - timedelta(hours=1)).isoformat(),
            "visibility_scope": "public",
        },
        {
            "message_id": 1005,
            "guild_id": 12345,
            "channel_id": 123456,
            "author_id": 101,
            "author_name": "Bob",
            "author_roles_snapshot": "Member",
            "content": "Thanks for the reminder! I'll be there.",
            "created_at": (now - timedelta(minutes=30)).isoformat(),
            "visibility_scope": "public",
        },
    ]

    with db.transaction():
        for msg in messages:
            db.execute(
                """
                INSERT INTO messages (
                    message_id, guild_id, channel_id, author_id, author_name,
                    author_roles_snapshot, content, created_at, visibility_scope
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    msg["message_id"],
                    msg["guild_id"],
                    msg["channel_id"],
                    msg["author_id"],
                    msg["author_name"],
                    msg["author_roles_snapshot"],
                    msg["content"],
                    msg["created_at"],
                    msg["visibility_scope"],
                ),
            )

    yield db
    db.close()


@pytest.fixture
def mock_llm_client() -> MagicMock:
    """Create a mock LLM client with realistic response."""
    client = MagicMock()

    # Realistic channel digest response
    mock_response = MagicMock()
    mock_response.content = """## Activity Summary
The channel had moderate activity with 5 messages from 3 participants.
The mood was collaborative and educational, with members sharing learning experiences.

## Key Topics
1. **Python Learning** - Alice shared progress on Python tutorials, specifically asyncio
2. **Weekly Sync** - Charlie reminded the group about the upcoming meeting

## Notable Moments
- Alice and Bob had an engaging exchange about asyncio and await patterns
- The community showed good responsiveness to meeting reminders

## Emerging Themes
- Interest in Python async programming is growing
- The team maintains good communication about scheduled events"""

    mock_response.prompt_tokens = 250
    mock_response.completion_tokens = 180

    client.complete_with_prompt = AsyncMock(return_value=mock_response)
    client.prompts = MagicMock()
    client.prompts.prompt_exists.return_value = True
    client.prompts.load_prompt.return_value = "Test prompt content"
    client.prompts.render_prompt = MagicMock(return_value="Rendered prompt")

    return client


@pytest.fixture
def test_config(tmp_path: Path, layers_dir: Path) -> ZosConfig:
    """Create a test configuration."""
    return ZosConfig(
        database=DatabaseConfig(path=tmp_path / "test.db"),
        budget=BudgetConfig(
            total_tokens_per_run=50000,
            per_topic_cap=5000,
            category_weights=CategoryWeights(channel=100),  # Focus on channels
        ),
        layers_dir=layers_dir,
    )


@pytest.fixture
def allocation_plan_for_channel(test_db_with_messages: Database) -> AllocationPlan:
    """Create an allocation plan with a channel topic and corresponding run record."""
    channel_topic = TopicKey.channel(123456)
    run_id = "test-run-phase9"
    now = datetime.now(UTC)

    # Create a run record to satisfy foreign key constraints
    run_repo = RunRepository(test_db_with_messages)
    run = Run(
        run_id=run_id,
        layer_name="channel_digest",
        triggered_by=TriggerType.MANUAL,
        status=RunStatus.RUNNING,
        started_at=now,
        window_start=now - timedelta(hours=24),
        window_end=now,
    )
    run_repo.create_run(run)

    return AllocationPlan(
        run_id=run_id,
        total_budget=50000,
        per_topic_cap=5000,
        category_allocations={
            TopicCategory.CHANNEL: CategoryAllocation(
                category=TopicCategory.CHANNEL,
                weight=100,
                total_tokens=50000,
                topic_allocations=[
                    TopicAllocation(
                        topic_key=channel_topic,
                        allocated_tokens=5000,
                        salience_balance=100.0,
                        salience_proportion=1.0,
                    ),
                ],
            ),
        },
        created_at=now,
    )


# =============================================================================
# Layer Definition Tests
# =============================================================================


class TestChannelDigestLayerDefinition:
    """Tests for channel_digest layer definition."""

    def test_layer_exists(self, layers_dir: Path) -> None:
        """Test that the channel_digest layer exists."""
        layer_path = layers_dir / "channel_digest" / "layer.yml"
        assert layer_path.exists(), f"Layer file not found: {layer_path}"

    def test_layer_loads_successfully(self, layer_loader: LayerLoader) -> None:
        """Test that the layer definition loads without errors."""
        layer = layer_loader.load("channel_digest")

        assert layer.name == "channel_digest"
        assert layer.schedule is not None
        assert "channel" in layer.targets.categories

    def test_layer_validates(self, layer_loader: LayerLoader) -> None:
        """Test that layer validation passes."""
        errors = layer_loader.validate("channel_digest")
        assert errors == [], f"Layer validation errors: {errors}"

    def test_prompts_exist(self, layers_dir: Path) -> None:
        """Test that all required prompts exist."""
        prompts_dir = layers_dir / "channel_digest" / "prompts"
        assert prompts_dir.exists()

        assert (prompts_dir / "system.j2").exists()
        assert (prompts_dir / "summarize.j2").exists()

    def test_layer_has_correct_pipeline(self, layer_loader: LayerLoader) -> None:
        """Test that the pipeline has expected nodes."""
        layer = layer_loader.load("channel_digest")

        node_types = [n.type for n in layer.pipeline.nodes]
        assert "fetch_messages" in node_types
        assert "fetch_insights" in node_types
        assert "llm_call" in node_types
        assert "store_insight" in node_types
        assert "output" in node_types

    def test_layer_targets_channels(self, layer_loader: LayerLoader) -> None:
        """Test that the layer targets channels."""
        layer = layer_loader.load("channel_digest")

        assert "channel" in layer.targets.categories
        assert layer.targets.min_salience > 0  # Has minimum threshold

    def test_layer_has_schedule(self, layer_loader: LayerLoader) -> None:
        """Test that the layer has a cron schedule."""
        layer = layer_loader.load("channel_digest")

        assert layer.schedule is not None
        # Should be a valid cron expression (e.g., "0 3 * * *")
        assert len(layer.schedule.split()) == 5


# =============================================================================
# Prompt Rendering Tests
# =============================================================================


class TestPromptRendering:
    """Tests for Jinja2 prompt template rendering."""

    def test_system_prompt_loads(self, layers_dir: Path) -> None:
        """Test that system prompt loads correctly."""
        prompt_path = layers_dir / "channel_digest" / "prompts" / "system.j2"
        content = prompt_path.read_text()

        assert "Zos" in content
        assert "analyst" in content.lower() or "analyze" in content.lower()

    def test_summarize_prompt_loads(self, layers_dir: Path) -> None:
        """Test that summarize prompt loads correctly."""
        prompt_path = layers_dir / "channel_digest" / "prompts" / "summarize.j2"
        content = prompt_path.read_text()

        # Should reference expected variables
        assert "messages" in content or "messages_text" in content
        assert "insights" in content

    def test_summarize_prompt_renders_with_messages(self, layers_dir: Path) -> None:
        """Test that summarize prompt renders correctly with message data."""
        from jinja2 import Environment, FileSystemLoader

        prompts_dir = layers_dir / "channel_digest" / "prompts"
        env = Environment(loader=FileSystemLoader(str(prompts_dir)))
        template = env.get_template("summarize.j2")

        # Render with sample data
        context = {
            "messages_text": "Alice: Hello everyone!\nBob: Hi Alice!",
            "insights": [
                {"summary": "Previous insight about channel activity"},
            ],
        }
        rendered = template.render(**context)

        assert "Alice" in rendered
        assert "Bob" in rendered
        assert "Previous insight" in rendered

    def test_summarize_prompt_handles_empty_messages(self, layers_dir: Path) -> None:
        """Test that summarize prompt handles empty messages gracefully."""
        from jinja2 import Environment, FileSystemLoader

        prompts_dir = layers_dir / "channel_digest" / "prompts"
        env = Environment(loader=FileSystemLoader(str(prompts_dir)))
        template = env.get_template("summarize.j2")

        # Render with empty data
        context = {
            "messages_text": "",
            "insights": [],
        }
        rendered = template.render(**context)

        # Should still produce valid output
        assert len(rendered) > 0
        # Should indicate no messages
        assert "No messages" in rendered or "no messages" in rendered.lower()


# =============================================================================
# Pipeline Execution Tests
# =============================================================================


class TestPipelineExecution:
    """Tests for pipeline execution with channel_digest layer."""

    @pytest.fixture
    def executor(
        self,
        test_db_with_messages: Database,
        mock_llm_client: MagicMock,
        test_config: ZosConfig,
    ) -> PipelineExecutor:
        """Create a pipeline executor."""
        return PipelineExecutor(
            db=test_db_with_messages,
            llm_client=mock_llm_client,
            config=test_config,
        )

    @pytest.mark.asyncio
    async def test_execute_channel_digest_success(
        self,
        executor: PipelineExecutor,
        layer_loader: LayerLoader,
        allocation_plan_for_channel: AllocationPlan,
    ) -> None:
        """Test successful execution of channel_digest layer."""
        layer = layer_loader.load("channel_digest")

        result = await executor.execute(
            layer=layer,
            allocation_plan=allocation_plan_for_channel,
        )

        assert result.success is True
        assert result.layer_name == "channel_digest"
        assert result.targets_processed >= 1

    @pytest.mark.asyncio
    async def test_execute_fetches_messages(
        self,
        executor: PipelineExecutor,
        layer_loader: LayerLoader,
        allocation_plan_for_channel: AllocationPlan,
    ) -> None:
        """Test that execution fetches messages correctly."""
        layer = layer_loader.load("channel_digest")

        result = await executor.execute(
            layer=layer,
            allocation_plan=allocation_plan_for_channel,
        )

        # Check trace for fetch_messages node (named "get_recent_messages" in layer.yml)
        fetch_trace = next(
            (t for t in result.trace if t["node"] == "get_recent_messages"), None
        )
        assert fetch_trace is not None
        assert fetch_trace["success"] is True

    @pytest.mark.asyncio
    async def test_execute_calls_llm(
        self,
        executor: PipelineExecutor,
        layer_loader: LayerLoader,
        allocation_plan_for_channel: AllocationPlan,
        mock_llm_client: MagicMock,
    ) -> None:
        """Test that execution calls the LLM."""
        layer = layer_loader.load("channel_digest")

        await executor.execute(
            layer=layer,
            allocation_plan=allocation_plan_for_channel,
        )

        # LLM should have been called
        mock_llm_client.complete_with_prompt.assert_called()

    @pytest.mark.asyncio
    async def test_execute_stores_insight(
        self,
        executor: PipelineExecutor,
        layer_loader: LayerLoader,
        allocation_plan_for_channel: AllocationPlan,
        test_db_with_messages: Database,
    ) -> None:
        """Test that execution stores an insight."""
        layer = layer_loader.load("channel_digest")

        result = await executor.execute(
            layer=layer,
            allocation_plan=allocation_plan_for_channel,
        )

        assert result.success is True

        # Check that insight was stored
        insight_repo = InsightRepository(test_db_with_messages)
        topic = TopicKey.channel(123456)
        insights = insight_repo.get_insights(topic)

        assert len(insights) >= 1
        assert insights[0].layer == "channel_digest"

    @pytest.mark.asyncio
    async def test_execute_dry_run(
        self,
        executor: PipelineExecutor,
        layer_loader: LayerLoader,
        allocation_plan_for_channel: AllocationPlan,
        test_db_with_messages: Database,
    ) -> None:
        """Test dry-run mode doesn't store insights."""
        layer = layer_loader.load("channel_digest")

        result = await executor.execute(
            layer=layer,
            allocation_plan=allocation_plan_for_channel,
            dry_run=True,
        )

        assert result.success is True

        # Should not have stored insights
        insight_repo = InsightRepository(test_db_with_messages)
        topic = TopicKey.channel(123456)
        insights = insight_repo.get_insights(topic)

        assert len(insights) == 0

    @pytest.mark.asyncio
    async def test_execute_tracks_tokens(
        self,
        executor: PipelineExecutor,
        layer_loader: LayerLoader,
        allocation_plan_for_channel: AllocationPlan,
    ) -> None:
        """Test that token usage is tracked."""
        layer = layer_loader.load("channel_digest")

        result = await executor.execute(
            layer=layer,
            allocation_plan=allocation_plan_for_channel,
        )

        assert result.total_tokens > 0
        # Should include prompt + completion tokens
        assert result.total_tokens == 430  # 250 + 180 from mock

    @pytest.mark.asyncio
    async def test_execute_records_trace(
        self,
        executor: PipelineExecutor,
        layer_loader: LayerLoader,
        allocation_plan_for_channel: AllocationPlan,
    ) -> None:
        """Test that execution trace is recorded."""
        layer = layer_loader.load("channel_digest")

        result = await executor.execute(
            layer=layer,
            allocation_plan=allocation_plan_for_channel,
        )

        # Trace should have entries for each node (using layer-defined names)
        node_names = {t["node"] for t in result.trace}
        assert "get_recent_messages" in node_names  # fetch_messages
        assert "get_prior_insights" in node_names  # fetch_insights
        assert "summarize" in node_names  # llm_call
        assert "save_summary" in node_names  # store_insight
        assert "log_output" in node_names  # output


# =============================================================================
# Insight Storage Tests
# =============================================================================


class TestInsightStorage:
    """Tests for insight storage from channel_digest layer."""

    @pytest.mark.asyncio
    async def test_insight_has_correct_topic(
        self,
        test_db_with_messages: Database,
        mock_llm_client: MagicMock,
        test_config: ZosConfig,
        layer_loader: LayerLoader,
        allocation_plan_for_channel: AllocationPlan,
    ) -> None:
        """Test that stored insight has correct topic key."""
        executor = PipelineExecutor(
            db=test_db_with_messages,
            llm_client=mock_llm_client,
            config=test_config,
        )
        layer = layer_loader.load("channel_digest")

        await executor.execute(layer, allocation_plan_for_channel)

        insight_repo = InsightRepository(test_db_with_messages)
        topic = TopicKey.channel(123456)
        insights = insight_repo.get_insights(topic)

        assert len(insights) >= 1
        assert insights[0].topic_key == "channel:123456"

    @pytest.mark.asyncio
    async def test_insight_has_summary(
        self,
        test_db_with_messages: Database,
        mock_llm_client: MagicMock,
        test_config: ZosConfig,
        layer_loader: LayerLoader,
        allocation_plan_for_channel: AllocationPlan,
    ) -> None:
        """Test that stored insight has LLM-generated summary."""
        executor = PipelineExecutor(
            db=test_db_with_messages,
            llm_client=mock_llm_client,
            config=test_config,
        )
        layer = layer_loader.load("channel_digest")

        await executor.execute(layer, allocation_plan_for_channel)

        insight_repo = InsightRepository(test_db_with_messages)
        topic = TopicKey.channel(123456)
        insights = insight_repo.get_insights(topic)

        assert len(insights) >= 1
        # Summary should contain content from mock LLM response
        assert "Activity Summary" in insights[0].summary

    @pytest.mark.asyncio
    async def test_insight_has_source_refs(
        self,
        test_db_with_messages: Database,
        mock_llm_client: MagicMock,
        test_config: ZosConfig,
        layer_loader: LayerLoader,
        allocation_plan_for_channel: AllocationPlan,
    ) -> None:
        """Test that stored insight has source message references."""
        executor = PipelineExecutor(
            db=test_db_with_messages,
            llm_client=mock_llm_client,
            config=test_config,
        )
        layer = layer_loader.load("channel_digest")

        await executor.execute(layer, allocation_plan_for_channel)

        insight_repo = InsightRepository(test_db_with_messages)
        topic = TopicKey.channel(123456)
        insights = insight_repo.get_insights(topic)

        assert len(insights) >= 1
        # Should have source references to the messages
        assert len(insights[0].source_refs) > 0

    @pytest.mark.asyncio
    async def test_insight_has_correct_scope(
        self,
        test_db_with_messages: Database,
        mock_llm_client: MagicMock,
        test_config: ZosConfig,
        layer_loader: LayerLoader,
        allocation_plan_for_channel: AllocationPlan,
    ) -> None:
        """Test that stored insight has correct privacy scope."""
        executor = PipelineExecutor(
            db=test_db_with_messages,
            llm_client=mock_llm_client,
            config=test_config,
        )
        layer = layer_loader.load("channel_digest")

        await executor.execute(layer, allocation_plan_for_channel)

        insight_repo = InsightRepository(test_db_with_messages)
        topic = TopicKey.channel(123456)
        insights = insight_repo.get_insights(topic)

        assert len(insights) >= 1
        # All test messages are public, so scope should be public
        assert insights[0].sources_scope_max == "public"

    @pytest.mark.asyncio
    async def test_insight_has_layer_attribution(
        self,
        test_db_with_messages: Database,
        mock_llm_client: MagicMock,
        test_config: ZosConfig,
        layer_loader: LayerLoader,
        allocation_plan_for_channel: AllocationPlan,
    ) -> None:
        """Test that stored insight has layer attribution."""
        executor = PipelineExecutor(
            db=test_db_with_messages,
            llm_client=mock_llm_client,
            config=test_config,
        )
        layer = layer_loader.load("channel_digest")

        await executor.execute(layer, allocation_plan_for_channel)

        insight_repo = InsightRepository(test_db_with_messages)
        topic = TopicKey.channel(123456)
        insights = insight_repo.get_insights(topic)

        assert len(insights) >= 1
        assert insights[0].layer == "channel_digest"


# =============================================================================
# Run Manager Integration Tests
# =============================================================================


class TestRunManagerIntegration:
    """Tests for RunManager integration with channel_digest layer."""

    @pytest.fixture
    def run_manager(
        self,
        test_db_with_messages: Database,
        mock_llm_client: MagicMock,
        test_config: ZosConfig,
        layer_loader: LayerLoader,
    ) -> RunManager:
        """Create a run manager."""
        return RunManager(
            db=test_db_with_messages,
            llm_client=mock_llm_client,
            config=test_config,
            layer_loader=layer_loader,
        )

    @pytest.mark.asyncio
    async def test_execute_layer_creates_run_record(
        self,
        run_manager: RunManager,
        test_db_with_messages: Database,
    ) -> None:
        """Test that executing layer creates a run record."""
        # Add salience so the layer has targets
        now = datetime.now(UTC)
        salience_repo = SalienceRepository(test_db_with_messages)
        salience_repo.earn(
            topic_key=TopicKey.channel(123456),
            amount=100.0,
            reason="test",
            timestamp=now,
        )

        result = await run_manager.execute_layer(
            layer_name="channel_digest",
            triggered_by=TriggerType.MANUAL,
        )

        assert result is not None
        assert result.layer_name == "channel_digest"
        assert result.status == RunStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_execute_layer_calculates_window(
        self,
        run_manager: RunManager,
        test_db_with_messages: Database,
    ) -> None:
        """Test that run has calculated time window."""
        from zos.salience.repository import SalienceRepository

        now = datetime.now(UTC)
        salience_repo = SalienceRepository(test_db_with_messages)
        salience_repo.earn(
            topic_key=TopicKey.channel(123456),
            amount=100.0,
            reason="test",
            timestamp=now,
        )

        result = await run_manager.execute_layer(
            layer_name="channel_digest",
            triggered_by=TriggerType.MANUAL,
        )

        assert result is not None
        assert result.window_start is not None
        assert result.window_end is not None
        assert result.window_start < result.window_end

    @pytest.mark.asyncio
    async def test_execute_layer_stores_trace(
        self,
        run_manager: RunManager,
        test_db_with_messages: Database,
    ) -> None:
        """Test that run stores execution trace."""
        from zos.salience.repository import SalienceRepository

        now = datetime.now(UTC)
        salience_repo = SalienceRepository(test_db_with_messages)
        salience_repo.earn(
            topic_key=TopicKey.channel(123456),
            amount=100.0,
            reason="test",
            timestamp=now,
        )

        result = await run_manager.execute_layer(
            layer_name="channel_digest",
            triggered_by=TriggerType.MANUAL,
        )

        assert result is not None

        run_repo = RunRepository(test_db_with_messages)
        trace = run_repo.get_trace(result.run_id)

        assert len(trace) > 0

    @pytest.mark.asyncio
    async def test_execute_layer_records_metrics(
        self,
        run_manager: RunManager,
        test_db_with_messages: Database,
    ) -> None:
        """Test that run records execution metrics."""
        from zos.salience.repository import SalienceRepository

        now = datetime.now(UTC)
        salience_repo = SalienceRepository(test_db_with_messages)
        salience_repo.earn(
            topic_key=TopicKey.channel(123456),
            amount=100.0,
            reason="test",
            timestamp=now,
        )

        result = await run_manager.execute_layer(
            layer_name="channel_digest",
            triggered_by=TriggerType.MANUAL,
        )

        assert result is not None
        assert result.tokens_used > 0
        assert result.targets_processed > 0

    @pytest.mark.asyncio
    async def test_execute_layer_skips_if_running(
        self,
        run_manager: RunManager,
        test_db_with_messages: Database,
    ) -> None:
        """Test that layer execution is skipped if already running."""
        # Create a running run
        run_repo = RunRepository(test_db_with_messages)
        now = datetime.now(UTC)
        existing_run = Run(
            run_id="existing-run",
            layer_name="channel_digest",
            triggered_by=TriggerType.SCHEDULE,
            status=RunStatus.RUNNING,
            started_at=now,
            window_start=now,
            window_end=now,
        )
        run_repo.create_run(existing_run)

        result = await run_manager.execute_layer(
            layer_name="channel_digest",
            triggered_by=TriggerType.MANUAL,
        )

        # Should skip and return None
        assert result is None

    @pytest.mark.asyncio
    async def test_execute_layer_stores_insights(
        self,
        run_manager: RunManager,
        test_db_with_messages: Database,
    ) -> None:
        """Test that layer execution stores insights."""
        from zos.salience.repository import SalienceRepository

        now = datetime.now(UTC)
        salience_repo = SalienceRepository(test_db_with_messages)
        salience_repo.earn(
            topic_key=TopicKey.channel(123456),
            amount=100.0,
            reason="test",
            timestamp=now,
        )

        result = await run_manager.execute_layer(
            layer_name="channel_digest",
            triggered_by=TriggerType.MANUAL,
        )

        assert result is not None

        # Verify insight was stored
        insight_repo = InsightRepository(test_db_with_messages)
        insights = insight_repo.get_insights_by_run(result.run_id)

        assert len(insights) >= 1

    @pytest.mark.asyncio
    async def test_dry_run_does_not_store_insights(
        self,
        run_manager: RunManager,
        test_db_with_messages: Database,
    ) -> None:
        """Test that dry-run does not store insights."""
        from zos.salience.repository import SalienceRepository

        now = datetime.now(UTC)
        salience_repo = SalienceRepository(test_db_with_messages)
        salience_repo.earn(
            topic_key=TopicKey.channel(123456),
            amount=100.0,
            reason="test",
            timestamp=now,
        )

        result = await run_manager.execute_layer(
            layer_name="channel_digest",
            triggered_by=TriggerType.MANUAL,
            dry_run=True,
        )

        assert result is not None

        # Verify no insights were stored
        insight_repo = InsightRepository(test_db_with_messages)
        insights = insight_repo.get_insights_by_run(result.run_id)

        assert len(insights) == 0


# =============================================================================
# Quality Validation Tests
# =============================================================================


class TestOutputQuality:
    """Tests for validating output quality of channel_digest layer."""

    @pytest.mark.asyncio
    async def test_summary_is_not_empty(
        self,
        test_db_with_messages: Database,
        mock_llm_client: MagicMock,
        test_config: ZosConfig,
        layer_loader: LayerLoader,
        allocation_plan_for_channel: AllocationPlan,
    ) -> None:
        """Test that generated summary is not empty."""
        executor = PipelineExecutor(
            db=test_db_with_messages,
            llm_client=mock_llm_client,
            config=test_config,
        )
        layer = layer_loader.load("channel_digest")

        await executor.execute(layer, allocation_plan_for_channel)

        insight_repo = InsightRepository(test_db_with_messages)
        topic = TopicKey.channel(123456)
        insights = insight_repo.get_insights(topic)

        assert len(insights) >= 1
        assert len(insights[0].summary) > 100  # Reasonable length

    @pytest.mark.asyncio
    async def test_summary_has_structure(
        self,
        test_db_with_messages: Database,
        mock_llm_client: MagicMock,
        test_config: ZosConfig,
        layer_loader: LayerLoader,
        allocation_plan_for_channel: AllocationPlan,
    ) -> None:
        """Test that generated summary has expected structure."""
        executor = PipelineExecutor(
            db=test_db_with_messages,
            llm_client=mock_llm_client,
            config=test_config,
        )
        layer = layer_loader.load("channel_digest")

        await executor.execute(layer, allocation_plan_for_channel)

        insight_repo = InsightRepository(test_db_with_messages)
        topic = TopicKey.channel(123456)
        insights = insight_repo.get_insights(topic)

        assert len(insights) >= 1
        summary = insights[0].summary

        # Check for expected sections based on prompt
        assert "Activity Summary" in summary or "Summary" in summary
        assert "Key Topics" in summary or "Topics" in summary
