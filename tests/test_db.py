"""Tests for the database module."""

from pathlib import Path

from zos.config import DatabaseConfig
from zos.db import SCHEMA_VERSION, Database


class TestDatabase:
    """Tests for the Database class."""

    def test_initialize_creates_file(self, temp_dir: Path):
        db_path = temp_dir / "test.db"
        config = DatabaseConfig(path=db_path)
        db = Database(config)

        assert not db_path.exists()
        db.initialize()
        assert db_path.exists()

        db.close()

    def test_initialize_creates_metadata_table(self, test_db: Database):
        result = test_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='zos_metadata'"
        ).fetchone()
        assert result is not None
        assert result[0] == "zos_metadata"

    def test_schema_version(self, test_db: Database):
        version = test_db.get_schema_version()
        assert version == SCHEMA_VERSION

    def test_execute_with_params(self, test_db: Database):
        test_db.execute(
            "INSERT INTO zos_metadata (key, value) VALUES (?, ?)",
            ("test_key", "test_value"),
        )
        result = test_db.execute(
            "SELECT value FROM zos_metadata WHERE key = ?", ("test_key",)
        ).fetchone()
        assert result[0] == "test_value"

    def test_execute_with_dict_params(self, test_db: Database):
        test_db.execute(
            "INSERT INTO zos_metadata (key, value) VALUES (:key, :value)",
            {"key": "dict_key", "value": "dict_value"},
        )
        result = test_db.execute(
            "SELECT value FROM zos_metadata WHERE key = :key", {"key": "dict_key"}
        ).fetchone()
        assert result[0] == "dict_value"

    def test_transaction_commit(self, test_db: Database):
        with test_db.transaction():
            test_db.execute(
                "INSERT INTO zos_metadata (key, value) VALUES (?, ?)",
                ("tx_key", "tx_value"),
            )

        result = test_db.execute(
            "SELECT value FROM zos_metadata WHERE key = ?", ("tx_key",)
        ).fetchone()
        assert result[0] == "tx_value"

    def test_transaction_rollback(self, test_db: Database):
        try:
            with test_db.transaction():
                test_db.execute(
                    "INSERT INTO zos_metadata (key, value) VALUES (?, ?)",
                    ("rollback_key", "rollback_value"),
                )
                raise ValueError("Force rollback")
        except ValueError:
            pass

        result = test_db.execute(
            "SELECT value FROM zos_metadata WHERE key = ?", ("rollback_key",)
        ).fetchone()
        assert result is None

    def test_row_factory(self, test_db: Database):
        result = test_db.execute(
            "SELECT key, value FROM zos_metadata WHERE key = 'schema_version'"
        ).fetchone()
        # Should be accessible by column name
        assert result["key"] == "schema_version"
        assert result["value"] == str(SCHEMA_VERSION)

    def test_executemany(self, test_db: Database):
        data = [
            ("multi_1", "value_1"),
            ("multi_2", "value_2"),
            ("multi_3", "value_3"),
        ]
        test_db.executemany("INSERT INTO zos_metadata (key, value) VALUES (?, ?)", data)

        result = test_db.execute(
            "SELECT COUNT(*) FROM zos_metadata WHERE key LIKE 'multi_%'"
        ).fetchone()
        assert result[0] == 3

    def test_creates_parent_directory(self, temp_dir: Path):
        nested_path = temp_dir / "nested" / "dirs" / "test.db"
        config = DatabaseConfig(path=nested_path)
        db = Database(config)
        db.initialize()
        assert nested_path.exists()
        db.close()


class TestMigrations:
    """Tests for database migrations."""

    def test_migration_idempotent(self, test_db: Database):
        # Running migrate again should be safe
        initial_version = test_db.get_schema_version()
        test_db.migrate()
        assert test_db.get_schema_version() == initial_version

    def test_fresh_db_migrates_to_current(self, temp_dir: Path):
        config = DatabaseConfig(path=temp_dir / "fresh.db")
        db = Database(config)
        db.initialize()

        assert db.get_schema_version() == SCHEMA_VERSION
        db.close()
