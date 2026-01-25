# Story 4.1: Layer YAML Loading

**Epic**: Reflection
**Status**: 🟢 Complete
**Estimated complexity**: Medium

## Goal

Implement loading and validation of layer YAML definitions using Pydantic models.

## Acceptance Criteria

- [x] Layer YAML files load from `layers/` directory
- [x] Pydantic models validate layer structure
- [x] Invalid YAML produces clear error messages
- [x] Content hash computed for versioning
- [x] Layers discoverable by name
- [x] Hot reload supported (re-read on demand)

## Technical Notes

### Layer Directory Structure

```
layers/
├── reflection/
│   ├── nightly-user.yaml
│   ├── nightly-dyad.yaml
│   ├── nightly-channel.yaml
│   └── weekly-self.yaml
└── synthesis/
    └── global-user.yaml
```

### Pydantic Models

```python
# src/zos/layers.py
from pydantic import BaseModel, Field, field_validator
from typing import Literal, Any
from enum import Enum

class NodeType(str, Enum):
    FETCH_MESSAGES = "fetch_messages"
    FETCH_INSIGHTS = "fetch_insights"
    LLM_CALL = "llm_call"
    STORE_INSIGHT = "store_insight"
    REDUCE = "reduce"
    OUTPUT = "output"
    SYNTHESIZE_TO_GLOBAL = "synthesize_to_global"
    UPDATE_SELF_CONCEPT = "update_self_concept"

class Node(BaseModel):
    """A single node in a layer pipeline."""
    name: str | None = None
    type: NodeType
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator('params')
    @classmethod
    def validate_params_for_type(cls, v, info):
        """Validate params match the node type."""
        # Could add type-specific validation here
        return v

class LayerCategory(str, Enum):
    USER = "user"
    DYAD = "dyad"
    CHANNEL = "channel"
    SUBJECT = "subject"
    SELF = "self"
    SYNTHESIS = "synthesis"

class Layer(BaseModel):
    """A complete layer definition."""
    name: str
    category: LayerCategory
    description: str | None = None

    # Scheduling
    schedule: str | None = None  # Cron expression
    trigger: str | None = None   # For non-scheduled layers
    trigger_threshold: int | None = None  # For self-reflection

    # Target selection
    target_category: str | None = None
    target_filter: str | None = None
    max_targets: int = 10

    # Pipeline
    nodes: list[Node]

    @field_validator('schedule')
    @classmethod
    def validate_cron(cls, v):
        """Validate cron expression."""
        if v is None:
            return v
        # Simple validation - could use croniter for full validation
        parts = v.split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {v}")
        return v

    @field_validator('nodes')
    @classmethod
    def validate_nodes_not_empty(cls, v):
        """Ensure at least one node."""
        if not v:
            raise ValueError("Layer must have at least one node")
        return v
```

### Layer Loading

```python
import yaml
import hashlib
from pathlib import Path

class LayerLoader:
    """Loads and validates layer definitions."""

    def __init__(self, layers_dir: Path = Path("layers")):
        self.layers_dir = layers_dir
        self._cache: dict[str, tuple[Layer, str]] = {}  # name -> (layer, hash)

    def load_all(self) -> dict[str, Layer]:
        """Load all layers from the layers directory."""
        layers = {}

        for yaml_path in self.layers_dir.rglob("*.yaml"):
            try:
                layer = self.load_file(yaml_path)
                layers[layer.name] = layer
            except Exception as e:
                log.error(
                    "layer_load_failed",
                    path=str(yaml_path),
                    error=str(e),
                )
                raise

        log.info("layers_loaded", count=len(layers))
        return layers

    def load_file(self, path: Path) -> Layer:
        """Load a single layer file."""
        content = path.read_text()

        # Compute content hash for versioning
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        # Parse YAML
        data = yaml.safe_load(content)

        # Validate with Pydantic
        layer = Layer(**data)

        # Cache with hash
        self._cache[layer.name] = (layer, content_hash)

        return layer

    def get_layer(self, name: str) -> Layer | None:
        """Get a layer by name."""
        if name in self._cache:
            return self._cache[name][0]
        return None

    def get_hash(self, name: str) -> str | None:
        """Get the content hash for a layer."""
        if name in self._cache:
            return self._cache[name][1]
        return None

    def reload(self):
        """Reload all layers from disk."""
        self._cache.clear()
        return self.load_all()
```

