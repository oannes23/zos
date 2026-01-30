"""Configuration loading and validation for Zos."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class ModelProfile(BaseModel):
    """Configuration for an LLM model profile."""

    provider: str
    model: str


class ModelsConfig(BaseModel):
    """Configuration for LLM models and providers."""

    profiles: dict[str, ModelProfile | str]
    providers: dict[str, dict[str, Any]]

    def resolve_profile(self, name: str) -> ModelProfile:
        """Resolve a profile name (may be alias) to actual profile.

        Args:
            name: Profile name to resolve.

        Returns:
            The resolved ModelProfile.

        Raises:
            KeyError: If profile name not found.
            ValueError: If alias chain is circular or too deep.
        """
        seen: set[str] = set()
        current = name

        while True:
            if current in seen:
                raise ValueError(f"Circular alias detected: {current}")
            seen.add(current)

            if len(seen) > 10:
                raise ValueError(f"Alias chain too deep for profile: {name}")

            profile = self.profiles.get(current)
            if profile is None:
                raise KeyError(f"Unknown model profile: {current}")

            if isinstance(profile, str):
                # It's an alias, follow it
                current = profile
            else:
                return profile

    def get_api_key(self, provider: str) -> str | None:
        """Get API key for a provider from environment.

        Args:
            provider: Provider name (e.g., 'anthropic').

        Returns:
            API key from environment, or None if not found.
        """
        provider_config = self.providers.get(provider, {})
        env_var = provider_config.get("api_key_env")
        if env_var:
            return os.environ.get(env_var)
        return None


class SalienceCapsConfig(BaseModel):
    """Salience caps per topic type."""

    server_user: int = 100
    global_user: int = 150
    channel: int = 150
    thread: int = 50
    role: int = 80
    dyad: int = 80
    user_in_channel: int = 40
    dyad_in_channel: int = 30
    subject: int = 60
    emoji: int = 60
    self_topic: int = Field(100, alias="self")


class SalienceWeightsConfig(BaseModel):
    """Salience earning weights per activity type."""

    message: float = 1.0
    reaction: float = 0.5
    mention: float = 2.0
    reply: float = 1.5
    thread_create: float = 2.0
    dm_message: float = 1.5
    emoji_use: float = 0.5
    media_boost_factor: float = 1.2
    self_mention: float = 5.0  # Extra salience when Zos is directly mentioned


class SalienceBudgetConfig(BaseModel):
    """Salience budget allocation per group."""

    social: float = 0.30
    global_group: float = Field(0.15, alias="global")
    spaces: float = 0.30
    semantic: float = 0.15
    culture: float = 0.10

    @model_validator(mode="after")
    def validate_budget_sum(self) -> "SalienceBudgetConfig":
        """Warn if budget doesn't sum to approximately 1.0."""
        total = self.social + self.global_group + self.spaces + self.semantic + self.culture
        if abs(total - 1.0) > 0.05:
            # Just a warning - allow flexibility
            pass
        return self


class SalienceConfig(BaseModel):
    """Full salience configuration."""

    caps: SalienceCapsConfig = Field(default_factory=SalienceCapsConfig)
    weights: SalienceWeightsConfig = Field(default_factory=SalienceWeightsConfig)
    propagation_factor: float = 0.3
    global_propagation_factor: float = 0.3
    spillover_factor: float = 0.5
    initial_global_warmth: float = 5.0
    retention_rate: float = 0.3
    decay_threshold_days: int = 7
    decay_rate_per_day: float = 0.01
    warm_threshold: float = 1.0
    min_reflection_salience: float = 10.0  # Minimum salience for topic to be eligible for reflection
    cost_per_token: float = 0.001  # Salience cost per LLM token for reflection spending
    budget: SalienceBudgetConfig = Field(default_factory=SalienceBudgetConfig)
    self_budget: float = 20
    global_reflection_budget: float = 15.0  # Budget for global topics (cross-server/DM)


class ChattinessConfig(BaseModel):
    """Chattiness configuration (MVP 1 prep)."""

    decay_threshold_hours: float = 1
    decay_rate_per_hour: float = 0.05
    base_spend: float = 10


class PrivacyConfig(BaseModel):
    """Privacy configuration."""

    review_pass: str = "private_context"
    first_contact_message: str = ""

    @field_validator("review_pass")
    @classmethod
    def validate_review_pass(cls, v: str) -> str:
        """Validate review_pass is one of allowed values."""
        allowed = {"always", "private_context", "never"}
        if v not in allowed:
            raise ValueError(f"review_pass must be one of: {allowed}")
        return v


