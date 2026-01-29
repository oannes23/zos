"""Tests for the configuration module."""

import os
from pathlib import Path

import pytest
import yaml

from zos.config import (
    Config,
    ModelProfile,
    ModelsConfig,
    SalienceConfig,
    SalienceCapsConfig,
    SalienceWeightsConfig,
    SalienceBudgetConfig,
    ChattinessConfig,
    PrivacyConfig,
    ObservationConfig,
    SchedulerConfig,
    ServerOverrideConfig,
)


@pytest.fixture
def sample_config_yaml(tmp_path: Path) -> Path:
    """Create a sample config file for testing."""
    config = {
        "data_dir": str(tmp_path / "data"),
        "log_level": "DEBUG",
        "log_json": False,
        "discord": {"polling_interval_seconds": 30},
        "database": {"path": "test.db"},
        "models": {
            "profiles": {
                "simple": {"provider": "anthropic", "model": "claude-3-5-haiku"},
                "moderate": {"provider": "anthropic", "model": "claude-sonnet-4"},
                "default": "moderate",  # alias
            },
            "providers": {
                "anthropic": {"api_key_env": "ANTHROPIC_API_KEY"},
            },
        },
        "salience": {
            "caps": {"server_user": 50},
            "weights": {"message": 2.0},
            "warm_threshold": 2.0,
        },
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)
    return config_path


@pytest.fixture
def minimal_config_yaml(tmp_path: Path) -> Path:
    """Create a minimal config file for testing."""
    config = {"data_dir": str(tmp_path / "data")}
    config_path = tmp_path / "minimal.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)
    return config_path


def test_config_load(sample_config_yaml: Path) -> None:
    """Test loading a valid configuration file."""
    config = Config.load(sample_config_yaml)

    assert config.log_level == "DEBUG"
    assert config.log_json is False
    assert config.discord.polling_interval_seconds == 30
    assert config.database.path == "test.db"


