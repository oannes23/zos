"""Tests for the migration system.

Covers comprehensive migration edge cases, ordering, and schema validation.
Critical for maintaining integrity of Zos's accumulated understanding.
"""

from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text

from zos.config import Config
from zos.database import (
    get_engine,
    schema_version,
    messages,
    topics,
    insights,
    layer_runs,
    servers,
    channels,
    reactions,
    users,
)
from zos.migrations import get_current_version, get_migrations, migrate
from zos.migrations.runner import get_pending_migrations


@pytest.fixture
def test_config(tmp_path: Path) -> Config:
    """Create a test configuration with temp database."""
    return Config(data_dir=tmp_path)


@pytest.fixture
def engine(test_config: Config):
    """Create a test database engine (no tables yet)."""
    return get_engine(test_config)


# =============================================================================
# Basic Migration Discovery & Status
# =============================================================================


class TestMigrationDiscovery:
    """Tests for migration file discovery and loading."""

    def test_get_migrations(self) -> None:
        """Test that migrations are discovered."""
        migrations = get_migrations()

        # Should have at least the initial migration
        assert len(migrations) >= 1

        # First migration should be version 1
        assert migrations[0][0] == 1

    def test_migrations_have_version_attribute(self) -> None:
        """Test that all discovered migrations have VERSION attribute."""
        migrations = get_migrations()
        assert len(migrations) > 0

        for version, module in migrations:
            assert hasattr(module, "VERSION"), f"Migration module missing VERSION: {module}"
            assert module.VERSION == version, f"VERSION mismatch in {module}"

    def test_migrations_have_description_attribute(self) -> None:
        """Test that all discovered migrations have DESCRIPTION."""
        migrations = get_migrations()
        assert len(migrations) > 0

        for version, module in migrations:
            assert hasattr(module, "DESCRIPTION"), f"Migration module missing DESCRIPTION: {module}"
            assert isinstance(module.DESCRIPTION, str), f"DESCRIPTION not a string in {module}"
            assert len(module.DESCRIPTION) > 0, f"DESCRIPTION is empty in {module}"

    def test_migrations_have_upgrade_function(self) -> None:
        """Test that all discovered migrations have upgrade function."""
        migrations = get_migrations()
        assert len(migrations) > 0

        for version, module in migrations:
            assert hasattr(module, "upgrade"), f"Migration module missing upgrade: {module}"
            assert callable(module.upgrade), f"upgrade is not callable in {module}"

    def test_migrations_are_ordered_by_version(self) -> None:
        """Test that migrations are ordered by version number."""
        migrations = get_migrations()
        versions = [v for v, _ in migrations]

        # Should be in ascending order
        assert versions == sorted(versions), "Migrations not ordered by version"

        # Should have no duplicates
        assert len(versions) == len(set(versions)), "Duplicate migration versions"

    def test_migration_versions_are_sequential(self) -> None:
        """Test that migration versions form a sequence (no gaps)."""
        migrations = get_migrations()
        if len(migrations) <= 1:
            pytest.skip("Need multiple migrations for this test")

        versions = [v for v, _ in migrations]
        expected = list(range(versions[0], versions[-1] + 1))
        assert versions == expected, f"Non-sequential versions: {versions} vs {expected}"


# =============================================================================
# Current Version Tracking
# =============================================================================


class TestCurrentVersion:
    """Tests for tracking current schema version."""

    def test_fresh_database_version_zero(self, engine) -> None:
        """Test that a fresh database reports version 0."""
        version = get_current_version(engine)
        assert version == 0

    def test_version_after_single_migration(self, engine) -> None:
        """Test that version increments after migration."""
        assert get_current_version(engine) == 0

        migrate(engine, target_version=1)

        assert get_current_version(engine) == 1

    def test_version_after_all_migrations(self, engine) -> None:
        """Test version after applying all migrations."""
        migrate(engine)

        current = get_current_version(engine)
        all_versions = [v for v, _ in get_migrations()]

        assert current == max(all_versions), f"Current version {current} != max {max(all_versions)}"

    def test_get_current_version_with_corrupted_schema_table(self, engine) -> None:
        """Test graceful handling when _schema_version table is missing."""
        # Manually create the table, then delete it
        from zos.database import metadata
        metadata.create_all(engine)

        # Drop the version table
        with engine.connect() as conn:
            conn.execute(text("DROP TABLE _schema_version"))
            conn.commit()

        # Should return 0 when table doesn't exist
        version = get_current_version(engine)
        assert version == 0


