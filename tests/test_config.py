"""Tests for the configuration system."""

from pathlib import Path

import pytest
import yaml

from zos.config import (
    BudgetConfig,
    CategoryWeights,
    DatabaseConfig,
    DiscordConfig,
    LoggingConfig,
    ZosConfig,
    load_config,
)


class TestDiscordConfig:
    """Tests for DiscordConfig."""

    def test_defaults(self):
        config = DiscordConfig()
        assert config.token == ""
        assert config.guilds == []
        assert config.excluded_channels == []
        assert config.output_channels == []
        assert config.tracking_opt_in_role is None

    def test_custom_values(self):
        config = DiscordConfig(
            token="test-token",
            guilds=["Test Guild", "Other Guild"],
            excluded_channels=["bot-spam"],
            output_channels=["general"],
            tracking_opt_in_role="Zos Participant",
        )
        assert config.token == "test-token"
        assert config.guilds == ["Test Guild", "Other Guild"]
        assert config.excluded_channels == ["bot-spam"]
        assert config.tracking_opt_in_role == "Zos Participant"


class TestDatabaseConfig:
    """Tests for DatabaseConfig."""

    def test_defaults(self):
        config = DatabaseConfig()
        assert config.path == Path("data/zos.db")

    def test_path_expansion(self):
        config = DatabaseConfig(path="~/test.db")
        assert config.path == Path.home() / "test.db"

    def test_string_path(self):
        config = DatabaseConfig(path="custom/path/db.sqlite")
        assert config.path == Path("custom/path/db.sqlite")


class TestCategoryWeights:
    """Tests for CategoryWeights."""

    def test_defaults(self):
        weights = CategoryWeights()
        assert weights.user == 20
        assert weights.channel == 20
        assert weights.user_in_channel == 10
        assert weights.dyad == 5
        assert weights.dyad_in_channel == 5

    def test_custom_weights(self):
        weights = CategoryWeights(user=50, channel=30)
        assert weights.user == 50
        assert weights.channel == 30

    def test_negative_weight_rejected(self):
        with pytest.raises(ValueError):
            CategoryWeights(user=-1)


class TestBudgetConfig:
    """Tests for BudgetConfig."""

    def test_defaults(self):
        config = BudgetConfig()
        assert config.total_tokens_per_run == 100000
        assert config.per_topic_cap == 10000
        assert isinstance(config.category_weights, CategoryWeights)


class TestLoggingConfig:
    """Tests for LoggingConfig."""

    def test_defaults(self):
        config = LoggingConfig()
        assert config.level == "INFO"
        assert config.file is None

    def test_custom_level(self):
        config = LoggingConfig(level="DEBUG")
        assert config.level == "DEBUG"


class TestZosConfig:
    """Tests for the root ZosConfig."""

    def test_defaults(self):
        config = ZosConfig()
        assert isinstance(config.discord, DiscordConfig)
        assert isinstance(config.database, DatabaseConfig)
        assert isinstance(config.budget, BudgetConfig)
        assert isinstance(config.logging, LoggingConfig)
        assert config.layers_dir == Path("layers")
        assert config.enabled_layers == []

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("ZOS_LOGGING__LEVEL", "DEBUG")
        config = ZosConfig()
        assert config.logging.level == "DEBUG"


class TestLoadConfig:
    """Tests for config loading."""

    def test_load_from_yaml(self, temp_dir: Path):
        config_path = temp_dir / "config.yml"
        config_data = {
            "discord": {"guilds": ["Test Guild"]},
            "logging": {"level": "DEBUG"},
            "enabled_layers": ["test_layer"],
        }
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        config = load_config(config_path)
        assert config.discord.guilds == ["Test Guild"]
        assert config.logging.level == "DEBUG"
        assert config.enabled_layers == ["test_layer"]

    def test_load_missing_file(self, temp_dir: Path):
        # Should return defaults when file doesn't exist
        config = load_config(temp_dir / "nonexistent.yml")
        assert isinstance(config, ZosConfig)

    def test_env_provides_defaults(self, temp_dir: Path, monkeypatch):
        config_path = temp_dir / "config.yml"
        # YAML doesn't specify logging level
        config_data = {"discord": {"guilds": ["Test Guild"]}}
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        # Env var provides the value when YAML doesn't specify it
        monkeypatch.setenv("ZOS_LOGGING__LEVEL", "ERROR")
        config = load_config(config_path)
        assert config.logging.level == "ERROR"

    def test_yaml_takes_precedence_over_env(self, temp_dir: Path, monkeypatch):
        config_path = temp_dir / "config.yml"
        # YAML explicitly specifies logging level
        config_data = {"logging": {"level": "WARNING"}}
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        # Env var is set but YAML value takes precedence (constructor args > env)
        monkeypatch.setenv("ZOS_LOGGING__LEVEL", "ERROR")
        config = load_config(config_path)
        assert config.logging.level == "WARNING"
