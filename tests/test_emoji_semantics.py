"""Integration tests for the emoji_semantics layer.

Tests verify the complete emoji semantics pipeline works:
- Layer definition loading and validation
- Message fetching with reactions
- Cross-layer insight fetching (prior analysis, user profiles, channel context)
- Jinja2 prompt rendering
- LLM call execution (mocked)
- Insight storage with structured payload
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
def test_db_with_reactions(tmp_path: Path) -> Database:
    """Create a test database with messages and reactions."""
    config = DatabaseConfig(path=tmp_path / "test.db")
    db = Database(config)
    db.initialize()

    now = datetime.now(UTC)

    # Insert sample messages in a channel
    messages = [
        {
            "message_id": 4001,
            "guild_id": 12345,
            "channel_id": 123456,
            "author_id": 100,
            "author_name": "alice_dev",
            "author_roles_snapshot": "Member",
            "content": "Just deployed my first ML model to production!",
            "created_at": (now - timedelta(days=10)).isoformat(),
            "visibility_scope": "public",
        },
        {
            "message_id": 4002,
            "guild_id": 12345,
            "channel_id": 123456,
            "author_id": 200,
            "author_name": "bob_coder",
            "author_roles_snapshot": "Member",
            "content": "That's awesome! How long did the training take?",
            "created_at": (now - timedelta(days=10, hours=-1)).isoformat(),
            "visibility_scope": "public",
        },
        {
            "message_id": 4003,
            "guild_id": 12345,
            "channel_id": 123456,
            "author_id": 100,
            "author_name": "alice_dev",
            "author_roles_snapshot": "Member",
            "content": "About 3 hours on a GPU. The results are pretty good!",
            "created_at": (now - timedelta(days=9)).isoformat(),
            "visibility_scope": "public",
        },
        {
            "message_id": 4004,
            "guild_id": 12345,
            "channel_id": 123456,
            "author_id": 300,
            "author_name": "charlie_ml",
            "author_roles_snapshot": "Member",
            "content": "Here's my latest meme about debugging neural networks",
            "created_at": (now - timedelta(days=5)).isoformat(),
            "visibility_scope": "public",
        },
        {
            "message_id": 4005,
            "guild_id": 12345,
            "channel_id": 123456,
            "author_id": 200,
            "author_name": "bob_coder",
            "author_roles_snapshot": "Member",
            "content": "Anyone know why my model keeps overfitting?",
            "created_at": (now - timedelta(days=3)).isoformat(),
            "visibility_scope": "public",
        },
    ]

    # Insert reactions for messages
    # Note: Custom emojis use format "name:id" in emoji column
    reactions = [
        # Reactions to Alice's deployment message
        {"message_id": 4001, "emoji": "thumbsup", "user_id": 200},
        {"message_id": 4001, "emoji": "thumbsup", "user_id": 300},
        {"message_id": 4001, "emoji": "tada", "user_id": 200},
        {"message_id": 4001, "emoji": "shipIt:123456", "user_id": 300},  # Custom emoji
        # Reactions to Bob's question
        {"message_id": 4002, "emoji": "eyes", "user_id": 100},
        # Reactions to Alice's follow-up
        {"message_id": 4003, "emoji": "100", "user_id": 200},
        {"message_id": 4003, "emoji": "bigbrain:123457", "user_id": 300},  # Custom emoji
        # Reactions to meme
        {"message_id": 4004, "emoji": "joy", "user_id": 100},
        {"message_id": 4004, "emoji": "joy", "user_id": 200},
        {"message_id": 4004, "emoji": "pepethink:123458", "user_id": 100},  # Custom emoji
        # Reactions to overfitting question
        {"message_id": 4005, "emoji": "thinking_face", "user_id": 100},
        {"message_id": 4005, "emoji": "pepethink:123458", "user_id": 300},  # Custom emoji
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

        for reaction in reactions:
            db.execute(
                """
                INSERT INTO reactions (message_id, emoji, user_id, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    reaction["message_id"],
                    reaction["emoji"],
                    reaction["user_id"],
                    now.isoformat(),
                ),
            )

    yield db
    db.close()