class ObservationConfig(BaseModel):
    """Observation configuration."""

    vision_enabled: bool = True
    vision_rate_limit_per_minute: int = 10
    link_fetch_enabled: bool = True
    youtube_transcript_enabled: bool = True
    video_duration_threshold_minutes: int = 30
    backfill_hours: int = 24
    reaction_user_rate_limit_per_minute: int = 20
    media_queue_max_size: int = 100
    link_queue_max_size: int = 50
    link_rate_limit_per_minute: int = 5
    reaction_resync_hours: int = 24


class SchedulerConfig(BaseModel):
    """Scheduler configuration."""

    timezone: str = "UTC"
    reflection_cron: str = "0 13 * * *"


class DevelopmentConfig(BaseModel):
    """Development configuration for dev-only features."""

    dev_mode: bool = False
    allow_mutations: bool = True


class OperatorsConfig(BaseModel):
    """Operators configuration for command access control."""

    user_ids: list[str] = Field(default_factory=list)
    role_id: str | None = None


class DiscordConfig(BaseModel):
    """Discord configuration."""

    polling_interval_seconds: int = 300
    operators: OperatorsConfig = Field(default_factory=OperatorsConfig)
    bot_user_id: str | None = None  # Auto-detected at runtime from Discord


class DatabaseConfig(BaseModel):
    """Database configuration."""

    path: str = "zos.db"


class ServerOverrideConfig(BaseModel):
    """Per-server configuration overrides."""

    privacy_gate_role: str | None = None
    threads_as_topics: bool = True
    disabled_layers: list[str] = Field(default_factory=list)
    chattiness: dict[str, Any] | None = None
    focus: float = 1.0
    reflection_budget: float = 100.0  # Per-server reflection budget


class Config(BaseModel):
    """Root configuration for Zos."""

    data_dir: Path = Path("./data")
    log_level: str = "INFO"
    log_json: bool = True
    self_concept_max_chars: int = 15000

    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    models: ModelsConfig | None = None
    salience: SalienceConfig = Field(default_factory=SalienceConfig)
    chattiness: ChattinessConfig = Field(default_factory=ChattinessConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    observation: ObservationConfig = Field(default_factory=ObservationConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    development: DevelopmentConfig = Field(default_factory=DevelopmentConfig)
    servers: dict[str, ServerOverrideConfig] = Field(default_factory=dict)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log_level is valid."""
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR"}
        v_upper = v.upper()
        if v_upper not in allowed:
            raise ValueError(f"log_level must be one of: {allowed}")
        return v_upper

    @property
    def database_path(self) -> Path:
        """Get full path to database file."""
        return self.data_dir / self.database.path

    @property
    def discord_token(self) -> str | None:
        """Get Discord token from environment."""
        return os.environ.get("DISCORD_TOKEN")

    def resolve_model_profile(self, name: str) -> ModelProfile:
        """Resolve a model profile by name.

        Args:
            name: Profile name to resolve.

        Returns:
            The resolved ModelProfile.

        Raises:
            ValueError: If models config is not set or profile not found.
        """
        if self.models is None:
            raise ValueError("Models configuration not set")
        return self.models.resolve_profile(name)

    def get_server_config(self, server_id: str) -> ServerOverrideConfig:
        """Get configuration for a specific server.

        Args:
            server_id: Discord server ID.

        Returns:
            Server-specific config, or defaults if not configured.
        """
        return self.servers.get(server_id, ServerOverrideConfig())

    @classmethod
    def load(cls, config_path: Path | str = Path("config.yaml")) -> "Config":
        """Load configuration from YAML file with env var overlay.

        Args:
            config_path: Path to YAML configuration file.

        Returns:
            Validated Config instance.

        Raises:
            FileNotFoundError: If config file doesn't exist.
            ValueError: If config is invalid.
        """
        config_path = Path(config_path)

        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(config_path) as f:
            yaml_config = yaml.safe_load(f) or {}

        # Environment variable overrides
        if "ZOS_DATA_DIR" in os.environ:
            yaml_config["data_dir"] = os.environ["ZOS_DATA_DIR"]
        if "ZOS_LOG_LEVEL" in os.environ:
            yaml_config["log_level"] = os.environ["ZOS_LOG_LEVEL"]
        if "ZOS_LOG_JSON" in os.environ:
            yaml_config["log_json"] = os.environ["ZOS_LOG_JSON"].lower() == "true"

        return cls.model_validate(yaml_config)

    @classmethod
    def load_or_default(cls, config_path: Path | str | None = None) -> "Config":
        """Load configuration, falling back to defaults if file not found.

        Args:
            config_path: Optional path to YAML configuration file.

        Returns:
            Config instance (from file or defaults).
        """
        if config_path is None:
            # Try default locations
            for path in [Path("config.yaml"), Path("config.yml")]:
                if path.exists():
                    return cls.load(path)
            # Return defaults
            return cls()

        try:
            return cls.load(config_path)
        except FileNotFoundError:
            return cls()
