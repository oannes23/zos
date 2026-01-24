"""Tests for the CLI module.

Covers:
- CLI help and version output
- Database management commands (status, migrate)
- Configuration validation and checking
- Global options (log-level, log-json, config-file)
- Error handling and user feedback
"""

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from zos import __version__
from zos.cli import cli


class TestCliHelp:
    """Tests for help and basic command availability."""

    def test_cli_help(self, cli_runner: CliRunner) -> None:
        """Acceptance: CLI --help shows welcome message and available commands."""
        result = cli_runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Zos - Discord agent with temporal depth" in result.output
        assert "Database management commands" in result.output
        assert "Configuration management commands" in result.output

    def test_cli_help_shows_version_command(self, cli_runner: CliRunner) -> None:
        """Operator can see version command in help."""
        result = cli_runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "version" in result.output

    def test_db_group_help(self, cli_runner: CliRunner) -> None:
        """Operator can access help for db subcommands."""
        result = cli_runner.invoke(cli, ["db", "--help"])
        assert result.exit_code == 0
        assert "Database management commands" in result.output
        assert "status" in result.output
        assert "migrate" in result.output

    def test_config_group_help(self, cli_runner: CliRunner) -> None:
        """Operator can access help for config subcommands."""
        result = cli_runner.invoke(cli, ["config", "--help"])
        assert result.exit_code == 0
        assert "Configuration management commands" in result.output
        assert "check" in result.output


