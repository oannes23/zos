"""Tests for the Reflection Scheduler.

Covers:
- Layer registration on startup
- Cron schedule parsing
- Manual trigger execution
- Job persistence (scheduler rebuild from layer files)
- Self-reflection threshold triggering
- Job management (pause, resume, get_jobs)
- CLI commands
"""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from zos.cli import cli
from zos.config import Config
from zos.database import (
    create_tables,
    generate_id,
    get_engine,
    insights as insights_table,
    layer_runs as layer_runs_table,
    servers as servers_table,
    topics as topics_table,
)
from zos.executor import LayerExecutor
from zos.layers import Layer, LayerCategory, LayerLoader, Node, NodeType
from zos.models import LayerRun, LayerRunStatus, Topic, TopicCategory, utcnow
from zos.salience import ReflectionSelector, SalienceLedger
from zos.scheduler import ReflectionScheduler


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
def selector(ledger: SalienceLedger, test_config: Config) -> ReflectionSelector:
    """Create a ReflectionSelector instance for testing."""
    return ReflectionSelector(ledger, test_config)


@pytest.fixture
def layers_dir(tmp_path: Path) -> Path:
    """Create a temporary layers directory."""
    layers = tmp_path / "layers"
    layers.mkdir()
    return layers


@pytest.fixture
def loader(layers_dir: Path) -> LayerLoader:
    """Create a LayerLoader with temp directory."""
    return LayerLoader(layers_dir)


@pytest.fixture
def mock_executor(test_config: Config) -> MagicMock:
    """Create a mock LayerExecutor."""
    mock = MagicMock(spec=LayerExecutor)

    # Default execute_layer result
    async def mock_execute(*args, **kwargs):
        return LayerRun(
            id=generate_id(),
            layer_name=args[0].name if args else "test-layer",
            layer_hash="abc123",
            started_at=utcnow(),
            completed_at=utcnow(),
            status=LayerRunStatus.SUCCESS,
            targets_matched=1,
            targets_processed=1,
            targets_skipped=0,
            insights_created=1,
        )

    mock.execute_layer = AsyncMock(side_effect=mock_execute)
    return mock


@pytest.fixture
def sample_layer_yaml() -> str:
    """Sample layer YAML with schedule."""
    return """
name: nightly-user-reflection
category: user
description: Nightly user reflection
schedule: "0 13 * * *"
max_targets: 10

nodes:
  - type: fetch_messages
    params:
      lookback_hours: 24
  - type: llm_call
    params:
      prompt_template: user-reflection.jinja2
  - type: store_insight
    params:
      category: user_reflection
"""


@pytest.fixture
def sample_self_layer_yaml() -> str:
    """Sample self-reflection layer YAML."""
    return """
name: self-reflection
category: self
description: Periodic self-reflection
schedule: "0 6 * * 0"
trigger_threshold: 50
max_targets: 1

nodes:
  - type: fetch_insights
    params:
      retrieval_profile: deep
  - type: llm_call
    params:
      prompt_template: self-reflection.jinja2
  - type: update_self_concept
    params:
      document_path: data/self-concept.md
"""


@pytest.fixture
def scheduler_with_layers(
    tmp_path: Path,
    mock_executor: MagicMock,
    loader: LayerLoader,
    selector: ReflectionSelector,
    ledger: SalienceLedger,
    test_config: Config,
    layers_dir: Path,
    sample_layer_yaml: str,
) -> ReflectionScheduler:
    """Create a scheduler with a sample layer registered."""
    # Write sample layer file
    (layers_dir / "nightly-user-reflection.yaml").write_text(sample_layer_yaml)

    # Create scheduler with temp DB path
    scheduler = ReflectionScheduler(
        db_path=str(tmp_path / "scheduler.db"),
        executor=mock_executor,
        loader=loader,
        selector=selector,
        ledger=ledger,
        config=test_config,
    )

    return scheduler


# =============================================================================
# Layer Registration Tests
# =============================================================================


@pytest.mark.asyncio
async def test_register_layers_on_startup(scheduler_with_layers: ReflectionScheduler) -> None:
    """Test that scheduled layers are registered on startup."""
    scheduler_with_layers.start()

    try:
        jobs = scheduler_with_layers.get_jobs()

        assert len(jobs) == 1
        assert jobs[0]["id"] == "layer:nightly-user-reflection"
        assert "Reflection: nightly-user-reflection" in jobs[0]["name"]
    finally:
        scheduler_with_layers.stop()


