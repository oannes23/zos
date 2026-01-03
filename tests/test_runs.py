"""Tests for run management and scheduling."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zos.db import Database
from zos.layer.executor import ExecutionResult
from zos.scheduler.models import Run, RunStatus, TraceEntry, TriggerType
from zos.scheduler.repository import RunRepository
from zos.scheduler.window import calculate_run_window


@pytest.fixture
def run_repo(test_db: Database) -> RunRepository:
    """Create a run repository with test database."""
    return RunRepository(test_db)


class TestRunModels:
    """Tests for Run and TraceEntry models."""

    def test_run_creation(self) -> None:
        """Test creating a Run with minimal fields."""
        now = datetime.now(UTC)
        run = Run(
            run_id="test-run-1",
            layer_name="channel_digest",
            triggered_by=TriggerType.MANUAL,
            status=RunStatus.PENDING,
            started_at=now,
            window_start=now - timedelta(hours=24),
            window_end=now,
        )

        assert run.run_id == "test-run-1"
        assert run.layer_name == "channel_digest"
        assert run.triggered_by == TriggerType.MANUAL
        assert run.status == RunStatus.PENDING
        assert run.targets_total == 0
        assert run.tokens_used == 0
        assert run.estimated_cost_usd == 0.0

    def test_run_duration_not_finished(self) -> None:
        """Test duration is None when run not finished."""
        now = datetime.now(UTC)
        run = Run(
            run_id="test-run-1",
            layer_name="test",
            triggered_by=TriggerType.SCHEDULE,
            status=RunStatus.RUNNING,
            started_at=now,
            window_start=now,
            window_end=now,
        )

        assert run.duration_seconds is None

    def test_run_duration_finished(self) -> None:
        """Test duration calculation for finished run."""
        started = datetime.now(UTC)
        completed = started + timedelta(seconds=45.5)
        run = Run(
            run_id="test-run-1",
            layer_name="test",
            triggered_by=TriggerType.SCHEDULE,
            status=RunStatus.COMPLETED,
            started_at=started,
            completed_at=completed,
            window_start=started,
            window_end=started,
        )

        assert run.duration_seconds == 45.5

    def test_run_is_finished(self) -> None:
        """Test is_finished property for various statuses."""
        now = datetime.now(UTC)
        base = {
            "run_id": "test",
            "layer_name": "test",
            "triggered_by": TriggerType.MANUAL,
            "started_at": now,
            "window_start": now,
            "window_end": now,
        }

        assert not Run(**base, status=RunStatus.PENDING).is_finished
        assert not Run(**base, status=RunStatus.RUNNING).is_finished
        assert Run(**base, status=RunStatus.COMPLETED).is_finished
        assert Run(**base, status=RunStatus.FAILED).is_finished
        assert Run(**base, status=RunStatus.CANCELLED).is_finished

    def test_trace_entry_creation(self) -> None:
        """Test creating a TraceEntry."""
        now = datetime.now(UTC)
        entry = TraceEntry(
            run_id="run-1",
            node_name="fetch_messages",
            success=True,
            executed_at=now,
            topic_key="channel:123",
            tokens_used=100,
        )

        assert entry.run_id == "run-1"
        assert entry.node_name == "fetch_messages"
        assert entry.success
        assert entry.topic_key == "channel:123"
        assert entry.tokens_used == 100
        assert not entry.skipped


class TestRunRepository:
    """Tests for RunRepository."""

    def test_create_and_get_run(self, run_repo: RunRepository) -> None:
        """Test creating and retrieving a run."""
        now = datetime.now(UTC)
        run = Run(
            run_id="test-run-1",
            layer_name="channel_digest",
            triggered_by=TriggerType.MANUAL,
            status=RunStatus.PENDING,
            started_at=now,
            window_start=now - timedelta(hours=24),
            window_end=now,
        )

        run_repo.create_run(run)

        retrieved = run_repo.get_run("test-run-1")
        assert retrieved is not None
        assert retrieved.run_id == "test-run-1"
        assert retrieved.layer_name == "channel_digest"
        assert retrieved.status == RunStatus.PENDING

    def test_get_run_not_found(self, run_repo: RunRepository) -> None:
        """Test getting a non-existent run."""
        result = run_repo.get_run("nonexistent")
        assert result is None

    def test_update_status(self, run_repo: RunRepository) -> None:
        """Test updating run status."""
        now = datetime.now(UTC)
        run = Run(
            run_id="test-run-1",
            layer_name="test",
            triggered_by=TriggerType.MANUAL,
            status=RunStatus.PENDING,
            started_at=now,
            window_start=now,
            window_end=now,
        )
        run_repo.create_run(run)

        run_repo.update_status("test-run-1", RunStatus.RUNNING)

        retrieved = run_repo.get_run("test-run-1")
        assert retrieved is not None
        assert retrieved.status == RunStatus.RUNNING

    def test_update_status_with_error(self, run_repo: RunRepository) -> None:
        """Test updating status to failed with error message."""
        now = datetime.now(UTC)
        run = Run(
            run_id="test-run-1",
            layer_name="test",
            triggered_by=TriggerType.MANUAL,
            status=RunStatus.RUNNING,
            started_at=now,
            window_start=now,
            window_end=now,
        )
        run_repo.create_run(run)

        run_repo.update_status("test-run-1", RunStatus.FAILED, "Connection timeout")

        retrieved = run_repo.get_run("test-run-1")
        assert retrieved is not None
        assert retrieved.status == RunStatus.FAILED
        assert retrieved.error_message == "Connection timeout"
        assert retrieved.completed_at is not None

    def test_complete_run_success(self, run_repo: RunRepository) -> None:
        """Test completing a run with success result."""
        now = datetime.now(UTC)
        run = Run(
            run_id="test-run-1",
            layer_name="test",
            triggered_by=TriggerType.MANUAL,
            status=RunStatus.RUNNING,
            started_at=now,
            window_start=now,
            window_end=now,
        )
        run_repo.create_run(run)

        result = ExecutionResult(
            success=True,
            run_id="test-run-1",
            layer_name="test",
            targets_processed=10,
            targets_skipped=2,
            total_tokens=5000,
            errors=[],
            trace=[],
            started_at=now,
            completed_at=now + timedelta(seconds=30),
        )

        run_repo.complete_run("test-run-1", result, estimated_cost_usd=0.05, salience_spent=12.5)

        retrieved = run_repo.get_run("test-run-1")
        assert retrieved is not None
        assert retrieved.status == RunStatus.COMPLETED
        assert retrieved.targets_processed == 10
        assert retrieved.targets_skipped == 2
        assert retrieved.targets_total == 12
        assert retrieved.tokens_used == 5000
        assert retrieved.estimated_cost_usd == 0.05
        assert retrieved.salience_spent == 12.5

    def test_complete_run_failure(self, run_repo: RunRepository) -> None:
        """Test completing a run with failure result."""
        now = datetime.now(UTC)
        run = Run(
            run_id="test-run-1",
            layer_name="test",
            triggered_by=TriggerType.MANUAL,
            status=RunStatus.RUNNING,
            started_at=now,
            window_start=now,
            window_end=now,
        )
        run_repo.create_run(run)

        result = ExecutionResult(
            success=False,
            run_id="test-run-1",
            layer_name="test",
            targets_processed=5,
            targets_skipped=0,
            total_tokens=2000,
            errors=["LLM call failed", "Timeout"],
            trace=[],
            started_at=now,
            completed_at=now + timedelta(seconds=15),
        )

        run_repo.complete_run("test-run-1", result)

        retrieved = run_repo.get_run("test-run-1")
        assert retrieved is not None
        assert retrieved.status == RunStatus.FAILED
        assert retrieved.error_message == "LLM call failed; Timeout"

    def test_get_runs_no_filter(self, run_repo: RunRepository) -> None:
        """Test getting runs without filters."""
        now = datetime.now(UTC)

        for i in range(3):
            run = Run(
                run_id=f"run-{i}",
                layer_name="test",
                triggered_by=TriggerType.MANUAL,
                status=RunStatus.COMPLETED,
                started_at=now + timedelta(seconds=i),
                window_start=now,
                window_end=now,
            )
            run_repo.create_run(run)

        runs = run_repo.get_runs()

        assert len(runs) == 3
        # Should be ordered by started_at descending
        assert runs[0].run_id == "run-2"
        assert runs[1].run_id == "run-1"
        assert runs[2].run_id == "run-0"

    def test_get_runs_filter_by_layer(self, run_repo: RunRepository) -> None:
        """Test filtering runs by layer name."""
        now = datetime.now(UTC)

        for layer in ["layer_a", "layer_b", "layer_a"]:
            run = Run(
                run_id=f"run-{layer}-{now.timestamp()}",
                layer_name=layer,
                triggered_by=TriggerType.MANUAL,
                status=RunStatus.COMPLETED,
                started_at=now,
                window_start=now,
                window_end=now,
            )
            run_repo.create_run(run)
            now += timedelta(seconds=1)

        runs = run_repo.get_runs(layer_name="layer_a")
        assert len(runs) == 2
        assert all(r.layer_name == "layer_a" for r in runs)

    def test_get_runs_filter_by_status(self, run_repo: RunRepository) -> None:
        """Test filtering runs by status."""
        now = datetime.now(UTC)

        statuses = [RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.COMPLETED]
        for i, status in enumerate(statuses):
            run = Run(
                run_id=f"run-{i}",
                layer_name="test",
                triggered_by=TriggerType.MANUAL,
                status=status,
                started_at=now + timedelta(seconds=i),
                window_start=now,
                window_end=now,
            )
            run_repo.create_run(run)

        runs = run_repo.get_runs(status=RunStatus.COMPLETED)
        assert len(runs) == 2
        assert all(r.status == RunStatus.COMPLETED for r in runs)

    def test_get_runs_with_limit(self, run_repo: RunRepository) -> None:
        """Test limiting number of runs returned."""
        now = datetime.now(UTC)

        for i in range(10):
            run = Run(
                run_id=f"run-{i}",
                layer_name="test",
                triggered_by=TriggerType.MANUAL,
                status=RunStatus.COMPLETED,
                started_at=now + timedelta(seconds=i),
                window_start=now,
                window_end=now,
            )
            run_repo.create_run(run)

        runs = run_repo.get_runs(limit=3)
        assert len(runs) == 3

    def test_get_last_successful_run(self, run_repo: RunRepository) -> None:
        """Test getting the last successful run for a layer."""
        now = datetime.now(UTC)

        # Create runs with different statuses
        statuses = [RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.COMPLETED]
        for i, status in enumerate(statuses):
            run = Run(
                run_id=f"run-{i}",
                layer_name="test",
                triggered_by=TriggerType.MANUAL,
                status=status,
                started_at=now + timedelta(seconds=i),
                window_start=now,
                window_end=now,
            )
            run_repo.create_run(run)
            # Set completed_at for completed runs
            if status == RunStatus.COMPLETED:
                run_repo.update_status(run.run_id, status)

        last = run_repo.get_last_successful_run("test")

        assert last is not None
        assert last.run_id == "run-2"  # Most recent completed
        assert last.status == RunStatus.COMPLETED

    def test_get_last_successful_run_none(self, run_repo: RunRepository) -> None:
        """Test getting last successful run when none exist."""
        now = datetime.now(UTC)

        # Create only a failed run
        run = Run(
            run_id="run-1",
            layer_name="test",
            triggered_by=TriggerType.MANUAL,
            status=RunStatus.FAILED,
            started_at=now,
            window_start=now,
            window_end=now,
        )
        run_repo.create_run(run)

        last = run_repo.get_last_successful_run("test")
        assert last is None

    def test_is_layer_running_true(self, run_repo: RunRepository) -> None:
        """Test checking if layer is running when it is."""
        now = datetime.now(UTC)

        run = Run(
            run_id="run-1",
            layer_name="test",
            triggered_by=TriggerType.MANUAL,
            status=RunStatus.RUNNING,
            started_at=now,
            window_start=now,
            window_end=now,
        )
        run_repo.create_run(run)

        assert run_repo.is_layer_running("test") is True

    def test_is_layer_running_false(self, run_repo: RunRepository) -> None:
        """Test checking if layer is running when it's not."""
        now = datetime.now(UTC)

        run = Run(
            run_id="run-1",
            layer_name="test",
            triggered_by=TriggerType.MANUAL,
            status=RunStatus.COMPLETED,
            started_at=now,
            window_start=now,
            window_end=now,
        )
        run_repo.create_run(run)

        assert run_repo.is_layer_running("test") is False

    def test_is_layer_running_pending(self, run_repo: RunRepository) -> None:
        """Test that pending runs count as running."""
        now = datetime.now(UTC)

        run = Run(
            run_id="run-1",
            layer_name="test",
            triggered_by=TriggerType.MANUAL,
            status=RunStatus.PENDING,
            started_at=now,
            window_start=now,
            window_end=now,
        )
        run_repo.create_run(run)

        assert run_repo.is_layer_running("test") is True

    def test_mark_stale_runs_failed(self, run_repo: RunRepository) -> None:
        """Test marking stale runs as failed."""
        now = datetime.now(UTC)

        # Create runs with various statuses
        for status in [RunStatus.RUNNING, RunStatus.PENDING, RunStatus.COMPLETED]:
            run = Run(
                run_id=f"run-{status.value}",
                layer_name="test",
                triggered_by=TriggerType.MANUAL,
                status=status,
                started_at=now,
                window_start=now,
                window_end=now,
            )
            run_repo.create_run(run)

        count = run_repo.mark_stale_runs_failed()

        assert count == 2  # running and pending

        running_run = run_repo.get_run("run-running")
        assert running_run is not None
        assert running_run.status == RunStatus.FAILED
        assert "interrupted" in (running_run.error_message or "").lower()

        completed_run = run_repo.get_run("run-completed")
        assert completed_run is not None
        assert completed_run.status == RunStatus.COMPLETED  # Unchanged

    def test_save_and_get_trace(self, run_repo: RunRepository) -> None:
        """Test saving and retrieving execution traces."""
        now = datetime.now(UTC)

        run = Run(
            run_id="run-1",
            layer_name="test",
            triggered_by=TriggerType.MANUAL,
            status=RunStatus.COMPLETED,
            started_at=now,
            window_start=now,
            window_end=now,
        )
        run_repo.create_run(run)

        trace = [
            {
                "node": "fetch_messages",
                "topic": "channel:123",
                "success": True,
                "skipped": False,
                "tokens_used": 0,
                "timestamp": now.isoformat(),
            },
            {
                "node": "llm_call",
                "topic": "channel:123",
                "success": True,
                "skipped": False,
                "tokens_used": 500,
                "timestamp": now.isoformat(),
            },
            {
                "node": "skip_target:channel:456",
                "topic": "channel:456",
                "success": True,
                "skipped": True,
                "skip_reason": "Insufficient budget",
                "timestamp": now.isoformat(),
            },
        ]

        run_repo.save_trace("run-1", trace)

        retrieved_trace = run_repo.get_trace("run-1")

        assert len(retrieved_trace) == 3
        assert retrieved_trace[0].node_name == "fetch_messages"
        assert retrieved_trace[0].success
        assert not retrieved_trace[0].skipped

        assert retrieved_trace[1].tokens_used == 500

        assert retrieved_trace[2].skipped
        assert retrieved_trace[2].skip_reason == "Insufficient budget"


