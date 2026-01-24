# Story 1.2: Config System

**Epic**: Foundation
**Status**: 🟢 Complete
**Estimated complexity**: Medium

## Goal

Implement configuration loading from YAML files with environment variable overlay, validated by Pydantic.

## Acceptance Criteria

- [x] `config.yaml` loads with Pydantic validation
- [x] Environment variables override YAML values (for secrets)
- [x] Invalid config produces clear error messages
- [x] Model profiles are defined and accessible
- [x] Salience weights/caps are configurable
- [x] `zos config check` validates configuration

## Configuration Structure

Based on the specs, the config needs to cover:

```yaml
# config.yaml

# General
data_dir: ./data
log_level: INFO
log_json: true

# Discord
discord:
  polling_interval_seconds: 60
  # token comes from DISCORD_TOKEN env var

# Database
database:
  path: ${data_dir}/zos.db

# LLM Model Profiles
models:
  profiles:
    simple:
      provider: anthropic
      model: claude-3-5-haiku-20241022
    moderate:
      provider: anthropic
      model: claude-sonnet-4-20250514
    complex:
      provider: anthropic
      model: claude-opus-4-20250514

    # Semantic aliases
    default: moderate
    reflection: moderate
    conversation: moderate
    synthesis: complex
    self_reflection: complex
    review: simple
    vision: moderate

  providers:
    anthropic:
      api_key_env: ANTHROPIC_API_KEY
    openai:
      api_key_env: OPENAI_API_KEY

# Salience (from salience.md)
salience:
  caps:
    server_user: 100
    channel: 150
    # ... (full set from spec)

  weights:
    message: 1.0
    reaction: 0.5
    mention: 2.0
    # ... (full set from spec)

  propagation_factor: 0.3
  spillover_factor: 0.5
  retention_rate: 0.3
  decay_threshold_days: 7
  decay_rate_per_day: 0.01

  budget:
    social: 0.30
    global: 0.15
    spaces: 0.30
    semantic: 0.20
    culture: 0.10

# Chattiness (from chattiness.md)
chattiness:
  decay_threshold_hours: 1
  decay_rate_per_hour: 0.05
  base_spend: 10
  # ... (subset for MVP 0, full chat is MVP 1)

# Privacy
privacy:
  review_pass: private_context  # always | private_context | never
  first_contact_message: |
    I remember what you tell me...

# Observation
observation:
  vision_enabled: true
  link_fetch_enabled: true
  youtube_transcript_enabled: true
  video_duration_threshold_minutes: 30

# Server-specific overrides
servers:
  # Keyed by Discord server ID
  # "123456789":
  #   privacy_gate_role: "987654321"
  #   threads_as_topics: false
```

## Technical Notes

### Pydantic Settings

Use `pydantic-settings` for env var integration:

```python
# src/zos/config.py
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
import yaml
from pathlib import Path

class ModelProfile(BaseModel):
    provider: str
    model: str

class ModelsConfig(BaseModel):
    profiles: dict[str, ModelProfile | str]  # str for aliases
    providers: dict[str, dict]

class SalienceConfig(BaseModel):
    caps: dict[str, int]
    weights: dict[str, float]
    propagation_factor: float = 0.3
    # ... etc

class Config(BaseSettings):
    data_dir: Path = Path("./data")
    log_level: str = "INFO"
    log_json: bool = True

    discord_token: str = Field(default="", env="DISCORD_TOKEN")

    models: ModelsConfig
    salience: SalienceConfig
    # ... etc

    @classmethod
    def load(cls, config_path: Path = Path("config.yaml")) -> "Config":
        """Load config from YAML, overlay env vars."""
        with open(config_path) as f:
            yaml_config = yaml.safe_load(f)
        return cls(**yaml_config)
```

### Alias Resolution

Model profile aliases need resolution:

```python
def resolve_model_profile(self, name: str) -> ModelProfile:
    """Resolve a profile name (may be alias) to actual profile."""
    profile = self.models.profiles.get(name)
    if isinstance(profile, str):
        # It's an alias, resolve it
        return self.resolve_model_profile(profile)
    return profile
```

### CLI Command

```python
@cli.command()
@click.option("--config", "-c", default="config.yaml", help="Config file path")
def config_check(config: str):
    """Validate configuration file."""
    try:
        cfg = Config.load(Path(config))
        click.echo("Configuration valid!")
        click.echo(f"  Data dir: {cfg.data_dir}")
        click.echo(f"  Model profiles: {len(cfg.models.profiles)}")
    except Exception as e:
        click.echo(f"Configuration error: {e}", err=True)
        raise SystemExit(1)
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/config.py` | Config loading and Pydantic models |
| `config.yaml.example` | Full example configuration |
| `src/zos/cli.py` | Add `config check` command |
| `tests/test_config.py` | Config validation tests |

## Test Cases

1. Valid config loads successfully
2. Missing required field produces clear error
3. Invalid type produces clear error
4. Env var overrides YAML value
5. Model profile alias resolves correctly
6. Default values work when optional fields omitted

## Definition of Done

- [ ] `config.yaml.example` documents all options
- [ ] `zos config check` validates and reports errors
- [ ] Tests cover validation edge cases
- [ ] Secrets (tokens, API keys) come from env vars only

---

**Requires**: Story 1.1 (project scaffold)
**Blocks**: Stories 1.3+ (everything needs config)