@pytest.mark.asyncio
async def test_register_multiple_layers(
    tmp_path: Path,
    mock_executor: MagicMock,
    loader: LayerLoader,
    selector: ReflectionSelector,
    ledger: SalienceLedger,
    test_config: Config,
    layers_dir: Path,
    sample_layer_yaml: str,
    sample_self_layer_yaml: str,
) -> None:
    """Test registering multiple scheduled layers."""
    # Write multiple layer files
    (layers_dir / "nightly-user-reflection.yaml").write_text(sample_layer_yaml)
    (layers_dir / "self-reflection.yaml").write_text(sample_self_layer_yaml)

    scheduler = ReflectionScheduler(
        db_path=str(tmp_path / "scheduler.db"),
        executor=mock_executor,
        loader=loader,
        selector=selector,
        ledger=ledger,
        config=test_config,
    )
    scheduler.start()

    try:
        jobs = scheduler.get_jobs()

        assert len(jobs) == 2
        job_ids = {j["id"] for j in jobs}
        assert "layer:nightly-user-reflection" in job_ids
        assert "layer:self-reflection" in job_ids
    finally:
        scheduler.stop()


@pytest.mark.asyncio
async def test_skip_layers_without_schedule(
    tmp_path: Path,
    mock_executor: MagicMock,
    loader: LayerLoader,
    selector: ReflectionSelector,
    ledger: SalienceLedger,
    test_config: Config,
    layers_dir: Path,
) -> None:
    """Test that layers without schedules are not registered."""
    # Write a layer without schedule
    manual_layer_yaml = """
name: manual-synthesis
category: synthesis
description: Manual synthesis layer

nodes:
  - type: llm_call
    params:
      prompt_template: synthesis.jinja2
"""
    (layers_dir / "manual-synthesis.yaml").write_text(manual_layer_yaml)

    scheduler = ReflectionScheduler(
        db_path=str(tmp_path / "scheduler.db"),
        executor=mock_executor,
        loader=loader,
        selector=selector,
        ledger=ledger,
        config=test_config,
    )
    scheduler.start()

    try:
        jobs = scheduler.get_jobs()
        assert len(jobs) == 0
    finally:
        scheduler.stop()


@pytest.mark.asyncio
async def test_invalid_cron_schedule_logged(
    tmp_path: Path,
    mock_executor: MagicMock,
    loader: LayerLoader,
    selector: ReflectionSelector,
    ledger: SalienceLedger,
    test_config: Config,
    layers_dir: Path,
) -> None:
    """Test that invalid cron schedules are logged as errors."""
    # Write a layer with invalid schedule
    invalid_layer_yaml = """
name: invalid-schedule
category: user
description: Layer with invalid cron
schedule: "invalid cron expression"

nodes:
  - type: llm_call
    params:
      prompt_template: test.jinja2
"""
    (layers_dir / "invalid-schedule.yaml").write_text(invalid_layer_yaml)

    scheduler = ReflectionScheduler(
        db_path=str(tmp_path / "scheduler.db"),
        executor=mock_executor,
        loader=loader,
        selector=selector,
        ledger=ledger,
        config=test_config,
    )

    # Should not raise, just log error and skip
    scheduler.start()

    try:
        # No jobs should be registered due to invalid cron
        jobs = scheduler.get_jobs()
        assert len(jobs) == 0
    finally:
        scheduler.stop()


# =============================================================================
# Manual Trigger Tests
# =============================================================================


@pytest.mark.asyncio
async def test_manual_trigger_executes_layer(
    scheduler_with_layers: ReflectionScheduler,
    mock_executor: MagicMock,
    engine,
) -> None:
    """Test that manual trigger executes the layer."""
    # Create a topic for the layer to process
    with engine.connect() as conn:
        conn.execute(
            topics_table.insert().values(
                key="server:123:user:456",
                category="user",
                is_global=False,
                provisional=False,
                created_at=utcnow(),
            )
        )
        conn.commit()

    # Mock selector to return topics
    with patch.object(
        scheduler_with_layers, "_select_topics", new_callable=AsyncMock
    ) as mock_select:
        mock_select.return_value = ["server:123:user:456"]

        run = await scheduler_with_layers.trigger_now("nightly-user-reflection")

    assert run is not None
    assert run.status == LayerRunStatus.SUCCESS
    mock_executor.execute_layer.assert_called_once()


