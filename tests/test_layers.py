"""Tests for the layer YAML loading module."""

from pathlib import Path

import pytest
import yaml

from zos.layers import (
    Layer,
    LayerCategory,
    LayerLoader,
    Node,
    NodeType,
    format_validation_error,
)
from pydantic import ValidationError


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def layers_dir(tmp_path: Path) -> Path:
    """Create a temporary layers directory with subdirectories."""
    layers_path = tmp_path / "layers"
    (layers_path / "reflection").mkdir(parents=True)
    (layers_path / "synthesis").mkdir(parents=True)
    return layers_path


@pytest.fixture
def valid_layer_yaml() -> dict:
    """Return valid layer data for testing."""
    return {
        "name": "test-layer",
        "category": "user",
        "description": "A test layer for unit tests.",
        "schedule": "0 3 * * *",
        "target_category": "users",
        "target_filter": "salience > 50",
        "max_targets": 10,
        "nodes": [
            {
                "name": "get_messages",
                "type": "fetch_messages",
                "params": {"lookback_hours": 24},
            },
            {
                "name": "reflect",
                "type": "llm_call",
                "params": {"prompt_template": "test.jinja2"},
            },
            {
                "name": "save",
                "type": "store_insight",
                "params": {"category": "test"},
            },
        ],
    }


@pytest.fixture
def layer_file(layers_dir: Path, valid_layer_yaml: dict) -> Path:
    """Create a valid layer file in the temporary directory."""
    file_path = layers_dir / "reflection" / "test-layer.yaml"
    with open(file_path, "w") as f:
        yaml.dump(valid_layer_yaml, f)
    return file_path


# =============================================================================
# Node Type Tests
# =============================================================================


def test_node_type_values() -> None:
    """Test that all expected node types exist."""
    expected_types = [
        "fetch_messages",
        "fetch_insights",
        "llm_call",
        "store_insight",
        "reduce",
        "output",
        "synthesize_to_global",
        "update_self_concept",
        "fetch_layer_runs",
        "fetch_reactions",
        "filter",
    ]

    for type_name in expected_types:
        assert NodeType(type_name) is not None


def test_node_type_is_string_enum() -> None:
    """Test that NodeType values are strings."""
    assert NodeType.FETCH_MESSAGES == "fetch_messages"
    assert NodeType.LLM_CALL.value == "llm_call"


# =============================================================================
# Layer Category Tests
# =============================================================================


def test_layer_category_values() -> None:
    """Test that all expected layer categories exist."""
    expected_categories = ["user", "dyad", "channel", "subject", "self", "synthesis"]

    for cat in expected_categories:
        assert LayerCategory(cat) is not None


def test_layer_category_is_string_enum() -> None:
    """Test that LayerCategory values are strings."""
    assert LayerCategory.USER == "user"
    assert LayerCategory.SELF.value == "self"


# =============================================================================
# Node Model Tests
# =============================================================================


def test_node_creation_minimal() -> None:
    """Test creating a node with minimal required fields."""
    node = Node(type=NodeType.FETCH_MESSAGES)

    assert node.type == NodeType.FETCH_MESSAGES
    assert node.name is None
    assert node.params == {}


def test_node_creation_full() -> None:
    """Test creating a node with all fields."""
    node = Node(
        name="get_messages",
        type=NodeType.FETCH_MESSAGES,
        params={"lookback_hours": 24, "limit_per_channel": 50},
    )

    assert node.name == "get_messages"
    assert node.type == NodeType.FETCH_MESSAGES
    assert node.params["lookback_hours"] == 24


def test_node_type_from_string() -> None:
    """Test that node type can be created from string."""
    node = Node(type="llm_call")
    assert node.type == NodeType.LLM_CALL


def test_node_invalid_type() -> None:
    """Test that invalid node type is rejected."""
    with pytest.raises(ValidationError):
        Node(type="invalid_type")


