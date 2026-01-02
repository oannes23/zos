"""Tests for layer loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from zos.exceptions import LayerValidationError
from zos.layer.loader import LayerLoader


class TestLayerLoader:
    """Tests for LayerLoader."""

    @pytest.fixture
    def layers_dir(self, tmp_path: Path) -> Path:
        """Create a temporary layers directory."""
        return tmp_path

    @pytest.fixture
    def valid_layer_dir(self, layers_dir: Path) -> Path:
        """Create a valid layer directory."""
        layer_dir = layers_dir / "test_layer"
        layer_dir.mkdir()
        prompts_dir = layer_dir / "prompts"
        prompts_dir.mkdir()

        # Create layer.yml
        (layer_dir / "layer.yml").write_text(
            """
name: test_layer
description: A test layer
targets:
  categories:
    - channel
pipeline:
  for_each: target
  nodes:
    - type: fetch_messages
      lookback_hours: 24
    - type: llm_call
      prompt: summarize
"""
        )

        # Create prompts
        (prompts_dir / "system.j2").write_text("You are a test assistant.")
        (prompts_dir / "summarize.j2").write_text("Summarize: {{ messages }}")

        return layer_dir

    def test_load_valid_layer(
        self, layers_dir: Path, valid_layer_dir: Path  # noqa: ARG002
    ) -> None:
        """Test loading a valid layer."""
        loader = LayerLoader(layers_dir)
        layer = loader.load("test_layer")

        assert layer.name == "test_layer"
        assert layer.description == "A test layer"
        assert layer.targets.categories == ["channel"]
        assert layer.pipeline.for_each == "target"
        assert len(layer.pipeline.nodes) == 2

    def test_load_caches_layer(
        self, layers_dir: Path, valid_layer_dir: Path  # noqa: ARG002
    ) -> None:
        """Test that layers are cached."""
        loader = LayerLoader(layers_dir)

        layer1 = loader.load("test_layer")
        layer2 = loader.load("test_layer")

        assert layer1 is layer2

    def test_load_bypass_cache(
        self, layers_dir: Path, valid_layer_dir: Path  # noqa: ARG002
    ) -> None:
        """Test bypassing cache."""
        loader = LayerLoader(layers_dir)

        layer1 = loader.load("test_layer")
        layer2 = loader.load("test_layer", use_cache=False)

        # Different instances
        assert layer1 is not layer2
        # But same content
        assert layer1.name == layer2.name

    def test_load_nonexistent_layer(self, layers_dir: Path) -> None:
        """Test loading a nonexistent layer."""
        loader = LayerLoader(layers_dir)

        with pytest.raises(LayerValidationError, match="Layer not found"):
            loader.load("nonexistent")

    def test_load_invalid_yaml(self, layers_dir: Path) -> None:
        """Test loading layer with invalid YAML."""
        layer_dir = layers_dir / "bad_yaml"
        layer_dir.mkdir()
        (layer_dir / "layer.yml").write_text("{ invalid yaml: [")

        loader = LayerLoader(layers_dir)

        with pytest.raises(LayerValidationError, match="Invalid YAML"):
            loader.load("bad_yaml")

    def test_load_invalid_schema(self, layers_dir: Path) -> None:
        """Test loading layer with invalid schema."""
        layer_dir = layers_dir / "bad_schema"
        layer_dir.mkdir()
        (layer_dir / "layer.yml").write_text(
            """
name: bad_schema
# Missing required pipeline field
"""
        )

        loader = LayerLoader(layers_dir)

        with pytest.raises(LayerValidationError, match="validation failed"):
            loader.load("bad_schema")

    def test_load_empty_file(self, layers_dir: Path) -> None:
        """Test loading empty layer file."""
        layer_dir = layers_dir / "empty"
        layer_dir.mkdir()
        (layer_dir / "layer.yml").write_text("")

        loader = LayerLoader(layers_dir)

        with pytest.raises(LayerValidationError, match="Empty layer file"):
            loader.load("empty")

    def test_load_all(
        self, layers_dir: Path, valid_layer_dir: Path  # noqa: ARG002
    ) -> None:
        """Test loading all layers."""
        # Create another valid layer
        layer2_dir = layers_dir / "layer2"
        layer2_dir.mkdir()
        (layer2_dir / "prompts").mkdir()
        (layer2_dir / "layer.yml").write_text(
            """