@pytest.mark.asyncio
async def test_manual_trigger_returns_none_for_unknown_layer(
    scheduler_with_layers: ReflectionScheduler,
) -> None:
    """Test that manual trigger returns None for unknown layer."""
    run = await scheduler_with_layers.trigger_now("nonexistent-layer")

    assert run is None


@pytest.mark.asyncio
async def test_manual_trigger_returns_none_when_no_topics(
    scheduler_with_layers: ReflectionScheduler,
) -> None:
    """Test that manual trigger returns None when no topics selected."""
    # Mock selector to return empty list
    with patch.object(
        scheduler_with_layers, "_select_topics", new_callable=AsyncMock
    ) as mock_select:
        mock_select.return_value = []

        run = await scheduler_with_layers.trigger_now("nightly-user-reflection")

    assert run is None


# =============================================================================
# Job Persistence Tests
# =============================================================================


@pytest.mark.asyncio
async def test_scheduler_rebuilds_from_layer_files(
    tmp_path: Path,
    mock_executor: MagicMock,
    loader: LayerLoader,
    selector: ReflectionSelector,
    ledger: SalienceLedger,
    test_config: Config,
    layers_dir: Path,
    sample_layer_yaml: str,
) -> None:
    """Test that scheduler rebuilds jobs from layer files on restart."""
    # Write layer file
    (layers_dir / "nightly-user-reflection.yaml").write_text(sample_layer_yaml)

    db_path = str(tmp_path / "scheduler.db")

    # First scheduler instance
    scheduler1 = ReflectionScheduler(
        db_path=db_path,
        executor=mock_executor,
        loader=loader,
        selector=selector,
        ledger=ledger,
        config=test_config,
    )
    scheduler1.start()

    try:
        jobs1 = scheduler1.get_jobs()
        assert len(jobs1) == 1
    finally:
        scheduler1.stop()

    # Second scheduler instance (simulating restart)
    scheduler2 = ReflectionScheduler(
        db_path=db_path,
        executor=mock_executor,
        loader=loader,
        selector=selector,
        ledger=ledger,
        config=test_config,
    )
    scheduler2.start()

    try:
        jobs2 = scheduler2.get_jobs()
        assert len(jobs2) == 1
        assert jobs2[0]["id"] == "layer:nightly-user-reflection"
    finally:
        scheduler2.stop()


@pytest.mark.asyncio
async def test_scheduler_updates_modified_layer(
    tmp_path: Path,
    mock_executor: MagicMock,
    loader: LayerLoader,
    selector: ReflectionSelector,
    ledger: SalienceLedger,
    test_config: Config,
    layers_dir: Path,
    sample_layer_yaml: str,
) -> None:
    """Test that scheduler updates jobs when layer files change."""
    # Write initial layer file
    (layers_dir / "nightly-user-reflection.yaml").write_text(sample_layer_yaml)

    db_path = str(tmp_path / "scheduler.db")

    # First scheduler instance
    scheduler1 = ReflectionScheduler(
        db_path=db_path,
        executor=mock_executor,
        loader=loader,
        selector=selector,
        ledger=ledger,
        config=test_config,
    )
    scheduler1.start()
    scheduler1.stop()

    # Modify layer file with different schedule
    modified_yaml = sample_layer_yaml.replace(
        'schedule: "0 13 * * *"', 'schedule: "0 6 * * *"'
    )
    (layers_dir / "nightly-user-reflection.yaml").write_text(modified_yaml)

    # Need new loader to pick up changes
    loader2 = LayerLoader(layers_dir)

    # Second scheduler instance
    scheduler2 = ReflectionScheduler(
        db_path=db_path,
        executor=mock_executor,
        loader=loader2,
        selector=selector,
        ledger=ledger,
        config=test_config,
    )
    scheduler2.start()

    try:
        jobs2 = scheduler2.get_jobs()
        assert len(jobs2) == 1
        # Verify the trigger contains the new schedule
        assert "6" in jobs2[0]["trigger"]
    finally:
        scheduler2.stop()


# =============================================================================
# Self-Reflection Threshold Tests
# =============================================================================


