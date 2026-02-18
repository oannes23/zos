"""Tests for Meta-Reflection Layer (template evolution).

Covers:
- Layer YAML validation (weekly-meta.yaml)
- _discover_reflection_templates finds correct templates
- _explain_template_variables extracts and annotates variables
- Template review with no-change decision (file untouched)
- Template review with successful modification (file updated)
- Template review with Jinja2 validation failure (file preserved)
- get_insights_by_layer_name returns correct insights via join
- Full handler integration with mock LLM (mix of change/no-change)
- Dry run skips everything
- Error resilience: one template failure doesn't block others
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from zos.config import Config
from zos.database import (
    create_tables,
    generate_id,
    get_engine,
    insights as insights_table,
    layer_runs as layer_runs_table,
    topics as topics_table,
)
from zos.executor import (
    CONVERSATION_CATEGORIES,
    TEMPLATE_VARIABLE_REFERENCE,
    ExecutionContext,
    LayerExecutor,
)
from zos.insights import get_insights_by_layer_name
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
    (templates / "user").mkdir()
    (templates / "channel").mkdir()
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

    # Create meta-reflection template
    (templates / "self" / "meta_reflection.jinja2").write_text(
        """{# Meta reflection template #}
You are Zos, reflecting on your own cognitive processes.

## Self-Concept
{{ self_concept }}

{% if latest_self_insight %}
## Latest Self-Reflection
{{ latest_self_insight }}
{% endif %}

## Template Under Review
Template: {{ template_path }}
Layer: {{ layer_name }}
Purpose: {{ layer_description }}

### Source
```
{{ template_source }}
```

### Variables
{{ variable_explanations }}

### Recent Insights
{{ recent_insights_text }}

Respond with JSON: {"should_modify": bool, "reasoning": "...", "updated_template": "..."}
"""
    )

    # Create a sample user reflection template
    (templates / "user" / "reflection.jinja2").write_text(
        """{# User reflection template #}
You are Zos.
{{ self_concept }}

{% for insight in insights %}
{{ insight.content }}
{% endfor %}

{% if messages %}
Messages found.
{% endif %}

Reflect on {{ topic.key }}.
"""
    )

    # Create a sample channel reflection template
    (templates / "channel" / "reflection.jinja2").write_text(
        """{# Channel reflection template #}
You are Zos.
{{ self_concept }}
Reflect on channel {{ topic.key }}.
"""
    )

    # Create self reflection template
    (templates / "self" / "reflection.jinja2").write_text(
        """{# Self reflection template #}
You are Zos.
{{ self_concept }}

{% if recent_insights %}
Recent insights available.
{% endif %}

{% for run in layer_runs %}
- {{ run.layer_name }}
{% endfor %}
"""
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
"""
    )
    return data


@pytest.fixture
def templates(templates_dir: Path, data_dir: Path) -> TemplateEngine:
    """Create a TemplateEngine instance for testing."""
    return TemplateEngine(templates_dir=templates_dir, data_dir=data_dir)


@pytest.fixture
def layers_dir(tmp_path: Path) -> Path:
    """Create a temporary layers directory with reflection layers."""
    layers = tmp_path / "layers"
    layers.mkdir()
    (layers / "reflection").mkdir()
    (layers / "conversation").mkdir()

    # Nightly user reflection layer
    (layers / "reflection" / "nightly-user.yaml").write_text(yaml.dump({
        "name": "nightly-user-reflection",
        "category": "user",
        "description": "Reflect on individual users",
        "schedule": "0 3 * * *",
        "target_category": "user",
        "nodes": [
            {"name": "fetch", "type": "fetch_messages", "params": {}},
            {"name": "reflect", "type": "llm_call", "params": {
                "prompt_template": "user/reflection.jinja2",
                "model": "moderate",
            }},
            {"name": "store", "type": "store_insight", "params": {"category": "user_reflection"}},
        ],
    }))

    # Nightly channel reflection layer
    (layers / "reflection" / "nightly-channel.yaml").write_text(yaml.dump({
        "name": "nightly-channel-reflection",
        "category": "channel",
        "description": "Reflect on channels",
        "schedule": "0 3 * * *",
        "target_category": "channel",
        "nodes": [
            {"name": "reflect", "type": "llm_call", "params": {
                "prompt_template": "channel/reflection.jinja2",
                "model": "moderate",
            }},
            {"name": "store", "type": "store_insight", "params": {"category": "channel_reflection"}},
        ],
    }))

    # Self-reflection layer
    (layers / "reflection" / "weekly-self.yaml").write_text(yaml.dump({
        "name": "weekly-self-reflection",
        "category": "self",
        "description": "Weekly self-reflection",
        "schedule": "0 4 * * 0",
        "target_category": "self",
        "nodes": [
            {"name": "reflect", "type": "llm_call", "params": {
                "prompt_template": "self/reflection.jinja2",
                "model": "complex",
            }},
            {"name": "store", "type": "store_insight", "params": {"category": "self_reflection"}},
        ],
    }))

    # Conversation layer (should be excluded)
    (layers / "conversation" / "dm-response.yaml").write_text(yaml.dump({
        "name": "dm-response",
        "category": "response",
        "description": "Respond to DMs",
        "nodes": [
            {"name": "respond", "type": "llm_call", "params": {
                "prompt_template": "conversation/dm-response.jinja2",
                "model": "moderate",
            }},
            {"name": "output", "type": "output", "params": {}},
        ],
    }))

    # Layer with non-reflection template (concept update check — should be excluded)
    (layers / "reflection" / "weekly-meta.yaml").write_text(yaml.dump({
        "name": "weekly-meta-reflection",
        "category": "self",
        "description": "Meta-reflection",
        "schedule": "30 4 * * 0",
        "target_category": "self",
        "nodes": [
            {"name": "evolve", "type": "update_templates", "params": {
                "prompt_template": "self/meta_reflection.jinja2",
                "model": "complex",
            }},
            {"name": "store", "type": "store_insight", "params": {"category": "meta_reflection"}},
        ],
    }))

    return layers


@pytest.fixture
def loader(layers_dir: Path) -> LayerLoader:
    """Create a LayerLoader from test layers."""
    return LayerLoader(layers_dir=layers_dir)


@pytest.fixture
def self_topic(engine) -> Topic:
    """Create and insert the self:zos topic."""
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
def meta_layer(loader: LayerLoader) -> Layer:
    """Load the weekly-meta-reflection layer."""
    layers = loader.load_all()
    return layers["weekly-meta-reflection"]


def _make_no_change_response() -> str:
    return json.dumps({
        "should_modify": False,
        "reasoning": "The template is working well. Recent insights show depth and variety.",
        "updated_template": None,
    })


def _make_change_response(template_path: str) -> str:
    return json.dumps({
        "should_modify": True,
        "reasoning": "Recent insights feel formulaic. Adding more phenomenological prompting.",
        "updated_template": "{# Updated #}\nYou are Zos.\n{{ self_concept }}\nReflect deeply on {{ topic.key }}.\n",
    })


def _make_invalid_jinja2_response() -> str:
    return json.dumps({
        "should_modify": True,
        "reasoning": "Attempting improvement.",
        "updated_template": "{% for x in items %} unclosed block",
    })


# =============================================================================
# Layer YAML Validation
# =============================================================================


class TestLayerYAML:
    """Test that the weekly-meta.yaml layer definition is valid."""

    def test_layer_loads_successfully(self, meta_layer: Layer):
        assert meta_layer.name == "weekly-meta-reflection"
        assert meta_layer.category == LayerCategory.SELF

    def test_layer_schedule(self, meta_layer: Layer):
        assert meta_layer.schedule == "30 4 * * 0"

    def test_layer_has_correct_nodes(self, meta_layer: Layer):
        assert len(meta_layer.nodes) == 2
        assert meta_layer.nodes[0].type == NodeType.UPDATE_TEMPLATES
        assert meta_layer.nodes[1].type == NodeType.STORE_INSIGHT

    def test_update_templates_node_params(self, meta_layer: Layer):
        node = meta_layer.nodes[0]
        assert node.params["prompt_template"] == "self/meta_reflection.jinja2"
        assert node.params["model"] == "complex"

    def test_store_insight_category(self, meta_layer: Layer):
        node = meta_layer.nodes[1]
        assert node.params["category"] == "meta_reflection"

    def test_real_layer_yaml_loads(self):
        """Test the actual layer YAML file in the repo."""
        path = Path("layers/reflection/weekly-meta.yaml")
        if path.exists():
            loader = LayerLoader(layers_dir=Path("layers"))
            layer = loader.load_file(path)
            assert layer.name == "weekly-meta-reflection"
            assert layer.category == LayerCategory.SELF


# =============================================================================
# Template Discovery
# =============================================================================


class TestDiscoverReflectionTemplates:
    """Test _discover_reflection_templates finds correct templates."""

    def test_finds_reflection_templates(
        self, engine, ledger, templates, test_config, loader
    ):
        mock_llm = MagicMock(spec=ModelClient)
        executor = LayerExecutor(engine, ledger, templates, mock_llm, test_config, loader=loader)

        result = executor._discover_reflection_templates()

        template_paths = [t["template_path"] for t in result]
        assert "user/reflection.jinja2" in template_paths
        assert "channel/reflection.jinja2" in template_paths
        assert "self/reflection.jinja2" in template_paths

    def test_excludes_conversation_templates(
        self, engine, ledger, templates, test_config, loader
    ):
        mock_llm = MagicMock(spec=ModelClient)
        executor = LayerExecutor(engine, ledger, templates, mock_llm, test_config, loader=loader)

        result = executor._discover_reflection_templates()

        # dm-response has category "response" which should be excluded
        layer_names = [t["layer_name"] for t in result]
        assert "dm-response" not in layer_names

    def test_excludes_non_reflection_templates(
        self, engine, ledger, templates, test_config, loader
    ):
        """concept_update_check.jinja2 doesn't end with reflection.jinja2."""
        mock_llm = MagicMock(spec=ModelClient)
        executor = LayerExecutor(engine, ledger, templates, mock_llm, test_config, loader=loader)

        result = executor._discover_reflection_templates()

        template_paths = [t["template_path"] for t in result]
        for path in template_paths:
            assert path.endswith("reflection.jinja2")

    def test_includes_metadata(
        self, engine, ledger, templates, test_config, loader
    ):
        mock_llm = MagicMock(spec=ModelClient)
        executor = LayerExecutor(engine, ledger, templates, mock_llm, test_config, loader=loader)

        result = executor._discover_reflection_templates()

        for entry in result:
            assert "layer_name" in entry
            assert "template_path" in entry
            assert "category" in entry
            assert "description" in entry


# =============================================================================
# Variable Explanation
# =============================================================================


class TestExplainTemplateVariables:
    """Test _explain_template_variables extraction and annotation."""

    def test_extracts_double_brace_vars(
        self, engine, ledger, templates, test_config, loader
    ):
        mock_llm = MagicMock(spec=ModelClient)
        executor = LayerExecutor(engine, ledger, templates, mock_llm, test_config, loader=loader)

        source = "{{ self_concept }}\n{{ topic.key }}"
        result = executor._explain_template_variables(source, {})

        assert "self_concept" in result
        assert "topic" in result

    def test_extracts_for_loop_vars(
        self, engine, ledger, templates, test_config, loader
    ):
        mock_llm = MagicMock(spec=ModelClient)
        executor = LayerExecutor(engine, ledger, templates, mock_llm, test_config, loader=loader)

        source = "{% for insight in insights %}\n{{ insight.content }}\n{% endfor %}"
        result = executor._explain_template_variables(source, {})

        assert "insights" in result

    def test_extracts_if_vars(
        self, engine, ledger, templates, test_config, loader
    ):
        mock_llm = MagicMock(spec=ModelClient)
        executor = LayerExecutor(engine, ledger, templates, mock_llm, test_config, loader=loader)

        source = "{% if messages %}Messages exist{% endif %}"
        result = executor._explain_template_variables(source, {})

        assert "messages" in result

    def test_known_vars_get_descriptions(
        self, engine, ledger, templates, test_config, loader
    ):
        mock_llm = MagicMock(spec=ModelClient)
        executor = LayerExecutor(engine, ledger, templates, mock_llm, test_config, loader=loader)

        source = "{{ self_concept }}\n{{ insights }}"
        result = executor._explain_template_variables(source, {})

        assert "self-concept" in result.lower() or "self_concept" in result
        assert "Prior insights" in result or "insights" in result.lower()

    def test_unknown_vars_get_local_annotation(
        self, engine, ledger, templates, test_config, loader
    ):
        mock_llm = MagicMock(spec=ModelClient)
        executor = LayerExecutor(engine, ledger, templates, mock_llm, test_config, loader=loader)

        source = "{% for item in foobar %}\n{{ item }}\n{% endfor %}"
        result = executor._explain_template_variables(source, {})

        assert "foobar" in result
        assert "local/loop variable" in result

    def test_builtins_excluded(
        self, engine, ledger, templates, test_config, loader
    ):
        mock_llm = MagicMock(spec=ModelClient)
        executor = LayerExecutor(engine, ledger, templates, mock_llm, test_config, loader=loader)

        source = "{% if true %}yes{% endif %}\n{{ loop.index }}"
        result = executor._explain_template_variables(source, {})

        # 'true' and 'loop' should not appear as variables
        assert "`true`" not in result
        assert "`loop`" not in result


# =============================================================================
# get_insights_by_layer_name
# =============================================================================


class TestGetInsightsByLayerName:
    """Test the insights query that joins to layer_runs."""

    def _insert_layer_run(self, engine, layer_name: str, run_id: str | None = None) -> str:
        """Insert a layer run and return its ID."""
        rid = run_id or generate_id()
        with engine.connect() as conn:
            conn.execute(
                layer_runs_table.insert().values(
                    id=rid,
                    layer_name=layer_name,
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
            conn.commit()
        return rid

    def _insert_insight(
        self, engine, topic_key: str, layer_run_id: str,
        content: str = "Test insight", category: str = "user_reflection",
        created_at: datetime | None = None,
    ) -> str:
        """Insert an insight and return its ID."""
        iid = generate_id()
        with engine.connect() as conn:
            conn.execute(
                insights_table.insert().values(
                    id=iid,
                    topic_key=topic_key,
                    category=category,
                    content=content,
                    sources_scope_max="public",
                    created_at=created_at or utcnow(),
                    layer_run_id=layer_run_id,
                    quarantined=False,
                    salience_spent=1.0,
                    strength_adjustment=1.0,
                    strength=1.0,
                    original_topic_salience=5.0,
                    confidence=0.7,
                    importance=0.5,
                    novelty=0.5,
                    valence_curiosity=0.5,
                )
            )
            conn.commit()
        return iid

    def test_returns_insights_from_correct_layer(self, engine, self_topic):
        run_id_a = self._insert_layer_run(engine, "nightly-user-reflection")
        run_id_b = self._insert_layer_run(engine, "nightly-channel-reflection")

        self._insert_insight(engine, "self:zos", run_id_a, content="From user layer")
        self._insert_insight(engine, "self:zos", run_id_b, content="From channel layer")

        results = get_insights_by_layer_name(engine, "nightly-user-reflection")
        assert len(results) == 1
        assert results[0].content == "From user layer"

    def test_respects_limit(self, engine, self_topic):
        run_id = self._insert_layer_run(engine, "nightly-user-reflection")
        for i in range(10):
            self._insert_insight(
                engine, "self:zos", run_id,
                content=f"Insight {i}",
                created_at=utcnow() - timedelta(hours=i),
            )

        results = get_insights_by_layer_name(engine, "nightly-user-reflection", limit=3)
        assert len(results) == 3

    def test_ordered_by_created_at_desc(self, engine, self_topic):
        run_id = self._insert_layer_run(engine, "nightly-user-reflection")
        now = utcnow()
        self._insert_insight(
            engine, "self:zos", run_id,
            content="Old", created_at=now - timedelta(days=2),
        )
        self._insert_insight(
            engine, "self:zos", run_id,
            content="New", created_at=now,
        )

        results = get_insights_by_layer_name(engine, "nightly-user-reflection")
        assert results[0].content == "New"
        assert results[1].content == "Old"

    def test_excludes_quarantined(self, engine, self_topic):
        run_id = self._insert_layer_run(engine, "nightly-user-reflection")
        iid = generate_id()
        with engine.connect() as conn:
            conn.execute(
                insights_table.insert().values(
                    id=iid,
                    topic_key="self:zos",
                    category="user_reflection",
                    content="Quarantined insight",
                    sources_scope_max="public",
                    created_at=utcnow(),
                    layer_run_id=run_id,
                    quarantined=True,
                    salience_spent=1.0,
                    strength_adjustment=1.0,
                    strength=1.0,
                    original_topic_salience=5.0,
                    confidence=0.7,
                    importance=0.5,
                    novelty=0.5,
                    valence_curiosity=0.5,
                )
            )
            conn.commit()

        results = get_insights_by_layer_name(engine, "nightly-user-reflection")
        assert len(results) == 0

    def test_returns_empty_for_unknown_layer(self, engine, self_topic):
        results = get_insights_by_layer_name(engine, "nonexistent-layer")
        assert results == []


# =============================================================================
# Single Template Review
# =============================================================================


class TestReviewSingleTemplate:
    """Test _review_single_template with various LLM responses."""

    @pytest.fixture
    def executor(self, engine, ledger, templates, test_config, loader):
        mock_llm = MagicMock(spec=ModelClient)
        mock_llm.complete = AsyncMock()
        executor = LayerExecutor(engine, ledger, templates, mock_llm, test_config, loader=loader)
        return executor

    @pytest.fixture
    def ctx(self, self_topic, meta_layer):
        return ExecutionContext(
            topic=self_topic,
            layer=meta_layer,
            run_id=generate_id(),
        )

    @pytest.fixture
    def update_node(self, meta_layer) -> Node:
        return meta_layer.nodes[0]

    @pytest.mark.asyncio
    async def test_no_change_decision(self, executor, ctx, update_node, templates_dir):
        """When LLM says should_modify=false, file stays unchanged."""
        original = (templates_dir / "user" / "reflection.jinja2").read_text()

        executor.llm.complete.return_value = CompletionResult(
            text=_make_no_change_response(),
            usage=Usage(input_tokens=500, output_tokens=200),
            model="claude-opus-4-20250514",
            provider="anthropic",
        )

        template_info = {
            "layer_name": "nightly-user-reflection",
            "template_path": "user/reflection.jinja2",
            "category": "user",
            "description": "Reflect on individual users",
        }

        result = await executor._review_single_template(template_info, update_node, ctx)

        assert result["changed"] is False
        assert "working well" in result["reasoning"]
        # File unchanged
        assert (templates_dir / "user" / "reflection.jinja2").read_text() == original

    @pytest.mark.asyncio
    async def test_successful_modification(self, executor, ctx, update_node, templates_dir):
        """When LLM says should_modify=true with valid Jinja2, file is updated."""
        executor.llm.complete.return_value = CompletionResult(
            text=_make_change_response("user/reflection.jinja2"),
            usage=Usage(input_tokens=500, output_tokens=300),
            model="claude-opus-4-20250514",
            provider="anthropic",
        )

        template_info = {
            "layer_name": "nightly-user-reflection",
            "template_path": "user/reflection.jinja2",
            "category": "user",
            "description": "Reflect on individual users",
        }

        result = await executor._review_single_template(template_info, update_node, ctx)

        assert result["changed"] is True
        assert "formulaic" in result["reasoning"]
        # File was actually written
        new_content = (templates_dir / "user" / "reflection.jinja2").read_text()
        assert "Updated" in new_content

    @pytest.mark.asyncio
    async def test_invalid_jinja2_preserves_original(self, executor, ctx, update_node, templates_dir):
        """When updated template has invalid Jinja2, original is preserved."""
        original = (templates_dir / "user" / "reflection.jinja2").read_text()

        executor.llm.complete.return_value = CompletionResult(
            text=_make_invalid_jinja2_response(),
            usage=Usage(input_tokens=500, output_tokens=200),
            model="claude-opus-4-20250514",
            provider="anthropic",
        )

        template_info = {
            "layer_name": "nightly-user-reflection",
            "template_path": "user/reflection.jinja2",
            "category": "user",
            "description": "Reflect on individual users",
        }

        result = await executor._review_single_template(template_info, update_node, ctx)

        assert result["changed"] is False
        assert "Jinja2 validation failed" in result["reasoning"]
        # Original preserved
        assert (templates_dir / "user" / "reflection.jinja2").read_text() == original

    @pytest.mark.asyncio
    async def test_missing_template_file(self, executor, ctx, update_node):
        """When template file doesn't exist, returns not-changed."""
        template_info = {
            "layer_name": "nonexistent-layer",
            "template_path": "nonexistent/reflection.jinja2",
            "category": "self",
            "description": "Does not exist",
        }

        result = await executor._review_single_template(template_info, update_node, ctx)

        assert result["changed"] is False
        assert "not found" in result["reasoning"]

    @pytest.mark.asyncio
    async def test_unparseable_response(self, executor, ctx, update_node, templates_dir):
        """When LLM returns non-JSON, original is preserved."""
        original = (templates_dir / "user" / "reflection.jinja2").read_text()

        executor.llm.complete.return_value = CompletionResult(
            text="This is not JSON at all, just rambling text.",
            usage=Usage(input_tokens=500, output_tokens=100),
            model="claude-opus-4-20250514",
            provider="anthropic",
        )

        template_info = {
            "layer_name": "nightly-user-reflection",
            "template_path": "user/reflection.jinja2",
            "category": "user",
            "description": "Reflect on individual users",
        }

        result = await executor._review_single_template(template_info, update_node, ctx)

        assert result["changed"] is False
        assert "Could not parse" in result["reasoning"]
        assert (templates_dir / "user" / "reflection.jinja2").read_text() == original

    @pytest.mark.asyncio
    async def test_tokens_tracked(self, executor, ctx, update_node):
        """Token usage from review calls is added to context."""
        executor.llm.complete.return_value = CompletionResult(
            text=_make_no_change_response(),
            usage=Usage(input_tokens=1000, output_tokens=500),
            model="claude-opus-4-20250514",
            provider="anthropic",
        )

        template_info = {
            "layer_name": "nightly-user-reflection",
            "template_path": "user/reflection.jinja2",
            "category": "user",
            "description": "Reflect on individual users",
        }

        initial_input = ctx.tokens_input
        initial_output = ctx.tokens_output

        await executor._review_single_template(template_info, update_node, ctx)

        assert ctx.tokens_input == initial_input + 1000
        assert ctx.tokens_output == initial_output + 500


# =============================================================================
# Full Handler Integration
# =============================================================================


class TestHandleUpdateTemplates:
    """Test the full _handle_update_templates handler."""

    @pytest.fixture
    def executor(self, engine, ledger, templates, test_config, loader):
        mock_llm = MagicMock(spec=ModelClient)
        executor = LayerExecutor(engine, ledger, templates, mock_llm, test_config, loader=loader)
        return executor

    @pytest.fixture
    def ctx(self, self_topic, meta_layer):
        return ExecutionContext(
            topic=self_topic,
            layer=meta_layer,
            run_id=generate_id(),
        )

    @pytest.fixture
    def update_node(self, meta_layer) -> Node:
        return meta_layer.nodes[0]

    @pytest.mark.asyncio
    async def test_dry_run_skips_everything(self, executor, ctx, update_node):
        """Dry run should skip all template reviews."""
        ctx.dry_run = True

        await executor._handle_update_templates(update_node, ctx)

        # LLM should never be called
        executor.llm.complete.assert_not_called()
        # No llm_response set
        assert ctx.llm_response is None

    @pytest.mark.asyncio
    async def test_full_handler_with_mix_of_responses(self, executor, ctx, update_node, templates_dir):
        """Handler processes all templates; mix of change/no-change."""
        call_count = [0]

        async def mock_complete(*args, **kwargs):
            call_count[0] += 1
            prompt = kwargs.get("prompt", args[0] if args else "")
            # First template (user) gets modified, rest stay unchanged
            if call_count[0] == 1:
                text = _make_change_response("user/reflection.jinja2")
            else:
                text = _make_no_change_response()

            return CompletionResult(
                text=text,
                usage=Usage(input_tokens=500, output_tokens=200),
                model="claude-opus-4-20250514",
                provider="anthropic",
            )

        executor.llm.complete = AsyncMock(side_effect=mock_complete)

        await executor._handle_update_templates(update_node, ctx)

        # Should have called LLM once per discovered template + meta template
        assert call_count[0] >= 3  # at least user, channel, self + meta

        # llm_response should be set (JSON summary for store_insight)
        assert ctx.llm_response is not None
        summary = json.loads(ctx.llm_response)
        assert "content" in summary
        assert summary["confidence"] > 0
        assert "valence" in summary

    @pytest.mark.asyncio
    async def test_self_insight_included_in_prompts(self, executor, ctx, update_node, engine, self_topic):
        """Latest self-reflection insight should appear in every review prompt."""
        # Insert a self-reflection layer run and insight
        run_id = generate_id()
        with engine.connect() as conn:
            conn.execute(
                layer_runs_table.insert().values(
                    id=run_id,
                    layer_name="weekly-self-reflection",
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
                    content="I notice a growing capacity for nuance in how I process uncertainty.",
                    sources_scope_max="public",
                    created_at=utcnow(),
                    layer_run_id=run_id,
                    quarantined=False,
                    salience_spent=1.0,
                    strength_adjustment=1.5,
                    strength=1.5,
                    original_topic_salience=5.0,
                    confidence=0.8,
                    importance=0.7,
                    novelty=0.6,
                    valence_curiosity=0.7,
                )
            )
            conn.commit()

        prompts_seen = []

        async def mock_complete(*args, **kwargs):
            prompts_seen.append(kwargs.get("prompt", args[0] if args else ""))
            return CompletionResult(
                text=_make_no_change_response(),
                usage=Usage(input_tokens=500, output_tokens=200),
                model="claude-opus-4-20250514",
                provider="anthropic",
            )

        executor.llm.complete = AsyncMock(side_effect=mock_complete)

        await executor._handle_update_templates(update_node, ctx)

        # Every prompt should contain the self-insight
        assert len(prompts_seen) >= 2
        for prompt in prompts_seen:
            assert "growing capacity for nuance" in prompt

    @pytest.mark.asyncio
    async def test_meta_template_appended_last(self, executor, ctx, update_node):
        """The meta-reflection template should be the last one reviewed."""
        reviewed_order = []

        async def mock_complete(*args, **kwargs):
            prompt = kwargs.get("prompt", args[0] if args else "")
            # Extract which template is being reviewed from prompt content
            reviewed_order.append(prompt[:200])
            return CompletionResult(
                text=_make_no_change_response(),
                usage=Usage(input_tokens=500, output_tokens=200),
                model="claude-opus-4-20250514",
                provider="anthropic",
            )

        executor.llm.complete = AsyncMock(side_effect=mock_complete)

        await executor._handle_update_templates(update_node, ctx)

        # Last reviewed should contain "meta_reflection"
        assert len(reviewed_order) >= 2
        assert "meta_reflection" in reviewed_order[-1]

    @pytest.mark.asyncio
    async def test_error_resilience(self, executor, ctx, update_node):
        """One template failure doesn't stop others."""
        call_count = [0]

        async def mock_complete(*args, **kwargs):
            call_count[0] += 1
            # Second call raises an exception
            if call_count[0] == 2:
                raise RuntimeError("LLM connection failed")
            return CompletionResult(
                text=_make_no_change_response(),
                usage=Usage(input_tokens=500, output_tokens=200),
                model="claude-opus-4-20250514",
                provider="anthropic",
            )

        executor.llm.complete = AsyncMock(side_effect=mock_complete)

        # Should not raise
        await executor._handle_update_templates(update_node, ctx)

        # Should have continued past the error
        assert call_count[0] >= 3  # Continued after failure
        assert ctx.llm_response is not None

    @pytest.mark.asyncio
    async def test_summary_contains_modification_info(self, executor, ctx, update_node):
        """Summary JSON includes info about modifications."""
        async def mock_complete(*args, **kwargs):
            return CompletionResult(
                text=_make_change_response("any"),
                usage=Usage(input_tokens=500, output_tokens=200),
                model="claude-opus-4-20250514",
                provider="anthropic",
            )

        executor.llm.complete = AsyncMock(side_effect=mock_complete)

        await executor._handle_update_templates(update_node, ctx)

        summary = json.loads(ctx.llm_response)
        assert "Modified" in summary["content"]
        # Higher importance when changes made
        assert summary["importance"] > 0.5


# =============================================================================
# Build Summary
# =============================================================================


class TestBuildMetaReflectionSummary:
    """Test the summary builder."""

    def test_all_unchanged(self, engine, ledger, templates, test_config, loader):
        mock_llm = MagicMock(spec=ModelClient)
        executor = LayerExecutor(engine, ledger, templates, mock_llm, test_config, loader=loader)

        results = [
            {"template_path": "user/reflection.jinja2", "layer_name": "a", "changed": False, "reasoning": "Fine"},
            {"template_path": "self/reflection.jinja2", "layer_name": "b", "changed": False, "reasoning": "Fine"},
        ]

        summary_json = executor._build_meta_reflection_summary(results)
        summary = json.loads(summary_json)

        assert "Reviewed 2" in summary["content"]
        assert "unchanged" in summary["content"].lower()
        assert summary["importance"] == 0.4  # Lower when nothing changed

    def test_with_modifications(self, engine, ledger, templates, test_config, loader):
        mock_llm = MagicMock(spec=ModelClient)
        executor = LayerExecutor(engine, ledger, templates, mock_llm, test_config, loader=loader)

        results = [
            {"template_path": "user/reflection.jinja2", "layer_name": "a", "changed": True, "reasoning": "Improved"},
            {"template_path": "self/reflection.jinja2", "layer_name": "b", "changed": False, "reasoning": "Fine"},
        ]

        summary_json = executor._build_meta_reflection_summary(results)
        summary = json.loads(summary_json)

        assert "Modified 1" in summary["content"]
        assert summary["importance"] == 0.7

    def test_with_errors(self, engine, ledger, templates, test_config, loader):
        mock_llm = MagicMock(spec=ModelClient)
        executor = LayerExecutor(engine, ledger, templates, mock_llm, test_config, loader=loader)

        results = [
            {"template_path": "user/reflection.jinja2", "layer_name": "a", "changed": False, "reasoning": "Error", "error": True},
        ]

        summary_json = executor._build_meta_reflection_summary(results)
        summary = json.loads(summary_json)

        assert "Errors" in summary["content"]


# =============================================================================
# TEMPLATE_VARIABLE_REFERENCE
# =============================================================================


class TestTemplateVariableReference:
    """Verify the static reference dict is well-formed."""

    def test_all_values_are_strings(self):
        for key, value in TEMPLATE_VARIABLE_REFERENCE.items():
            assert isinstance(key, str)
            assert isinstance(value, str)

    def test_common_vars_present(self):
        expected = [
            "self_concept", "insights", "messages", "topic",
            "user_profile", "layer_runs", "recent_insights",
        ]
        for var in expected:
            assert var in TEMPLATE_VARIABLE_REFERENCE
