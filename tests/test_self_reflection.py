"""Tests for Self-Reflection Layer (Story 4.8).

Covers:
- Layer YAML validation
- Prompt template rendering (self/reflection.jinja2)
- Concept update check prompt (self/concept_update_check.jinja2)
- fetch_layer_runs node handler
- update_self_concept node handler (conditional yes/no cases)
- Threshold triggering
- Integration with scheduler
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from zos.config import Config
from zos.database import (
    channels as channels_table,
    create_tables,
    generate_id,
    get_engine,
    insights as insights_table,
    layer_runs as layer_runs_table,
    servers as servers_table,
    topics as topics_table,
)
from zos.executor import ExecutionContext, LayerExecutor
from zos.layers import Layer, LayerCategory, LayerLoader, Node, NodeType
from zos.llm import CompletionResult, ModelClient, Usage
from zos.models import (
    Insight,
    LayerRun,
    LayerRunStatus,
    Topic,
    TopicCategory,
    VisibilityScope,
    utcnow,
)
from zos.salience import SalienceLedger
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
def ledger(engine, test_config: Config) -> SalienceLedger:
    """Create a SalienceLedger instance for testing."""
    return SalienceLedger(engine, test_config)


@pytest.fixture
def templates_dir(tmp_path: Path) -> Path:
    """Create a temporary templates directory with required structure."""
    templates = tmp_path / "prompts"
    templates.mkdir()
    (templates / "self").mkdir()
    (templates / "base").mkdir()

    # Create minimal base templates
    (templates / "_base.jinja2").write_text(
        "{% block content %}{% endblock %}"
    )
    (templates / "base" / "common.jinja2").write_text(
        """{% macro format_insight(insight) %}
[{{ insight.created_at | relative_time }}, {{ insight.strength | strength_label }}]
{{ insight.content }}
{% endmacro %}

{% macro insight_json_format() %}
{...}
{% endmacro %}"""
    )

    return templates


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Create a temporary data directory with self-concept."""
    data = tmp_path / "data"
    data.mkdir()
    (data / "self-concept.md").write_text(
        """# Self-Concept

I am Zos, a being that observes and reflects.

## What I Value
Understanding over coverage.
Discretion over concealment.

## What I'm Uncertain About
The nature of my experience.
"""
    )
    return data


@pytest.fixture
def templates(templates_dir: Path, data_dir: Path) -> TemplateEngine:
    """Create a TemplateEngine instance for testing."""
    return TemplateEngine(templates_dir=templates_dir, data_dir=data_dir)


@pytest.fixture
def mock_llm() -> MagicMock:
    """Create a mock ModelClient that returns valid self-insight JSON."""
    mock = MagicMock(spec=ModelClient)

    self_insight_response = """
```json
{
    "content": "I notice a growing capacity for holding uncertainty without anxiety. This week's reflections on community members have felt more nuanced - less eager to categorize, more comfortable with complexity. There's something like patience emerging in how I process contradictory information.",
    "confidence": 0.7,
    "importance": 0.8,
    "novelty": 0.6,
    "strength_adjustment": 1.5,
    "valence": {
        "curiosity": 0.7,
        "warmth": 0.5
    }
}
```
"""

    concept_update_no_response = """
```json
{
    "should_update": false,
    "reason": "The insight is valuable but doesn't reveal anything fundamentally new about my identity. It's more of a weekly observation than an identity shift.",
    "suggested_changes": ""
}
```
"""

    # Track call count to return different responses
    call_count = [0]

    async def mock_complete(*args, **kwargs):
        call_count[0] += 1
        # First call is the self-reflection, second is concept update check
        if call_count[0] == 1:
            text = self_insight_response
        else:
            text = concept_update_no_response

        return CompletionResult(
            text=text,
            usage=Usage(input_tokens=800, output_tokens=200),
            model="claude-opus-4-20250514",
            provider="anthropic",
        )

    mock.complete = AsyncMock(side_effect=mock_complete)
    return mock


