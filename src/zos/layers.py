"""Layer YAML loading and validation for Zos.

Layers are declarative cognitive pipelines defined in YAML. They specify
how reflection and conversation processing works, making cognitive logic
inspectable, modifiable, and eventually self-modifiable.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from zos.logging import get_logger

log = get_logger("layers")


# =============================================================================
# Node Types
# =============================================================================


class NodeType(str, Enum):
    """Types of nodes in a layer pipeline.

    Core nodes:
    - fetch_messages: Retrieve conversation history
    - fetch_insights: Retrieve prior understanding
    - llm_call: Process through language model
    - store_insight: Persist new understanding
    - reduce: Combine multiple outputs
    - output: Emit to external destination
    - filter: Self-review draft before sending

    Special nodes:
    - synthesize_to_global: Consolidate server-scoped insights to global topic
    - update_self_concept: Update the self-concept.md document
    - fetch_layer_runs: Retrieve layer run history for self-reflection
    - fetch_reactions: Retrieve emoji reaction patterns for a user
    """

    FETCH_MESSAGES = "fetch_messages"
    FETCH_INSIGHTS = "fetch_insights"
    FETCH_REACTIONS = "fetch_reactions"
    LLM_CALL = "llm_call"
    STORE_INSIGHT = "store_insight"
    REDUCE = "reduce"
    OUTPUT = "output"
    FILTER = "filter"
    SYNTHESIZE_TO_GLOBAL = "synthesize_to_global"
    UPDATE_SELF_CONCEPT = "update_self_concept"
    FETCH_LAYER_RUNS = "fetch_layer_runs"


# =============================================================================
# Layer Category
# =============================================================================


class LayerCategory(str, Enum):
    """Layer category determines budget allocation and organization.

    Reflection categories (scheduled):
    - user: Reflects on individual users
    - dyad: Reflects on relationships
    - channel: Reflects on spaces/channels
    - subject: Reflects on semantic topics
    - emoji: Reflects on emoji as cultural artifacts
    - self: Self-reflection
    - synthesis: Consolidates insights across scopes

    Conversation categories (impulse-triggered):
    - response: Direct response to DMs
    - participation: Contributing to channel conversations
    - insight_sharing: Sharing subject insights post-reflection
    """

    USER = "user"
    DYAD = "dyad"
    CHANNEL = "channel"
    SUBJECT = "subject"
    EMOJI = "emoji"
    SELF = "self"
    SYNTHESIS = "synthesis"

    # Conversation categories
    RESPONSE = "response"
    PARTICIPATION = "participation"
    INSIGHT_SHARING = "insight_sharing"


# =============================================================================
# Node Model
# =============================================================================


class Node(BaseModel):
    """A single node in a layer pipeline.

    Nodes are executed sequentially, each receiving context from prior nodes
    and contributing to the context passed to subsequent nodes.

    Attributes:
        name: Optional human-readable name for the node.
        type: The node type determining its behavior.
        params: Type-specific configuration parameters.
    """

    name: str | None = None
    type: NodeType
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("params")
    @classmethod
    def validate_params_for_type(cls, v: dict[str, Any], info) -> dict[str, Any]:
        """Validate params match the node type.

        Currently a placeholder for future type-specific validation.
        """
        # Future: Add type-specific validation based on info.data['type']
        return v


# =============================================================================
# Layer Model
# =============================================================================


class Layer(BaseModel):
    """A complete layer definition.

    Layers are YAML-defined cognitive pipelines that specify how reflection
    or conversation processing works. Each layer has a category, optional
    scheduling, target selection criteria, and a sequence of nodes.

    Attributes:
        name: Unique identifier for the layer.
        category: Layer category for budget allocation.
        description: Human-readable description of what the layer does.
        schedule: Cron expression for scheduled execution (e.g., "0 3 * * *").
        trigger: Alternative trigger for non-scheduled layers.
        trigger_threshold: Threshold for self-reflection triggers.
        target_category: Category of topics this layer targets.
        target_filter: Expression for selecting which topics to process.
        max_targets: Maximum number of targets to process per run.
        nodes: Sequence of nodes to execute.
    """

    name: str
    category: LayerCategory
    description: str | None = None

    # Scheduling
    schedule: str | None = None  # Cron expression
    trigger: str | None = None  # For non-scheduled layers
    trigger_threshold: int | None = None  # For self-reflection

    # Target selection
    target_category: str | None = None
    target_filter: str | None = None
    max_targets: int = 10

    # Pipeline
    nodes: list[Node]

    @field_validator("schedule")
    @classmethod
    def validate_cron(cls, v: str | None) -> str | None:
        """Validate cron expression format.

        Performs basic validation that the cron expression has 5 parts.
        More thorough validation could use croniter library.
        """
        if v is None:
            return v

        parts = v.split()
        if len(parts) != 5:
            raise ValueError(
                f"Invalid cron expression: '{v}'. "
                f"Expected 5 parts (minute hour day month weekday), got {len(parts)}"
            )
        return v

    @field_validator("nodes")
    @classmethod
    def validate_nodes_not_empty(cls, v: list[Node]) -> list[Node]:
        """Ensure at least one node is defined."""
        if not v:
            raise ValueError("Layer must have at least one node")
        return v


# =============================================================================
# Error Formatting
# =============================================================================


def format_validation_error(error: ValidationError, path: Path) -> str:
    """Format Pydantic validation error for user display.

    Args:
        error: The Pydantic ValidationError to format.
        path: Path to the file that failed validation.

    Returns:
        Human-readable error message with location details.
    """
    lines = [f"Invalid layer definition in {path}:"]
    for err in error.errors():
        loc = " -> ".join(str(loc_part) for loc_part in err["loc"])
        lines.append(f"  {loc}: {err['msg']}")
    return "\n".join(lines)


# =============================================================================
# Layer Loader
# =============================================================================


class LayerLoader:
    """Loads and validates layer definitions from YAML files.

    The LayerLoader handles:
    - Discovery of layer files in a directory tree
    - YAML parsing and Pydantic validation
    - Content hash computation for versioning
    - Caching and hot reload support

    Attributes:
        layers_dir: Base directory for layer YAML files.
    """

    def __init__(self, layers_dir: Path = Path("layers")) -> None:
        """Initialize the layer loader.

        Args:
            layers_dir: Base directory to search for layer YAML files.
        """
        self.layers_dir = layers_dir
        self._cache: dict[str, tuple[Layer, str]] = {}  # name -> (layer, hash)

    def load_all(self) -> dict[str, Layer]:
        """Load all layers from the layers directory.

        Recursively finds all .yaml files in the layers directory,
        parses and validates each one, and returns a dictionary
        keyed by layer name.

        Returns:
            Dictionary mapping layer names to Layer objects.

        Raises:
            FileNotFoundError: If the layers directory doesn't exist.
            ValueError: If any layer file fails validation.
            yaml.YAMLError: If any file contains invalid YAML.
        """
        if not self.layers_dir.exists():
            raise FileNotFoundError(f"Layers directory not found: {self.layers_dir}")

        layers: dict[str, Layer] = {}

        for yaml_path in self.layers_dir.rglob("*.yaml"):
            try:
                layer = self.load_file(yaml_path)
                if layer.name in layers:
                    log.warning(
                        "duplicate_layer_name",
                        name=layer.name,
                        path=str(yaml_path),
                        existing_path="(already loaded)",
                    )
                layers[layer.name] = layer
            except ValidationError as e:
                error_msg = format_validation_error(e, yaml_path)
                log.error("layer_validation_failed", path=str(yaml_path), error=error_msg)
                raise ValueError(error_msg) from e
            except yaml.YAMLError as e:
                log.error("layer_yaml_parse_failed", path=str(yaml_path), error=str(e))
                raise
            except Exception as e:
                log.error("layer_load_failed", path=str(yaml_path), error=str(e))
                raise

        log.info("layers_loaded", count=len(layers), directory=str(self.layers_dir))
        return layers

    def load_file(self, path: Path) -> Layer:
        """Load a single layer file.

        Parses the YAML file, validates it against the Layer model,
        computes a content hash for versioning, and caches the result.

        Args:
            path: Path to the YAML file to load.

        Returns:
            Validated Layer object.

        Raises:
            FileNotFoundError: If the file doesn't exist.
            ValidationError: If the file fails Pydantic validation.
            yaml.YAMLError: If the file contains invalid YAML.
        """
        if not path.exists():
            raise FileNotFoundError(f"Layer file not found: {path}")

        content = path.read_text()

        # Compute content hash for versioning
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        # Parse YAML
        data = yaml.safe_load(content)
        if data is None:
            raise ValueError(f"Empty layer file: {path}")

        # Validate with Pydantic
        layer = Layer.model_validate(data)

        # Cache with hash
        self._cache[layer.name] = (layer, content_hash)

        log.debug("layer_loaded", name=layer.name, hash=content_hash, path=str(path))

        return layer

    def get_layer(self, name: str) -> Layer | None:
        """Get a layer by name from cache.

        Args:
            name: Name of the layer to retrieve.

        Returns:
            The Layer object if cached, None otherwise.
        """
        if name in self._cache:
            return self._cache[name][0]
        return None

    def get_hash(self, name: str) -> str | None:
        """Get the content hash for a layer.

        The content hash is computed from the raw YAML file content
        using SHA-256 (first 16 characters). This enables versioning
        and change detection.

        Args:
            name: Name of the layer.

        Returns:
            Content hash if layer is cached, None otherwise.
        """
        if name in self._cache:
            return self._cache[name][1]
        return None

    def reload(self) -> dict[str, Layer]:
        """Reload all layers from disk.

        Clears the cache and re-loads all layer files.
        Useful for hot-reload scenarios during development.

        Returns:
            Dictionary mapping layer names to Layer objects.
        """
        self._cache.clear()
        return self.load_all()

    def list_layers(self) -> list[str]:
        """List all cached layer names.

        Returns:
            Sorted list of layer names.
        """
        return sorted(self._cache.keys())