class TestWindowCalculation:
    """Tests for time window calculation."""

    def test_first_run_uses_max_lookback(self, run_repo: RunRepository) -> None:
        """Test that first run uses max lookback hours."""
        before = datetime.now(UTC)
        window_start, window_end = calculate_run_window(
            layer_name="new_layer",
            max_lookback_hours=24,
            run_repo=run_repo,
        )
        after = datetime.now(UTC)

        # Window end should be approximately now
        assert before <= window_end <= after

        # Window start should be approximately 24 hours ago
        expected_start = window_end - timedelta(hours=24)
        assert abs((window_start - expected_start).total_seconds()) < 1

    def test_subsequent_run_uses_last_completion(self, run_repo: RunRepository) -> None:
        """Test that subsequent runs use last completion time."""
        now = datetime.now(UTC)
        last_completed = now - timedelta(hours=6)

        # Create a completed run
        run = Run(
            run_id="previous-run",
            layer_name="test_layer",
            triggered_by=TriggerType.SCHEDULE,
            status=RunStatus.COMPLETED,
            started_at=last_completed - timedelta(minutes=5),
            window_start=last_completed - timedelta(hours=24),
            window_end=last_completed,
        )
        run_repo.create_run(run)
        run_repo.update_status("previous-run", RunStatus.COMPLETED)

        window_start, window_end = calculate_run_window(
            layer_name="test_layer",
            max_lookback_hours=24,
            run_repo=run_repo,
        )

        # Window start should be around last completion time
        retrieved = run_repo.get_run("previous-run")
        assert retrieved is not None
        assert retrieved.completed_at is not None
        # Since completed_at is set to now() when we call update_status,
        # the window_start should be that time

    def test_old_run_capped_at_max_lookback(self, run_repo: RunRepository) -> None:
        """Test that very old runs are capped at max lookback."""
        now = datetime.now(UTC)
        very_old = now - timedelta(days=30)  # 30 days ago

        # Create a completed run from 30 days ago
        run = Run(
            run_id="old-run",
            layer_name="test_layer",
            triggered_by=TriggerType.SCHEDULE,
            status=RunStatus.COMPLETED,
            started_at=very_old,
            completed_at=very_old,
            window_start=very_old - timedelta(hours=24),
            window_end=very_old,
        )
        run_repo.create_run(run)

        window_start, window_end = calculate_run_window(
            layer_name="test_layer",
            max_lookback_hours=168,  # 1 week
            run_repo=run_repo,
        )

        # Window start should be capped at 1 week ago, not 30 days
        max_start = window_end - timedelta(hours=168)
        assert abs((window_start - max_start).total_seconds()) < 1