@pytest.fixture
def mock_llm_client() -> MagicMock:
    """Create a mock LLM client with realistic emoji analysis response."""
    client = MagicMock()

    # Realistic emoji analysis response
    mock_response = MagicMock()
    mock_response.content = """## Emoji Overview

This channel has an active reaction culture centered around celebrating achievements
and engaging with technical discussions. Custom emojis are used to express
community-specific sentiments.

## Custom Emoji Meanings

- :shipIt: - Used to celebrate code deployments and production releases
- :bigbrain: - Praising clever solutions or smart observations
- :pepethink: - Thoughtful consideration of complex problems or questions

## Reaction Semantics

Reactions in this channel primarily serve three functions:
1. **Celebration**: tada, thumbsup, 100 - celebrating achievements
2. **Engagement**: eyes, thinking_face - showing interest in questions
3. **Humor**: joy, pepethink - responding to memes and relatable content

## Popular Reactions

1. thumbsup (2 uses) - General approval and support
2. joy (2 uses) - Responding to humor
3. :pepethink: (2 uses) - Thoughtful consideration

## User Patterns

- Bob tends to react with thumbsup for quick acknowledgments
- Charlie frequently uses custom emojis like :shipIt: and :bigbrain:

## Trends

The channel shows healthy engagement with both standard and custom emoji usage.

```json
{
  "emoji_dictionary": {
    ":shipIt:": {
      "meaning": "approval for deployment-ready code",
      "usage": "approval",
      "confidence": 0.85
    },
    ":bigbrain:": {
      "meaning": "praising clever solutions",
      "usage": "approval",
      "confidence": 0.8
    },
    ":pepethink:": {
      "meaning": "thoughtful consideration",
      "usage": "engagement",
      "confidence": 0.9
    }
  },
  "top_reactions": [
    {
      "emoji": "thumbsup",
      "count": 2,
      "primary_use": "general approval"
    },
    {
      "emoji": "joy",
      "count": 2,
      "primary_use": "humor response"
    }
  ],
  "channel_emoji_culture": "Active reaction culture celebrating achievements and engaging thoughtfully"
}
```"""

    mock_response.prompt_tokens = 450
    mock_response.completion_tokens = 380

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
def allocation_plan_for_channel(test_db_with_reactions: Database) -> AllocationPlan:
    """Create an allocation plan with a channel topic and corresponding run record."""
    channel_topic = TopicKey.channel(123456)
    run_id = "test-run-emoji-semantics"
    now = datetime.now(UTC)

    # Create a run record to satisfy foreign key constraints
    run_repo = RunRepository(test_db_with_reactions)
    run = Run(
        run_id=run_id,
        layer_name="emoji_semantics",
        triggered_by=TriggerType.MANUAL,
        status=RunStatus.RUNNING,
        started_at=now,
        window_start=now - timedelta(days=14),
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
                        salience_balance=25.0,
                        salience_proportion=1.0,
                    )
                ],
            )
        },
        created_at=now,
    )


# =============================================================================
# Test Classes
# =============================================================================


class TestEmojiSemanticsLayerDefinition:
    """Tests for emoji_semantics layer definition and loading."""

    def test_layer_file_exists(self, layers_dir: Path) -> None:
        """Test that the emoji_semantics layer file exists."""
        layer_path = layers_dir / "emoji_semantics" / "layer.yml"
        assert layer_path.exists(), "emoji_semantics/layer.yml should exist"

    def test_layer_loads_successfully(self, layer_loader: LayerLoader) -> None:
        """Test that the layer loads without errors."""
        layer = layer_loader.load("emoji_semantics")
        assert layer is not None
        assert layer.name == "emoji_semantics"

    def test_layer_has_correct_schedule(self, layer_loader: LayerLoader) -> None:
        """Test that the layer has the expected schedule."""
        layer = layer_loader.load("emoji_semantics")
        assert layer.schedule == "0 6 * * 0"  # 6 AM Sundays

    def test_layer_targets_channels(self, layer_loader: LayerLoader) -> None:
        """Test that the layer targets channel topics."""
        layer = layer_loader.load("emoji_semantics")
        assert "channel" in layer.targets.categories

    def test_layer_has_correct_pipeline_nodes(
        self, layer_loader: LayerLoader
    ) -> None:
        """Test that the layer has expected pipeline nodes."""
        layer = layer_loader.load("emoji_semantics")
        node_types = [n.type for n in layer.pipeline.nodes]

        assert "fetch_messages" in node_types
        assert "fetch_insights" in node_types
        assert "llm_call" in node_types
        assert "store_insight" in node_types
        assert "output" in node_types

    def test_layer_prompts_exist(self, layers_dir: Path) -> None:
        """Test that required prompt files exist."""
        prompts_dir = layers_dir / "emoji_semantics" / "prompts"
        assert (prompts_dir / "system.j2").exists()
        assert (prompts_dir / "analyze.j2").exists()

    def test_layer_fetches_reactions(self, layer_loader: LayerLoader) -> None:
        """Test that the layer uses include_reactions: true."""
        layer = layer_loader.load("emoji_semantics")
        # Find the fetch_messages node
        fetch_messages_node = next(
            n for n in layer.pipeline.nodes if n.type == "fetch_messages"
        )
        assert fetch_messages_node.include_reactions is True


