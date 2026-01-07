"""Integration tests for the user_profile layer.

Tests verify the complete user profile pipeline works:
- Layer definition loading and validation
- User message fetching
- Cross-layer insight fetching (prior profile and channel context)
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
def test_db_with_user_messages(tmp_path: Path) -> Database:
    """Create a test database with messages from a specific user."""
    config = DatabaseConfig(path=tmp_path / "test.db")
    db = Database(config)
    db.initialize()

    # Insert sample messages from user 100 (Alice)
    now = datetime.now(UTC)
    messages = [
        {
            "message_id": 2001,
            "guild_id": 12345,
            "channel_id": 123456,
            "author_id": 100,
            "author_name": "alice_dev",
            "author_roles_snapshot": "Member",
            "content": "Hey everyone! I'm Alice, a software developer. she/her pronouns.",
            "created_at": (now - timedelta(days=5)).isoformat(),
            "visibility_scope": "public",
        },
        {
            "message_id": 2002,
            "guild_id": 12345,
            "channel_id": 123456,
            "author_id": 100,
            "author_name": "alice_dev",
            "author_roles_snapshot": "Member",
            "content": "I've been working on a Python machine learning project lately.",
            "created_at": (now - timedelta(days=4)).isoformat(),
            "visibility_scope": "public",
        },
        {
            "message_id": 2003,
            "guild_id": 12345,
            "channel_id": 123457,
            "author_id": 100,
            "author_name": "alice_dev",
            "author_roles_snapshot": "Member",
            "content": "Anyone have experience with PyTorch? I'm trying to optimize my model.",
            "created_at": (now - timedelta(days=3)).isoformat(),
            "visibility_scope": "public",
        },
        {
            "message_id": 2004,
            "guild_id": 12345,
            "channel_id": 123456,
            "author_id": 100,
            "author_name": "alice_dev",
            "author_roles_snapshot": "Member",
            "content": "Thanks for the help! I really appreciate this community.",
            "created_at": (now - timedelta(days=2)).isoformat(),
            "visibility_scope": "public",
        },
        {
            "message_id": 2005,
            "guild_id": 12345,
            "channel_id": 123456,
            "author_id": 100,
            "author_name": "alice_dev",
            "author_roles_snapshot": "Member",
            "content": "Just deployed my first ML model to production! Really excited about it.",
            "created_at": (now - timedelta(days=1)).isoformat(),
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
    """Create a mock LLM client with realistic user profile response."""
    client = MagicMock()

    # Realistic user profile response
    mock_response = MagicMock()
    mock_response.content = """## Profile Summary

Alice is an enthusiastic software developer with a focus on machine learning and Python.
She actively participates in technical discussions and has recently deployed her first
ML model to production.

## Communication Style

Alice communicates in a friendly, casual manner while remaining technically precise.
She is appreciative of community help and shares her achievements openly.

## Interests

- Python programming
- Machine learning / deep learning
- PyTorch
- Model deployment

## Profile Updates

- Names: Alice, alice_dev (from Discord username)
- Pronouns: she/her (stated explicitly in introduction)
- Occupation: Software developer (self-identified)

## Notable Changes

This week Alice achieved a significant milestone by deploying her first ML model
to production, indicating growth in her professional development.