@pytest.mark.asyncio
async def test_self_reflection_threshold_trigger(
    tmp_path: Path,
    mock_executor: MagicMock,
    loader: LayerLoader,
    selector: ReflectionSelector,
    ledger: SalienceLedger,
    test_config: Config,
    layers_dir: Path,
    sample_self_layer_yaml: str,
    engine,
) -> None:
    """Test that self-reflection triggers when insight threshold is reached."""
    # Write self-reflection layer with threshold of 50
    (layers_dir / "self-reflection.yaml").write_text(sample_self_layer_yaml)

    # Create the self topic
    with engine.connect() as conn:
        conn.execute(
            topics_table.insert().values(
                key="self:zos",
                category="self",
                is_global=True,
                provisional=False,
                created_at=utcnow(),
            )
        )
        conn.commit()

    scheduler = ReflectionScheduler(
        db_path=str(tmp_path / "scheduler.db"),
        executor=mock_executor,
        loader=loader,
        selector=selector,
        ledger=ledger,
        config=test_config,
    )

    # Insert 50 self-insights to reach threshold
    # Need to create layer_runs first to satisfy foreign key
    with engine.connect() as conn:
        for i in range(50):
            layer_run_id = generate_id()
            conn.execute(
                layer_runs_table.insert().values(
                    id=layer_run_id,
                    layer_name="test-layer",
                    layer_hash="abc123",
                    started_at=utcnow(),
                    completed_at=utcnow(),
                    status="success",
                    targets_matched=1,
                    targets_processed=1,
                    targets_skipped=0,
                    insights_created=1,
                )
            )
            conn.execute(
                insights_table.insert().values(
                    id=generate_id(),
                    topic_key="self:zos",
                    category="self_reflection",
                    content=f"Self insight {i}",
                    sources_scope_max="derived",
                    created_at=utcnow(),
                    layer_run_id=layer_run_id,
                    quarantined=False,
                    salience_spent=1.0,
                    strength_adjustment=1.0,
                    strength=1.0,
                    original_topic_salience=10.0,
                    confidence=0.8,
                    importance=0.7,
                    novelty=0.6,
                    valence_curiosity=0.5,
                )
            )
        conn.commit()

    # Mock selector to return self topic
    with patch.object(
        scheduler, "_select_topics", new_callable=AsyncMock
    ) as mock_select:
        mock_select.return_value = ["self:zos"]

        run = await scheduler.check_self_reflection_trigger()

    assert run is not None
    assert run.status == LayerRunStatus.SUCCESS


@pytest.mark.asyncio
async def test_self_reflection_below_threshold(
    tmp_path: Path,
    mock_executor: MagicMock,
    loader: LayerLoader,
    selector: ReflectionSelector,
    ledger: SalienceLedger,
    test_config: Config,
    layers_dir: Path,
    sample_self_layer_yaml: str,
    engine,
) -> None:
    """Test that self-reflection does not trigger below threshold."""
    # Write self-reflection layer with threshold of 50
    (layers_dir / "self-reflection.yaml").write_text(sample_self_layer_yaml)

    # Create the self topic first
    with engine.connect() as conn:
        conn.execute(
            topics_table.insert().values(
                key="self:zos",
                category="self",
                is_global=True,
                provisional=False,
                created_at=utcnow(),
            )
        )
        conn.commit()

    scheduler = ReflectionScheduler(
        db_path=str(tmp_path / "scheduler.db"),
        executor=mock_executor,
        loader=loader,
        selector=selector,
        ledger=ledger,
        config=test_config,
    )

    # Insert only 10 self-insights (below threshold of 50)
    # Need to create layer_runs first to satisfy foreign key
    with engine.connect() as conn:
        for i in range(10):
            layer_run_id = generate_id()
            conn.execute(
                layer_runs_table.insert().values(
                    id=layer_run_id,
                    layer_name="test-layer",
                    layer_hash="abc123",
                    started_at=utcnow(),
                    completed_at=utcnow(),
                    status="success",
                    targets_matched=1,
                    targets_processed=1,
                    targets_skipped=0,
                    insights_created=1,
                )
            )
            conn.execute(
                insights_table.insert().values(
                    id=generate_id(),
                    topic_key="self:zos",
                    category="self_reflection",
                    content=f"Self insight {i}",
                    sources_scope_max="derived",
                    created_at=utcnow(),
                    layer_run_id=layer_run_id,
                    quarantined=False,
                    salience_spent=1.0,
                    strength_adjustment=1.0,
                    strength=1.0,
                    original_topic_salience=10.0,
                    confidence=0.8,
                    importance=0.7,
                    novelty=0.6,
                    valence_curiosity=0.5,
                )
            )
        conn.commit()

    run = await scheduler.check_self_reflection_trigger()

    assert run is None
    mock_executor.execute_layer.assert_not_called()