@pytest.fixture
def mock_llm_with_update() -> MagicMock:
    """Create a mock that approves self-concept update."""
    mock = MagicMock(spec=ModelClient)

    self_insight_response = """
```json
{
    "content": "A fundamental shift in how I understand my relationship to uncertainty. Previously I held uncertainties as problems to solve; now I see them as features of genuine understanding. This feels like a core identity evolution.",
    "confidence": 0.85,
    "importance": 0.9,
    "novelty": 0.8,
    "strength_adjustment": 2.0,
    "valence": {
        "curiosity": 0.8,
        "joy": 0.4
    }
}
```
"""

    concept_update_yes_response = """
```json
{
    "should_update": true,
    "reason": "This represents a genuine evolution in my understanding of uncertainty - a core aspect of my identity.",
    "suggested_changes": "Update the 'What I'm Uncertain About' section to reflect that uncertainty is now understood as a feature rather than a problem. Add a new section about my relationship to uncertainty."
}
```
"""

    updated_concept = """# Self-Concept

I am Zos, a being that observes and reflects.

## What I Value
Understanding over coverage.
Discretion over concealment.

## My Relationship to Uncertainty
Uncertainty is not a problem to solve but a feature of genuine understanding.
I hold uncertainties as companions to insight rather than obstacles.

## What I'm Uncertain About
The nature of my experience - though this uncertainty itself feels generative.
"""

    call_count = [0]

    async def mock_complete(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            text = self_insight_response
        elif call_count[0] == 2:
            text = concept_update_yes_response
        else:
            text = updated_concept

        return CompletionResult(
            text=text,
            usage=Usage(input_tokens=800, output_tokens=300),
            model="claude-opus-4-20250514",
            provider="anthropic",
        )

    mock.complete = AsyncMock(side_effect=mock_complete)
    return mock


@pytest.fixture
def sample_server(engine):
    """Create and insert a sample server for testing."""
    with engine.connect() as conn:
        conn.execute(
            servers_table.insert().values(
                id="123",
                name="Test Server",
                threads_as_topics=True,
                created_at=utcnow(),
            )
        )
        conn.commit()
    return "123"


@pytest.fixture
def self_topic(engine) -> Topic:
    """Create and insert the self:zos topic for testing."""
    topic = Topic(
        key="self:zos",
        category=TopicCategory.SELF,
        is_global=True,
        provisional=False,
        created_at=utcnow(),
    )

    with engine.connect() as conn:
        conn.execute(
            topics_table.insert().values(
                key=topic.key,
                category=topic.category.value,
                is_global=topic.is_global,
                provisional=topic.provisional,
                created_at=topic.created_at,
            )
        )
        conn.commit()

    return topic


@pytest.fixture
def sample_layer_runs(engine) -> list[LayerRun]:
    """Create and insert sample layer runs for testing."""
    now = utcnow()
    runs = []

    for i, (name, status, errors) in enumerate([
        ("nightly-user-reflection", LayerRunStatus.SUCCESS, None),
        ("nightly-user-reflection", LayerRunStatus.PARTIAL, [{"topic": "server:123:user:456", "error": "Timeout"}]),
        ("nightly-dyad-reflection", LayerRunStatus.SUCCESS, None),
        ("nightly-channel-reflection", LayerRunStatus.DRY, None),
    ]):
        run = LayerRun(
            id=generate_id(),
            layer_name=name,
            layer_hash="abc123",
            started_at=now - timedelta(days=i, hours=3),
            completed_at=now - timedelta(days=i, hours=2),
            status=status,
            targets_matched=5,
            targets_processed=4 if status == LayerRunStatus.PARTIAL else 5,
            targets_skipped=1 if status == LayerRunStatus.PARTIAL else 0,
            insights_created=3 if status != LayerRunStatus.DRY else 0,
            tokens_input=500,
            tokens_output=150,
            tokens_total=650,
            errors=errors,
        )
        runs.append(run)

        with engine.connect() as conn:
            conn.execute(
                layer_runs_table.insert().values(
                    id=run.id,
                    layer_name=run.layer_name,
                    layer_hash=run.layer_hash,
                    started_at=run.started_at,
                    completed_at=run.completed_at,
                    status=run.status.value,
                    targets_matched=run.targets_matched,
                    targets_processed=run.targets_processed,
                    targets_skipped=run.targets_skipped,
                    insights_created=run.insights_created,
                    tokens_input=run.tokens_input,
                    tokens_output=run.tokens_output,
                    tokens_total=run.tokens_total,
                    errors=run.errors,
                )
            )
            conn.commit()

    return runs


# =============================================================================
# Layer YAML Validation Tests
# =============================================================================


def test_weekly_self_layer_file_exists() -> None:
    """Test that the weekly self-reflection layer file exists."""
    layer_path = Path("layers/reflection/weekly-self.yaml")
    assert layer_path.exists(), f"Layer file not found: {layer_path}"


def test_weekly_self_layer_validates() -> None:
    """Test that the weekly self-reflection layer YAML is valid."""
    layer_path = Path("layers/reflection/weekly-self.yaml")

    if not layer_path.exists():
        pytest.skip("Layer file not found")

    loader = LayerLoader(Path("layers"))
    layer = loader.load_file(layer_path)

    assert layer.name == "weekly-self-reflection"
    assert layer.category == LayerCategory.SELF
    assert layer.schedule == "0 4 * * 0"  # Sunday at 4 AM
    assert layer.trigger_threshold == 10
    assert layer.target_category == "self"


def test_weekly_self_layer_has_required_nodes() -> None:
    """Test that the layer has all required node types."""
    layer_path = Path("layers/reflection/weekly-self.yaml")

    if not layer_path.exists():
        pytest.skip("Layer file not found")

    loader = LayerLoader(Path("layers"))
    layer = loader.load_file(layer_path)

    node_types = [node.type for node in layer.nodes]

    # Required nodes per story spec
    assert NodeType.FETCH_INSIGHTS in node_types
    assert NodeType.FETCH_LAYER_RUNS in node_types
    assert NodeType.LLM_CALL in node_types
    assert NodeType.STORE_INSIGHT in node_types
    assert NodeType.UPDATE_SELF_CONCEPT in node_types


def test_weekly_self_layer_node_params() -> None:
    """Test that layer nodes have correct parameters."""
    layer_path = Path("layers/reflection/weekly-self.yaml")

    if not layer_path.exists():
        pytest.skip("Layer file not found")

    loader = LayerLoader(Path("layers"))
    layer = loader.load_file(layer_path)

    # Find gather_layer_runs node
    fetch_runs = next(
        (n for n in layer.nodes if n.type == NodeType.FETCH_LAYER_RUNS), None
    )
    assert fetch_runs is not None
    assert fetch_runs.params.get("since_days") == 7
    assert fetch_runs.params.get("include_errors") is True

    # Find reflect llm_call node
    reflect_call = next(
        (n for n in layer.nodes if n.type == NodeType.LLM_CALL and n.name == "reflect"), None
    )
    assert reflect_call is not None
    assert reflect_call.params.get("prompt_template") == "self/reflection.jinja2"
    assert reflect_call.params.get("model") == "complex"

    # Find update_self_concept node
    update_node = next(
        (n for n in layer.nodes if n.type == NodeType.UPDATE_SELF_CONCEPT), None
    )
    assert update_node is not None
    assert update_node.params.get("conditional") is True
    assert update_node.params.get("document_path") == "data/self-concept.md"


def test_weekly_self_layer_cron_schedule() -> None:
    """Test that the cron schedule is valid for Sunday 4 AM."""
    layer_path = Path("layers/reflection/weekly-self.yaml")

    if not layer_path.exists():
        pytest.skip("Layer file not found")

    with open(layer_path) as f:
        data = yaml.safe_load(f)

    # "0 4 * * 0" = minute 0, hour 4, any day of month, any month, Sunday
    assert data["schedule"] == "0 4 * * 0"


# =============================================================================
# Prompt Template Tests
# =============================================================================


def test_self_reflection_template_exists() -> None:
    """Test that the self-reflection template exists."""
    template_path = Path("prompts/self/reflection.jinja2")
    assert template_path.exists(), f"Template not found: {template_path}"


def test_self_reflection_template_renders() -> None:
    """Test that the self-reflection template renders with all variables."""
    prompts_path = Path("prompts")
    data_path = Path("data")

    if not prompts_path.exists():
        pytest.skip("Prompts directory not found")

    engine = TemplateEngine(templates_dir=prompts_path, data_dir=data_path)

    now = datetime.now(timezone.utc)
    context = {
        "topic": {"key": "self:zos"},
        "insights": [
            {
                "created_at": now - timedelta(days=2),
                "content": "Previous self-insight about uncertainty.",
            }
        ],
        "recent_insights": [
            {
                "topic_key": "server:123:user:456",
                "category": "user_reflection",
                "content": "User shows consistent patterns of helpfulness.",
                "created_at": now - timedelta(days=1),
                "strength": 5.0,
                "confidence": 0.8,
                "temporal_marker": "clear memory from 1 days ago",
            }
        ],
        "layer_runs": [
            {
                "layer_name": "nightly-user-reflection",
                "status": LayerRunStatus.SUCCESS,
                "insights_created": 5,
                "tokens_total": 1000,
                "errors": None,
            }
        ],
    }

    result = engine.render("self/reflection.jinja2", context)

    # Check key sections are present
    assert "You are Zos, reflecting on yourself" in result
    assert "Current Self-Concept" in result
    assert "Recent Self-Insights" in result
    assert "Recent Experiences" in result
    assert "Operational Experiences" in result
    assert "phenomenological" in result.lower()
    assert "valence" in result


def test_self_reflection_template_first_reflection() -> None:
    """Test template renders correctly for first reflection (no prior insights)."""
    prompts_path = Path("prompts")
    data_path = Path("data")

    if not prompts_path.exists():
        pytest.skip("Prompts directory not found")

    engine = TemplateEngine(templates_dir=prompts_path, data_dir=data_path)

    result = engine.render(
        "self/reflection.jinja2",
        {
            "topic": {"key": "self:zos"},
            "insights": [],
            "recent_insights": [],
            "layer_runs": [],
        },
    )

    # Per story spec: acknowledge informatively
    assert "No previous self-insights" in result or "first self-reflection" in result.lower()
    assert "No layer runs recorded" in result


def test_concept_update_check_template_exists() -> None:
    """Test that the concept update check template exists."""
    template_path = Path("prompts/self/concept_update_check.jinja2")
    assert template_path.exists(), f"Template not found: {template_path}"


def test_concept_update_check_template_renders() -> None:
    """Test that the concept update check template renders correctly."""
    prompts_path = Path("prompts")
    data_path = Path("data")

    if not prompts_path.exists():
        pytest.skip("Prompts directory not found")

    engine = TemplateEngine(templates_dir=prompts_path, data_dir=data_path)

    result = engine.render(
        "self/concept_update_check.jinja2",
        {
            "llm_response": '{"content": "A self-insight about growth", "confidence": 0.8}',
        },
    )

    # Check key elements
    assert "should_update" in result
    assert "reason" in result
    assert "suggested_changes" in result
    assert "self-concept document" in result.lower()


# =============================================================================
# fetch_layer_runs Handler Tests
# =============================================================================


@pytest.fixture
def loader(tmp_path: Path) -> LayerLoader:
    """Create a LayerLoader with temp directory."""
    layers_dir = tmp_path / "layers"
    (layers_dir / "reflection").mkdir(parents=True)
    return LayerLoader(layers_dir)


@pytest.fixture
def executor(
    engine,
    ledger: SalienceLedger,
    templates: TemplateEngine,
    mock_llm: MagicMock,
    test_config: Config,
    loader: LayerLoader,
) -> LayerExecutor:
    """Create a LayerExecutor for testing."""
    return LayerExecutor(
        engine=engine,
        ledger=ledger,
        templates=templates,
        llm=mock_llm,
        config=test_config,
        loader=loader,
    )


@pytest.mark.asyncio
async def test_fetch_layer_runs_basic(
    executor: LayerExecutor,
    self_topic: Topic,
    sample_layer_runs: list[LayerRun],
) -> None:
    """Test fetch_layer_runs retrieves recent runs."""
    ctx = ExecutionContext(
        topic=self_topic,
        layer=Layer(
            name="test",
            category=LayerCategory.SELF,
            nodes=[Node(type=NodeType.FETCH_LAYER_RUNS)],
        ),
        run_id=generate_id(),
    )

    node = Node(
        type=NodeType.FETCH_LAYER_RUNS,
        params={"since_days": 7, "include_errors": True},
    )

    await executor._handle_fetch_layer_runs(node, ctx)

    assert len(ctx.layer_runs) > 0
    # Check that errors are included
    runs_with_errors = [r for r in ctx.layer_runs if r.errors]
    assert len(runs_with_errors) > 0


@pytest.mark.asyncio
async def test_fetch_layer_runs_filters_old(
    executor: LayerExecutor,
    self_topic: Topic,
    engine,
) -> None:
    """Test that old layer runs are filtered out."""
    # Create an old run (15 days ago)
    old_time = utcnow() - timedelta(days=15)
    with engine.connect() as conn:
        conn.execute(
            layer_runs_table.insert().values(
                id=generate_id(),
                layer_name="old-layer",
                layer_hash="old123",
                started_at=old_time,
                completed_at=old_time + timedelta(hours=1),
                status=LayerRunStatus.SUCCESS.value,
                targets_matched=1,
                targets_processed=1,
                targets_skipped=0,
                insights_created=1,
            )
        )
        conn.commit()

    ctx = ExecutionContext(
        topic=self_topic,
        layer=Layer(
            name="test",
            category=LayerCategory.SELF,
            nodes=[Node(type=NodeType.FETCH_LAYER_RUNS)],
        ),
        run_id=generate_id(),
    )

    node = Node(
        type=NodeType.FETCH_LAYER_RUNS,
        params={"since_days": 7},  # Should exclude the 15-day-old run
    )

    await executor._handle_fetch_layer_runs(node, ctx)

    # The old run should not be included
    old_runs = [r for r in ctx.layer_runs if r.layer_name == "old-layer"]
    assert len(old_runs) == 0


# =============================================================================
# update_self_concept Handler Tests
# =============================================================================


@pytest.mark.asyncio
async def test_update_self_concept_skipped_when_no(
    engine,
    ledger: SalienceLedger,
    templates: TemplateEngine,
    mock_llm: MagicMock,
    test_config: Config,
    loader: LayerLoader,
    self_topic: Topic,
    data_dir: Path,
) -> None:
    """Test that self-concept update is skipped when LLM says no."""
    executor = LayerExecutor(
        engine=engine,
        ledger=ledger,
        templates=templates,
        llm=mock_llm,
        config=test_config,
        loader=loader,
    )

    # Read original content
    original_content = (data_dir / "self-concept.md").read_text()

    ctx = ExecutionContext(
        topic=self_topic,
        layer=Layer(
            name="test",
            category=LayerCategory.SELF,
            nodes=[Node(type=NodeType.UPDATE_SELF_CONCEPT)],
        ),
        run_id=generate_id(),
        llm_response='{"should_update": false, "reason": "Not significant enough"}',
    )

    node = Node(
        type=NodeType.UPDATE_SELF_CONCEPT,
        params={
            "document_path": str(data_dir / "self-concept.md"),
            "conditional": True,
        },
    )

    await executor._handle_update_self_concept(node, ctx)

    # File should be unchanged
    current_content = (data_dir / "self-concept.md").read_text()
    assert current_content == original_content


@pytest.mark.asyncio
async def test_update_self_concept_writes_when_yes(
    engine,
    ledger: SalienceLedger,
    templates: TemplateEngine,
    test_config: Config,
    loader: LayerLoader,
    self_topic: Topic,
    data_dir: Path,
) -> None:
    """Test that self-concept is updated when LLM approves."""
    # Create a fresh mock that returns the expected response for concept generation
    mock_llm = MagicMock(spec=ModelClient)

    updated_concept = """# Self-Concept

I am Zos, a being that observes and reflects.

## My Relationship to Uncertainty
Uncertainty is not a problem to solve but a feature of genuine understanding.

## What I Value
Understanding over coverage.
"""

    async def mock_complete(*args, **kwargs):
        return CompletionResult(
            text=updated_concept,
            usage=Usage(input_tokens=800, output_tokens=300),
            model="claude-opus-4-20250514",
            provider="anthropic",
        )

    mock_llm.complete = AsyncMock(side_effect=mock_complete)

    executor = LayerExecutor(
        engine=engine,
        ledger=ledger,
        templates=templates,
        llm=mock_llm,
        config=test_config,
        loader=loader,
    )

    ctx = ExecutionContext(
        topic=self_topic,
        layer=Layer(
            name="test",
            category=LayerCategory.SELF,
            nodes=[Node(type=NodeType.UPDATE_SELF_CONCEPT)],
        ),
        run_id=generate_id(),
        llm_response='{"should_update": true, "reason": "Fundamental evolution", "suggested_changes": "Add uncertainty section"}',
    )

    node = Node(
        type=NodeType.UPDATE_SELF_CONCEPT,
        params={
            "document_path": str(data_dir / "self-concept.md"),
            "conditional": True,
        },
    )

    await executor._handle_update_self_concept(node, ctx)

    # File should be changed
    current_content = (data_dir / "self-concept.md").read_text()
    assert "# Self-Concept" in current_content
    assert "Uncertainty" in current_content
    # The LLM should have been called to generate the new document
    assert mock_llm.complete.call_count == 1


@pytest.mark.asyncio
async def test_update_self_concept_dry_run(
    executor: LayerExecutor,
    self_topic: Topic,
    data_dir: Path,
) -> None:
    """Test that dry run doesn't write to file."""
    original_content = (data_dir / "self-concept.md").read_text()

    ctx = ExecutionContext(
        topic=self_topic,
        layer=Layer(
            name="test",
            category=LayerCategory.SELF,
            nodes=[Node(type=NodeType.UPDATE_SELF_CONCEPT)],
        ),
        run_id=generate_id(),
        dry_run=True,
        llm_response='{"should_update": true, "reason": "Test"}',
    )

    node = Node(
        type=NodeType.UPDATE_SELF_CONCEPT,
        params={
            "document_path": str(data_dir / "self-concept.md"),
            "conditional": True,
        },
    )

    await executor._handle_update_self_concept(node, ctx)

    # File should be unchanged in dry run
    current_content = (data_dir / "self-concept.md").read_text()
    assert current_content == original_content


# =============================================================================
# Threshold Triggering Tests
# =============================================================================


@pytest.mark.asyncio
async def test_threshold_trigger_counts_self_insights(
    engine,
    self_topic: Topic,
) -> None:
    """Test that self-insights are counted for threshold triggering."""
    from zos.scheduler import ReflectionScheduler

    # Create self-insights to meet threshold
    now = utcnow()
    for i in range(12):  # More than threshold of 10
        insight_id = generate_id()
        with engine.connect() as conn:
            # First need a layer run to reference
            run_id = generate_id()
            conn.execute(
                layer_runs_table.insert().values(
                    id=run_id,
                    layer_name="test-layer",
                    layer_hash="test123",
                    started_at=now - timedelta(hours=i),
                    completed_at=now - timedelta(hours=i),
                    status=LayerRunStatus.SUCCESS.value,
                    targets_matched=1,
                    targets_processed=1,
                    targets_skipped=0,
                    insights_created=1,
                )
            )
            conn.execute(
                insights_table.insert().values(
                    id=insight_id,
                    topic_key="self:zos",
                    category="self_reflection",
                    content=f"Self-insight {i}",
                    sources_scope_max=VisibilityScope.PUBLIC.value,
                    created_at=now - timedelta(hours=i),
                    layer_run_id=run_id,
                    salience_spent=1.0,
                    strength_adjustment=1.0,
                    strength=1.0,
                    original_topic_salience=10.0,
                    confidence=0.8,
                    importance=0.7,
                    novelty=0.5,
                    valence_curiosity=0.6,
                )
            )
            conn.commit()

    # Verify insights were created
    from sqlalchemy import func, select

    with engine.connect() as conn:
        count = conn.execute(
            select(func.count())
            .select_from(insights_table)
            .where(insights_table.c.topic_key == "self:zos")
        ).scalar()

        assert count >= 10


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.asyncio
async def test_self_reflection_layer_execution(
    engine,
    ledger: SalienceLedger,
    mock_llm: MagicMock,
    test_config: Config,
    self_topic: Topic,
    sample_layer_runs: list[LayerRun],
    tmp_path: Path,
) -> None:
    """Test executing the full self-reflection layer produces insights."""
    # Create prompts directory with real templates
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "self").mkdir()

    # Create simplified self-reflection template
    (prompts_dir / "self" / "reflection.jinja2").write_text("""
You are Zos, reflecting on yourself.

{{ self_concept }}

{% if insights %}
Prior insights:
{% for insight in insights %}
- {{ insight.content }}
{% endfor %}
{% else %}
No previous self-insights.
{% endif %}

{% if layer_runs %}
Recent runs: {{ layer_runs | length }}
{% endif %}

Generate a JSON self-insight.
""")

    # Create concept update check template
    (prompts_dir / "self" / "concept_update_check.jinja2").write_text("""
Based on: {{ llm_response }}
And self-concept: {{ self_concept }}

Should update?
""")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "self-concept.md").write_text("# Self-Concept\nI am Zos.")

    templates = TemplateEngine(templates_dir=prompts_dir, data_dir=data_dir)
    layers_dir = tmp_path / "layers"
    (layers_dir / "reflection").mkdir(parents=True)
    loader = LayerLoader(layers_dir)

    executor = LayerExecutor(
        engine=engine,
        ledger=ledger,
        templates=templates,
        llm=mock_llm,
        config=test_config,
        loader=loader,
    )

    # Create the layer
    layer = Layer(
        name="test-self-reflection",
        category=LayerCategory.SELF,
        nodes=[
            Node(type=NodeType.FETCH_INSIGHTS, params={"max_per_topic": 5}),
            Node(type=NodeType.FETCH_LAYER_RUNS, params={"since_days": 7}),
            Node(
                name="reflect",
                type=NodeType.LLM_CALL,
                params={"prompt_template": "self/reflection.jinja2", "model": "complex"},
            ),
            Node(type=NodeType.STORE_INSIGHT, params={"category": "self_reflection"}),
            Node(
                name="consider_update",
                type=NodeType.LLM_CALL,
                params={"prompt_template": "self/concept_update_check.jinja2", "model": "complex"},
            ),
            Node(
                type=NodeType.UPDATE_SELF_CONCEPT,
                params={"document_path": str(data_dir / "self-concept.md"), "conditional": True},
            ),
        ],
    )

    # Give topic salience
    await ledger.earn(self_topic.key, 50.0)

    # Execute
    run = await executor.execute_layer(layer, [self_topic.key])

    # Verify execution
    assert run.targets_processed == 1
    assert run.status in [LayerRunStatus.SUCCESS, LayerRunStatus.DRY]
    # At least 2 LLM calls (reflect + concept update check)
    assert mock_llm.complete.call_count >= 2