# =============================================================================
# Migration Execution & Idempotency
# =============================================================================


class TestMigrationExecution:
    """Tests for applying migrations."""

    def test_migrate_creates_tables(self, engine) -> None:
        """Test that migrate creates all tables."""
        # Before migration
        inspector = inspect(engine)
        assert "messages" not in inspector.get_table_names()

        # Run migrations
        new_version = migrate(engine)

        # After migration
        assert new_version >= 1

        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())

        # Check core tables exist
        assert "servers" in table_names
        assert "messages" in table_names
        assert "topics" in table_names
        assert "insights" in table_names
        assert "_schema_version" in table_names

    def test_migrate_is_idempotent(self, engine) -> None:
        """Test that running migrate twice is safe."""
        # First migration
        version1 = migrate(engine)

        # Get row count before second migrate
        with engine.connect() as conn:
            result1 = conn.execute(select(schema_version)).fetchall()
            count_before = len(result1)

        # Second migration (should be no-op)
        version2 = migrate(engine)

        # Get row count after
        with engine.connect() as conn:
            result2 = conn.execute(select(schema_version)).fetchall()
            count_after = len(result2)

        assert version1 == version2
        # No new version rows should be added
        assert count_before == count_after

    def test_migrate_records_version(self, engine) -> None:
        """Test that migration records version in database."""
        migrate(engine)

        with engine.connect() as conn:
            result = conn.execute(select(schema_version)).fetchall()

            # Should have at least one version recorded
            assert len(result) >= 1

            # Version 1 should be recorded
            versions = [row.version for row in result]
            assert 1 in versions

    def test_migrate_records_description(self, engine) -> None:
        """Test that migration records description."""
        migrate(engine)

        with engine.connect() as conn:
            result = conn.execute(select(schema_version)).fetchall()

            assert len(result) >= 1
            for row in result:
                assert row.description is not None
                assert len(row.description) > 0

    def test_migrate_records_timestamp(self, engine) -> None:
        """Test that migration records applied_at timestamp."""
        from datetime import datetime, timezone

        before = datetime.now(timezone.utc).replace(tzinfo=None)
        migrate(engine)
        after = datetime.now(timezone.utc).replace(tzinfo=None)

        with engine.connect() as conn:
            result = conn.execute(select(schema_version)).fetchall()

            assert len(result) >= 1
            for row in result:
                assert row.applied_at is not None
                # Timestamp should be recent (naive datetime comparison)
                assert before <= row.applied_at <= after

    def test_migrate_to_specific_version(self, engine) -> None:
        """Test migrating to a specific version."""
        version = migrate(engine, target_version=1)

        assert version == 1

        # Can migrate further
        version2 = migrate(engine)
        assert version2 >= 1


# =============================================================================
# Pending Migrations
# =============================================================================


class TestPendingMigrations:
    """Tests for get_pending_migrations function."""

    def test_all_migrations_pending_on_fresh_db(self, engine) -> None:
        """Test that all migrations are pending on fresh database."""
        pending = get_pending_migrations(engine)
        all_migrations = get_migrations()

        assert len(pending) == len(all_migrations)

    def test_no_pending_after_full_migrate(self, engine) -> None:
        """Test that no migrations are pending after full migration."""
        migrate(engine)

        pending = get_pending_migrations(engine)
        assert len(pending) == 0

    def test_pending_after_partial_migrate(self, engine) -> None:
        """Test pending migrations after partial migration."""
        all_migrations = get_migrations()
        if len(all_migrations) <= 1:
            pytest.skip("Need multiple migrations for this test")

        # Migrate to first version only
        migrate(engine, target_version=1)

        pending = get_pending_migrations(engine)

        # Should have remaining migrations
        assert len(pending) > 0
        # All pending versions should be > 1
        for version, _ in pending:
            assert version > 1

    def test_pending_returns_module_objects(self, engine) -> None:
        """Test that pending migrations return actual module objects."""
        pending = get_pending_migrations(engine)

        for version, module in pending:
            assert isinstance(version, int)
            assert version > 0
            assert hasattr(module, "upgrade")
            assert hasattr(module, "VERSION")