class TestPromptRendering:
    """Tests for emoji_semantics prompt template rendering."""

    def test_system_prompt_content(self, layers_dir: Path) -> None:
        """Test that system prompt has expected content."""
        system_prompt = (
            layers_dir / "emoji_semantics" / "prompts" / "system.j2"
        ).read_text()

        assert "Zos" in system_prompt
        assert "emoji" in system_prompt.lower()
        assert "reaction" in system_prompt.lower()

    def test_analyze_prompt_has_template_variables(
        self, layers_dir: Path
    ) -> None:
        """Test that analyze prompt has expected Jinja2 variables."""
        analyze_prompt = (
            layers_dir / "emoji_semantics" / "prompts" / "analyze.j2"
        ).read_text()

        assert "messages_text" in analyze_prompt
        assert "reaction_summary" in analyze_prompt
        assert "prior_emoji_analysis" in analyze_prompt
        assert "channel_context" in analyze_prompt


class TestPipelineExecution:
    """Tests for emoji_semantics pipeline execution."""

    @pytest.mark.asyncio
    async def test_pipeline_executes_successfully(
        self,
        layer_loader: LayerLoader,
        test_db_with_reactions: Database,
        mock_llm_client: MagicMock,
        allocation_plan_for_channel: AllocationPlan,
        test_config: ZosConfig,
    ) -> None:
        """Test that the full pipeline executes without errors."""
        layer = layer_loader.load("emoji_semantics")

        executor = PipelineExecutor(
            db=test_db_with_reactions,
            llm_client=mock_llm_client,
            config=test_config,
        )

        result = await executor.execute(layer, allocation_plan_for_channel)

        assert result.success is True
        assert result.layer_name == "emoji_semantics"
        assert result.targets_processed >= 1

    @pytest.mark.asyncio
    async def test_pipeline_calls_llm(
        self,
        layer_loader: LayerLoader,
        test_db_with_reactions: Database,
        mock_llm_client: MagicMock,
        allocation_plan_for_channel: AllocationPlan,
        test_config: ZosConfig,
    ) -> None:
        """Test that the pipeline makes LLM calls."""
        layer = layer_loader.load("emoji_semantics")

        executor = PipelineExecutor(
            db=test_db_with_reactions,
            llm_client=mock_llm_client,
            config=test_config,
        )

        await executor.execute(layer, allocation_plan_for_channel)

        mock_llm_client.complete_with_prompt.assert_called()

    @pytest.mark.asyncio
    async def test_pipeline_tracks_tokens(
        self,
        layer_loader: LayerLoader,
        test_db_with_reactions: Database,
        mock_llm_client: MagicMock,
        allocation_plan_for_channel: AllocationPlan,
        test_config: ZosConfig,
    ) -> None:
        """Test that token usage is tracked."""
        layer = layer_loader.load("emoji_semantics")

        executor = PipelineExecutor(
            db=test_db_with_reactions,
            llm_client=mock_llm_client,
            config=test_config,
        )

        result = await executor.execute(layer, allocation_plan_for_channel)

        # 450 prompt + 380 completion = 830
        assert result.total_tokens > 0