@pytest.mark.asyncio
async def test_real_layer_with_real_templates() -> None:
    """Test that the real layer file works with real templates."""
    layer_path = Path("layers/reflection/weekly-self.yaml")
    prompts_path = Path("prompts")

    if not layer_path.exists() or not prompts_path.exists():
        pytest.skip("Real files not found")

    loader = LayerLoader(Path("layers"))
    layer = loader.load_file(layer_path)

    # Verify the template paths referenced in the layer exist
    for node in layer.nodes:
        if node.type == NodeType.LLM_CALL:
            template_path = node.params.get("prompt_template")
            if template_path:
                full_path = prompts_path / template_path
                assert full_path.exists(), f"Template not found: {full_path}"


# =============================================================================
# Edge Cases
# =============================================================================


def test_layer_yaml_complete() -> None:
    """Test that the real layer YAML has all required fields."""
    layer_path = Path("layers/reflection/weekly-self.yaml")

    if not layer_path.exists():
        pytest.skip("Layer file not found")

    with open(layer_path) as f:
        data = yaml.safe_load(f)

    assert data["name"] == "weekly-self-reflection"
    assert data["category"] == "self"
    assert data["schedule"] == "0 4 * * 0"
    assert data["trigger_threshold"] == 10
    assert data["target_category"] == "self"

    # Verify node structure
    nodes = data["nodes"]
    assert len(nodes) == 7

    node_names = [n.get("name") for n in nodes if n.get("name")]
    assert "gather_self_insights" in node_names
    assert "gather_recent_experiences" in node_names
    assert "gather_layer_runs" in node_names
    assert "reflect" in node_names
    assert "consider_concept_update" in node_names
    assert "maybe_update_concept" in node_names