# =============================================================================
# Migration Check Function
# =============================================================================


class TestMigrationCheck:
    """Tests for the check() function in migrations."""

    def test_check_function_exists(self) -> None:
        """Test that migration modules have check function."""
        migrations = get_migrations()
        assert len(migrations) > 0

        for version, module in migrations:
            assert hasattr(module, "check"), f"Migration {version} missing check function"
            assert callable(module.check), f"check is not callable in migration {version}"

    def test_check_returns_false_on_fresh_db(self, engine) -> None:
        """Test that check() returns False on fresh database."""
        migrations = get_migrations()
        version, module = migrations[0]

        result = module.check(engine)
        assert result is False, "check() should return False on fresh database"

    def test_check_returns_true_after_migration(self, engine) -> None:
        """Test that check() returns True after migration is applied."""
        migrations = get_migrations()
        if len(migrations) < 1:
            pytest.skip("No migrations to test")

        version, module = migrations[0]

        # Before migration
        assert module.check(engine) is False

        # Apply migration
        migrate(engine, target_version=version)

        # After migration
        assert module.check(engine) is True

    def test_check_detects_partial_migration(self, engine) -> None:
        """Test that check detects when not all tables are created."""
        migrations = get_migrations()
        if len(migrations) < 1:
            pytest.skip("No migrations to test")

        version, module = migrations[0]

        # Manually create schema table but not all tables
        from zos.database import metadata
        schema_version.create(engine)

        # check() should return False because not all tables exist
        result = module.check(engine)
        assert result is False


# =============================================================================
# Schema Validation
# =============================================================================


class TestSchemaValidation:
    """Tests for verifying schema matches expected structure."""

    def test_schema_has_all_core_tables(self, engine) -> None:
        """Test that migrated schema has all core tables."""
        migrate(engine)

        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())

        # Core entities
        assert "servers" in table_names
        assert "users" in table_names
        assert "channels" in table_names
        assert "messages" in table_names
        assert "reactions" in table_names

        # Topics and salience
        assert "topics" in table_names
        assert "salience_ledger" in table_names

        # Insights
        assert "insights" in table_names
        assert "layer_runs" in table_names
        assert "llm_calls" in table_names

        # Chattiness
        assert "chattiness_ledger" in table_names
        assert "conversation_log" in table_names

    def test_schema_version_table_structure(self, engine) -> None:
        """Test that _schema_version table has correct columns."""
        migrate(engine)

        inspector = inspect(engine)
        columns = {col["name"]: col for col in inspector.get_columns("_schema_version")}

        assert "version" in columns
        assert "applied_at" in columns
        assert "description" in columns

    def test_messages_table_structure(self, engine) -> None:
        """Test that messages table has correct columns."""
        migrate(engine)

        inspector = inspect(engine)
        columns = {col["name"]: col for col in inspector.get_columns("messages")}

        # Critical columns
        assert "id" in columns
        assert "channel_id" in columns
        assert "author_id" in columns
        assert "content" in columns
        assert "created_at" in columns
        assert "visibility_scope" in columns
        assert "deleted_at" in columns  # Soft delete support

    def test_insights_table_structure(self, engine) -> None:
        """Test that insights table has correct columns."""
        migrate(engine)

        inspector = inspect(engine)
        columns = {col["name"]: col for col in inspector.get_columns("insights")}

        # Critical columns for accumulated understanding
        assert "id" in columns
        assert "topic_key" in columns
        assert "content" in columns
        assert "created_at" in columns
        assert "layer_run_id" in columns
        assert "confidence" in columns
        assert "importance" in columns
        assert "novelty" in columns

        # Valence dimensions
        assert "valence_joy" in columns
        assert "valence_concern" in columns
        assert "valence_curiosity" in columns
        assert "valence_warmth" in columns
        assert "valence_tension" in columns

    def test_layer_runs_table_structure(self, engine) -> None:
        """Test that layer_runs table has correct columns."""
        migrate(engine)

        inspector = inspect(engine)
        columns = {col["name"]: col for col in inspector.get_columns("layer_runs")}

        # Critical columns for tracking execution
        assert "id" in columns
        assert "layer_name" in columns
        assert "started_at" in columns
        assert "completed_at" in columns
        assert "status" in columns
        assert "targets_processed" in columns
        assert "insights_created" in columns

    def test_foreign_key_relationships(self, engine) -> None:
        """Test that foreign key relationships are established."""
        migrate(engine)

        inspector = inspect(engine)

        # Messages should reference channels and servers
        message_fks = inspector.get_foreign_keys("messages")
        referenced_tables = {fk["referred_table"] for fk in message_fks}
        assert "channels" in referenced_tables or "servers" in referenced_tables

        # Insights should reference topics
        insights_fks = inspector.get_foreign_keys("insights")
        referenced_tables = {fk["referred_table"] for fk in insights_fks}
        assert "topics" in referenced_tables

    def test_indexes_exist(self, engine) -> None:
        """Test that expected indexes exist."""
        migrate(engine)

        inspector = inspect(engine)

        # Check for critical indexes
        messages_indexes = inspector.get_indexes("messages")
        index_names = {idx["name"] for idx in messages_indexes}

        # At least one index should exist on messages
        assert len(messages_indexes) > 0