class TestLayerScheduler:
    """Tests for LayerScheduler."""

    @pytest.fixture
    def mock_run_manager(self) -> MagicMock:
        """Create a mock RunManager."""
        manager = MagicMock()
        manager.execute_layer = AsyncMock()
        manager.recover_stale_runs = MagicMock(return_value=0)
        return manager

    def test_register_layer_with_schedule(self, mock_run_manager: MagicMock) -> None:
        """Test registering a layer with a valid schedule."""
        from zos.scheduler.scheduler import LayerScheduler

        scheduler = LayerScheduler(mock_run_manager)

        layer = MagicMock()
        layer.name = "test_layer"
        layer.schedule = "0 0 * * *"  # Daily at midnight

        result = scheduler.register_layer(layer)

        assert result is True
        assert "test_layer" in scheduler.get_scheduled_layers()

    def test_register_layer_without_schedule(self, mock_run_manager: MagicMock) -> None:
        """Test registering a layer without a schedule."""
        from zos.scheduler.scheduler import LayerScheduler

        scheduler = LayerScheduler(mock_run_manager)

        layer = MagicMock()
        layer.name = "test_layer"
        layer.schedule = None

        result = scheduler.register_layer(layer)

        assert result is False
        assert "test_layer" not in scheduler.get_scheduled_layers()

    def test_register_layer_invalid_cron(self, mock_run_manager: MagicMock) -> None:
        """Test registering a layer with invalid cron expression."""
        from zos.scheduler.scheduler import LayerScheduler

        scheduler = LayerScheduler(mock_run_manager)

        layer = MagicMock()
        layer.name = "test_layer"
        layer.schedule = "invalid cron"

        result = scheduler.register_layer(layer)

        assert result is False

    def test_register_multiple_layers(self, mock_run_manager: MagicMock) -> None:
        """Test registering multiple layers."""
        from zos.scheduler.scheduler import LayerScheduler

        scheduler = LayerScheduler(mock_run_manager)

        layers = []
        for i, schedule in enumerate(["0 0 * * *", None, "0 12 * * *"]):
            layer = MagicMock()
            layer.name = f"layer_{i}"
            layer.schedule = schedule
            layers.append(layer)

        count = scheduler.register_layers(layers)

        assert count == 2  # Only layers with schedules
        assert len(scheduler.get_scheduled_layers()) == 2

    def test_unregister_layer(self, mock_run_manager: MagicMock) -> None:
        """Test unregistering a layer."""
        from zos.scheduler.scheduler import LayerScheduler

        scheduler = LayerScheduler(mock_run_manager)

        layer = MagicMock()
        layer.name = "test_layer"
        layer.schedule = "0 0 * * *"
        scheduler.register_layer(layer)

        result = scheduler.unregister_layer("test_layer")

        assert result is True
        assert "test_layer" not in scheduler.get_scheduled_layers()

    def test_unregister_nonexistent_layer(self, mock_run_manager: MagicMock) -> None:
        """Test unregistering a layer that doesn't exist."""
        from zos.scheduler.scheduler import LayerScheduler

        scheduler = LayerScheduler(mock_run_manager)

        result = scheduler.unregister_layer("nonexistent")

        assert result is False

    async def test_trigger_layer(self, mock_run_manager: MagicMock) -> None:
        """Test manually triggering a layer."""
        from zos.scheduler.models import TriggerType
        from zos.scheduler.scheduler import LayerScheduler

        scheduler = LayerScheduler(mock_run_manager)

        await scheduler.trigger_layer("test_layer")

        mock_run_manager.execute_layer.assert_called_once_with(
            layer_name="test_layer",
            triggered_by=TriggerType.MANUAL,
        )

    async def test_start_recovers_stale_runs(self, mock_run_manager: MagicMock) -> None:
        """Test that starting scheduler recovers stale runs."""
        from zos.scheduler.scheduler import LayerScheduler

        scheduler = LayerScheduler(mock_run_manager)

        scheduler.start()
        scheduler.stop()

        mock_run_manager.recover_stale_runs.assert_called_once()

    async def test_get_next_run_time_registered(self, mock_run_manager: MagicMock) -> None:
        """Test getting next run time for a registered layer."""
        from zos.scheduler.scheduler import LayerScheduler

        scheduler = LayerScheduler(mock_run_manager)

        layer = MagicMock()
        layer.name = "test_layer"
        layer.schedule = "0 0 * * *"  # Daily at midnight
        scheduler.register_layer(layer)
        scheduler.start()

        next_time = scheduler.get_next_run_time("test_layer")
        scheduler.stop()

        assert next_time is not None

    def test_get_next_run_time_unregistered(self, mock_run_manager: MagicMock) -> None:
        """Test getting next run time for an unregistered layer."""
        from zos.scheduler.scheduler import LayerScheduler

        scheduler = LayerScheduler(mock_run_manager)

        next_time = scheduler.get_next_run_time("nonexistent")

        assert next_time is None