```json
{
  "profile": {
    "known_names": ["Alice", "alice_dev"],
    "pronouns": "she/her",
    "occupation": "software developer",
    "interests": ["Python", "machine learning", "PyTorch", "model deployment"],
    "communication_style": "friendly and technically engaged"
  },
  "confidence": {
    "names": 0.9,
    "pronouns": 0.95,
    "occupation": 0.85
  }
}
```"""

    mock_response.prompt_tokens = 350
    mock_response.completion_tokens = 280

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
            category_weights=CategoryWeights(user=100),  # Focus on users
        ),
        layers_dir=layers_dir,
    )


@pytest.fixture
def allocation_plan_for_user(test_db_with_user_messages: Database) -> AllocationPlan:
    """Create an allocation plan with a user topic and corresponding run record."""
    user_topic = TopicKey.user(100)
    run_id = "test-run-user-profile"
    now = datetime.now(UTC)

    # Create a run record to satisfy foreign key constraints
    run_repo = RunRepository(test_db_with_user_messages)
    run = Run(
        run_id=run_id,
        layer_name="user_profile",
        triggered_by=TriggerType.MANUAL,
        status=RunStatus.RUNNING,
        started_at=now,
        window_start=now - timedelta(days=7),
        window_end=now,
    )
    run_repo.create_run(run)

    return AllocationPlan(
        run_id=run_id,
        total_budget=50000,
        per_topic_cap=5000,
        category_allocations={
            TopicCategory.USER: CategoryAllocation(
                category=TopicCategory.USER,
                weight=100,
                total_tokens=50000,
                topic_allocations=[
                    TopicAllocation(
                        topic_key=user_topic,
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


class TestUserProfileLayerDefinition:
    """Tests for user_profile layer definition and loading."""

    def test_layer_file_exists(self, layers_dir: Path) -> None:
        """Test that the user_profile layer file exists."""
        layer_path = layers_dir / "user_profile" / "layer.yml"
        assert layer_path.exists(), "user_profile/layer.yml should exist"

    def test_layer_loads_successfully(self, layer_loader: LayerLoader) -> None:
        """Test that the layer loads without errors."""
        layer = layer_loader.load("user_profile")
        assert layer is not None
        assert layer.name == "user_profile"

    def test_layer_has_correct_schedule(self, layer_loader: LayerLoader) -> None:
        """Test that the layer has the expected schedule."""
        layer = layer_loader.load("user_profile")
        assert layer.schedule == "0 4 * * *"  # 4 AM daily

    def test_layer_targets_users(self, layer_loader: LayerLoader) -> None:
        """Test that the layer targets user topics."""
        layer = layer_loader.load("user_profile")
        assert "user" in layer.targets.categories

    def test_layer_has_correct_pipeline_nodes(
        self, layer_loader: LayerLoader
    ) -> None:
        """Test that the layer has expected pipeline nodes."""
        layer = layer_loader.load("user_profile")
        node_types = [n.type for n in layer.pipeline.nodes]

        assert "fetch_messages" in node_types
        assert "fetch_insights" in node_types
        assert "llm_call" in node_types
        assert "store_insight" in node_types
        assert "output" in node_types

    def test_layer_prompts_exist(self, layers_dir: Path) -> None:
        """Test that required prompt files exist."""
        prompts_dir = layers_dir / "user_profile" / "prompts"
        assert (prompts_dir / "system.j2").exists()
        assert (prompts_dir / "analyze.j2").exists()


class TestPromptRendering:
    """Tests for user_profile prompt template rendering."""

    def test_system_prompt_content(self, layers_dir: Path) -> None:
        """Test that system prompt has expected content."""
        system_prompt = (
            layers_dir / "user_profile" / "prompts" / "system.j2"
        ).read_text()

        assert "Zos" in system_prompt
        assert "user" in system_prompt.lower() or "community" in system_prompt.lower()
        assert "privacy" in system_prompt.lower()

    def test_analyze_prompt_has_template_variables(
        self, layers_dir: Path
    ) -> None:
        """Test that analyze prompt has expected Jinja2 variables."""
        analyze_prompt = (
            layers_dir / "user_profile" / "prompts" / "analyze.j2"
        ).read_text()

        assert "messages_text" in analyze_prompt
        assert "prior_profile" in analyze_prompt
        assert "channel_context" in analyze_prompt


class TestPipelineExecution:
    """Tests for user_profile pipeline execution."""

    @pytest.mark.asyncio
    async def test_pipeline_executes_successfully(
        self,
        layer_loader: LayerLoader,
        test_db_with_user_messages: Database,
        mock_llm_client: MagicMock,
        allocation_plan_for_user: AllocationPlan,
        test_config: ZosConfig,
    ) -> None:
        """Test that the full pipeline executes without errors."""
        layer = layer_loader.load("user_profile")

        executor = PipelineExecutor(
            db=test_db_with_user_messages,
            llm_client=mock_llm_client,
            config=test_config,
        )

        result = await executor.execute(layer, allocation_plan_for_user)

        assert result.success is True
        assert result.layer_name == "user_profile"
        assert result.targets_processed >= 1

    @pytest.mark.asyncio
    async def test_pipeline_calls_llm(
        self,
        layer_loader: LayerLoader,
        test_db_with_user_messages: Database,
        mock_llm_client: MagicMock,
        allocation_plan_for_user: AllocationPlan,
        test_config: ZosConfig,
    ) -> None:
        """Test that the pipeline makes LLM calls."""
        layer = layer_loader.load("user_profile")

        executor = PipelineExecutor(
            db=test_db_with_user_messages,
            llm_client=mock_llm_client,
            config=test_config,
        )

        await executor.execute(layer, allocation_plan_for_user)

        mock_llm_client.complete_with_prompt.assert_called()

    @pytest.mark.asyncio
    async def test_pipeline_tracks_tokens(
        self,
        layer_loader: LayerLoader,
        test_db_with_user_messages: Database,
        mock_llm_client: MagicMock,
        allocation_plan_for_user: AllocationPlan,
        test_config: ZosConfig,
    ) -> None:
        """Test that token usage is tracked."""
        layer = layer_loader.load("user_profile")

        executor = PipelineExecutor(
            db=test_db_with_user_messages,
            llm_client=mock_llm_client,
            config=test_config,
        )

        result = await executor.execute(layer, allocation_plan_for_user)

        # 350 prompt + 280 completion = 630
        assert result.total_tokens > 0


class TestInsightStorage:
    """Tests for user_profile insight storage."""

    @pytest.mark.asyncio
    async def test_insight_stored_with_user_topic(
        self,
        layer_loader: LayerLoader,
        test_db_with_user_messages: Database,
        mock_llm_client: MagicMock,
        allocation_plan_for_user: AllocationPlan,
        test_config: ZosConfig,
    ) -> None:
        """Test that insights are stored with correct user topic key."""
        layer = layer_loader.load("user_profile")

        executor = PipelineExecutor(
            db=test_db_with_user_messages,
            llm_client=mock_llm_client,
            config=test_config,
        )

        await executor.execute(layer, allocation_plan_for_user)

        # Check insight was stored
        insight_repo = InsightRepository(test_db_with_user_messages)
        user_topic = TopicKey.user(100)
        insights = insight_repo.get_insights(user_topic, limit=10)

        assert len(insights) >= 1
        assert insights[0].topic_key == user_topic.key

    @pytest.mark.asyncio
    async def test_insight_has_layer_attribution(
        self,
        layer_loader: LayerLoader,
        test_db_with_user_messages: Database,
        mock_llm_client: MagicMock,
        allocation_plan_for_user: AllocationPlan,
        test_config: ZosConfig,
    ) -> None:
        """Test that stored insights have layer name."""
        layer = layer_loader.load("user_profile")

        executor = PipelineExecutor(
            db=test_db_with_user_messages,
            llm_client=mock_llm_client,
            config=test_config,
        )

        await executor.execute(layer, allocation_plan_for_user)

        insight_repo = InsightRepository(test_db_with_user_messages)
        user_topic = TopicKey.user(100)
        insights = insight_repo.get_insights(user_topic, limit=10)

        assert insights[0].layer == "user_profile"

    @pytest.mark.asyncio
    async def test_insight_has_payload(
        self,
        layer_loader: LayerLoader,
        test_db_with_user_messages: Database,
        mock_llm_client: MagicMock,
        allocation_plan_for_user: AllocationPlan,
        test_config: ZosConfig,
    ) -> None:
        """Test that insights have structured payload (include_payload: true)."""
        layer = layer_loader.load("user_profile")

        executor = PipelineExecutor(
            db=test_db_with_user_messages,
            llm_client=mock_llm_client,
            config=test_config,
        )

        await executor.execute(layer, allocation_plan_for_user)

        insight_repo = InsightRepository(test_db_with_user_messages)
        user_topic = TopicKey.user(100)
        insights = insight_repo.get_insights(user_topic, limit=10)

        # Payload should be present (include_payload: true in layer config)
        assert insights[0].payload is not None


class TestRunManagerIntegration:
    """Tests for RunManager integration with user_profile layer."""

    @pytest.mark.asyncio
    async def test_run_manager_creates_run_record(
        self,
        layer_loader: LayerLoader,
        test_db_with_user_messages: Database,
        mock_llm_client: MagicMock,
        test_config: ZosConfig,
    ) -> None:
        """Test that RunManager creates proper run records."""
        salience_repo = SalienceRepository(test_db_with_user_messages)
        user_topic = TopicKey.user(100)
        now = datetime.now(UTC)

        # Add salience for the user
        salience_repo.earn(
            topic_key=user_topic,
            amount=25.0,
            reason="test",
            timestamp=now,
        )

        run_manager = RunManager(
            db=test_db_with_user_messages,
            llm_client=mock_llm_client,
            config=test_config,
            layer_loader=layer_loader,
        )

        run = await run_manager.execute_layer(
            layer_name="user_profile",
            triggered_by=TriggerType.MANUAL,
        )

        assert run is not None
        assert run.layer_name == "user_profile"
        assert run.status == RunStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_run_records_metrics(
        self,
        layer_loader: LayerLoader,
        test_db_with_user_messages: Database,
        mock_llm_client: MagicMock,
        test_config: ZosConfig,
    ) -> None:
        """Test that run records include metrics."""
        salience_repo = SalienceRepository(test_db_with_user_messages)
        user_topic = TopicKey.user(100)
        now = datetime.now(UTC)

        salience_repo.earn(
            topic_key=user_topic,
            amount=25.0,
            reason="test",
            timestamp=now,
        )

        run_manager = RunManager(
            db=test_db_with_user_messages,
            llm_client=mock_llm_client,
            config=test_config,
            layer_loader=layer_loader,
        )

        run = await run_manager.execute_layer(
            layer_name="user_profile",
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
        test_db_with_user_messages: Database,
        mock_llm_client: MagicMock,
        allocation_plan_for_user: AllocationPlan,
        test_config: ZosConfig,
    ) -> None:
        """Test that generated summaries have reasonable length."""
        layer = layer_loader.load("user_profile")

        executor = PipelineExecutor(
            db=test_db_with_user_messages,
            llm_client=mock_llm_client,
            config=test_config,
        )

        await executor.execute(layer, allocation_plan_for_user)

        insight_repo = InsightRepository(test_db_with_user_messages)
        user_topic = TopicKey.user(100)
        insights = insight_repo.get_insights(user_topic, limit=10)

        # Summary should be substantial but not empty
        assert len(insights[0].summary) > 100