# =============================================================================
# Error Handling & Edge Cases
# =============================================================================


class TestErrorHandling:
    """Tests for error conditions and recovery."""

    def test_get_current_version_with_no_version_table(self, engine) -> None:
        """Test get_current_version handles missing version table gracefully."""
        # Fresh database has no version table
        version = get_current_version(engine)

        assert version == 0
        assert isinstance(version, int)

    def test_get_current_version_with_empty_version_table(self, engine) -> None:
        """Test get_current_version with empty version table."""
        # Create the version table but leave it empty
        from zos.database import metadata
        schema_version.create(engine)

        version = get_current_version(engine)

        # Should return 0 when table exists but is empty
        assert version == 0

    def test_get_current_version_returns_max_version(self, engine) -> None:
        """Test that get_current_version returns the maximum version."""
        from datetime import datetime, timezone

        # Create version table and add multiple entries
        from zos.database import metadata
        schema_version.create(engine)

        with engine.connect() as conn:
            # Insert multiple versions
            for v in [1, 2, 3]:
                conn.execute(
                    schema_version.insert().values(
                        version=v,
                        applied_at=datetime.now(timezone.utc),
                        description=f"Version {v}",
                    )
                )
            conn.commit()

        version = get_current_version(engine)
        assert version == 3

    def test_migrate_with_nonexistent_target_version(self, engine) -> None:
        """Test migrate with target_version higher than available migrations."""
        all_versions = [v for v, _ in get_migrations()]
        target = max(all_versions) + 1000

        # Should migrate to max available, not fail
        version = migrate(engine, target_version=target)

        assert version == max(all_versions)

    def test_migrate_with_zero_target_version(self, engine) -> None:
        """Test migrate with target_version=0 is no-op."""
        version = migrate(engine, target_version=0)

        # Should return 0, no migrations applied
        assert version == 0

    def test_migrate_does_not_downgrade(self, engine) -> None:
        """Test that migrations never downgrade version."""
        # Migrate to version 1
        v1 = migrate(engine, target_version=1)
        assert v1 == 1

        # Try to migrate to version 1 again
        v2 = migrate(engine, target_version=1)

        # Should still be version 1
        assert v2 == 1


# =============================================================================
# CLI Integration Tests
# =============================================================================