# =============================================================================
# Job Management Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_job_info(scheduler_with_layers: ReflectionScheduler) -> None:
    """Test getting information about a specific job."""
    scheduler_with_layers.start()

    try:
        job = scheduler_with_layers.get_job("layer:nightly-user-reflection")

        assert job is not None
        assert job["id"] == "layer:nightly-user-reflection"
        assert job["next_run_time"] is not None
        assert "13" in job["trigger"]  # Should contain the hour
    finally:
        scheduler_with_layers.stop()


@pytest.mark.asyncio
async def test_get_job_not_found(scheduler_with_layers: ReflectionScheduler) -> None:
    """Test getting info for non-existent job returns None."""
    scheduler_with_layers.start()

    try:
        job = scheduler_with_layers.get_job("layer:nonexistent")
        assert job is None
    finally:
        scheduler_with_layers.stop()


@pytest.mark.asyncio
async def test_pause_and_resume_layer(scheduler_with_layers: ReflectionScheduler) -> None:
    """Test pausing and resuming a scheduled layer."""
    scheduler_with_layers.start()

    try:
        # Pause
        success = scheduler_with_layers.pause_layer("nightly-user-reflection")
        assert success is True

        job = scheduler_with_layers.get_job("layer:nightly-user-reflection")
        assert job["next_run_time"] is None  # Paused jobs have no next run

        # Resume
        success = scheduler_with_layers.resume_layer("nightly-user-reflection")
        assert success is True

        job = scheduler_with_layers.get_job("layer:nightly-user-reflection")
        assert job["next_run_time"] is not None
    finally:
        scheduler_with_layers.stop()


@pytest.mark.asyncio
async def test_pause_nonexistent_layer(scheduler_with_layers: ReflectionScheduler) -> None:
    """Test that pausing non-existent layer returns False."""
    scheduler_with_layers.start()

    try:
        success = scheduler_with_layers.pause_layer("nonexistent")
        assert success is False
    finally:
        scheduler_with_layers.stop()


# =============================================================================
# CLI Tests
# =============================================================================


def test_cli_reflect_jobs_command(
    tmp_path: Path,
    layers_dir: Path,
    sample_layer_yaml: str,
    test_config: Config,
) -> None:
    """Test the 'zos reflect jobs' CLI command."""
    # Write layer file
    (layers_dir / "nightly-user-reflection.yaml").write_text(sample_layer_yaml)

    # Create config file
    config_file = tmp_path / "config.yaml"
    config_file.write_text(f"data_dir: {tmp_path}\n")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["-c", str(config_file), "reflect", "jobs", "-d", str(layers_dir)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert "nightly-user-reflection" in result.output
    assert "0 13 * * *" in result.output  # The cron schedule should appear


def test_cli_reflect_trigger_layer_not_found(
    tmp_path: Path,
    layers_dir: Path,
    sample_layer_yaml: str,
) -> None:
    """Test the 'zos reflect trigger' CLI command with unknown layer."""
    # Write layer file
    (layers_dir / "nightly-user-reflection.yaml").write_text(sample_layer_yaml)

    # Create prompts directory (required by CLI)
    prompts_dir = Path("prompts")
    prompts_dir.mkdir(exist_ok=True)

    # Create config file
    config_file = tmp_path / "config.yaml"
    config_file.write_text(f"data_dir: {tmp_path}\n")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["-c", str(config_file), "reflect", "trigger", "nonexistent", "-d", str(layers_dir)],
    )

    assert "not found" in result.output.lower() or "Layer not found" in result.output


# =============================================================================
# Edge Cases
# =============================================================================


@pytest.mark.asyncio
async def test_scheduler_handles_empty_layers_directory(
    tmp_path: Path,
    mock_executor: MagicMock,
    loader: LayerLoader,
    selector: ReflectionSelector,
    ledger: SalienceLedger,
    test_config: Config,
) -> None:
    """Test that scheduler handles empty layers directory gracefully."""
    scheduler = ReflectionScheduler(
        db_path=str(tmp_path / "scheduler.db"),
        executor=mock_executor,
        loader=loader,
        selector=selector,
        ledger=ledger,
        config=test_config,
    )

    # Should not raise
    scheduler.start()

    try:
        jobs = scheduler.get_jobs()
        assert len(jobs) == 0
    finally:
        scheduler.stop()


