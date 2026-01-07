"""Integration tests for the social_dynamics layer.

Tests verify the complete social dynamics pipeline works:
- Layer definition loading and validation
- Interaction message fetching for user pairs
- Cross-layer insight fetching (prior dynamics, user profiles, channel context)
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
def test_db_with_dyad_messages(tmp_path: Path) -> Database:
    """Create a test database with messages from two interacting users."""
    config = DatabaseConfig(path=tmp_path / "test.db")
    db = Database(config)
    db.initialize()

    # Insert sample messages showing interactions between user 100 (Alice) and user 200 (Bob)
    now = datetime.now(UTC)
    messages = [
        # Alice's message that Bob responds to
        {
            "message_id": 3001,
            "guild_id": 12345,
            "channel_id": 123456,
            "author_id": 100,
            "author_name": "alice_dev",
            "author_roles_snapshot": "Member",
            "content": "Hey Bob, have you worked with PyTorch before?",
            "created_at": (now - timedelta(days=10)).isoformat(),
            "visibility_scope": "public",
        },
        # Bob's response
        {
            "message_id": 3002,
            "guild_id": 12345,
            "channel_id": 123456,
            "author_id": 200,
            "author_name": "bob_coder",
            "author_roles_snapshot": "Member",
            "content": "Hey Alice! Yes, I've been using it for a few months now. What do you need help with?",
            "created_at": (now - timedelta(days=10, hours=-1)).isoformat(),
            "visibility_scope": "public",
        },
        # Alice follow-up
        {
            "message_id": 3003,
            "guild_id": 12345,
            "channel_id": 123456,
            "author_id": 100,
            "author_name": "alice_dev",
            "author_roles_snapshot": "Member",
            "content": "Thanks! I'm trying to optimize my model training. The batch processing is slow.",
            "created_at": (now - timedelta(days=9)).isoformat(),
            "visibility_scope": "public",
        },
        # Bob helping
        {
            "message_id": 3004,
            "guild_id": 12345,
            "channel_id": 123456,
            "author_id": 200,
            "author_name": "bob_coder",
            "author_roles_snapshot": "Member",
            "content": "Have you tried using DataLoader with num_workers? That usually helps a lot.",
            "created_at": (now - timedelta(days=9, hours=-2)).isoformat(),
            "visibility_scope": "public",
        },
        # Alice expressing gratitude
        {
            "message_id": 3005,
            "guild_id": 12345,
            "channel_id": 123456,
            "author_id": 100,
            "author_name": "alice_dev",
            "author_roles_snapshot": "Member",
            "content": "That worked perfectly! You're a lifesaver Bob, thanks so much!",
            "created_at": (now - timedelta(days=8)).isoformat(),
            "visibility_scope": "public",
        },
        # Later interaction - collaborative
        {
            "message_id": 3006,
            "guild_id": 12345,
            "channel_id": 123457,
            "author_id": 200,
            "author_name": "bob_coder",
            "author_roles_snapshot": "Member",
            "content": "Alice, I saw your PR on the ML repo. Great work on the preprocessing module!",
            "created_at": (now - timedelta(days=3)).isoformat(),
            "visibility_scope": "public",
        },
        # Alice responding positively
        {
            "message_id": 3007,
            "guild_id": 12345,
            "channel_id": 123457,
            "author_id": 100,
            "author_name": "alice_dev",
            "author_roles_snapshot": "Member",
            "content": "Thanks Bob! Would you have time to review it? I'd value your feedback.",
            "created_at": (now - timedelta(days=3, hours=-1)).isoformat(),
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
    """Create a mock LLM client with realistic social dynamics response."""
    client = MagicMock()

    # Realistic relationship analysis response
    mock_response = MagicMock()
    mock_response.content = """## Relationship Summary

Alice and Bob have developed a supportive, collaborative relationship centered around
Python and machine learning development. Bob frequently helps Alice with technical
questions, and they show mutual respect for each other's work.

## Interaction Style

Their interactions are friendly and technically focused. Alice often seeks Bob's
expertise, while Bob provides helpful, detailed responses. Both express appreciation
for each other's contributions.

## Shared Interests

- Python programming
- Machine learning / deep learning
- PyTorch framework
- Open source contributions
- Code review