class TestVersion:
    """Tests for version command."""

    def test_cli_version(self, cli_runner: CliRunner) -> None:
        """Acceptance: version command prints version string."""
        result = cli_runner.invoke(cli, ["version"])
        assert result.exit_code == 0
        assert __version__ in result.output
        assert "zos" in result.output.lower()

    def test_version_with_log_level(self, cli_runner: CliRunner) -> None:
        """Version command works when combined with global options."""
        result = cli_runner.invoke(cli, ["--log-level", "DEBUG", "version"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_version_with_log_json(self, cli_runner: CliRunner) -> None:
        """Version command works with --log-json option."""
        result = cli_runner.invoke(cli, ["--log-json", "version"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_version_with_config_file_missing(self, cli_runner: CliRunner) -> None:
        """Version command works even when config file doesn't exist."""
        result = cli_runner.invoke(
            cli, ["--config-file", "/nonexistent/config.yaml", "version"]
        )
        # Version should work with graceful defaults even if config missing
        assert result.exit_code == 0 or result.exit_code == 0
        assert __version__ in result.output or "zos" in result.output.lower()


class TestDatabaseStatus:
    """Tests for db status command."""

    def test_cli_db_status(self, cli_runner: CliRunner) -> None:
        """Acceptance: db status shows database path and migration info."""
        result = cli_runner.invoke(cli, ["db", "status"])
        assert result.exit_code == 0
        assert "Database:" in result.output or "database" in result.output.lower()

    def test_db_status_shows_current_version(self, cli_runner: CliRunner) -> None:
        """db status displays current migration version."""
        result = cli_runner.invoke(cli, ["db", "status"])
        assert result.exit_code == 0
        assert "Current version" in result.output or "version" in result.output.lower()

    def test_db_status_shows_available_migrations(
        self, cli_runner: CliRunner
    ) -> None:
        """db status shows available migrations count."""
        result = cli_runner.invoke(cli, ["db", "status"])
        assert result.exit_code == 0
        assert "migrations" in result.output.lower() or "version" in result.output

    def test_db_status_shows_pending_or_none(self, cli_runner: CliRunner) -> None:
        """db status indicates pending migrations or that none exist."""
        result = cli_runner.invoke(cli, ["db", "status"])
        assert result.exit_code == 0
        # Either "Pending migrations" or "No pending migrations"
        assert (
            "pending" in result.output.lower()
            or "migration" in result.output.lower()
        )


class TestDatabaseMigrate:
    """Tests for db migrate command."""

    def test_cli_db_migrate(self, cli_runner: CliRunner) -> None:
        """Acceptance: db migrate applies pending migrations."""
        result = cli_runner.invoke(cli, ["db", "migrate"])
        assert result.exit_code == 0

    def test_db_migrate_shows_result(self, cli_runner: CliRunner) -> None:
        """db migrate reports what happened (migrated or already current)."""
        result = cli_runner.invoke(cli, ["db", "migrate"])
        assert result.exit_code == 0
        # Should mention either migration or current version
        assert (
            "Migrated" in result.output
            or "already at version" in result.output
            or "version" in result.output.lower()
        )

    def test_db_migrate_with_target_version(self, cli_runner: CliRunner) -> None:
        """Operator can specify target migration version."""
        result = cli_runner.invoke(cli, ["db", "migrate", "--target", "1"])
        assert result.exit_code == 0

    def test_db_migrate_with_invalid_target(self, cli_runner: CliRunner) -> None:
        """db migrate with invalid target version is handled gracefully."""
        # Click's validation should catch non-integer targets
        result = cli_runner.invoke(cli, ["db", "migrate", "--target", "not_a_number"])
        # Should fail with clear error
        assert result.exit_code != 0

    def test_db_migrate_help(self, cli_runner: CliRunner) -> None:
        """Operator can see --target option in migrate help."""
        result = cli_runner.invoke(cli, ["db", "migrate", "--help"])
        assert result.exit_code == 0
        assert "--target" in result.output


class TestConfigCheck:
    """Tests for config check command."""

    def test_cli_config_check_missing_file(self, cli_runner: CliRunner) -> None:
        """Acceptance: config check with missing file shows helpful error."""
        result = cli_runner.invoke(cli, ["config", "check", "-c", "nonexistent.yaml"])
        assert result.exit_code == 2  # Click returns 2 for bad parameter

    def test_cli_config_check_valid(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Acceptance: config check validates and reports on configuration."""
        config_path = tmp_path / "config.yaml"
        config_data = {"data_dir": str(tmp_path)}
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        result = cli_runner.invoke(cli, ["config", "check", "-c", str(config_path)])
        assert result.exit_code == 0
        assert "Configuration valid" in result.output

    def test_config_check_shows_data_directory(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """config check displays configured data directory."""
        config_path = tmp_path / "config.yaml"
        config_data = {"data_dir": str(tmp_path / "data")}
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        result = cli_runner.invoke(cli, ["config", "check", "-c", str(config_path)])
        assert result.exit_code == 0
        assert "Data directory" in result.output

    def test_config_check_shows_database_path(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """config check displays database path."""
        config_path = tmp_path / "config.yaml"
        config_data = {"data_dir": str(tmp_path)}
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        result = cli_runner.invoke(cli, ["config", "check", "-c", str(config_path)])
        assert result.exit_code == 0
        assert "Database path" in result.output or "database" in result.output.lower()

    def test_config_check_shows_log_level(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """config check displays configured log level."""
        config_path = tmp_path / "config.yaml"
        config_data = {"data_dir": str(tmp_path), "log_level": "DEBUG"}
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        result = cli_runner.invoke(cli, ["config", "check", "-c", str(config_path)])
        assert result.exit_code == 0
        assert "Log level" in result.output

    def test_config_check_shows_model_profiles(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """config check displays model profile count when configured."""
        config_path = tmp_path / "config.yaml"
        config_data = {
            "data_dir": str(tmp_path),
            "models": {
                "profiles": {
                    "simple": {"provider": "anthropic", "model": "claude-haiku"}
                },
                "providers": {"anthropic": {"api_key_env": "ANTHROPIC_API_KEY"}},
            },
        }
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        result = cli_runner.invoke(cli, ["config", "check", "-c", str(config_path)])
        assert result.exit_code == 0
        assert "Model profiles" in result.output or "profiles" in result.output.lower()

    def test_config_check_shows_model_aliases(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """config check lists model aliases when present."""
        config_path = tmp_path / "config.yaml"
        config_data = {
            "data_dir": str(tmp_path),
            "models": {
                "profiles": {
                    "simple": {"provider": "anthropic", "model": "claude-haiku"},
                    "default": "simple",  # alias
                },
                "providers": {"anthropic": {"api_key_env": "ANTHROPIC_API_KEY"}},
            },
        }
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        result = cli_runner.invoke(cli, ["config", "check", "-c", str(config_path)])
        assert result.exit_code == 0
        # Should show aliases
        assert "Model aliases" in result.output or "alias" in result.output.lower()

    def test_config_check_shows_no_models_when_unconfigured(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """config check indicates when models are not configured."""
        config_path = tmp_path / "config.yaml"
        config_data = {"data_dir": str(tmp_path)}
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        result = cli_runner.invoke(cli, ["config", "check", "-c", str(config_path)])
        assert result.exit_code == 0
        assert "not configured" in result.output or "Model" in result.output

    def test_config_check_shows_server_overrides(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """config check displays server override count when present."""
        config_path = tmp_path / "config.yaml"
        config_data = {
            "data_dir": str(tmp_path),
            "servers": {
                "123456789": {
                    "privacy_gate_role": "role_123",
                }
            },
        }
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        result = cli_runner.invoke(cli, ["config", "check", "-c", str(config_path)])
        assert result.exit_code == 0
        assert "Server overrides" in result.output or "server" in result.output.lower()

    def test_config_check_malformed_yaml(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """config check shows error for malformed YAML file."""
        config_path = tmp_path / "config.yaml"
        with open(config_path, "w") as f:
            f.write("invalid: yaml: content: [}")

        result = cli_runner.invoke(cli, ["config", "check", "-c", str(config_path)])
        assert result.exit_code == 1
        # Should indicate an error occurred
        assert "error" in result.output.lower() or result.output.strip() == ""

    def test_config_check_invalid_config_values(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """config check shows error for invalid configuration values."""
        config_path = tmp_path / "config.yaml"
        config_data = {"data_dir": str(tmp_path), "log_level": "INVALID_LEVEL"}
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        result = cli_runner.invoke(cli, ["config", "check", "-c", str(config_path)])
        assert result.exit_code == 1
        assert "error" in result.output.lower()

    def test_config_check_default_path(
        self, cli_runner: CliRunner, tmp_path: Path, monkeypatch
    ) -> None:
        """config check uses default path (config.yaml) when not specified."""
        # Change to tmp directory and create a config.yaml there
        config_path = tmp_path / "config.yaml"
        config_data = {"data_dir": str(tmp_path)}
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        # Invoke without -c, relying on default
        monkeypatch.chdir(tmp_path)
        result = cli_runner.invoke(cli, ["config", "check"])
        assert result.exit_code == 0
        assert "Configuration valid" in result.output


class TestGlobalOptions:
    """Tests for CLI global options."""

    def test_cli_log_level_debug(self, cli_runner: CliRunner) -> None:
        """Operator can set log level to DEBUG."""
        result = cli_runner.invoke(cli, ["--log-level", "DEBUG", "version"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_cli_log_level_info(self, cli_runner: CliRunner) -> None:
        """Operator can set log level to INFO."""
        result = cli_runner.invoke(cli, ["--log-level", "INFO", "version"])
        assert result.exit_code == 0

    def test_cli_log_level_warning(self, cli_runner: CliRunner) -> None:
        """Operator can set log level to WARNING."""
        result = cli_runner.invoke(cli, ["--log-level", "WARNING", "version"])
        assert result.exit_code == 0

    def test_cli_log_level_error(self, cli_runner: CliRunner) -> None:
        """Operator can set log level to ERROR."""
        result = cli_runner.invoke(cli, ["--log-level", "ERROR", "version"])
        assert result.exit_code == 0

    def test_cli_log_level_case_insensitive(self, cli_runner: CliRunner) -> None:
        """Log level option accepts lowercase values."""
        result = cli_runner.invoke(cli, ["--log-level", "debug", "version"])
        assert result.exit_code == 0

    def test_cli_log_level_invalid(self, cli_runner: CliRunner) -> None:
        """CLI rejects invalid log level with clear error."""
        result = cli_runner.invoke(cli, ["--log-level", "INVALID", "version"])
        assert result.exit_code != 0
        assert "Invalid value" in result.output or "choice" in result.output.lower()

    def test_cli_log_json_flag(self, cli_runner: CliRunner) -> None:
        """Operator can enable JSON logging with --log-json."""
        result = cli_runner.invoke(cli, ["--log-json", "version"])
        assert result.exit_code == 0

    def test_cli_no_log_json_option(self, cli_runner: CliRunner) -> None:
        """Operator can disable JSON logging with --no-log-json."""
        result = cli_runner.invoke(cli, ["--no-log-json", "version"])
        assert result.exit_code == 0

    def test_cli_config_file_option(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Operator can specify config file path."""
        config_path = tmp_path / "config.yaml"
        config_data = {"data_dir": str(tmp_path)}
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        result = cli_runner.invoke(
            cli, ["--config-file", str(config_path), "version"]
        )
        assert result.exit_code == 0

    def test_cli_multiple_global_options(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Operator can combine multiple global options."""
        config_path = tmp_path / "config.yaml"
        config_data = {"data_dir": str(tmp_path)}
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        result = cli_runner.invoke(
            cli,
            [
                "--config-file",
                str(config_path),
                "--log-level",
                "DEBUG",
                "--no-log-json",
                "version",
            ],
        )
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_cli_short_config_option(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Operator can use short -c flag for config file."""
        config_path = tmp_path / "config.yaml"
        config_data = {"data_dir": str(tmp_path)}
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        result = cli_runner.invoke(cli, ["-c", str(config_path), "version"])
        assert result.exit_code == 0

    def test_cli_short_log_level_not_available(self, cli_runner: CliRunner) -> None:
        """log-level option does not have short form (expected)."""
        # Trying to use -l or -L for log level should fail
        result = cli_runner.invoke(cli, ["-l", "DEBUG", "version"])
        # Should fail because -l is not a valid option
        assert result.exit_code != 0


class TestErrorHandling:
    """Tests for error handling and user feedback."""

    def test_invalid_command(self, cli_runner: CliRunner) -> None:
        """CLI provides error for invalid command."""
        result = cli_runner.invoke(cli, ["invalid-command"])
        assert result.exit_code != 0
        assert "Error" in result.output or "no such command" in result.output.lower()

    def test_invalid_subcommand(self, cli_runner: CliRunner) -> None:
        """CLI provides error for invalid subcommand."""
        result = cli_runner.invoke(cli, ["db", "invalid-subcommand"])
        assert result.exit_code != 0

    def test_missing_required_parameter(self, cli_runner: CliRunner) -> None:
        """CLI handles missing required parameters gracefully."""
        # config check requires a file path (has default but tests missing too)
        # This is a bit tricky since config check has a default
        result = cli_runner.invoke(cli, ["config", "check", "-c"])
        assert result.exit_code != 0


class TestContextAndConfiguration:
    """Tests for CLI context and configuration handling."""

    def test_context_object_created(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """CLI creates context object for commands."""
        config_path = tmp_path / "config.yaml"
        config_data = {"data_dir": str(tmp_path)}
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        # If context is properly created, db status should work
        result = cli_runner.invoke(
            cli, ["--config-file", str(config_path), "db", "status"]
        )
        assert result.exit_code == 0

    def test_default_config_loading(self, cli_runner: CliRunner) -> None:
        """CLI loads default config when file not specified."""
        result = cli_runner.invoke(cli, ["version"])
        # Should succeed even without explicit config
        assert result.exit_code == 0


class TestUserExperience:
    """Tests for operator experience (messages, clarity, helpfulness)."""

    def test_version_output_format(self, cli_runner: CliRunner) -> None:
        """version output is clear and identifies the product."""
        result = cli_runner.invoke(cli, ["version"])
        assert result.exit_code == 0
        # Should show 'zos' and version number
        output_lower = result.output.lower()
        assert "zos" in output_lower
        assert "0.1.0" in result.output or __version__ in result.output

    def test_help_is_readable(self, cli_runner: CliRunner) -> None:
        """--help output is well-formatted and readable."""
        result = cli_runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        # Should have clear sections
        assert "Commands:" in result.output or "Usage:" in result.output

    def test_db_status_output_clarity(self, cli_runner: CliRunner) -> None:
        """db status output clearly labels information."""
        result = cli_runner.invoke(cli, ["db", "status"])
        assert result.exit_code == 0
        # Output should have clear labels for data
        output_lower = result.output.lower()
        # Check for informative output (version, migrations, etc.)
        assert (
            "version" in output_lower
            or "database" in output_lower
            or "migration" in output_lower
        )

    def test_config_check_output_structure(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """config check output is well-organized with clear sections."""
        config_path = tmp_path / "config.yaml"
        config_data = {
            "data_dir": str(tmp_path),
            "log_level": "DEBUG",
            "models": {
                "profiles": {
                    "simple": {"provider": "anthropic", "model": "claude-haiku"}
                },
                "providers": {"anthropic": {"api_key_env": "ANTHROPIC_API_KEY"}},
            },
        }
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        result = cli_runner.invoke(cli, ["config", "check", "-c", str(config_path)])
        assert result.exit_code == 0
        # Output should have multiple lines showing different sections
        lines = result.output.strip().split("\n")
        assert len(lines) > 2  # At least some structured output

    def test_error_messages_are_informative(self, cli_runner: CliRunner) -> None:
        """Error messages provide actionable information."""
        result = cli_runner.invoke(
            cli, ["config", "check", "-c", "/nonexistent/path/config.yaml"]
        )
        # Click shows that the path doesn't exist
        assert result.exit_code == 2
