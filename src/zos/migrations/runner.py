"""Migration runner for Zos database schema evolution.

This module provides the core migration functionality:
- Discovering available migrations
- Tracking applied versions
- Applying pending migrations
"""

from __future__ import annotations

import importlib
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine

from zos.database import schema_version
from zos.logging import get_logger

log = get_logger("migrations")


def get_migrations() -> list[tuple[int, ModuleType]]:
    """Discover all migration modules in the migrations directory.

    Returns:
        List of (version, module) tuples, sorted by version.
    """
    migrations_dir = Path(__file__).parent
    migrations: list[tuple[int, ModuleType]] = []

    for path in sorted(migrations_dir.glob("[0-9][0-9][0-9]_*.py")):
        module_name = path.stem
        module = importlib.import_module(f"zos.migrations.{module_name}")

        if not hasattr(module, "VERSION"):
            log.warning("migration_missing_version", file=module_name)
            continue

        migrations.append((module.VERSION, module))

    return migrations


def get_current_version(engine: Engine) -> int:
    """Get current schema version from database.

    Args:
        engine: SQLAlchemy engine.

    Returns:
        Current version number, or 0 if no migrations applied.
    """
    inspector = inspect(engine)

    # Check if version table exists
    if "_schema_version" not in inspector.get_table_names():
        return 0

    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT MAX(version) FROM _schema_version")
        ).scalar()
        return result or 0


def migrate(engine: Engine, target_version: int | None = None) -> int:
    """Apply pending migrations up to target_version.

    Args:
        engine: SQLAlchemy engine.
        target_version: Maximum version to apply. If None, apply all.

    Returns:
        New current version after migrations.
    """
    current = get_current_version(engine)
    migrations = get_migrations()

    if not migrations:
        log.info("no_migrations_found")
        return current

    applied_count = 0

    for version, module in migrations:
        if version <= current:
            continue
        if target_version is not None and version > target_version:
            break

        description = getattr(module, "DESCRIPTION", "No description")
        log.info("applying_migration", version=version, description=description)

        try:
            # Apply the migration
            module.upgrade(engine)

            # Record that it was applied
            with engine.connect() as conn:
                conn.execute(
                    schema_version.insert().values(
                        version=version,
                        applied_at=datetime.now(timezone.utc),
                        description=description,
                    )
                )
                conn.commit()

            applied_count += 1
            log.info("migration_applied", version=version)

        except Exception as e:
            log.error("migration_failed", version=version, error=str(e))
            raise

    if applied_count == 0:
        log.info("no_pending_migrations")
    else:
        log.info("migrations_complete", count=applied_count)

    return get_current_version(engine)


def get_pending_migrations(engine: Engine) -> list[tuple[int, ModuleType]]:
    """Get list of migrations that haven't been applied yet.

    Args:
        engine: SQLAlchemy engine.

    Returns:
        List of (version, module) tuples for pending migrations.
    """
    current = get_current_version(engine)
    migrations = get_migrations()
    return [(v, m) for v, m in migrations if v > current]