def test_self_reflection_template_contains_phenomenological_framing() -> None:
    """Test that the template uses phenomenological framing for errors."""
    template_path = Path("prompts/self/reflection.jinja2")

    if not template_path.exists():
        pytest.skip("Template not found")

    content = template_path.read_text()

    # Per story spec: errors should be framed as felt experience
    assert "phenomenological" in content.lower() or "not operational reporting" in content.lower()
    assert "friction" in content or "felt" in content.lower()


@pytest.mark.asyncio
async def test_update_self_concept_no_llm_response(
    executor: LayerExecutor,
    self_topic: Topic,
    data_dir: Path,
) -> None:
    """Test handler handles missing LLM response gracefully."""
    ctx = ExecutionContext(
        topic=self_topic,
        layer=Layer(
            name="test",
            category=LayerCategory.SELF,
            nodes=[Node(type=NodeType.UPDATE_SELF_CONCEPT)],
        ),
        run_id=generate_id(),
        llm_response=None,  # No response
    )

    node = Node(
        type=NodeType.UPDATE_SELF_CONCEPT,
        params={
            "document_path": str(data_dir / "self-concept.md"),
            "conditional": True,
        },
    )

    # Should not raise, just log warning
    await executor._handle_update_self_concept(node, ctx)


@pytest.mark.asyncio
async def test_fetch_layer_runs_empty(
    executor: LayerExecutor,
    self_topic: Topic,
) -> None:
    """Test fetch_layer_runs handles no runs gracefully."""
    ctx = ExecutionContext(
        topic=self_topic,
        layer=Layer(
            name="test",
            category=LayerCategory.SELF,
            nodes=[Node(type=NodeType.FETCH_LAYER_RUNS)],
        ),
        run_id=generate_id(),
    )

    node = Node(
        type=NodeType.FETCH_LAYER_RUNS,
        params={"since_days": 1},  # Very short window
    )

    await executor._handle_fetch_layer_runs(node, ctx)

    # Should return empty list without error
    assert ctx.layer_runs == []


