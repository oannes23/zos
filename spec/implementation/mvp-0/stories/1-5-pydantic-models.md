# Story 1.5: Pydantic Models

**Epic**: Foundation
**Status**: 🟢 Complete
**Estimated complexity**: Medium

## Goal

Define Pydantic models for all entities that bridge between the database (SQLAlchemy Core) and application code, with proper serialization and validation.

## Acceptance Criteria

- [x] Pydantic model for each entity in data-model.md
- [x] Models validate data on construction
- [x] Models serialize to/from database rows
- [x] Models serialize to JSON (for API)
- [x] ULID fields validate format
- [x] Enum fields constrain to valid values
- [x] Valence constraint enforced at model level

## Models to Create

### Core Entities

```python
# src/zos/models.py
from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime
from enum import Enum
from typing import Optional
from ulid import ULID

class VisibilityScope(str, Enum):
    PUBLIC = "public"
    DM = "dm"

class TopicCategory(str, Enum):
    USER = "user"
    CHANNEL = "channel"
    THREAD = "thread"
    ROLE = "role"
    DYAD = "dyad"
    USER_IN_CHANNEL = "user_in_channel"
    DYAD_IN_CHANNEL = "dyad_in_channel"
    SUBJECT = "subject"
    EMOJI = "emoji"
    SELF = "self"

class TransactionType(str, Enum):
    EARN = "earn"
    SPEND = "spend"
    RETAIN = "retain"
    DECAY = "decay"
    PROPAGATE = "propagate"
    SPILLOVER = "spillover"
    WARM = "warm"

class LayerRunStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    DRY = "dry"
```

### Message Model

```python
class Message(BaseModel):
    id: str  # Discord snowflake
    channel_id: str
    server_id: Optional[str] = None
    author_id: str
    content: str
    created_at: datetime
    visibility_scope: VisibilityScope
    reactions_aggregate: Optional[dict] = None
    reply_to_id: Optional[str] = None
    thread_id: Optional[str] = None
    has_media: bool = False
    has_links: bool = False
    ingested_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True  # Enable ORM mode for SQLAlchemy rows
```

### Topic Model

```python
class Topic(BaseModel):
    key: str  # Primary key - validated format
    category: TopicCategory
    is_global: bool
    provisional: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_activity_at: Optional[datetime] = None
    metadata: Optional[dict] = None

    @field_validator("key")
    @classmethod
    def validate_topic_key(cls, v: str) -> str:
        """Validate topic key format."""
        # Global patterns
        if v.startswith("user:") or v.startswith("dyad:") or v.startswith("self:"):
            return v
        # Server-scoped must start with server:
        if v.startswith("server:"):
            return v
        raise ValueError(f"Invalid topic key format: {v}")

    class Config:
        from_attributes = True
```

### Insight Model (with valence constraint)

```python
class Insight(BaseModel):
    id: str  # ULID
    topic_key: str
    category: str
    content: str
    sources_scope_max: VisibilityScope
    created_at: datetime
    layer_run_id: str
    supersedes: Optional[str] = None
    quarantined: bool = False

    # Strength and metrics
    salience_spent: float
    strength_adjustment: float = Field(ge=0.1, le=10.0)
    strength: float  # Computed
    confidence: float = Field(ge=0.0, le=1.0)
    importance: float = Field(ge=0.0, le=1.0)
    novelty: float = Field(ge=0.0, le=1.0)

    # Valence (at least one required)
    valence_joy: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    valence_concern: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    valence_curiosity: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    valence_warmth: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    valence_tension: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    # Cross-links
    context_channel: Optional[str] = None
    context_thread: Optional[str] = None
    subject: Optional[str] = None
    participants: Optional[list[str]] = None

    # Conflict tracking
    conflicts_with: Optional[list[str]] = None
    conflict_resolved: Optional[bool] = None

    # Synthesis tracking
    synthesis_source_ids: Optional[list[str]] = None

    @model_validator(mode="after")
    def validate_valence_required(self) -> "Insight":
        """Ensure at least one valence field is set."""
        if all(v is None for v in [
            self.valence_joy,
            self.valence_concern,
            self.valence_curiosity,
            self.valence_warmth,
            self.valence_tension,
        ]):
            raise ValueError("At least one valence field must be set")
        return self

    @field_validator("id")
    @classmethod
    def validate_ulid(cls, v: str) -> str:
        """Validate ULID format."""
        try:
            ULID.from_str(v)
        except ValueError:
            raise ValueError(f"Invalid ULID: {v}")
        return v

    class Config:
        from_attributes = True
```

### Layer Run Model

```python
class LayerRun(BaseModel):
    id: str  # ULID
    layer_name: str
    layer_hash: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: LayerRunStatus
    targets_matched: int
    targets_processed: int
    targets_skipped: int
    insights_created: int
    model_profile: Optional[str] = None
    model_provider: Optional[str] = None
    model_name: Optional[str] = None
    tokens_input: Optional[int] = None
    tokens_output: Optional[int] = None
    tokens_total: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    errors: Optional[list[dict]] = None

    class Config:
        from_attributes = True
```

### Salience Ledger Entry

```python
class SalienceEntry(BaseModel):
    id: str  # ULID
    topic_key: str
    transaction_type: TransactionType
    amount: float
    reason: Optional[str] = None
    source_topic: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True
```

## Helper Functions

```python
# Database <-> Model conversion helpers

def row_to_model[T: BaseModel](row, model_class: type[T]) -> T:
    """Convert SQLAlchemy row to Pydantic model."""
    return model_class.model_validate(row._mapping)

def model_to_dict(model: BaseModel) -> dict:
    """Convert Pydantic model to dict for database insert."""
    return model.model_dump(exclude_none=False)

def generate_id() -> str:
    """Generate new ULID."""
    return str(ULID())
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/models.py` | All Pydantic models |
| `tests/test_models.py` | Model validation tests |

## Test Cases

1. Message model accepts valid data
2. Topic key validation rejects invalid formats
3. Insight valence constraint enforced
4. ULID validation works
5. Enum fields reject invalid values
6. Models serialize to JSON correctly
7. Models construct from database rows

## Definition of Done

- [ ] All entities have Pydantic models
- [ ] Validation constraints match spec
- [ ] Tests cover validation edge cases
- [ ] Models work with SQLAlchemy rows

---

**Requires**: Story 1.3 (database schema for field alignment)
**Blocks**: Epic 2+ (all code uses these models)
