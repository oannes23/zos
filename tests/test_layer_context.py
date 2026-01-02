"""Tests for layer pipeline context."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from zos.layer.context import PipelineContext, TraceEntry
from zos.topics.topic_key import TopicKey


class TestTraceEntry:
    """Tests for TraceEntry dataclass."""

    def test_create_entry(self) -> None:
        """Test creating a trace entry."""
        entry = TraceEntry(
            node="test_node",
            topic="channel:123",
            success=True,
            skipped=False,
            skip_reason=None,
            tokens_used=100,
            error=None,
            timestamp="2024-01-01T12:00:00+00:00",
        )
        assert entry.node == "test_node"
        assert entry.success is True


class TestPipelineContext:
    """Tests for PipelineContext."""

    @pytest.fixture
    def mock_deps(self) -> dict:
        """Create mock dependencies."""
        return {
            "db": MagicMock(),
            "llm_client": MagicMock(),
            "message_repo": MagicMock(),
            "salience_repo": MagicMock(),
            "token_ledger": MagicMock(),
        }

    @pytest.fixture
    def context(self, mock_deps: dict) -> PipelineContext:
        """Create a test context."""
        return PipelineContext(
            run_id="test-run-123",
            layer_name="test_layer",
            run_start=datetime.now(UTC),
            current_topic=TopicKey.channel(123456),
            **mock_deps,
        )

    def test_set_and_get(self, context: PipelineContext) -> None:
        """Test setting and getting data."""
        context.set("messages", ["msg1", "msg2"])
        context.set("count", 42)

        assert context.get("messages") == ["msg1", "msg2"]
        assert context.get("count") == 42

    def test_get_default(self, context: PipelineContext) -> None:
        """Test getting with default value."""
        assert context.get("nonexistent") is None
        assert context.get("nonexistent", "default") == "default"

    def test_has(self, context: PipelineContext) -> None:
        """Test checking key existence."""
        context.set("key", "value")

        assert context.has("key") is True
        assert context.has("other") is False

    def test_add_trace(self, context: PipelineContext) -> None:
        """Test adding trace entries."""
        context.add_trace(
            "node1",
            success=True,
            tokens_used=100,
        )
        context.add_trace(
            "node2",
            success=False,
            error="Something failed",
        )

        trace = context.get_trace()

        assert len(trace) == 2
        assert trace[0]["node"] == "node1"
        assert trace[0]["success"] is True
        assert trace[0]["tokens_used"] == 100
        assert trace[1]["node"] == "node2"
        assert trace[1]["success"] is False
        assert trace[1]["error"] == "Something failed"

    def test_add_trace_with_topic(self, context: PipelineContext) -> None:
        """Test trace includes topic."""
        context.add_trace("node", success=True)

        trace = context.get_trace()

        assert trace[0]["topic"] == "channel:123456"

    def test_add_trace_skip(self, context: PipelineContext) -> None:
        """Test adding skipped trace entry."""
        context.add_trace(
            "skipped_node",
            success=True,
            skipped=True,
            skip_reason="Budget exhausted",
        )

        trace = context.get_trace()

        assert trace[0]["skipped"] is True
        assert trace[0]["skip_reason"] == "Budget exhausted"

    def test_get_trace_returns_copy(self, context: PipelineContext) -> None:
        """Test that get_trace returns a copy."""
        context.add_trace("node", success=True)

        trace1 = context.get_trace()
        trace2 = context.get_trace()

        assert trace1 is not trace2
        assert trace1 == trace2

    def test_fork_for_target(
        self, context: PipelineContext, mock_deps: dict  # noqa: ARG002
    ) -> None:
        """Test forking context for a new target."""
        context.set("original_data", "value")

        new_topic = TopicKey.user(789)
        forked = context.fork_for_target(new_topic)

        # Same run metadata
        assert forked.run_id == context.run_id
        assert forked.layer_name == context.layer_name
        assert forked.run_start == context.run_start

        # Different topic
        assert forked.current_topic == new_topic
        assert forked.current_topic != context.current_topic

        # Fresh data store
        assert forked.has("original_data") is False

        # Same dependencies
        assert forked.db is context.db
        assert forked.llm_client is context.llm_client

    def test_fork_shares_trace(self, context: PipelineContext) -> None:
        """Test that forked context shares trace."""
        context.add_trace("original", success=True)

        forked = context.fork_for_target(TopicKey.user(789))
        forked.add_trace("forked", success=True)

        # Both contexts see same trace
        assert len(context.get_trace()) == 2
        assert len(forked.get_trace()) == 2

    def test_context_without_topic(self, mock_deps: dict) -> None:
        """Test context without current topic."""
        context = PipelineContext(
            run_id="test",
            layer_name="test",
            run_start=datetime.now(UTC),
            **mock_deps,
        )

        assert context.current_topic is None

        context.add_trace("node", success=True)
        trace = context.get_trace()

        assert trace[0]["topic"] is None