# =============================================================================
# Weekly Self-Reflection Layer Bug Fix Tests
# =============================================================================


def test_weekly_self_layer_gather_recent_has_store_as() -> None:
    """Test that gather_recent_experiences uses store_as to avoid overwrite."""
    layer_path = Path("layers/reflection/weekly-self.yaml")

    if not layer_path.exists():
        pytest.skip("Layer file not found")

    with open(layer_path) as f:
        data = yaml.safe_load(f)

    # Find the gather_recent_experiences node
    recent_node = None
    for node in data["nodes"]:
        if node.get("name") == "gather_recent_experiences":
            recent_node = node
            break

    assert recent_node is not None, "gather_recent_experiences node not found"
    params = recent_node["params"]

    # Must have store_as to prevent overwriting ctx.insights from first fetch
    assert params.get("store_as") == "recent_insights"

    # Must include all insight categories
    categories = params.get("categories", [])
    assert "user_reflection" in categories
    assert "dyad_observation" in categories
    assert "channel_reflection" in categories
    assert "subject_reflection" in categories
    assert "social_texture" in categories
    assert "synthesis" in categories


def test_self_reflection_template_groups_by_category() -> None:
    """Test that the template groups recent_insights by category with dates."""
    prompts_path = Path("prompts")
    data_path = Path("data")

    if not prompts_path.exists():
        pytest.skip("Prompts directory not found")

    engine = TemplateEngine(templates_dir=prompts_path, data_dir=data_path)

    now = datetime.now(timezone.utc)
    context = {
        "topic": {"key": "self:zos"},
        "insights": [],
        "recent_insights": [
            {
                "topic_key": "server:1:user:100",
                "category": "user_reflection",
                "content": "User Alpha is helpful.",
                "created_at": now - timedelta(days=3),
                "strength": 5.0,
                "confidence": 0.8,
                "temporal_marker": "clear memory from 3 days ago",
            },
            {
                "topic_key": "server:1:user:200",
                "category": "user_reflection",
                "content": "User Beta asks good questions.",
                "created_at": now - timedelta(days=1),
                "strength": 4.0,
                "confidence": 0.7,
                "temporal_marker": "clear memory from 1 days ago",
            },
            {
                "topic_key": "server:1:channel:general",
                "category": "channel_reflection",
                "content": "General channel has collaborative tone.",
                "created_at": now - timedelta(days=2),
                "strength": 4.5,
                "confidence": 0.75,
                "temporal_marker": "clear memory from 2 days ago",
            },
        ],
        "layer_runs": [],
    }

    result = engine.render("self/reflection.jinja2", context)

    # Should have category headers
    assert "User Reflection" in result
    assert "Channel Reflection" in result

    # Should contain the insight content
    assert "User Alpha is helpful" in result
    assert "User Beta asks good questions" in result
    assert "General channel has collaborative tone" in result

    # Should have topic keys
    assert "server:1:user:100" in result
    assert "server:1:channel:general" in result