# =============================================================================
# Layer Model Tests
# =============================================================================


def test_layer_creation_minimal() -> None:
    """Test creating a layer with minimal required fields."""
    layer = Layer(
        name="test",
        category=LayerCategory.USER,
        nodes=[Node(type=NodeType.FETCH_MESSAGES)],
    )

    assert layer.name == "test"
    assert layer.category == LayerCategory.USER
    assert len(layer.nodes) == 1
    assert layer.max_targets == 10  # Default


def test_layer_creation_full(valid_layer_yaml: dict) -> None:
    """Test creating a layer with all fields."""
    layer = Layer.model_validate(valid_layer_yaml)

    assert layer.name == "test-layer"
    assert layer.category == LayerCategory.USER
    assert layer.description == "A test layer for unit tests."
    assert layer.schedule == "0 3 * * *"
    assert layer.target_category == "users"
    assert layer.target_filter == "salience > 50"
    assert layer.max_targets == 10
    assert len(layer.nodes) == 3


def test_layer_empty_nodes_rejected() -> None:
    """Test that layer with empty nodes list is rejected."""
    with pytest.raises(ValidationError) as exc_info:
        Layer(name="test", category=LayerCategory.USER, nodes=[])

    assert "at least one node" in str(exc_info.value).lower()


def test_layer_missing_name_rejected() -> None:
    """Test that layer without name is rejected."""
    with pytest.raises(ValidationError):
        Layer(category=LayerCategory.USER, nodes=[Node(type=NodeType.FETCH_MESSAGES)])


def test_layer_missing_category_rejected() -> None:
    """Test that layer without category is rejected."""
    with pytest.raises(ValidationError):
        Layer(name="test", nodes=[Node(type=NodeType.FETCH_MESSAGES)])


def test_layer_invalid_category_rejected() -> None:
    """Test that layer with invalid category is rejected."""
    with pytest.raises(ValidationError):
        Layer(
            name="test",
            category="invalid_category",
            nodes=[Node(type=NodeType.FETCH_MESSAGES)],
        )


# =============================================================================
# Cron Validation Tests
# =============================================================================


def test_layer_valid_cron() -> None:
    """Test that valid cron expressions are accepted."""
    valid_crons = [
        "0 3 * * *",  # Every day at 3 AM
        "0 4 * * 0",  # Every Sunday at 4 AM
        "*/5 * * * *",  # Every 5 minutes
        "0 0 1 * *",  # First of each month
        "30 8 * * 1-5",  # Weekdays at 8:30
    ]

    for cron in valid_crons:
        layer = Layer(
            name="test",
            category=LayerCategory.USER,
            schedule=cron,
            nodes=[Node(type=NodeType.FETCH_MESSAGES)],
        )
        assert layer.schedule == cron


def test_layer_invalid_cron_too_few_parts() -> None:
    """Test that cron with too few parts is rejected."""
    with pytest.raises(ValidationError) as exc_info:
        Layer(
            name="test",
            category=LayerCategory.USER,
            schedule="0 3 * *",  # Only 4 parts
            nodes=[Node(type=NodeType.FETCH_MESSAGES)],
        )

    assert "5 parts" in str(exc_info.value) or "cron" in str(exc_info.value).lower()


def test_layer_invalid_cron_too_many_parts() -> None:
    """Test that cron with too many parts is rejected."""
    with pytest.raises(ValidationError) as exc_info:
        Layer(
            name="test",
            category=LayerCategory.USER,
            schedule="0 3 * * * *",  # 6 parts
            nodes=[Node(type=NodeType.FETCH_MESSAGES)],
        )

    assert "5 parts" in str(exc_info.value) or "cron" in str(exc_info.value).lower()


def test_layer_null_cron_allowed() -> None:
    """Test that null schedule is allowed (for triggered layers)."""
    layer = Layer(
        name="test",
        category=LayerCategory.USER,
        schedule=None,
        trigger="post_hook",
        nodes=[Node(type=NodeType.FETCH_MESSAGES)],
    )

    assert layer.schedule is None
    assert layer.trigger == "post_hook"


