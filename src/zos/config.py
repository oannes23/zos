"""Configuration system for Zos."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from zos.llm.config import LLMConfig


class DiscordConfig(BaseModel):
    """Discord connection configuration."""

    token: str = Field(default="", description="Discord bot token (use env var)")
    guilds: list[int] = Field(
        default_factory=list,
        description="Guild IDs to watch (empty = all guilds bot is in)",
    )
    excluded_channels: list[int] = Field(
        default_factory=list,
        description="Channel IDs to exclude from observation (opt-out)",
    )
    output_channels: list[int] = Field(
        default_factory=list,
        description="Channel IDs where Zos can speak",
    )
    tracking_opt_in_role: str | None = Field(
        default=None,
        description="Role name required for user tracking (zero salience without)",
    )


class DatabaseConfig(BaseModel):
    """Database configuration."""

    path: Path = Field(default=Path("data/zos.db"), description="SQLite database path")

    @field_validator("path", mode="before")
    @classmethod
    def expand_path(cls, v: str | Path) -> Path:
        """Expand path and ensure it's a Path object."""
        if isinstance(v, str):
            return Path(v).expanduser()
        return v


class CategoryWeights(BaseModel):
    """Salience budget weights per topic category."""

    user: int = Field(default=40, ge=0)
    channel: int = Field(default=40, ge=0)
    user_in_channel: int = Field(default=15, ge=0)
    dyad: int = Field(default=5, ge=0)
    dyad_in_channel: int = Field(default=0, ge=0)

    def get_weight(self, category: str) -> int:
        """Get weight for a category by name.

        Args:
            category: Category name (user, channel, etc.) or TopicCategory value.

        Returns:
            The weight for that category, or 0 if not found.
        """
        # Handle TopicCategory enum or string
        if hasattr(category, "value"):
            category = category.value
        return getattr(self, category, 0)


class BudgetConfig(BaseModel):
    """Budget allocation configuration."""

    total_tokens_per_run: int = Field(
        default=100000, description="Total token budget per reflection run"
    )
    per_topic_cap: int = Field(default=10000, description="Max tokens per individual topic")
    category_weights: CategoryWeights = Field(default_factory=CategoryWeights)


class EarningWeights(BaseModel):
    """Weights for salience earning per activity type."""

    message: float = Field(default=1.0, ge=0, description="Points per message")
    reaction_given: float = Field(
        default=0.5, ge=0, description="Points for giving a reaction"
    )
    reaction_received: float = Field(
        default=0.3, ge=0, description="Points for receiving a reaction"
    )
    mention: float = Field(
        default=0.5, ge=0, description="Bonus points for mentions/replies (added to dyad keys)"
    )


class SalienceConfig(BaseModel):
    """Salience system configuration."""

    earning_weights: EarningWeights = Field(default_factory=EarningWeights)
    retention: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Fraction of salience retained after reflection (0.0 = reset, 1.0 = keep all)",
    )


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: str = Field(default="INFO", description="Log level")
    format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log format string",
    )
    file: Path | None = Field(default=None, description="Log file path (optional)")


class ApiConfig(BaseModel):
    """Web API configuration."""

    enabled: bool = Field(
        default=False,
        description="Enable web API server alongside Discord bot",
    )
    host: str = Field(
        default="127.0.0.1",
        description="API server bind address",
    )
    port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="API server port",
    )
    cors_origins: list[str] = Field(
        default_factory=list,
        description="Allowed CORS origins (empty = no CORS)",
    )


class ZosConfig(BaseSettings):
    """Root configuration for Zos."""

    model_config = SettingsConfigDict(
        env_prefix="ZOS_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    salience: SalienceConfig = Field(default_factory=SalienceConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    llm: LLMConfig | None = Field(
        default=None, description="LLM provider configuration"
    )
    layers_dir: Path = Field(
        default=Path("layers"), description="Directory containing layer definitions"
    )
    enabled_layers: list[str] = Field(
        default_factory=list, description="List of enabled layer names"
    )
    api: ApiConfig = Field(default_factory=ApiConfig)


def load_config(config_path: Path | None = None) -> ZosConfig:
    """Load configuration from YAML file with environment variable overrides.

    Args:
        config_path: Path to config.yml file. If None, uses default locations.

    Returns:
        Validated ZosConfig instance.
    """
    config_data: dict[str, Any] = {}

    # Try to find config file
    if config_path is None:
        search_paths = [
            Path("config/config.yml"),
            Path("config.yml"),
            Path.home() / ".config" / "zos" / "config.yml",
        ]
        for path in search_paths:
            if path.exists():
                config_path = path
                break

    # Load YAML if file exists
    if config_path and config_path.exists():
        with open(config_path) as f:
            loaded = yaml.safe_load(f)
            if loaded:
                config_data = loaded

    # Create config with YAML data as defaults, env vars take precedence
    return ZosConfig(**config_data)


# Global config instance (initialized lazily)
_config: ZosConfig | None = None


def get_config() -> ZosConfig:
    """Get the global configuration instance.

    Returns:
        The global ZosConfig instance.
    """
    global _config
    if _config is None:
        _config = load_config()
    return _config


def init_config(config_path: Path | None = None) -> ZosConfig:
    """Initialize the global configuration.

    Args:
        config_path: Optional path to config file.

    Returns:
        The initialized ZosConfig instance.
    """
    global _config
    _config = load_config(config_path)
    return _config