### Error Messages

```python
from pydantic import ValidationError

def format_validation_error(e: ValidationError, path: Path) -> str:
    """Format Pydantic validation error for user display."""
    lines = [f"Invalid layer definition in {path}:"]
    for error in e.errors():
        loc = " -> ".join(str(l) for l in error['loc'])
        lines.append(f"  {loc}: {error['msg']}")
    return "\n".join(lines)
```

### CLI Commands

```python
@cli.group()
def layer():
    """Layer management commands."""
    pass

@layer.command()
@click.option("--dir", "-d", default="layers", help="Layers directory")
def list(dir: str):
    """List all available layers."""
    loader = LayerLoader(Path(dir))
    layers = loader.load_all()

    for name, layer in sorted(layers.items()):
        schedule = layer.schedule or layer.trigger or "manual"
        click.echo(f"  {name}: {layer.category.value} ({schedule})")

@layer.command()
@click.argument("name")
@click.option("--dir", "-d", default="layers", help="Layers directory")
def validate(name: str, dir: str):
    """Validate a specific layer."""
    loader = LayerLoader(Path(dir))

    try:
        layers = loader.load_all()
        if name not in layers:
            click.echo(f"Layer '{name}' not found", err=True)
            raise SystemExit(1)

        layer = layers[name]
        click.echo(f"Layer '{name}' is valid")
        click.echo(f"  Category: {layer.category.value}")
        click.echo(f"  Nodes: {len(layer.nodes)}")
        click.echo(f"  Hash: {loader.get_hash(name)}")

    except ValidationError as e:
        click.echo(format_validation_error(e, Path(dir)), err=True)
        raise SystemExit(1)
```

### Example Layer File

```yaml
# layers/reflection/nightly-user.yaml
name: nightly-user-reflection
category: user
description: |
  Reflect on each user's recent activity to update understanding.
  Runs nightly, targeting users with highest salience.

schedule: "0 3 * * *"
target_category: users
target_filter: "salience > 50"
max_targets: 10

nodes:
  - name: get_messages
    type: fetch_messages
    params:
      lookback_hours: 24
      limit_per_channel: 50

  - name: get_prior
    type: fetch_insights
    params:
      retrieval_profile: recent
      max_per_topic: 3

  - name: reflect
    type: llm_call
    params:
      prompt_template: user/reflection.jinja2
      model: reflection
      max_tokens: 500

  - name: save
    type: store_insight
    params:
      category: user_reflection
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/layers.py` | Layer/Node models, LayerLoader |
| `src/zos/cli.py` | Layer commands |
| `layers/reflection/nightly-user.yaml` | Example layer |
| `tests/test_layer_loading.py` | Loading tests |

## Test Cases

1. Valid YAML loads successfully
2. Missing required field produces error
3. Invalid node type produces error
4. Invalid cron produces error
5. Content hash is consistent
6. Reload picks up changes
7. All example layers validate

## Definition of Done

- [x] Layers load from directory
- [x] Validation catches errors with clear messages
- [x] CLI commands work
- [x] Content hash computed

---

**Requires**: Epic 1 complete
**Blocks**: Stories 4.2-4.8

---

## Implementation Notes

Implemented 2026-01-25:

### Files Created/Modified

| File | Purpose |
|------|---------|
| `src/zos/layers.py` | NodeType enum, Node model, LayerCategory enum, Layer model, LayerLoader class, format_validation_error function |
| `src/zos/cli.py` | Added `zos layer list` and `zos layer validate` commands |
| `layers/reflection/nightly-user.yaml` | Example user reflection layer |
| `tests/test_layers.py` | 44 tests covering all acceptance criteria |

### Additional Details

- Added `fetch_layer_runs` node type for self-reflection accessing run history
- Content hash uses SHA-256 truncated to first 16 hex characters
- LayerLoader includes `list_layers()` method for cached layer names
- CLI provides helpful error messages including available layers on not-found