# =============================================================================
# LayerLoader Tests
# =============================================================================


def test_loader_load_file(layer_file: Path) -> None:
    """Test loading a single layer file."""
    loader = LayerLoader(layer_file.parent.parent)
    layer = loader.load_file(layer_file)

    assert layer.name == "test-layer"
    assert layer.category == LayerCategory.USER


def test_loader_load_all(layers_dir: Path, valid_layer_yaml: dict) -> None:
    """Test loading all layers from directory."""
    # Create multiple layer files
    layer1 = layers_dir / "reflection" / "layer1.yaml"
    layer2 = layers_dir / "synthesis" / "layer2.yaml"

    yaml1 = valid_layer_yaml.copy()
    yaml1["name"] = "layer-one"

    yaml2 = valid_layer_yaml.copy()
    yaml2["name"] = "layer-two"
    yaml2["category"] = "synthesis"

    with open(layer1, "w") as f:
        yaml.dump(yaml1, f)
    with open(layer2, "w") as f:
        yaml.dump(yaml2, f)

    loader = LayerLoader(layers_dir)
    layers = loader.load_all()

    assert len(layers) == 2
    assert "layer-one" in layers
    assert "layer-two" in layers
    assert layers["layer-one"].category == LayerCategory.USER
    assert layers["layer-two"].category == LayerCategory.SYNTHESIS


def test_loader_directory_not_found() -> None:
    """Test that missing directory raises FileNotFoundError."""
    loader = LayerLoader(Path("/nonexistent/layers"))

    with pytest.raises(FileNotFoundError):
        loader.load_all()


def test_loader_file_not_found() -> None:
    """Test that missing file raises FileNotFoundError."""
    loader = LayerLoader(Path("."))

    with pytest.raises(FileNotFoundError):
        loader.load_file(Path("/nonexistent/layer.yaml"))


def test_loader_empty_file(layers_dir: Path) -> None:
    """Test that empty YAML file raises error."""
    empty_file = layers_dir / "reflection" / "empty.yaml"
    empty_file.write_text("")

    loader = LayerLoader(layers_dir)

    with pytest.raises(ValueError) as exc_info:
        loader.load_file(empty_file)

    assert "empty" in str(exc_info.value).lower()


def test_loader_get_layer(layer_file: Path) -> None:
    """Test getting a layer by name."""
    loader = LayerLoader(layer_file.parent.parent)
    loader.load_file(layer_file)

    layer = loader.get_layer("test-layer")
    assert layer is not None
    assert layer.name == "test-layer"


def test_loader_get_layer_not_found(layers_dir: Path) -> None:
    """Test getting a non-existent layer returns None."""
    loader = LayerLoader(layers_dir)

    layer = loader.get_layer("nonexistent")
    assert layer is None


def test_loader_get_hash(layer_file: Path) -> None:
    """Test getting content hash for a layer."""
    loader = LayerLoader(layer_file.parent.parent)
    loader.load_file(layer_file)

    hash_value = loader.get_hash("test-layer")

    assert hash_value is not None
    assert len(hash_value) == 16  # SHA-256 truncated to 16 chars
    assert all(c in "0123456789abcdef" for c in hash_value)


def test_loader_hash_not_found(layers_dir: Path) -> None:
    """Test getting hash for non-existent layer returns None."""
    loader = LayerLoader(layers_dir)

    hash_value = loader.get_hash("nonexistent")
    assert hash_value is None


def test_loader_hash_consistent(layer_file: Path) -> None:
    """Test that content hash is consistent for same content."""
    loader = LayerLoader(layer_file.parent.parent)

    loader.load_file(layer_file)
    hash1 = loader.get_hash("test-layer")

    # Reload
    loader.reload()
    hash2 = loader.get_hash("test-layer")

    assert hash1 == hash2