class TestInsightStorage:
    """Tests for emoji_semantics insight storage."""

    @pytest.mark.asyncio
    async def test_insight_stored_with_channel_topic(
        self,
        layer_loader: LayerLoader,
        test_db_with_reactions: Database,
        mock_llm_client: MagicMock,
        allocation_plan_for_channel: AllocationPlan,
        test_config: ZosConfig,
    ) -> None:
        """Test that insights are stored with correct channel topic key."""
        layer = layer_loader.load("emoji_semantics")

        executor = PipelineExecutor(
            db=test_db_with_reactions,
            llm_client=mock_llm_client,
            config=test_config,
        )

        await executor.execute(layer, allocation_plan_for_channel)

        # Check insight was stored
        insight_repo = InsightRepository(test_db_with_reactions)
        channel_topic = TopicKey.channel(123456)
        insights = insight_repo.get_insights(channel_topic, limit=10)

        assert len(insights) >= 1
        assert insights[0].topic_key == channel_topic.key

    @pytest.mark.asyncio
    async def test_insight_has_layer_attribution(
        self,
        layer_loader: LayerLoader,
        test_db_with_reactions: Database,
        mock_llm_client: MagicMock,
        allocation_plan_for_channel: AllocationPlan,
        test_config: ZosConfig,
    ) -> None:
        """Test that stored insights have layer name."""
        layer = layer_loader.load("emoji_semantics")

        executor = PipelineExecutor(
            db=test_db_with_reactions,
            llm_client=mock_llm_client,
            config=test_config,
        )

        await executor.execute(layer, allocation_plan_for_channel)

        insight_repo = InsightRepository(test_db_with_reactions)
        channel_topic = TopicKey.channel(123456)
        insights = insight_repo.get_insights(channel_topic, limit=10)

        assert insights[0].layer == "emoji_semantics"

    @pytest.mark.asyncio
    async def test_insight_has_payload(
        self,
        layer_loader: LayerLoader,
        test_db_with_reactions: Database,
        mock_llm_client: MagicMock,
        allocation_plan_for_channel: AllocationPlan,
        test_config: ZosConfig,
    ) -> None:
        """Test that insights have structured payload (include_payload: true)."""
        layer = layer_loader.load("emoji_semantics")

        executor = PipelineExecutor(
            db=test_db_with_reactions,
            llm_client=mock_llm_client,
            config=test_config,
        )

        await executor.execute(layer, allocation_plan_for_channel)

        insight_repo = InsightRepository(test_db_with_reactions)
        channel_topic = TopicKey.channel(123456)
        insights = insight_repo.get_insights(channel_topic, limit=10)

        # Payload should be present (include_payload: true in layer config)
        assert insights[0].payload is not None


class TestRunManagerIntegration:
    """Tests for RunManager integration with emoji_semantics layer."""

    @pytest.mark.asyncio
    async def test_run_manager_creates_run_record(
        self,
        layer_loader: LayerLoader,
        test_db_with_reactions: Database,
        mock_llm_client: MagicMock,
        test_config: ZosConfig,
    ) -> None:
        """Test that RunManager creates proper run records."""
        salience_repo = SalienceRepository(test_db_with_reactions)
        channel_topic = TopicKey.channel(123456)
        now = datetime.now(UTC)

        # Add salience for the channel
        salience_repo.earn(
            topic_key=channel_topic,
            amount=25.0,
            reason="test",
            timestamp=now,
        )

        run_manager = RunManager(
            db=test_db_with_reactions,
            llm_client=mock_llm_client,
            config=test_config,
            layer_loader=layer_loader,
        )

        run = await run_manager.execute_layer(
            layer_name="emoji_semantics",
            triggered_by=TriggerType.MANUAL,
        )

        assert run is not None
        assert run.layer_name == "emoji_semantics"
        assert run.status == RunStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_run_records_metrics(
        self,
        layer_loader: LayerLoader,
        test_db_with_reactions: Database,
        mock_llm_client: MagicMock,
        test_config: ZosConfig,
    ) -> None:
        """Test that run records include metrics."""
        salience_repo = SalienceRepository(test_db_with_reactions)
        channel_topic = TopicKey.channel(123456)
        now = datetime.now(UTC)

        salience_repo.earn(
            topic_key=channel_topic,
            amount=25.0,
            reason="test",
            timestamp=now,
        )

        run_manager = RunManager(
            db=test_db_with_reactions,
            llm_client=mock_llm_client,
            config=test_config,
            layer_loader=layer_loader,
        )

        run = await run_manager.execute_layer(
            layer_name="emoji_semantics",
            triggered_by=TriggerType.MANUAL,
        )

        assert run.targets_processed >= 1
        assert run.tokens_used > 0


class TestOutputQuality:
    """Tests for output quality validation."""

    @pytest.mark.asyncio
    async def test_summary_has_reasonable_length(
        self,
        layer_loader: LayerLoader,
        test_db_with_reactions: Database,
        mock_llm_client: MagicMock,
        allocation_plan_for_channel: AllocationPlan,
        test_config: ZosConfig,
    ) -> None:
        """Test that generated summaries have reasonable length."""
        layer = layer_loader.load("emoji_semantics")

        executor = PipelineExecutor(
            db=test_db_with_reactions,
            llm_client=mock_llm_client,
            config=test_config,
        )

        await executor.execute(layer, allocation_plan_for_channel)

        insight_repo = InsightRepository(test_db_with_reactions)
        channel_topic = TopicKey.channel(123456)
        insights = insight_repo.get_insights(channel_topic, limit=10)

        # Summary should be substantial but not empty
        assert len(insights[0].summary) > 100
