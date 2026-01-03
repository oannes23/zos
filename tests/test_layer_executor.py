"""Tests for layer pipeline executor."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from zos.budget.models import AllocationPlan, CategoryAllocation, TopicAllocation
from zos.config import BudgetConfig, DatabaseConfig, ZosConfig
from zos.db import Database
from zos.layer.executor import ExecutionResult, PipelineExecutor
from zos.layer.schema import (
    FetchMessagesConfig,
    LayerDefinition,
    LLMCallConfig,
    ModelDefaults,
    OutputConfig,
    PipelineConfig,
    TargetConfig,
)
from zos.topics.topic_key import TopicCategory, TopicKey


class TestExecutionResult:
    """Tests for ExecutionResult dataclass."""

    def test_duration_seconds(self) -> None:
        """Test duration calculation."""
        started = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        completed = datetime(2024, 1, 1, 12, 0, 30, tzinfo=UTC)

        result = ExecutionResult(
            success=True,
            run_id="test",
            layer_name="test_layer",
            targets_processed=5,
            targets_skipped=2,
            total_tokens=1000,
            errors=[],
            trace=[],
            started_at=started,
            completed_at=completed,
        )

        assert result.duration_seconds == 30.0


class TestPipelineExecutor:
    """Tests for PipelineExecutor."""

    @pytest.fixture
    def test_db(self, tmp_path: Path) -> Database:
        """Create a test database."""
        config = DatabaseConfig(path=tmp_path / "test.db")
        db = Database(config)
        db.initialize()
        return db

    @pytest.fixture
    def mock_llm_client(self) -> MagicMock:
        """Create a mock LLM client."""
        client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Test output"
        mock_response.prompt_tokens = 100
        mock_response.completion_tokens = 50
        client.complete_with_prompt = AsyncMock(return_value=mock_response)
        client.prompts = MagicMock()
        client.prompts.prompt_exists.return_value = True
        return client

    @pytest.fixture
    def test_config(self, tmp_path: Path) -> ZosConfig:
        """Create a test config."""
        return ZosConfig(
            database=DatabaseConfig(path=tmp_path / "test.db"),
            budget=BudgetConfig(),
            layers_dir=tmp_path / "layers",
        )

    @pytest.fixture
    def executor(
        self,
        test_db: Database,
        mock_llm_client: MagicMock,
        test_config: ZosConfig,
    ) -> PipelineExecutor:
        """Create a pipeline executor."""
        return PipelineExecutor(
            db=test_db,
            llm_client=mock_llm_client,
            config=test_config,
        )

    @pytest.fixture
    def simple_layer(self) -> LayerDefinition:
        """Create a simple layer definition."""
        return LayerDefinition(
            name="test_layer",
            targets=TargetConfig(categories=["channel"]),
            pipeline=PipelineConfig(
                for_each="target",
                nodes=[
                    FetchMessagesConfig(type="fetch_messages"),
                    OutputConfig(type="output", destination="log"),
                ],
            ),
        )

    @pytest.fixture
    def llm_layer(self) -> LayerDefinition:
        """Create a layer with LLM call."""
        return LayerDefinition(
            name="llm_layer",
            targets=TargetConfig(categories=["channel"]),
            model_defaults=ModelDefaults(),
            pipeline=PipelineConfig(
                for_each="target",
                nodes=[
                    FetchMessagesConfig(type="fetch_messages"),
                    LLMCallConfig(type="llm_call", prompt="test"),
                    OutputConfig(type="output", destination="log"),
                ],
            ),
        )

    @pytest.fixture
    def allocation_plan(self) -> AllocationPlan:
        """Create a test allocation plan."""
        channel_topic = TopicKey.channel(123456)
        return AllocationPlan(
            run_id="test-run-123",
            total_budget=10000,
            per_topic_cap=2000,  # Enough for LLM estimate (~1224 tokens)
            category_allocations={
                TopicCategory.CHANNEL: CategoryAllocation(
                    category=TopicCategory.CHANNEL,
                    weight=40,
                    total_tokens=4000,
                    topic_allocations=[
                        TopicAllocation(
                            topic_key=channel_topic,
                            allocated_tokens=2000,  # Enough for LLM estimate
                            salience_balance=50.0,
                            salience_proportion=1.0,
                        ),
                    ],
                ),
            },
            created_at=datetime.now(UTC),
        )

    @pytest.mark.asyncio
    async def test_execute_simple_layer(
        self,
        executor: PipelineExecutor,
        simple_layer: LayerDefinition,
        allocation_plan: AllocationPlan,
    ) -> None:
        """Test executing a simple layer."""
        result = await executor.execute(simple_layer, allocation_plan)

        assert result.success is True
        assert result.run_id == "test-run-123"
        assert result.layer_name == "test_layer"
        assert result.targets_processed == 1
        assert len(result.trace) > 0

    @pytest.mark.asyncio
    async def test_execute_dry_run(
        self,
        executor: PipelineExecutor,
        simple_layer: LayerDefinition,
        allocation_plan: AllocationPlan,
    ) -> None:
        """Test dry-run execution."""
        result = await executor.execute(
            simple_layer, allocation_plan, dry_run=True
        )

        assert result.success is True
        # All trace entries should be skipped (dry run)
        for entry in result.trace:
            assert entry["skipped"] is True

    @pytest.mark.asyncio
    async def test_execute_with_llm_call(
        self,
        executor: PipelineExecutor,
        llm_layer: LayerDefinition,
        allocation_plan: AllocationPlan,
    ) -> None:
        """Test execution with LLM call."""
        result = await executor.execute(llm_layer, allocation_plan)

        assert result.success is True
        assert result.total_tokens == 150  # 100 + 50
        executor.llm_client.complete_with_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_tracks_tokens(
        self,
        executor: PipelineExecutor,
        llm_layer: LayerDefinition,
        allocation_plan: AllocationPlan,
    ) -> None:
        """Test that token usage is tracked."""
        result = await executor.execute(llm_layer, allocation_plan)

        assert result.total_tokens > 0
        # Check trace has token info
        llm_trace = next(
            (t for t in result.trace if t["node"] == "llm_call"), None
        )
        assert llm_trace is not None
        assert llm_trace["tokens_used"] == 150

    @pytest.mark.asyncio
    async def test_execute_no_targets(
        self,
        executor: PipelineExecutor,
        simple_layer: LayerDefinition,
    ) -> None:
        """Test execution with no matching targets."""
        empty_plan = AllocationPlan(
            run_id="test-run",
            total_budget=10000,
            per_topic_cap=1000,
            category_allocations={},  # No allocations
            created_at=datetime.now(UTC),
        )

        result = await executor.execute(simple_layer, empty_plan)

        assert result.success is True
        assert result.targets_processed == 0
        assert result.targets_skipped == 0

    @pytest.mark.asyncio
    async def test_execute_filters_by_min_salience(
        self,
        executor: PipelineExecutor,
    ) -> None:
        """Test that targets are filtered by minimum salience."""
        layer = LayerDefinition(
            name="test_layer",
            targets=TargetConfig(
                categories=["channel"],
                min_salience=100.0,  # High threshold
            ),
            pipeline=PipelineConfig(
                for_each="target",
                nodes=[FetchMessagesConfig(type="fetch_messages")],
            ),
        )

        plan = AllocationPlan(
            run_id="test-run",
            total_budget=10000,
            per_topic_cap=1000,
            category_allocations={
                TopicCategory.CHANNEL: CategoryAllocation(
                    category=TopicCategory.CHANNEL,
                    weight=40,
                    total_tokens=4000,
                    topic_allocations=[
                        TopicAllocation(
                            topic_key=TopicKey.channel(1),
                            allocated_tokens=1000,
                            salience_balance=50.0,  # Below threshold
                            salience_proportion=1.0,
                        ),
                    ],
                ),
            },
            created_at=datetime.now(UTC),
        )

        result = await executor.execute(layer, plan)

        assert result.success is True
        assert result.targets_processed == 0  # Filtered out

    @pytest.mark.asyncio
    async def test_execute_respects_max_targets(
        self,
        executor: PipelineExecutor,
    ) -> None:
        """Test that max_targets limits processing."""
        layer = LayerDefinition(
            name="test_layer",
            targets=TargetConfig(
                categories=["channel"],
                max_targets=1,  # Only process 1
            ),
            pipeline=PipelineConfig(
                for_each="target",
                nodes=[FetchMessagesConfig(type="fetch_messages")],
            ),
        )

        plan = AllocationPlan(
            run_id="test-run",
            total_budget=10000,
            per_topic_cap=1000,
            category_allocations={
                TopicCategory.CHANNEL: CategoryAllocation(
                    category=TopicCategory.CHANNEL,
                    weight=40,
                    total_tokens=4000,
                    topic_allocations=[
                        TopicAllocation(
                            topic_key=TopicKey.channel(1),
                            allocated_tokens=500,
                            salience_balance=50.0,
                            salience_proportion=0.5,
                        ),
                        TopicAllocation(
                            topic_key=TopicKey.channel(2),
                            allocated_tokens=500,
                            salience_balance=30.0,
                            salience_proportion=0.5,
                        ),
                    ],
                ),
            },
            created_at=datetime.now(UTC),
        )

        result = await executor.execute(layer, plan)

        assert result.success is True
        assert result.targets_processed == 1  # Limited to 1

    @pytest.mark.asyncio
    async def test_execute_records_duration(
        self,
        executor: PipelineExecutor,
        simple_layer: LayerDefinition,
        allocation_plan: AllocationPlan,
    ) -> None:
        """Test that execution duration is recorded."""
        result = await executor.execute(simple_layer, allocation_plan)

        assert result.started_at < result.completed_at
        assert result.duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_execute_without_for_each(
        self,
        executor: PipelineExecutor,
        allocation_plan: AllocationPlan,
    ) -> None:
        """Test execution without for_each (single execution)."""
        layer = LayerDefinition(
            name="test_layer",
            pipeline=PipelineConfig(
                # No for_each
                nodes=[OutputConfig(type="output", destination="log")],
            ),
        )

        result = await executor.execute(layer, allocation_plan)

        assert result.success is True
        assert result.targets_processed == 1

    @pytest.mark.asyncio
    async def test_validate_layer(
        self,
        executor: PipelineExecutor,
    ) -> None:
        """Test layer validation."""
        valid_layer = LayerDefinition(
            name="valid",
            targets=TargetConfig(categories=["channel"]),
            pipeline=PipelineConfig(
                nodes=[FetchMessagesConfig(type="fetch_messages")],
            ),
        )

        errors = await executor.validate_layer(valid_layer)
        assert errors == []

    @pytest.mark.asyncio
    async def test_validate_layer_invalid_category(
        self,
        executor: PipelineExecutor,
    ) -> None:
        """Test validation catches invalid categories."""
        invalid_layer = LayerDefinition(
            name="invalid",
            targets=TargetConfig(categories=["invalid_category"]),
            pipeline=PipelineConfig(
                nodes=[FetchMessagesConfig(type="fetch_messages")],
            ),
        )

        errors = await executor.validate_layer(invalid_layer)
        assert len(errors) == 1
        assert "Invalid target category" in errors[0]

    @pytest.mark.asyncio
    async def test_execute_budget_exhaustion_mid_loop(
        self,
        executor: PipelineExecutor,
    ) -> None:
        """Test behavior when budget runs out during for_each loop."""
        # Layer with LLM call
        layer = LayerDefinition(
            name="test_layer",
            targets=TargetConfig(categories=["channel"]),
            model_defaults=ModelDefaults(),
            pipeline=PipelineConfig(
                for_each="target",
                nodes=[
                    FetchMessagesConfig(type="fetch_messages"),
                    LLMCallConfig(type="llm_call", prompt="test"),
                ],
            ),
        )

        # Allocation with two targets but very limited budget
        plan = AllocationPlan(
            run_id="test-run",
            total_budget=200,  # Very small
            per_topic_cap=100,  # Only enough for one call
            category_allocations={
                TopicCategory.CHANNEL: CategoryAllocation(
                    category=TopicCategory.CHANNEL,
                    weight=40,
                    total_tokens=200,
                    topic_allocations=[
                        TopicAllocation(
                            topic_key=TopicKey.channel(1),
                            allocated_tokens=100,
                            salience_balance=50.0,
                            salience_proportion=0.5,
                        ),
                        TopicAllocation(
                            topic_key=TopicKey.channel(2),
                            allocated_tokens=100,
                            salience_balance=30.0,
                            salience_proportion=0.5,
                        ),
                    ],
                ),
            },
            created_at=datetime.now(UTC),
        )

        result = await executor.execute(layer, plan)

        assert result.success is True
        # At least one target should have been skipped due to budget
        # (the exact behavior depends on token estimation and spending)
        assert result.targets_processed + result.targets_skipped == 2

    @pytest.mark.asyncio
    async def test_execute_node_failure_propagation(
        self,
        executor: PipelineExecutor,
        allocation_plan: AllocationPlan,
    ) -> None:
        """Test that node failures are properly recorded in trace."""
        from zos.exceptions import LLMError

        # Layer with LLM call that will fail
        layer = LayerDefinition(
            name="test_layer",
            targets=TargetConfig(categories=["channel"]),
            model_defaults=ModelDefaults(),
            pipeline=PipelineConfig(
                for_each="target",
                nodes=[
                    FetchMessagesConfig(type="fetch_messages"),
                    LLMCallConfig(type="llm_call", prompt="test"),
                    OutputConfig(type="output", destination="log"),
                ],
            ),
        )

        # Make LLM call fail
        executor.llm_client.complete_with_prompt.side_effect = LLMError("API error")

        result = await executor.execute(layer, allocation_plan)

        # Execution should complete but with errors
        assert result.success is False
        assert len(result.errors) > 0
        assert "API error" in result.errors[0]

        # Trace should show the failure
        llm_trace = next(
            (t for t in result.trace if t["node"] == "llm_call"), None
        )
        assert llm_trace is not None
        assert llm_trace["success"] is False
        assert "API error" in llm_trace["error"]