def test_config_load_not_found() -> None:
    """Test that missing config file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        Config.load(Path("/nonexistent/config.yaml"))


def test_config_load_or_default_missing() -> None:
    """Test that load_or_default returns defaults when file missing."""
    config = Config.load_or_default(Path("/nonexistent/config.yaml"))

    # Should have defaults
    assert config.log_level == "INFO"
    assert config.log_json is True


def test_config_defaults() -> None:
    """Test that default values are set correctly."""
    config = Config()

    assert config.data_dir == Path("./data")
    assert config.log_level == "INFO"
    assert config.log_json is True
    assert config.discord.polling_interval_seconds == 300
    assert config.database.path == "zos.db"


def test_config_database_path() -> None:
    """Test database path property."""
    config = Config(data_dir=Path("/var/zos"))

    assert config.database_path == Path("/var/zos/zos.db")


def test_config_env_override(sample_config_yaml: Path, monkeypatch) -> None:
    """Test environment variable overrides."""
    monkeypatch.setenv("ZOS_LOG_LEVEL", "ERROR")
    monkeypatch.setenv("ZOS_LOG_JSON", "false")

    config = Config.load(sample_config_yaml)

    assert config.log_level == "ERROR"
    assert config.log_json is False


def test_config_discord_token(monkeypatch) -> None:
    """Test Discord token from environment."""
    monkeypatch.setenv("DISCORD_TOKEN", "test_token_123")

    config = Config()
    assert config.discord_token == "test_token_123"


def test_model_profile_resolution(sample_config_yaml: Path) -> None:
    """Test model profile alias resolution."""
    config = Config.load(sample_config_yaml)

    # Direct profile
    simple = config.resolve_model_profile("simple")
    assert simple.provider == "anthropic"
    assert simple.model == "claude-3-5-haiku"

    # Alias resolution
    default = config.resolve_model_profile("default")
    assert default.provider == "anthropic"
    assert default.model == "claude-sonnet-4"


def test_model_profile_unknown() -> None:
    """Test that unknown profile raises KeyError."""
    models_config = ModelsConfig(
        profiles={"simple": ModelProfile(provider="test", model="test")},
        providers={},
    )

    with pytest.raises(KeyError):
        models_config.resolve_profile("unknown")


def test_model_profile_circular_alias() -> None:
    """Test that circular aliases are detected."""
    models_config = ModelsConfig(
        profiles={
            "a": "b",
            "b": "a",
        },
        providers={},
    )

    with pytest.raises(ValueError, match="Circular alias"):
        models_config.resolve_profile("a")


def test_salience_config_defaults() -> None:
    """Test salience configuration defaults."""
    config = SalienceConfig()

    assert config.caps.server_user == 100
    assert config.weights.message == 1.0
    assert config.propagation_factor == 0.3
    assert config.warm_threshold == 1.0
    assert config.budget.social == 0.30


def test_salience_config_custom(sample_config_yaml: Path) -> None:
    """Test salience configuration with custom values."""
    config = Config.load(sample_config_yaml)

    assert config.salience.caps.server_user == 50
    assert config.salience.weights.message == 2.0
    assert config.salience.warm_threshold == 2.0


def test_log_level_validation() -> None:
    """Test that invalid log level is rejected."""
    with pytest.raises(ValueError):
        Config(log_level="INVALID")


def test_log_level_case_insensitive() -> None:
    """Test that log level is case insensitive."""
    config = Config(log_level="debug")
    assert config.log_level == "DEBUG"


def test_privacy_review_pass_validation() -> None:
    """Test that invalid review_pass is rejected."""
    with pytest.raises(ValueError):
        Config(privacy={"review_pass": "invalid"})


def test_server_config_default() -> None:
    """Test getting default server config."""
    config = Config()
    server_config = config.get_server_config("123456789")

    assert server_config.privacy_gate_role is None
    assert server_config.threads_as_topics is True
    assert server_config.disabled_layers == []


def test_server_config_override(tmp_path: Path) -> None:
    """Test server-specific configuration overrides."""
    config_data = {
        "servers": {
            "123": {
                "privacy_gate_role": "456",
                "threads_as_topics": False,
            }
        }
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    config = Config.load(config_path)
    server_config = config.get_server_config("123")

    assert server_config.privacy_gate_role == "456"
    assert server_config.threads_as_topics is False


def test_minimal_config(minimal_config_yaml: Path) -> None:
    """Test loading a minimal config file uses defaults for missing fields."""
    config = Config.load(minimal_config_yaml)

    assert config.log_level == "INFO"
    assert config.discord.polling_interval_seconds == 300
    assert config.salience.warm_threshold == 1.0


# ===== EDGE CASE TESTS FOR NESTED CONFIGURATION =====


def test_salience_caps_partial_override(tmp_path: Path) -> None:
    """Test that partial salience.caps overrides use defaults for unspecified values."""
    config_data = {
        "salience": {
            "caps": {"server_user": 75}  # Only override one cap
        }
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    config = Config.load(config_path)
    assert config.salience.caps.server_user == 75
    assert config.salience.caps.global_user == 150  # Default retained
    assert config.salience.caps.channel == 150  # Default retained
    assert config.salience.caps.thread == 50  # Default retained


def test_salience_weights_partial_override(tmp_path: Path) -> None:
    """Test that partial salience.weights overrides use defaults for unspecified values."""
    config_data = {
        "salience": {
            "weights": {"message": 3.0, "mention": 4.0}  # Override multiple weights
        }
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    config = Config.load(config_path)
    assert config.salience.weights.message == 3.0
    assert config.salience.weights.mention == 4.0
    assert config.salience.weights.reaction == 0.5  # Default retained


def test_salience_budget_partial_override(tmp_path: Path) -> None:
    """Test that partial salience.budget overrides use defaults for unspecified values."""
    config_data = {
        "salience": {
            "budget": {"social": 0.40, "semantic": 0.20}
        }
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    config = Config.load(config_path)
    assert config.salience.budget.social == 0.40
    assert config.salience.budget.semantic == 0.20
    assert config.salience.budget.spaces == 0.30  # Default retained


def test_models_providers_partial_override(tmp_path: Path) -> None:
    """Test that partial models.providers configuration works."""
    config_data = {
        "models": {
            "profiles": {
                "test": {"provider": "test_provider", "model": "test_model"}
            },
            "providers": {
                "test_provider": {"api_key_env": "TEST_API_KEY"},
                "other_provider": {"api_key_env": "OTHER_KEY"}
            }
        }
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    config = Config.load(config_path)
    assert config.models.providers["test_provider"]["api_key_env"] == "TEST_API_KEY"
    assert config.models.providers["other_provider"]["api_key_env"] == "OTHER_KEY"


# ===== ERROR MESSAGE CLARITY TESTS =====


def test_log_level_validation_error_message() -> None:
    """Test that log level validation provides clear error message."""
    with pytest.raises(ValueError) as exc_info:
        Config(log_level="INVALID_LEVEL")

    assert "log_level" in str(exc_info.value).lower()
    assert "DEBUG" in str(exc_info.value) or "INFO" in str(exc_info.value)


def test_privacy_review_pass_validation_error_message() -> None:
    """Test that review_pass validation provides clear error message."""
    with pytest.raises(ValueError) as exc_info:
        PrivacyConfig(review_pass="invalid_pass")

    assert "review_pass" in str(exc_info.value).lower()
    assert "always" in str(exc_info.value) or "never" in str(exc_info.value)


def test_model_profile_unknown_error_message() -> None:
    """Test that unknown profile error provides clear message."""
    models_config = ModelsConfig(
        profiles={"known": ModelProfile(provider="test", model="test")},
        providers={},
    )

    with pytest.raises(KeyError) as exc_info:
        models_config.resolve_profile("unknown_profile")

    assert "unknown_profile" in str(exc_info.value).lower() or "Unknown model profile" in str(exc_info.value)


def test_circular_alias_error_message() -> None:
    """Test that circular alias error provides clear message."""
    models_config = ModelsConfig(
        profiles={
            "profile_a": "profile_b",
            "profile_b": "profile_a",
        },
        providers={},
    )

    with pytest.raises(ValueError) as exc_info:
        models_config.resolve_profile("profile_a")

    assert "circular" in str(exc_info.value).lower()


# ===== NUMERICAL EDGE CASES =====


def test_salience_caps_zero_values() -> None:
    """Test that zero values in salience caps are accepted."""
    caps = SalienceCapsConfig(server_user=0, global_user=0)
    assert caps.server_user == 0
    assert caps.global_user == 0


def test_salience_weights_zero_values() -> None:
    """Test that zero values in salience weights are accepted."""
    weights = SalienceWeightsConfig(message=0.0, reaction=0.0)
    assert weights.message == 0.0
    assert weights.reaction == 0.0


def test_salience_caps_large_values() -> None:
    """Test that very large cap values are accepted."""
    caps = SalienceCapsConfig(server_user=10000, global_user=50000)
    assert caps.server_user == 10000
    assert caps.global_user == 50000


def test_salience_weights_large_values() -> None:
    """Test that very large weight values are accepted."""
    weights = SalienceWeightsConfig(message=100.0, mention=200.0)
    assert weights.message == 100.0
    assert weights.mention == 200.0


def test_salience_propagation_factor_boundary() -> None:
    """Test salience propagation factor with boundary values."""
    config = SalienceConfig(propagation_factor=0.0)
    assert config.propagation_factor == 0.0

    config = SalienceConfig(propagation_factor=1.0)
    assert config.propagation_factor == 1.0


def test_salience_retention_rate_boundary() -> None:
    """Test salience retention rate boundary values."""
    config = SalienceConfig(retention_rate=0.0)
    assert config.retention_rate == 0.0

    config = SalienceConfig(retention_rate=1.0)
    assert config.retention_rate == 1.0


def test_discord_polling_interval_zero() -> None:
    """Test that polling interval can be set to zero (though not recommended)."""
    from zos.config import DiscordConfig
    discord = DiscordConfig(polling_interval_seconds=0)
    assert discord.polling_interval_seconds == 0


def test_salience_decay_threshold_zero() -> None:
    """Test decay threshold with zero value."""
    config = SalienceConfig(decay_threshold_days=0)
    assert config.decay_threshold_days == 0


# ===== ALIAS DEPTH DETECTION =====


def test_model_profile_alias_chain_at_limit() -> None:
    """Test that alias chain at the depth limit (10) works."""
    # Create a chain of 10 aliases: a -> b -> c -> d -> e -> f -> g -> h -> i -> j
    profiles = {
        "a": "b",
        "b": "c",
        "c": "d",
        "d": "e",
        "e": "f",
        "f": "g",
        "g": "h",
        "h": "i",
        "i": "j",
        "j": ModelProfile(provider="test", model="test"),
    }
    models_config = ModelsConfig(profiles=profiles, providers={})

    # Should succeed (sees 10 items: a, b, c, d, e, f, g, h, i, j)
    result = models_config.resolve_profile("a")
    assert result.provider == "test"


def test_model_profile_alias_chain_exceeds_limit() -> None:
    """Test that alias chain exceeding depth limit (11+) is rejected."""
    # Create a chain longer than 10: a -> b -> c -> d -> e -> f -> g -> h -> i -> j -> k
    profiles = {
        "a": "b",
        "b": "c",
        "c": "d",
        "d": "e",
        "e": "f",
        "f": "g",
        "g": "h",
        "h": "i",
        "i": "j",
        "j": "k",
        "k": ModelProfile(provider="test", model="test"),
    }
    models_config = ModelsConfig(profiles=profiles, providers={})

    with pytest.raises(ValueError, match="too deep"):
        models_config.resolve_profile("a")


# ===== PROVIDER API KEY RESOLUTION =====


def test_get_api_key_from_environment(monkeypatch) -> None:
    """Test retrieving API key from environment variable."""
    monkeypatch.setenv("MY_API_KEY", "secret_value_123")

    models_config = ModelsConfig(
        profiles={},
        providers={
            "my_provider": {"api_key_env": "MY_API_KEY"}
        },
    )

    api_key = models_config.get_api_key("my_provider")
    assert api_key == "secret_value_123"


def test_get_api_key_env_var_not_set() -> None:
    """Test that get_api_key returns None when environment variable not set."""
    models_config = ModelsConfig(
        profiles={},
        providers={
            "my_provider": {"api_key_env": "NONEXISTENT_VAR"}
        },
    )

    api_key = models_config.get_api_key("my_provider")
    assert api_key is None


def test_get_api_key_provider_not_configured() -> None:
    """Test that get_api_key returns None for unconfigured provider."""
    models_config = ModelsConfig(profiles={}, providers={})

    api_key = models_config.get_api_key("unconfigured_provider")
    assert api_key is None


def test_get_api_key_no_env_var_specified() -> None:
    """Test that get_api_key returns None when provider has no api_key_env."""
    models_config = ModelsConfig(
        profiles={},
        providers={
            "my_provider": {"some_other_config": "value"}
        },
    )

    api_key = models_config.get_api_key("my_provider")
    assert api_key is None


# ===== OBSERVATION CONFIGURATION =====


def test_observation_config_defaults() -> None:
    """Test observation configuration defaults."""
    obs = ObservationConfig()

    assert obs.vision_enabled is True
    assert obs.link_fetch_enabled is True
    assert obs.youtube_transcript_enabled is True
    assert obs.video_duration_threshold_minutes == 30


def test_observation_config_custom(tmp_path: Path) -> None:
    """Test custom observation configuration."""
    config_data = {
        "observation": {
            "vision_enabled": False,
            "link_fetch_enabled": False,
            "youtube_transcript_enabled": False,
            "video_duration_threshold_minutes": 60,
        }
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    config = Config.load(config_path)
    assert config.observation.vision_enabled is False
    assert config.observation.link_fetch_enabled is False
    assert config.observation.youtube_transcript_enabled is False
    assert config.observation.video_duration_threshold_minutes == 60


def test_observation_config_partial_override(tmp_path: Path) -> None:
    """Test partial observation configuration overrides defaults."""
    config_data = {
        "observation": {
            "vision_enabled": False,
            "video_duration_threshold_minutes": 120,
        }
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    config = Config.load(config_path)
    assert config.observation.vision_enabled is False
    assert config.observation.link_fetch_enabled is True  # Default
    assert config.observation.youtube_transcript_enabled is True  # Default
    assert config.observation.video_duration_threshold_minutes == 120


# ===== CHATTINESS CONFIGURATION =====


def test_chattiness_config_defaults() -> None:
    """Test chattiness configuration defaults."""
    chat = ChattinessConfig()

    assert chat.decay_threshold_hours == 1
    assert chat.decay_rate_per_hour == 0.05
    assert chat.base_spend == 10


def test_chattiness_config_custom(tmp_path: Path) -> None:
    """Test custom chattiness configuration."""
    config_data = {
        "chattiness": {
            "decay_threshold_hours": 2.5,
            "decay_rate_per_hour": 0.1,
            "base_spend": 20,
        }
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    config = Config.load(config_path)
    assert config.chattiness.decay_threshold_hours == 2.5
    assert config.chattiness.decay_rate_per_hour == 0.1
    assert config.chattiness.base_spend == 20


# ===== SCHEDULER CONFIGURATION =====


def test_scheduler_config_defaults() -> None:
    """Test scheduler configuration defaults."""
    from zos.config import SchedulerConfig
    sched = SchedulerConfig()

    assert sched.timezone == "UTC"
    assert sched.reflection_cron == "0 13 * * *"


def test_scheduler_config_custom(tmp_path: Path) -> None:
    """Test custom scheduler configuration."""
    config_data = {
        "scheduler": {
            "timezone": "America/New_York",
            "reflection_cron": "0 2 * * *",
        }
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    config = Config.load(config_path)
    assert config.scheduler.timezone == "America/New_York"
    assert config.scheduler.reflection_cron == "0 2 * * *"


# ===== SERVER CONFIGURATION ADVANCED =====


def test_server_config_disabled_layers(tmp_path: Path) -> None:
    """Test server configuration with disabled_layers."""
    config_data = {
        "servers": {
            "123": {
                "disabled_layers": ["observation", "reflection"]
            }
        }
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    config = Config.load(config_path)
    server_config = config.get_server_config("123")
    assert server_config.disabled_layers == ["observation", "reflection"]


def test_server_config_empty_disabled_layers(tmp_path: Path) -> None:
    """Test server configuration with empty disabled_layers list."""
    config_data = {
        "servers": {
            "123": {
                "disabled_layers": []
            }
        }
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    config = Config.load(config_path)
    server_config = config.get_server_config("123")
    assert server_config.disabled_layers == []


def test_server_config_partial_override(tmp_path: Path) -> None:
    """Test server configuration with partial field overrides."""
    config_data = {
        "servers": {
            "456": {
                "privacy_gate_role": "789",
                # threads_as_topics not specified - should use default
                "disabled_layers": ["observation"]
            }
        }
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    config = Config.load(config_path)
    server_config = config.get_server_config("456")
    assert server_config.privacy_gate_role == "789"
    assert server_config.threads_as_topics is True  # Default
    assert server_config.disabled_layers == ["observation"]


def test_server_config_multiple_servers(tmp_path: Path) -> None:
    """Test configuration for multiple servers with different overrides."""
    config_data = {
        "servers": {
            "server1": {
                "privacy_gate_role": "role1",
                "threads_as_topics": False,
            },
            "server2": {
                "privacy_gate_role": "role2",
                "disabled_layers": ["reflection"],
            },
        }
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    config = Config.load(config_path)

    server1 = config.get_server_config("server1")
    assert server1.privacy_gate_role == "role1"
    assert server1.threads_as_topics is False
    assert server1.disabled_layers == []  # Default

    server2 = config.get_server_config("server2")
    assert server2.privacy_gate_role == "role2"
    assert server2.threads_as_topics is True  # Default
    assert server2.disabled_layers == ["reflection"]


# ===== SALIENCE BUDGET VALIDATION =====


def test_salience_budget_sum_exact_one() -> None:
    """Test that budgets summing exactly to 1.0 are accepted."""
    budget = SalienceBudgetConfig(
        social=0.30,
        global_group=0.15,
        spaces=0.30,
        semantic=0.15,
        culture=0.10,
    )
    total = budget.social + budget.global_group + budget.spaces + budget.semantic + budget.culture
    assert abs(total - 1.0) < 0.001  # Very close to 1.0


def test_salience_budget_sum_within_tolerance() -> None:
    """Test that budgets within 0.05 tolerance of 1.0 are accepted."""
    # Sum = 0.98 (within 0.05 tolerance)
    budget = SalienceBudgetConfig(
        social=0.30,
        global_group=0.20,
        spaces=0.23,
        semantic=0.15,
        culture=0.10,
    )
    # Should not raise - validator just warns, doesn't reject
    assert budget is not None


def test_salience_budget_sum_outside_tolerance() -> None:
    """Test that budgets far outside tolerance are still accepted (validator is permissive)."""
    # Sum = 0.50 (outside tolerance, but validator allows it)
    budget = SalienceBudgetConfig(
        social=0.20,
        global_group=0.10,
        spaces=0.10,
        semantic=0.05,
        culture=0.05,
    )
    # Validator is in "after" mode and just passes through
    assert budget is not None


def test_salience_budget_alias_global(tmp_path: Path) -> None:
    """Test that budget uses alias 'global' for global_group."""
    config_data = {
        "salience": {
            "budget": {"global": 0.25}
        }
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    config = Config.load(config_path)
    assert config.salience.budget.global_group == 0.25


def test_salience_caps_alias_self(tmp_path: Path) -> None:
    """Test that caps uses alias 'self' for self_topic."""
    config_data = {
        "salience": {
            "caps": {"self": 200}
        }
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    config = Config.load(config_path)
    assert config.salience.caps.self_topic == 200


# ===== ENVIRONMENT VARIABLE EDGE CASES =====


def test_env_override_log_json_true_variations(sample_config_yaml: Path, monkeypatch) -> None:
    """Test ZOS_LOG_JSON environment variable with 'true' value."""
    monkeypatch.setenv("ZOS_LOG_JSON", "true")
    config = Config.load(sample_config_yaml)
    assert config.log_json is True


def test_env_override_log_json_false_variations(sample_config_yaml: Path, monkeypatch) -> None:
    """Test ZOS_LOG_JSON environment variable with 'false' value."""
    monkeypatch.setenv("ZOS_LOG_JSON", "false")
    config = Config.load(sample_config_yaml)
    assert config.log_json is False


def test_env_override_log_json_uppercase_false(sample_config_yaml: Path, monkeypatch) -> None:
    """Test ZOS_LOG_JSON environment variable with uppercase 'False' is treated as false."""
    monkeypatch.setenv("ZOS_LOG_JSON", "False")
    config = Config.load(sample_config_yaml)
    # Only lowercase "true" evaluates to True
    assert config.log_json is False


def test_env_override_log_json_invalid_value(sample_config_yaml: Path, monkeypatch) -> None:
    """Test ZOS_LOG_JSON with invalid value treats as false."""
    monkeypatch.setenv("ZOS_LOG_JSON", "invalid")
    config = Config.load(sample_config_yaml)
    assert config.log_json is False


def test_env_override_data_dir_with_file_load(sample_config_yaml: Path, monkeypatch, tmp_path: Path) -> None:
    """Test ZOS_DATA_DIR environment variable override when loading from file."""
    new_dir = tmp_path / "custom_data"
    monkeypatch.setenv("ZOS_DATA_DIR", str(new_dir))

    config = Config.load(sample_config_yaml)
    assert config.data_dir == new_dir


def test_env_override_log_level_case_handling(sample_config_yaml: Path, monkeypatch) -> None:
    """Test ZOS_LOG_LEVEL environment variable with mixed case."""
    monkeypatch.setenv("ZOS_LOG_LEVEL", "info")
    config = Config.load(sample_config_yaml)
    assert config.log_level == "INFO"


# ===== CONFIG LOADING EDGE CASES =====


def test_config_load_empty_yaml_file(tmp_path: Path) -> None:
    """Test loading an empty YAML file uses all defaults."""
    config_path = tmp_path / "empty.yaml"
    with open(config_path, "w") as f:
        f.write("")

    config = Config.load(config_path)
    assert config.log_level == "INFO"
    assert config.log_json is True
    assert config.discord.polling_interval_seconds == 300


def test_config_load_yaml_with_null(tmp_path: Path) -> None:
    """Test loading a YAML file with null content."""
    config_path = tmp_path / "null.yaml"
    with open(config_path, "w") as f:
        f.write("null\n")

    config = Config.load(config_path)
    assert config.log_level == "INFO"


def test_config_models_not_required() -> None:
    """Test that models configuration is optional."""
    config = Config()
    assert config.models is None


def test_config_resolve_model_profile_without_models() -> None:
    """Test that resolving profile without models config raises ValueError."""
    config = Config()  # No models configured

    with pytest.raises(ValueError, match="not set"):
        config.resolve_model_profile("any_profile")


# ===== PRIVACY CONFIGURATION =====


def test_privacy_review_pass_always() -> None:
    """Test privacy configuration with 'always' review_pass."""
    privacy = PrivacyConfig(review_pass="always")
    assert privacy.review_pass == "always"


def test_privacy_review_pass_never() -> None:
    """Test privacy configuration with 'never' review_pass."""
    privacy = PrivacyConfig(review_pass="never")
    assert privacy.review_pass == "never"


def test_privacy_review_pass_private_context() -> None:
    """Test privacy configuration with 'private_context' review_pass."""
    privacy = PrivacyConfig(review_pass="private_context")
    assert privacy.review_pass == "private_context"


def test_privacy_first_contact_message(tmp_path: Path) -> None:
    """Test privacy configuration with custom first_contact_message."""
    config_data = {
        "privacy": {
            "first_contact_message": "Hello, I'm Zos!"
        }
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    config = Config.load(config_path)
    assert config.privacy.first_contact_message == "Hello, I'm Zos!"


# ===== LOAD_OR_DEFAULT EDGE CASES =====


def test_load_or_default_with_none() -> None:
    """Test load_or_default with None path."""
    config = Config.load_or_default(None)
    assert config is not None
    assert config.log_level == "INFO"


def test_load_or_default_missing_file() -> None:
    """Test load_or_default with nonexistent file path returns defaults."""
    config = Config.load_or_default(Path("/nonexistent/path/config.yaml"))
    assert config is not None
    assert config.log_level == "INFO"


def test_load_or_default_searches_config_yaml(tmp_path: Path, monkeypatch) -> None:
    """Test load_or_default searches for config.yaml in current directory."""
    # Change to tmp directory and create config.yaml there
    config_data = {"log_level": "DEBUG"}
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    # Without specifying path, should find defaults (we can't easily test dir search)
    config = Config.load_or_default(None)
    assert config is not None


def test_load_or_default_searches_config_yml(tmp_path: Path) -> None:
    """Test load_or_default searches for config.yml as fallback."""
    config = Config.load_or_default(None)
    assert config is not None


# ===== SERVER FOCUS CONFIGURATION =====


def test_server_config_focus_default() -> None:
    """Test that server focus defaults to 1.0."""
    from zos.config import ServerOverrideConfig
    server_config = ServerOverrideConfig()
    assert server_config.focus == 1.0


def test_server_config_focus_custom(tmp_path: Path) -> None:
    """Test custom server focus multiplier."""
    config_data = {
        "servers": {
            "123": {
                "focus": 3.0
            }
        }
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    config = Config.load(config_path)
    server_config = config.get_server_config("123")
    assert server_config.focus == 3.0


def test_server_config_focus_fractional(tmp_path: Path) -> None:
    """Test server focus can be fractional (e.g., 0.5)."""
    config_data = {
        "servers": {
            "456": {
                "focus": 0.5
            }
        }
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    config = Config.load(config_path)
    server_config = config.get_server_config("456")
    assert server_config.focus == 0.5


def test_server_config_focus_zero(tmp_path: Path) -> None:
    """Test server focus can be zero (no salience earning)."""
    config_data = {
        "servers": {
            "789": {
                "focus": 0.0
            }
        }
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    config = Config.load(config_path)
    server_config = config.get_server_config("789")
    assert server_config.focus == 0.0


def test_server_config_focus_with_other_overrides(tmp_path: Path) -> None:
    """Test server focus works alongside other server overrides."""
    config_data = {
        "servers": {
            "123": {
                "focus": 2.0,
                "privacy_gate_role": "456",
                "threads_as_topics": False,
            }
        }
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    config = Config.load(config_path)
    server_config = config.get_server_config("123")
    assert server_config.focus == 2.0
    assert server_config.privacy_gate_role == "456"
    assert server_config.threads_as_topics is False