## Relationship Strength

Strong - They interact consistently across multiple channels, help each other
regularly, and have begun collaborating on code reviews.

## Notable Patterns

- Bob is a reliable source of technical help for Alice
- Both engage with each other's work outside of direct questions
- There's a pattern of mutual appreciation and support

## Changes

This appears to be a developing collaboration, with recent interactions showing
increased engagement around shared projects.

```json
{
  "relationship": {
    "type": "collaborators",
    "strength": "strong",
    "primary_context": "#programming",
    "shared_interests": ["Python", "machine learning", "PyTorch", "code review"],
    "interaction_frequency": "frequent"
  },
  "confidence": {
    "type": 0.85,
    "strength": 0.8
  }
}
```"""

    mock_response.prompt_tokens = 400
    mock_response.completion_tokens = 320

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
            category_weights=CategoryWeights(dyad=100),  # Focus on dyads
        ),
        layers_dir=layers_dir,
    )


@pytest.fixture
def allocation_plan_for_dyad(test_db_with_dyad_messages: Database) -> AllocationPlan:
    """Create an allocation plan with a dyad topic and corresponding run record."""
    # Dyad topic for user pair 100 and 200
    dyad_topic = TopicKey.dyad(100, 200)
    run_id = "test-run-social-dynamics"
    now = datetime.now(UTC)

    # Create a run record to satisfy foreign key constraints
    run_repo = RunRepository(test_db_with_dyad_messages)
    run = Run(
        run_id=run_id,
        layer_name="social_dynamics",
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
            TopicCategory.DYAD: CategoryAllocation(
                category=TopicCategory.DYAD,
                weight=100,
                total_tokens=50000,
                topic_allocations=[
                    TopicAllocation(
                        topic_key=dyad_topic,
                        allocated_tokens=5000,
                        salience_balance=15.0,
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


class TestSocialDynamicsLayerDefinition:
    """Tests for social_dynamics layer definition and loading."""

    def test_layer_file_exists(self, layers_dir: Path) -> None:
        """Test that the social_dynamics layer file exists."""
        layer_path = layers_dir / "social_dynamics" / "layer.yml"
        assert layer_path.exists(), "social_dynamics/layer.yml should exist"

    def test_layer_loads_successfully(self, layer_loader: LayerLoader) -> None:
        """Test that the layer loads without errors."""
        layer = layer_loader.load("social_dynamics")
        assert layer is not None
        assert layer.name == "social_dynamics"

    def test_layer_has_correct_schedule(self, layer_loader: LayerLoader) -> None:
        """Test that the layer has the expected schedule."""
        layer = layer_loader.load("social_dynamics")
        assert layer.schedule == "0 5 * * 0"  # 5 AM Sundays

    def test_layer_targets_dyads(self, layer_loader: LayerLoader) -> None:
        """Test that the layer targets dyad topics."""
        layer = layer_loader.load("social_dynamics")
        assert "dyad" in layer.targets.categories

    def test_layer_has_correct_pipeline_nodes(
        self, layer_loader: LayerLoader
    ) -> None:
        """Test that the layer has expected pipeline nodes."""
        layer = layer_loader.load("social_dynamics")
        node_types = [n.type for n in layer.pipeline.nodes]

        assert "fetch_messages" in node_types
        assert "fetch_insights" in node_types
        assert "llm_call" in node_types
        assert "store_insight" in node_types
        assert "output" in node_types

    def test_layer_prompts_exist(self, layers_dir: Path) -> None:
        """Test that required prompt files exist."""
        prompts_dir = layers_dir / "social_dynamics" / "prompts"
        assert (prompts_dir / "system.j2").exists()
        assert (prompts_dir / "analyze.j2").exists()

    def test_layer_has_longer_lookback(self, layer_loader: LayerLoader) -> None:
        """Test that the layer has 2-week lookback for relationship analysis."""
        layer = layer_loader.load("social_dynamics")
        assert layer.max_lookback_hours == 336  # 2 weeks


class TestPromptRendering:
    """Tests for social_dynamics prompt template rendering."""

    def test_system_prompt_content(self, layers_dir: Path) -> None:
        """Test that system prompt has expected content."""
        system_prompt = (
            layers_dir / "social_dynamics" / "prompts" / "system.j2"
        ).read_text()

        assert "Zos" in system_prompt
        assert "social" in system_prompt.lower() or "relationship" in system_prompt.lower()
        assert "interaction" in system_prompt.lower()

    def test_analyze_prompt_has_template_variables(
        self, layers_dir: Path
    ) -> None:
        """Test that analyze prompt has expected Jinja2 variables."""
        analyze_prompt = (
            layers_dir / "social_dynamics" / "prompts" / "analyze.j2"
        ).read_text()

        assert "messages_text" in analyze_prompt
        assert "prior_dynamics" in analyze_prompt
        assert "user_profiles" in analyze_prompt
        assert "channel_context" in analyze_prompt


class TestPipelineExecution:
    """Tests for social_dynamics pipeline execution."""

    @pytest.mark.asyncio
    async def test_pipeline_executes_successfully(
        self,
        layer_loader: LayerLoader,
        test_db_with_dyad_messages: Database,
        mock_llm_client: MagicMock,
        allocation_plan_for_dyad: AllocationPlan,
        test_config: ZosConfig,
    ) -> None:
        """Test that the full pipeline executes without errors."""
        layer = layer_loader.load("social_dynamics")

        executor = PipelineExecutor(
            db=test_db_with_dyad_messages,
            llm_client=mock_llm_client,
            config=test_config,
        )

        result = await executor.execute(layer, allocation_plan_for_dyad)

        assert result.success is True
        assert result.layer_name == "social_dynamics"
        assert result.targets_processed >= 1

    @pytest.mark.asyncio
    async def test_pipeline_calls_llm(
        self,
        layer_loader: LayerLoader,
        test_db_with_dyad_messages: Database,
        mock_llm_client: MagicMock,
        allocation_plan_for_dyad: AllocationPlan,
        test_config: ZosConfig,
    ) -> None:
        """Test that the pipeline makes LLM calls."""
        layer = layer_loader.load("social_dynamics")

        executor = PipelineExecutor(
            db=test_db_with_dyad_messages,
            llm_client=mock_llm_client,
            config=test_config,
        )

        await executor.execute(layer, allocation_plan_for_dyad)

        mock_llm_client.complete_with_prompt.assert_called()

    @pytest.mark.asyncio
    async def test_pipeline_tracks_tokens(
        self,
        layer_loader: LayerLoader,
        test_db_with_dyad_messages: Database,
        mock_llm_client: MagicMock,
        allocation_plan_for_dyad: AllocationPlan,
        test_config: ZosConfig,
    ) -> None:
        """Test that token usage is tracked."""
        layer = layer_loader.load("social_dynamics")

        executor = PipelineExecutor(
            db=test_db_with_dyad_messages,
            llm_client=mock_llm_client,
            config=test_config,
        )

        result = await executor.execute(layer, allocation_plan_for_dyad)

        # 400 prompt + 320 completion = 720
        assert result.total_tokens > 0


class TestInsightStorage:
    """Tests for social_dynamics insight storage."""

    @pytest.mark.asyncio
    async def test_insight_stored_with_dyad_topic(
        self,
        layer_loader: LayerLoader,
        test_db_with_dyad_messages: Database,
        mock_llm_client: MagicMock,
        allocation_plan_for_dyad: AllocationPlan,
        test_config: ZosConfig,
    ) -> None:
        """Test that insights are stored with correct dyad topic key."""
        layer = layer_loader.load("social_dynamics")

        executor = PipelineExecutor(
            db=test_db_with_dyad_messages,
            llm_client=mock_llm_client,
            config=test_config,
        )

        await executor.execute(layer, allocation_plan_for_dyad)

        # Check insight was stored
        insight_repo = InsightRepository(test_db_with_dyad_messages)
        dyad_topic = TopicKey.dyad(100, 200)
        insights = insight_repo.get_insights(dyad_topic, limit=10)

        assert len(insights) >= 1
        assert insights[0].topic_key == dyad_topic.key

    @pytest.mark.asyncio
    async def test_insight_has_layer_attribution(
        self,
        layer_loader: LayerLoader,
        test_db_with_dyad_messages: Database,
        mock_llm_client: MagicMock,
        allocation_plan_for_dyad: AllocationPlan,
        test_config: ZosConfig,
    ) -> None:
        """Test that stored insights have layer name."""
        layer = layer_loader.load("social_dynamics")

        executor = PipelineExecutor(
            db=test_db_with_dyad_messages,
            llm_client=mock_llm_client,
            config=test_config,
        )

        await executor.execute(layer, allocation_plan_for_dyad)

        insight_repo = InsightRepository(test_db_with_dyad_messages)
        dyad_topic = TopicKey.dyad(100, 200)
        insights = insight_repo.get_insights(dyad_topic, limit=10)

        assert insights[0].layer == "social_dynamics"

    @pytest.mark.asyncio
    async def test_insight_has_payload(
        self,
        layer_loader: LayerLoader,
        test_db_with_dyad_messages: Database,
        mock_llm_client: MagicMock,
        allocation_plan_for_dyad: AllocationPlan,
        test_config: ZosConfig,
    ) -> None:
        """Test that insights have structured payload (include_payload: true)."""
        layer = layer_loader.load("social_dynamics")

        executor = PipelineExecutor(
            db=test_db_with_dyad_messages,
            llm_client=mock_llm_client,
            config=test_config,
        )

        await executor.execute(layer, allocation_plan_for_dyad)

        insight_repo = InsightRepository(test_db_with_dyad_messages)
        dyad_topic = TopicKey.dyad(100, 200)
        insights = insight_repo.get_insights(dyad_topic, limit=10)

        # Payload should be present (include_payload: true in layer config)
        assert insights[0].payload is not None


class TestRunManagerIntegration:
    """Tests for RunManager integration with social_dynamics layer."""

    @pytest.mark.asyncio
    async def test_run_manager_creates_run_record(
        self,
        layer_loader: LayerLoader,
        test_db_with_dyad_messages: Database,
        mock_llm_client: MagicMock,
        test_config: ZosConfig,
    ) -> None:
        """Test that RunManager creates proper run records."""
        salience_repo = SalienceRepository(test_db_with_dyad_messages)
        dyad_topic = TopicKey.dyad(100, 200)
        now = datetime.now(UTC)

        # Add salience for the dyad
        salience_repo.earn(
            topic_key=dyad_topic,
            amount=15.0,
            reason="test",
            timestamp=now,
        )

        run_manager = RunManager(
            db=test_db_with_dyad_messages,
            llm_client=mock_llm_client,
            config=test_config,
            layer_loader=layer_loader,
        )

        run = await run_manager.execute_layer(
            layer_name="social_dynamics",
            triggered_by=TriggerType.MANUAL,
        )

        assert run is not None
        assert run.layer_name == "social_dynamics"
        assert run.status == RunStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_run_records_metrics(
        self,
        layer_loader: LayerLoader,
        test_db_with_dyad_messages: Database,
        mock_llm_client: MagicMock,
        test_config: ZosConfig,
    ) -> None:
        """Test that run records include metrics."""
        salience_repo = SalienceRepository(test_db_with_dyad_messages)
        dyad_topic = TopicKey.dyad(100, 200)
        now = datetime.now(UTC)

        salience_repo.earn(
            topic_key=dyad_topic,
            amount=15.0,
            reason="test",
            timestamp=now,
        )

        run_manager = RunManager(
            db=test_db_with_dyad_messages,
            llm_client=mock_llm_client,
            config=test_config,
            layer_loader=layer_loader,
        )

        run = await run_manager.execute_layer(
            layer_name="social_dynamics",
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
        test_db_with_dyad_messages: Database,
        mock_llm_client: MagicMock,
        allocation_plan_for_dyad: AllocationPlan,
        test_config: ZosConfig,
    ) -> None:
        """Test that generated summaries have reasonable length."""
        layer = layer_loader.load("social_dynamics")

        executor = PipelineExecutor(
            db=test_db_with_dyad_messages,
            llm_client=mock_llm_client,
            config=test_config,
        )

        await executor.execute(layer, allocation_plan_for_dyad)

        insight_repo = InsightRepository(test_db_with_dyad_messages)
        dyad_topic = TopicKey.dyad(100, 200)
        insights = insight_repo.get_insights(dyad_topic, limit=10)

        # Summary should be substantial but not empty
        assert len(insights[0].summary) > 100