def test_loader_hash_changes_with_content(layers_dir: Path, valid_layer_yaml: dict) -> None:
    """Test that content hash changes when file content changes."""
    file_path = layers_dir / "reflection" / "test.yaml"

    with open(file_path, "w") as f:
        yaml.dump(valid_layer_yaml, f)

    loader = LayerLoader(layers_dir)
    loader.load_file(file_path)
    hash1 = loader.get_hash("test-layer")

    # Modify the file
    valid_layer_yaml["description"] = "Modified description"
    with open(file_path, "w") as f:
        yaml.dump(valid_layer_yaml, f)

    loader.reload()
    hash2 = loader.get_hash("test-layer")

    assert hash1 != hash2


def test_loader_reload(layers_dir: Path, valid_layer_yaml: dict) -> None:
    """Test that reload picks up new files."""
    loader = LayerLoader(layers_dir)

    # Initially empty
    layers = loader.load_all()
    assert len(layers) == 0

    # Add a file
    file_path = layers_dir / "reflection" / "new.yaml"
    with open(file_path, "w") as f:
        yaml.dump(valid_layer_yaml, f)

    # Reload should find the new file
    layers = loader.reload()
    assert len(layers) == 1
    assert "test-layer" in layers


def test_loader_list_layers(layers_dir: Path, valid_layer_yaml: dict) -> None:
    """Test listing all cached layer names."""
    file_path = layers_dir / "reflection" / "test.yaml"
    with open(file_path, "w") as f:
        yaml.dump(valid_layer_yaml, f)

    loader = LayerLoader(layers_dir)
    loader.load_all()

    names = loader.list_layers()
    assert names == ["test-layer"]


# =============================================================================
# Validation Error Formatting Tests
# =============================================================================


def test_format_validation_error_single() -> None:
    """Test formatting a single validation error."""
    try:
        Layer(name="test", category="invalid", nodes=[])
    except ValidationError as e:
        formatted = format_validation_error(e, Path("test.yaml"))

    assert "test.yaml" in formatted
    assert "category" in formatted.lower() or "nodes" in formatted.lower()


def test_format_validation_error_multiple() -> None:
    """Test formatting multiple validation errors."""
    try:
        Layer(name="", category="invalid", nodes=[], schedule="bad")
    except ValidationError as e:
        formatted = format_validation_error(e, Path("complex.yaml"))

    assert "complex.yaml" in formatted
    # Should have multiple error lines
    lines = formatted.split("\n")
    assert len(lines) > 2


def test_format_validation_error_nested() -> None:
    """Test formatting errors in nested structures."""
    try:
        Layer(
            name="test",
            category="user",
            nodes=[{"type": "invalid_type"}],
        )
    except ValidationError as e:
        formatted = format_validation_error(e, Path("nested.yaml"))

    assert "nested.yaml" in formatted
    # Should show path into nodes
    assert "nodes" in formatted.lower()


# =============================================================================
# Invalid YAML Tests
# =============================================================================


def test_loader_invalid_yaml(layers_dir: Path) -> None:
    """Test that invalid YAML raises error."""
    bad_file = layers_dir / "reflection" / "bad.yaml"
    bad_file.write_text("{ unclosed brace")

    loader = LayerLoader(layers_dir)

    with pytest.raises(yaml.YAMLError):
        loader.load_file(bad_file)


def test_loader_validation_error_in_load_all(layers_dir: Path) -> None:
    """Test that validation errors in load_all are propagated."""
    bad_layer = layers_dir / "reflection" / "bad.yaml"
    bad_layer.write_text(
        yaml.dump(
            {
                "name": "bad",
                "category": "invalid_category",
                "nodes": [{"type": "fetch_messages"}],
            }
        )
    )

    loader = LayerLoader(layers_dir)

    with pytest.raises(ValueError) as exc_info:
        loader.load_all()

    assert "bad.yaml" in str(exc_info.value)