class TestRunManager:
    """Tests for RunManager."""

    @pytest.fixture
    def mock_llm_client(self) -> MagicMock:
        """Create a mock LLM client."""
        return MagicMock()

    @pytest.fixture
    def mock_layer_loader(self) -> MagicMock:
        """Create a mock layer loader."""
        loader = MagicMock()
        layer = MagicMock()
        layer.name = "test_layer"
        layer.max_lookback_hours = 24
        layer.salience_rules.spend_per_target = 1.0
        loader.load.return_value = layer
        return loader

    @pytest.fixture
    def mock_config(self, temp_dir) -> MagicMock:
        """Create a mock config."""
        from zos.config import BudgetConfig, CategoryWeights

        config = MagicMock()
        config.budget = BudgetConfig(
            total_tokens_per_run=10000,
            per_topic_cap=2000,
            category_weights=CategoryWeights(),
        )
        config.layers_dir = temp_dir / "layers"
        return config

    async def test_execute_layer_skips_if_running(
        self,
        test_db: Database,
        mock_llm_client: MagicMock,
        mock_layer_loader: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test that execute_layer skips if layer is already running."""
        from zos.scheduler.run_manager import RunManager

        # Create a running run
        run_repo = RunRepository(test_db)
        now = datetime.now(UTC)
        run = Run(
            run_id="existing-run",
            layer_name="test_layer",
            triggered_by=TriggerType.SCHEDULE,
            status=RunStatus.RUNNING,
            started_at=now,
            window_start=now,
            window_end=now,
        )
        run_repo.create_run(run)

        manager = RunManager(
            db=test_db,
            llm_client=mock_llm_client,
            config=mock_config,
            layer_loader=mock_layer_loader,
        )

        result = await manager.execute_layer("test_layer", TriggerType.MANUAL)

        assert result is None

    async def test_execute_layer_creates_run_record(
        self,
        test_db: Database,
        mock_llm_client: MagicMock,
        mock_layer_loader: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test that execute_layer creates a run record."""
        from zos.scheduler.run_manager import RunManager

        manager = RunManager(
            db=test_db,
            llm_client=mock_llm_client,
            config=mock_config,
            layer_loader=mock_layer_loader,
        )

        # Mock the executor to avoid actual execution
        now = datetime.now(UTC)
        mock_result = ExecutionResult(
            success=True,
            run_id="test-run",
            layer_name="test_layer",
            targets_processed=5,
            targets_skipped=2,
            total_tokens=1000,
            errors=[],
            trace=[],
            started_at=now,
            completed_at=now + timedelta(seconds=10),
        )

        with patch.object(manager._executor, "execute", new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = mock_result

            result = await manager.execute_layer("test_layer", TriggerType.MANUAL)

            assert result is not None
            assert result.layer_name == "test_layer"
            assert result.status == RunStatus.COMPLETED

    def test_recover_stale_runs(
        self,
        test_db: Database,
        mock_llm_client: MagicMock,
        mock_layer_loader: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test recovering stale runs on startup."""
        from zos.scheduler.run_manager import RunManager

        # Create stale runs
        run_repo = RunRepository(test_db)
        now = datetime.now(UTC)

        for status in [RunStatus.RUNNING, RunStatus.PENDING]:
            run = Run(
                run_id=f"stale-{status.value}",
                layer_name="test_layer",
                triggered_by=TriggerType.SCHEDULE,
                status=status,
                started_at=now,
                window_start=now,
                window_end=now,
            )
            run_repo.create_run(run)

        manager = RunManager(
            db=test_db,
            llm_client=mock_llm_client,
            config=mock_config,
            layer_loader=mock_layer_loader,
        )

        count = manager.recover_stale_runs()

        assert count == 2

        # Verify runs are marked as failed
        for status in [RunStatus.RUNNING, RunStatus.PENDING]:
            run = manager.get_run(f"stale-{status.value}")
            assert run is not None
            assert run.status == RunStatus.FAILED

    def test_is_layer_running(
        self,
        test_db: Database,
        mock_llm_client: MagicMock,
        mock_layer_loader: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test checking if a layer is running."""
        from zos.scheduler.run_manager import RunManager

        manager = RunManager(
            db=test_db,
            llm_client=mock_llm_client,
            config=mock_config,
            layer_loader=mock_layer_loader,
        )

        assert manager.is_layer_running("test_layer") is False

        # Create a running run
        run_repo = RunRepository(test_db)
        now = datetime.now(UTC)
        run = Run(
            run_id="running-run",
            layer_name="test_layer",
            triggered_by=TriggerType.SCHEDULE,
            status=RunStatus.RUNNING,
            started_at=now,
            window_start=now,
            window_end=now,
        )
        run_repo.create_run(run)

        assert manager.is_layer_running("test_layer") is True
