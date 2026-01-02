"""Layer loader for YAML definitions.

Handles loading, validating, and caching layer definitions from YAML files.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import ValidationError

from zos.exceptions import LayerValidationError
from zos.layer.schema import LayerDefinition
from zos.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger("layer.loader")


class LayerLoader:
    """Loads and validates layer definitions from YAML files.

    Layer definitions are expected at:
        {layers_dir}/{layer_name}/layer.yml

    Prompts are expected at:
        {layers_dir}/{layer_name}/prompts/{prompt_name}.j2
    """

    def __init__(self, layers_dir: Path) -> None:
        """Initialize the loader.

        Args:
            layers_dir: Directory containing layer subdirectories.
        """
        self.layers_dir = Path(layers_dir)
        self._cache: dict[str, LayerDefinition] = {}

    def load(self, layer_name: str, use_cache: bool = True) -> LayerDefinition:
        """Load a layer definition by name.

        Args:
            layer_name: Name of the layer (directory name).
            use_cache: Whether to use cached definition.

        Returns:
            Validated LayerDefinition.

        Raises:
            LayerValidationError: If layer not found or invalid.
        """
        if use_cache and layer_name in self._cache:
            return self._cache[layer_name]

        layer_path = self.layers_dir / layer_name / "layer.yml"

        if not layer_path.exists():
            raise LayerValidationError(f"Layer not found: {layer_path}")

        try:
            with open(layer_path) as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise LayerValidationError(f"Invalid YAML in {layer_path}: {e}") from e

        if data is None:
            raise LayerValidationError(f"Empty layer file: {layer_path}")

        try:
            layer = LayerDefinition(**data)
        except ValidationError as e:
            raise LayerValidationError(
                f"Layer validation failed for {layer_name}: {e}"
            ) from e

        self._cache[layer_name] = layer
        logger.debug(f"Loaded layer: {layer_name}")
        return layer

    def load_all(self) -> list[LayerDefinition]:
        """Load all layers from the layers directory.

        Returns:
            List of successfully loaded layers.
        """
        layers: list[LayerDefinition] = []

        if not self.layers_dir.exists():
            logger.warning(f"Layers directory does not exist: {self.layers_dir}")
            return layers

        for path in self.layers_dir.iterdir():
            if path.is_dir() and (path / "layer.yml").exists():
                try:
                    layer = self.load(path.name)
                    layers.append(layer)
                except LayerValidationError as e:
                    logger.warning(f"Failed to load layer {path.name}: {e}")

        logger.info(f"Loaded {len(layers)} layers from {self.layers_dir}")
        return layers

    def validate(self, layer_name: str) -> list[str]:
        """Validate a layer definition and return errors.

        Checks:
        - Layer YAML is valid and parseable
        - Required prompt templates exist
        - Node configurations are valid

        Args:
            layer_name: Name of the layer to validate.

        Returns:
            List of error messages (empty if valid).
        """
        errors = []

        # Try to load the layer
        try:
            layer = self.load(layer_name, use_cache=False)
        except LayerValidationError as e:
            return [str(e)]

        # Check prompts directory exists
        prompts_dir = self.layers_dir / layer_name / "prompts"
        if not prompts_dir.exists():
            errors.append(f"Missing prompts directory: {prompts_dir}")
            return errors

        # Check required prompts exist
        for node_config in layer.pipeline.nodes:
            # Check user prompt for llm_call nodes
            if hasattr(node_config, "prompt") and node_config.prompt:
                prompt_path = prompts_dir / f"{node_config.prompt}.j2"
                if not prompt_path.exists():
                    errors.append(f"Missing prompt template: {prompt_path}")

            # Check system prompt for llm_call nodes
            if hasattr(node_config, "system_prompt") and node_config.system_prompt:
                system_path = prompts_dir / f"{node_config.system_prompt}.j2"
                if not system_path.exists():
                    errors.append(f"Missing system prompt: {system_path}")

        # Validate target categories
        valid_categories = {"user", "channel", "user_in_channel", "dyad", "dyad_in_channel"}
        for category in layer.targets.categories:
            if category not in valid_categories:
                errors.append(f"Invalid target category: {category}")

        return errors

    def list_layers(self) -> list[str]:
        """List available layer names.

        Returns:
            List of layer directory names.
        """
        if not self.layers_dir.exists():
            return []

        return [
            path.name
            for path in self.layers_dir.iterdir()
            if path.is_dir() and (path / "layer.yml").exists()
        ]

    def clear_cache(self) -> None:
        """Clear the layer cache."""
        self._cache.clear()

    def get_layer_path(self, layer_name: str) -> Path:
        """Get the path to a layer directory.

        Args:
            layer_name: Name of the layer.

        Returns:
            Path to the layer directory.
        """
        return self.layers_dir / layer_name

    def get_prompts_dir(self, layer_name: str) -> Path:
        """Get the path to a layer's prompts directory.

        Args:
            layer_name: Name of the layer.

        Returns:
            Path to the prompts directory.
        """
        return self.layers_dir / layer_name / "prompts"