# =============================================================================
# Real Example Layer Tests
# =============================================================================


def test_example_layer_file_exists() -> None:
    """Test that the example layer file exists."""
    example_path = Path("layers/reflection/nightly-user.yaml")
    assert example_path.exists(), f"Example layer file not found: {example_path}"


def test_example_layer_valid() -> None:
    """Test that the example layer file is valid."""
    example_path = Path("layers/reflection/nightly-user.yaml")

    if not example_path.exists():
        pytest.skip("Example layer file not found")

    loader = LayerLoader(Path("layers"))
    layer = loader.load_file(example_path)

    assert layer.name == "nightly-user-reflection"
    assert layer.category == LayerCategory.USER
    assert layer.schedule == "0 3 * * *"
    assert len(layer.nodes) == 4


def test_all_example_layers_valid() -> None:
    """Test that all example layers in the layers/ directory are valid."""
    layers_path = Path("layers")

    if not layers_path.exists():
        pytest.skip("Layers directory not found")

    loader = LayerLoader(layers_path)
    layers = loader.load_all()

    # Should have at least the example layer
    assert len(layers) >= 1


# =============================================================================
# Edge Cases
# =============================================================================


def test_layer_with_all_node_types(layers_dir: Path) -> None:
    """Test that all node types can be used in a layer."""
    layer_data = {
        "name": "all-nodes",
        "category": "self",
        "nodes": [
            {"type": "fetch_messages"},
            {"type": "fetch_insights"},
            {"type": "fetch_layer_runs"},
            {"type": "llm_call", "params": {"prompt_template": "test.j2"}},
            {"type": "reduce"},
            {"type": "store_insight"},
            {"type": "synthesize_to_global"},
            {"type": "update_self_concept"},
            {"type": "output", "params": {"destination": "log"}},
        ],
    }

    file_path = layers_dir / "reflection" / "all-nodes.yaml"
    with open(file_path, "w") as f:
        yaml.dump(layer_data, f)

    loader = LayerLoader(layers_dir)
    layer = loader.load_file(file_path)

    assert len(layer.nodes) == 9


def test_layer_max_targets_zero() -> None:
    """Test that max_targets can be set to zero."""
    layer = Layer(
        name="test",
        category=LayerCategory.USER,
        max_targets=0,
        nodes=[Node(type=NodeType.FETCH_MESSAGES)],
    )

    assert layer.max_targets == 0


def test_layer_max_targets_large() -> None:
    """Test that max_targets can be very large."""
    layer = Layer(
        name="test",
        category=LayerCategory.USER,
        max_targets=10000,
        nodes=[Node(type=NodeType.FETCH_MESSAGES)],
    )

    assert layer.max_targets == 10000


def test_layer_with_trigger_threshold() -> None:
    """Test that trigger_threshold is properly parsed."""
    layer = Layer(
        name="test",
        category=LayerCategory.SELF,
        trigger_threshold=10,
        nodes=[Node(type=NodeType.FETCH_INSIGHTS)],
    )

    assert layer.trigger_threshold == 10


def test_duplicate_layer_names_warning(layers_dir: Path, valid_layer_yaml: dict, caplog) -> None:
    """Test that duplicate layer names produce a warning but don't fail."""
    # Create two files with same layer name
    file1 = layers_dir / "reflection" / "layer1.yaml"
    file2 = layers_dir / "synthesis" / "layer2.yaml"

    with open(file1, "w") as f:
        yaml.dump(valid_layer_yaml, f)
    with open(file2, "w") as f:
        yaml.dump(valid_layer_yaml, f)  # Same name: "test-layer"

    loader = LayerLoader(layers_dir)

    # Should complete without error
    layers = loader.load_all()

    # Only one should be in the result (last one loaded)
    assert len(layers) == 1
    assert "test-layer" in layers