class TestCLIIntegration:
    """Tests for CLI commands."""

    def test_cli_db_status(self, cli_runner, tmp_path: Path) -> None:
        """Test the db status CLI command."""
        import yaml
        from zos.cli import cli

        # Create a temp config file
        config_path = tmp_path / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump({"data_dir": str(tmp_path)}, f)

        result = cli_runner.invoke(cli, ["-c", str(config_path), "db", "status"])

        assert result.exit_code == 0
        assert "Current version: 0" in result.output
        assert "Pending migrations" in result.output

    def test_cli_db_migrate(self, cli_runner, tmp_path: Path) -> None:
        """Test the db migrate CLI command."""
        import yaml
        from zos.cli import cli

        # Create a temp config file
        config_path = tmp_path / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump({"data_dir": str(tmp_path)}, f)

        result = cli_runner.invoke(cli, ["-c", str(config_path), "db", "migrate"])

        assert result.exit_code == 0
        assert "Migrated from version 0 to" in result.output

    def test_cli_db_status_after_migrate(self, cli_runner, tmp_path: Path) -> None:
        """Test db status shows no pending after migrate."""
        import yaml
        from zos.cli import cli

        # Create a temp config file
        config_path = tmp_path / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump({"data_dir": str(tmp_path)}, f)

        # First migrate
        cli_runner.invoke(cli, ["-c", str(config_path), "db", "migrate"])

        # Then check status
        result = cli_runner.invoke(cli, ["-c", str(config_path), "db", "status"])

        assert result.exit_code == 0
        assert "No pending migrations" in result.output


# =============================================================================
# Integration: Full Migration Workflow
# =============================================================================


class TestFullMigrationWorkflow:
    """Integration tests for complete migration scenarios."""

    def test_complete_migration_creates_usable_schema(self, engine) -> None:
        """Test that complete migration produces a schema ready for data insertion."""
        migrate(engine)

        # Should be able to insert test data
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)

        with engine.connect() as conn:
            # Insert a server
            conn.execute(
                servers.insert().values(
                    id="123456789",
                    name="Test Server",
                    created_at=now,
                )
            )

            # Insert a channel
            conn.execute(
                channels.insert().values(
                    id="987654321",
                    server_id="123456789",
                    name="test-channel",
                    type="text",
                    created_at=now,
                )
            )

            # Insert a message
            conn.execute(
                messages.insert().values(
                    id="msg-1",
                    channel_id="987654321",
                    server_id="123456789",
                    author_id="user-1",
                    content="Test message",
                    created_at=now,
                    visibility_scope="public",
                )
            )

            conn.commit()

        # Should be able to read the data back
        with engine.connect() as conn:
            result = conn.execute(select(messages)).fetchall()
            assert len(result) == 1
            assert result[0].content == "Test message"

    def test_migration_preserves_data_integrity(self, engine) -> None:
        """Test that migration doesn't corrupt existing data."""
        from datetime import datetime, timezone

        # Apply initial migration
        migrate(engine, target_version=1)

        # Insert test data
        with engine.connect() as conn:
            conn.execute(
                servers.insert().values(
                    id="test-server",
                    name="Test",
                    created_at=datetime.now(timezone.utc),
                )
            )
            conn.commit()

        # Re-run migrations
        migrate(engine)

        # Data should still be there
        with engine.connect() as conn:
            result = conn.execute(
                select(servers).where(servers.c.id == "test-server")
            ).fetchone()

        assert result is not None
        assert result.name == "Test"

    def test_multiple_partial_migrations(self, engine) -> None:
        """Test behavior of multiple partial migrations."""
        all_migrations = get_migrations()
        if len(all_migrations) <= 1:
            pytest.skip("Need multiple migrations for this test")

        # Migrate to first version
        v1 = migrate(engine, target_version=1)
        assert v1 == 1

        # Migrate to last version
        v_final = migrate(engine)
        assert v_final >= 1

        # Should have all tables
        inspector = inspect(engine)
        assert "messages" in inspector.get_table_names()
        assert "insights" in inspector.get_table_names()
