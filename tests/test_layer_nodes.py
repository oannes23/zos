"""Tests for layer pipeline nodes."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from zos.layer.context import PipelineContext
from zos.layer.nodes import (
    NodeResult,
    create_node,
)
from zos.layer.nodes.fetch_insights import FetchInsightsNode
from zos.layer.nodes.fetch_messages import FetchMessagesNode
from zos.layer.nodes.llm_call import LLMCallNode
from zos.layer.nodes.output import OutputNode
from zos.layer.nodes.reduce import ReduceNode
from zos.layer.nodes.store_insight import StoreInsightNode
from zos.layer.schema import (
    FetchInsightsConfig,
    FetchMessagesConfig,
    LLMCallConfig,
    ModelDefaults,
    OutputConfig,
    ReduceConfig,
    StoreInsightConfig,
)
from zos.topics.topic_key import TopicKey

# =============================================================================
# NodeResult Tests
# =============================================================================


class TestNodeResult:
    """Tests for NodeResult dataclass."""

    def test_ok_result(self) -> None:
        """Test creating success result."""
        result = NodeResult.ok(data="test data", tokens_used=100)
        assert result.success is True
        assert result.data == "test data"
        assert result.tokens_used == 100
        assert result.skipped is False
        assert result.error is None

    def test_skip_result(self) -> None:
        """Test creating skip result."""
        result = NodeResult.skip(reason="Budget exhausted")
        assert result.success is True
        assert result.skipped is True
        assert result.skip_reason == "Budget exhausted"

    def test_fail_result(self) -> None:
        """Test creating fail result."""
        result = NodeResult.fail(error="Something went wrong")
        assert result.success is False
        assert result.error == "Something went wrong"


# =============================================================================
# Node Factory Tests
# =============================================================================


class TestNodeFactory:
    """Tests for node factory function."""

    def test_create_fetch_messages_node(self) -> None:
        """Test creating FetchMessagesNode."""
        config = FetchMessagesConfig(type="fetch_messages")
        node = create_node(config)
        assert isinstance(node, FetchMessagesNode)

    def test_create_fetch_insights_node(self) -> None:
        """Test creating FetchInsightsNode."""
        config = FetchInsightsConfig(type="fetch_insights")
        node = create_node(config)
        assert isinstance(node, FetchInsightsNode)

    def test_create_llm_call_node(self) -> None:
        """Test creating LLMCallNode."""
        config = LLMCallConfig(type="llm_call", prompt="test")
        node = create_node(config)
        assert isinstance(node, LLMCallNode)

    def test_create_reduce_node(self) -> None:
        """Test creating ReduceNode."""
        config = ReduceConfig(type="reduce")
        node = create_node(config)
        assert isinstance(node, ReduceNode)

    def test_create_store_insight_node(self) -> None:
        """Test creating StoreInsightNode."""
        config = StoreInsightConfig(type="store_insight")
        node = create_node(config)
        assert isinstance(node, StoreInsightNode)

    def test_create_output_node(self) -> None:
        """Test creating OutputNode."""
        config = OutputConfig(type="output")
        node = create_node(config)
        assert isinstance(node, OutputNode)

    def test_unknown_node_type(self) -> None:
        """Test error for unknown node type."""
        from zos.exceptions import LayerValidationError

        # Create a mock config with unknown type
        config = MagicMock()
        config.type = "unknown_type"

        with pytest.raises(LayerValidationError, match="Unknown node type"):
            create_node(config)


# =============================================================================
# Context Fixture
# =============================================================================


@pytest.fixture
def mock_context(tmp_path: Path) -> PipelineContext:  # noqa: ARG001
    """Create a mock pipeline context."""
    # Create mock dependencies
    mock_db = MagicMock()
    mock_llm_client = MagicMock()
    mock_message_repo = MagicMock()
    mock_salience_repo = MagicMock()
    mock_token_ledger = MagicMock()
    mock_token_ledger.can_afford.return_value = True

    context = PipelineContext(
        run_id="test-run-123",
        layer_name="test_layer",
        run_start=datetime.now(UTC),
        db=mock_db,
        llm_client=mock_llm_client,
        message_repo=mock_message_repo,
        salience_repo=mock_salience_repo,
        token_ledger=mock_token_ledger,
        current_topic=TopicKey.channel(123456),
        model_defaults=ModelDefaults(),
    )
    return context


# =============================================================================
# FetchMessagesNode Tests
# =============================================================================


class TestFetchMessagesNode:
    """Tests for FetchMessagesNode."""

    @pytest.fixture
    def node(self) -> FetchMessagesNode:
        """Create a fetch_messages node."""
        config = FetchMessagesConfig(
            type="fetch_messages",
            lookback_hours=24,
            max_messages=100,
            scope="public",
        )
        return FetchMessagesNode(config=config)

    def test_node_type(self, node: FetchMessagesNode) -> None:
        """Test node type property."""
        assert node.node_type == "fetch_messages"

    @pytest.mark.asyncio
    async def test_execute_channel_topic(
        self, node: FetchMessagesNode, mock_context: PipelineContext
    ) -> None:
        """Test executing for channel topic."""
        # Setup mock messages
        mock_context.message_repo.get_messages_by_channel.return_value = [
            {"message_id": 1, "content": "Test 1", "visibility_scope": "public"},
            {"message_id": 2, "content": "Test 2", "visibility_scope": "public"},
        ]

        result = await node.execute(mock_context)

        assert result.success is True
        assert len(result.data) == 2
        assert mock_context.get("messages") == result.data
        mock_context.message_repo.get_messages_by_channel.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_user_topic(
        self, node: FetchMessagesNode, mock_context: PipelineContext
    ) -> None:
        """Test executing for user topic."""
        mock_context.current_topic = TopicKey.user(789)
        mock_context.message_repo.get_messages_by_user.return_value = [
            {"message_id": 1, "content": "Test", "visibility_scope": "public"}
        ]

        result = await node.execute(mock_context)

        assert result.success is True
        mock_context.message_repo.get_messages_by_user.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_filters_by_scope(
        self, node: FetchMessagesNode, mock_context: PipelineContext
    ) -> None:
        """Test that messages are filtered by visibility scope."""
        mock_context.message_repo.get_messages_by_channel.return_value = [
            {"message_id": 1, "content": "Public", "visibility_scope": "public"},
            {"message_id": 2, "content": "DM", "visibility_scope": "dm"},
        ]

        result = await node.execute(mock_context)

        # Only public message returned (node scope is "public")
        assert len(result.data) == 1
        assert result.data[0]["visibility_scope"] == "public"

    @pytest.mark.asyncio
    async def test_execute_no_topic(
        self, node: FetchMessagesNode, mock_context: PipelineContext
    ) -> None:
        """Test failure when no topic set."""
        mock_context.current_topic = None

        result = await node.execute(mock_context)

        assert result.success is False
        assert "No current topic" in result.error

    def test_validate_no_topic(
        self, node: FetchMessagesNode, mock_context: PipelineContext
    ) -> None:
        """Test validation catches missing topic."""
        mock_context.current_topic = None
        errors = node.validate(mock_context)
        assert len(errors) == 1
        assert "current topic" in errors[0]


# =============================================================================
# FetchInsightsNode Tests (Stub)
# =============================================================================


class TestFetchInsightsNode:
    """Tests for FetchInsightsNode (stub implementation)."""

    @pytest.fixture
    def node(self) -> FetchInsightsNode:
        """Create a fetch_insights node."""
        config = FetchInsightsConfig(type="fetch_insights", max_insights=10)
        return FetchInsightsNode(config=config)

    def test_node_type(self, node: FetchInsightsNode) -> None:
        """Test node type property."""
        assert node.node_type == "fetch_insights"

    @pytest.mark.asyncio
    async def test_execute_returns_empty_and_skips(
        self, node: FetchInsightsNode, mock_context: PipelineContext
    ) -> None:
        """Test stub returns empty list and skip status."""
        result = await node.execute(mock_context)

        assert result.success is True
        assert result.skipped is True
        assert "Phase 8" in result.skip_reason
        assert mock_context.get("insights") == []


# =============================================================================
# LLMCallNode Tests
# =============================================================================


class TestLLMCallNode:
    """Tests for LLMCallNode."""

    @pytest.fixture
    def node(self) -> LLMCallNode:
        """Create an llm_call node."""
        config = LLMCallConfig(
            type="llm_call",
            prompt="summarize",
            system_prompt="system",
        )
        return LLMCallNode(config=config)

    def test_node_type(self, node: LLMCallNode) -> None:
        """Test node type property."""
        assert node.node_type == "llm_call"

    @pytest.mark.asyncio
    async def test_execute_calls_llm(
        self, node: LLMCallNode, mock_context: PipelineContext
    ) -> None:
        """Test executing LLM call."""
        # Setup mock LLM response
        mock_response = MagicMock()
        mock_response.content = "Summary output"
        mock_response.prompt_tokens = 100
        mock_response.completion_tokens = 50
        mock_context.llm_client.complete_with_prompt = AsyncMock(
            return_value=mock_response
        )

        result = await node.execute(mock_context)

        assert result.success is True
        assert result.data == "Summary output"
        assert result.tokens_used == 150
        assert mock_context.get("llm_output") == "Summary output"
        mock_context.llm_client.complete_with_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_skips_when_budget_exhausted(
        self, node: LLMCallNode, mock_context: PipelineContext
    ) -> None:
        """Test skips when budget is exhausted."""
        mock_context.token_ledger.can_afford.return_value = False
        mock_context.token_ledger.get_remaining.return_value = 50

        result = await node.execute(mock_context)

        assert result.success is True
        assert result.skipped is True
        assert "Insufficient budget" in result.skip_reason

    @pytest.mark.asyncio
    async def test_execute_spends_tokens(
        self, node: LLMCallNode, mock_context: PipelineContext
    ) -> None:
        """Test that tokens are spent after call."""
        mock_response = MagicMock()
        mock_response.content = "Output"
        mock_response.prompt_tokens = 100
        mock_response.completion_tokens = 50
        mock_context.llm_client.complete_with_prompt = AsyncMock(
            return_value=mock_response
        )

        await node.execute(mock_context)

        mock_context.token_ledger.spend.assert_called_once()
        call_args = mock_context.token_ledger.spend.call_args
        assert call_args[0][1] == 150  # tokens spent

    def test_estimate_tokens(
        self, node: LLMCallNode, mock_context: PipelineContext
    ) -> None:
        """Test token estimation."""
        # Add some messages
        mock_context.set("messages", [
            {"content": "Short message"},
            {"content": "Another message here"},
        ])

        estimate = node.estimate_tokens(mock_context)

        # Should include message content + max_tokens for output
        assert estimate > 1024  # Base max_tokens


# =============================================================================
# ReduceNode Tests
# =============================================================================


class TestReduceNode:
    """Tests for ReduceNode."""

    @pytest.fixture
    def concat_node(self) -> ReduceNode:
        """Create a reduce node with concatenate strategy."""
        config = ReduceConfig(type="reduce", strategy="concatenate")
        return ReduceNode(config=config)

    def test_node_type(self, concat_node: ReduceNode) -> None:
        """Test node type property."""
        assert concat_node.node_type == "reduce"

    @pytest.mark.asyncio
    async def test_execute_concatenate(
        self, concat_node: ReduceNode, mock_context: PipelineContext
    ) -> None:
        """Test concatenate strategy."""
        mock_context.set("target_outputs", ["Output 1", "Output 2", "Output 3"])

        result = await concat_node.execute(mock_context)

        assert result.success is True
        assert "Output 1" in result.data
        assert "Output 2" in result.data
        assert "Output 3" in result.data
        assert mock_context.get("reduced_output") == result.data

    @pytest.mark.asyncio
    async def test_execute_empty_outputs(
        self, concat_node: ReduceNode, mock_context: PipelineContext
    ) -> None:
        """Test handling empty outputs."""
        mock_context.set("target_outputs", [])

        result = await concat_node.execute(mock_context)

        assert result.success is True
        assert result.data == ""

    @pytest.mark.asyncio
    async def test_execute_summarize(
        self, mock_context: PipelineContext
    ) -> None:
        """Test summarize strategy."""
        config = ReduceConfig(
            type="reduce",
            strategy="summarize",
            prompt="summarize_outputs",
        )
        node = ReduceNode(config=config)

        mock_context.set("target_outputs", ["Output 1", "Output 2"])

        # Mock LLM response
        mock_response = MagicMock()
        mock_response.content = "Combined summary"
        mock_response.prompt_tokens = 100
        mock_response.completion_tokens = 50
        mock_context.llm_client.complete_with_prompt = AsyncMock(
            return_value=mock_response
        )

        result = await node.execute(mock_context)

        assert result.success is True
        assert result.data == "Combined summary"
        assert result.tokens_used == 150

    def test_validate_summarize_requires_prompt(
        self, mock_context: PipelineContext
    ) -> None:
        """Test validation catches missing prompt for summarize."""
        config = ReduceConfig(type="reduce", strategy="summarize")  # No prompt
        node = ReduceNode(config=config)

        errors = node.validate(mock_context)

        assert len(errors) == 1
        assert "requires a prompt" in errors[0]

    @pytest.mark.asyncio
    async def test_execute_summarize_skips_when_budget_exhausted(
        self, mock_context: PipelineContext
    ) -> None:
        """Test summarize strategy respects budget."""
        config = ReduceConfig(
            type="reduce",
            strategy="summarize",
            prompt="summarize_outputs",
        )
        node = ReduceNode(config=config)

        mock_context.set("target_outputs", ["Output 1", "Output 2"])
        mock_context.token_ledger.can_afford.return_value = False
        mock_context.token_ledger.get_remaining.return_value = 50

        result = await node.execute(mock_context)

        assert result.success is True
        assert result.skipped is True
        assert "Insufficient budget" in result.skip_reason

    @pytest.mark.asyncio
    async def test_execute_summarize_spends_tokens(
        self, mock_context: PipelineContext
    ) -> None:
        """Test that tokens are spent after summarize."""
        config = ReduceConfig(
            type="reduce",
            strategy="summarize",
            prompt="summarize_outputs",
        )
        node = ReduceNode(config=config)

        mock_context.set("target_outputs", ["Output 1", "Output 2"])

        # Mock LLM response
        mock_response = MagicMock()
        mock_response.content = "Combined summary"
        mock_response.prompt_tokens = 100
        mock_response.completion_tokens = 50
        mock_context.llm_client.complete_with_prompt = AsyncMock(
            return_value=mock_response
        )

        await node.execute(mock_context)

        mock_context.token_ledger.spend.assert_called_once()
        call_args = mock_context.token_ledger.spend.call_args
        assert call_args[0][1] == 150  # tokens spent

    def test_estimate_tokens(self, mock_context: PipelineContext) -> None:
        """Test token estimation for summarize."""
        config = ReduceConfig(
            type="reduce",
            strategy="summarize",
            prompt="test",
            max_tokens=512,
        )
        node = ReduceNode(config=config)

        # Set outputs with known length
        mock_context.set("target_outputs", ["A" * 400, "B" * 400])  # 800 chars

        estimate = node.estimate_tokens(mock_context)

        # Should be: 800/4 (input) + 512 (max_tokens) = 712
        assert estimate == 712


# =============================================================================
# StoreInsightNode Tests (Stub)
# =============================================================================


class TestStoreInsightNode:
    """Tests for StoreInsightNode (stub implementation)."""

    @pytest.fixture
    def node(self) -> StoreInsightNode:
        """Create a store_insight node."""
        config = StoreInsightConfig(type="store_insight")
        return StoreInsightNode(config=config)

    def test_node_type(self, node: StoreInsightNode) -> None:
        """Test node type property."""
        assert node.node_type == "store_insight"

    @pytest.mark.asyncio
    async def test_execute_skips_with_message(
        self, node: StoreInsightNode, mock_context: PipelineContext
    ) -> None:
        """Test stub returns skip status."""
        mock_context.set("llm_output", "Test insight content")

        result = await node.execute(mock_context)

        assert result.success is True
        assert result.skipped is True
        assert "Phase 8" in result.skip_reason


# =============================================================================
# OutputNode Tests
# =============================================================================


class TestOutputNode:
    """Tests for OutputNode."""

    @pytest.fixture
    def log_node(self) -> OutputNode:
        """Create an output node with log destination."""
        config = OutputConfig(type="output", destination="log")
        return OutputNode(config=config)

    def test_node_type(self, log_node: OutputNode) -> None:
        """Test node type property."""
        assert log_node.node_type == "output"

    @pytest.mark.asyncio
    async def test_execute_log_destination(
        self, log_node: OutputNode, mock_context: PipelineContext
    ) -> None:
        """Test log destination."""
        mock_context.set("llm_output", "Test output")

        result = await log_node.execute(mock_context)

        assert result.success is True
        assert result.data == "Test output"
        assert result.skipped is False

    @pytest.mark.asyncio
    async def test_execute_none_destination(
        self, mock_context: PipelineContext
    ) -> None:
        """Test none destination skips."""
        config = OutputConfig(type="output", destination="none")
        node = OutputNode(config=config)

        result = await node.execute(mock_context)

        assert result.success is True
        assert result.skipped is True

    @pytest.mark.asyncio
    async def test_execute_discord_destination_stub(
        self, mock_context: PipelineContext
    ) -> None:
        """Test discord destination (stub)."""
        config = OutputConfig(
            type="output",
            destination="discord",
            channel_id=123456,
        )
        node = OutputNode(config=config)
        mock_context.set("llm_output", "Discord output")

        result = await node.execute(mock_context)

        assert result.success is True
        assert result.skipped is True  # Stub skips
        assert "Phase 11" in result.skip_reason

    @pytest.mark.asyncio
    async def test_execute_discord_requires_channel(
        self, mock_context: PipelineContext
    ) -> None:
        """Test discord destination requires channel_id."""
        config = OutputConfig(type="output", destination="discord")
        node = OutputNode(config=config)

        result = await node.execute(mock_context)

        assert result.success is False
        assert "channel_id" in result.error

    @pytest.mark.asyncio
    async def test_execute_prefers_reduced_output(
        self, log_node: OutputNode, mock_context: PipelineContext
    ) -> None:
        """Test that reduced_output is preferred over llm_output."""
        mock_context.set("llm_output", "LLM output")
        mock_context.set("reduced_output", "Reduced output")

        result = await log_node.execute(mock_context)

        assert result.data == "Reduced output"

    def test_validate_discord_channel(
        self, mock_context: PipelineContext
    ) -> None:
        """Test validation catches missing channel for discord."""
        config = OutputConfig(type="output", destination="discord")
        node = OutputNode(config=config)

        errors = node.validate(mock_context)

        assert len(errors) == 1
        assert "channel_id" in errors[0]