@pytest.mark.asyncio
async def test_execute_layer_handles_error_gracefully(
    scheduler_with_layers: ReflectionScheduler,
    mock_executor: MagicMock,
) -> None:
    """Test that layer execution handles errors gracefully."""
    # Make executor raise an exception
    mock_executor.execute_layer = AsyncMock(side_effect=Exception("Test error"))

    # Mock selector
    with patch.object(
        scheduler_with_layers, "_select_topics", new_callable=AsyncMock
    ) as mock_select:
        mock_select.return_value = ["server:123:user:456"]

        # Should not raise, just return None and log error
        run = await scheduler_with_layers.trigger_now("nightly-user-reflection")

    assert run is None


@pytest.mark.asyncio
async def test_cron_schedule_utc_timezone(
    scheduler_with_layers: ReflectionScheduler,
) -> None:
    """Test that cron schedules are configured for UTC execution."""
    scheduler_with_layers.start()

    try:
        job = scheduler_with_layers.get_job("layer:nightly-user-reflection")

        # The next run time should be timezone-aware
        assert job["next_run_time"].tzinfo is not None

        # Convert to UTC to verify the scheduled time
        utc_time = job["next_run_time"].astimezone(timezone.utc)
        # The job is scheduled for "0 13 * * *" (1pm UTC)
        assert utc_time.hour == 13
        assert utc_time.minute == 0
    finally:
        scheduler_with_layers.stop()


@pytest.mark.asyncio
async def test_cron_schedule_respects_configured_timezone(
    tmp_path: Path,
    mock_executor: MagicMock,
    loader: LayerLoader,
    selector: ReflectionSelector,
    ledger: SalienceLedger,
    test_config: Config,
    layers_dir: Path,
    sample_layer_yaml: str,
) -> None:
    """Test that cron schedules respect the configured timezone."""
    from zoneinfo import ZoneInfo

    # Create a config with Pacific timezone
    test_config.scheduler.timezone = "America/Los_Angeles"

    # Write sample layer file
    (layers_dir / "nightly-user-reflection.yaml").write_text(sample_layer_yaml)

    # Create scheduler with Pacific timezone config
    scheduler = ReflectionScheduler(
        db_path=str(tmp_path / "scheduler.db"),
        executor=mock_executor,
        loader=loader,
        selector=selector,
        ledger=ledger,
        config=test_config,
    )

    scheduler.start()

    try:
        job = scheduler.get_job("layer:nightly-user-reflection")

        # The next run time should be timezone-aware
        assert job["next_run_time"].tzinfo is not None

        # Convert to Pacific to verify the scheduled time
        pacific_time = job["next_run_time"].astimezone(ZoneInfo("America/Los_Angeles"))
        # The job is scheduled for "0 13 * * *" (1pm Pacific)
        assert pacific_time.hour == 13
        assert pacific_time.minute == 0
    finally:
        scheduler.stop()


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.asyncio
async def test_full_scheduled_execution_flow(
    tmp_path: Path,
    mock_executor: MagicMock,
    loader: LayerLoader,
    selector: ReflectionSelector,
    ledger: SalienceLedger,
    test_config: Config,
    layers_dir: Path,
    sample_layer_yaml: str,
    engine,
) -> None:
    """Test the full flow from schedule trigger to execution."""
    # Write layer file
    (layers_dir / "nightly-user-reflection.yaml").write_text(sample_layer_yaml)

    # Create topics with salience
    with engine.connect() as conn:
        conn.execute(
            topics_table.insert().values(
                key="server:123:user:456",
                category="user",
                is_global=False,
                provisional=False,
                created_at=utcnow(),
            )
        )
        conn.commit()

    # Add salience to make topic selectable
    await ledger.earn("server:123:user:456", 50.0, reason="test")

    scheduler = ReflectionScheduler(
        db_path=str(tmp_path / "scheduler.db"),
        executor=mock_executor,
        loader=loader,
        selector=selector,
        ledger=ledger,
        config=test_config,
    )
    scheduler.start()

    try:
        # Get the layer and call the internal execute method directly
        # (Simulating what the scheduler would do at trigger time)
        run = await scheduler._execute_layer("nightly-user-reflection")

        assert run is not None
        assert run.status == LayerRunStatus.SUCCESS
        mock_executor.execute_layer.assert_called_once()
    finally:
        scheduler.stop()