name: layer2
pipeline:
  nodes:
    - type: fetch_messages
"""
        )

        loader = LayerLoader(layers_dir)
        layers = loader.load_all()

        assert len(layers) == 2
        names = {layer.name for layer in layers}
        assert "test_layer" in names
        assert "layer2" in names

    def test_load_all_skips_invalid(
        self, layers_dir: Path, valid_layer_dir: Path  # noqa: ARG002
    ) -> None:
        """Test load_all skips invalid layers."""
        # Create an invalid layer
        bad_dir = layers_dir / "bad"
        bad_dir.mkdir()
        (bad_dir / "layer.yml").write_text("invalid: [")

        loader = LayerLoader(layers_dir)
        layers = loader.load_all()

        # Only valid layer loaded
        assert len(layers) == 1
        assert layers[0].name == "test_layer"

    def test_validate_valid_layer(
        self, layers_dir: Path, valid_layer_dir: Path  # noqa: ARG002
    ) -> None:
        """Test validating a valid layer."""
        loader = LayerLoader(layers_dir)
        errors = loader.validate("test_layer")

        assert errors == []

    def test_validate_missing_prompt(
        self, layers_dir: Path, valid_layer_dir: Path
    ) -> None:
        """Test validation catches missing prompts."""
        # Remove the summarize prompt
        (valid_layer_dir / "prompts" / "summarize.j2").unlink()

        loader = LayerLoader(layers_dir)
        errors = loader.validate("test_layer")

        assert len(errors) == 1
        assert "Missing prompt template" in errors[0]
        assert "summarize.j2" in errors[0]

    def test_validate_missing_prompts_dir(self, layers_dir: Path) -> None:
        """Test validation catches missing prompts directory."""
        layer_dir = layers_dir / "no_prompts"
        layer_dir.mkdir()
        (layer_dir / "layer.yml").write_text(
            """
name: no_prompts
pipeline:
  nodes:
    - type: llm_call
      prompt: test
"""
        )

        loader = LayerLoader(layers_dir)
        errors = loader.validate("no_prompts")

        assert len(errors) == 1
        assert "Missing prompts directory" in errors[0]

    def test_validate_invalid_category(
        self, layers_dir: Path
    ) -> None:
        """Test validation catches invalid target categories."""
        layer_dir = layers_dir / "bad_category"
        layer_dir.mkdir()
        (layer_dir / "prompts").mkdir()
        (layer_dir / "layer.yml").write_text(
            """
name: bad_category
targets:
  categories:
    - invalid_category
pipeline:
  nodes:
    - type: fetch_messages
"""
        )

        loader = LayerLoader(layers_dir)
        errors = loader.validate("bad_category")

        assert len(errors) == 1
        assert "Invalid target category" in errors[0]

    def test_list_layers(
        self, layers_dir: Path, valid_layer_dir: Path  # noqa: ARG002
    ) -> None:
        """Test listing available layers."""
        loader = LayerLoader(layers_dir)
        layer_names = loader.list_layers()

        assert "test_layer" in layer_names

    def test_list_layers_empty(self, tmp_path: Path) -> None:
        """Test listing layers in empty directory."""
        loader = LayerLoader(tmp_path)
        layer_names = loader.list_layers()

        assert layer_names == []

    def test_list_layers_nonexistent_dir(self, tmp_path: Path) -> None:
        """Test listing layers when directory doesn't exist."""
        loader = LayerLoader(tmp_path / "nonexistent")
        layer_names = loader.list_layers()

        assert layer_names == []

    def test_clear_cache(
        self, layers_dir: Path, valid_layer_dir: Path  # noqa: ARG002
    ) -> None:
        """Test clearing the cache."""
        loader = LayerLoader(layers_dir)

        layer1 = loader.load("test_layer")
        loader.clear_cache()
        layer2 = loader.load("test_layer")

        # Different instances after cache clear
        assert layer1 is not layer2

    def test_get_layer_path(self, layers_dir: Path) -> None:
        """Test getting layer path."""
        loader = LayerLoader(layers_dir)
        path = loader.get_layer_path("test_layer")

        assert path == layers_dir / "test_layer"

    def test_get_prompts_dir(self, layers_dir: Path) -> None:
        """Test getting prompts directory path."""
        loader = LayerLoader(layers_dir)
        path = loader.get_prompts_dir("test_layer")

        assert path == layers_dir / "test_layer" / "prompts"
