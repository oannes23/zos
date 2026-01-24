# Story 1.4: Migration System

**Epic**: Foundation
**Status**: 🔴 Not Started
**Estimated complexity**: Small

## Goal

Implement a simple, forward-only migration system that tracks schema versions and applies pending migrations.

## Acceptance Criteria

- [ ] `_schema_version` table tracks current version
- [ ] Migration files are numbered Python scripts
- [ ] `zos db migrate` applies pending migrations
- [ ] `zos db status` shows current version and pending migrations
- [ ] Migrations are idempotent (safe to run twice)
- [ ] Initial migration creates all tables from Story 1.3

## Design

### Philosophy

Keep it simple:
- Forward-only (no rollback — matches spec decision)
- Python scripts, not SQL files (can use SQLAlchemy)
- Sequential numbering (001, 002, ...)
- Track version in database

### Migration Structure

```
src/zos/migrations/
├── __init__.py
├── runner.py          # Migration execution logic
├── 001_initial.py     # Create all tables
├── 002_example.py     # Future migrations
└── ...
```

### Migration File Format

```python
# src/zos/migrations/001_initial.py
"""
Initial schema - create all tables for MVP 0.
"""
from sqlalchemy import MetaData
from zos.database import metadata, create_tables

VERSION = 1
DESCRIPTION = "Initial schema with all MVP 0 tables"

def upgrade(engine):
    """Apply this migration."""
    create_tables(engine)

def check(engine) -> bool:
    """Check if this migration has been applied."""
    # Check if tables exist
    inspector = inspect(engine)
    return "messages" in inspector.get_table_names()
```

### Schema Version Table

```python
schema_version = Table(
    "_schema_version",
    metadata,
    Column("version", Integer, primary_key=True),
    Column("applied_at", DateTime, nullable=False),
    Column("description", String, nullable=True),
)
```

### Migration Runner

```python
# src/zos/migrations/runner.py
from pathlib import Path
import importlib
from datetime import datetime

def get_migrations() -> list[tuple[int, module]]:
    """Discover all migration modules."""
    migrations_dir = Path(__file__).parent
    migrations = []

    for path in sorted(migrations_dir.glob("[0-9][0-9][0-9]_*.py")):
        module_name = path.stem
        module = importlib.import_module(f"zos.migrations.{module_name}")
        migrations.append((module.VERSION, module))

    return migrations

def get_current_version(engine) -> int:
    """Get current schema version from database."""
    with engine.connect() as conn:
        # Ensure version table exists
        if not inspect(engine).has_table("_schema_version"):
            return 0

        result = conn.execute(
            text("SELECT MAX(version) FROM _schema_version")
        ).scalar()
        return result or 0

def migrate(engine, target_version: int = None):
    """Apply pending migrations up to target_version."""
    current = get_current_version(engine)
    migrations = get_migrations()

    for version, module in migrations:
        if version <= current:
            continue
        if target_version and version > target_version:
            break

        log.info("applying_migration", version=version, description=module.DESCRIPTION)

        module.upgrade(engine)

        # Record migration
        with engine.connect() as conn:
            conn.execute(
                schema_version.insert().values(
                    version=version,
                    applied_at=datetime.utcnow(),
                    description=module.DESCRIPTION,
                )
            )
            conn.commit()

    return get_current_version(engine)
```

## CLI Commands

```python
@cli.group()
def db():
    """Database management commands."""
    pass

@db.command()
@click.pass_context
def migrate(ctx):
    """Apply pending database migrations."""
    config = ctx.obj["config"]
    engine = get_engine(config)

    before = get_current_version(engine)
    after = migrate(engine)

    if before == after:
        click.echo(f"Database already at version {after}")
    else:
        click.echo(f"Migrated from version {before} to {after}")

@db.command()
@click.pass_context
def status(ctx):
    """Show database migration status."""
    config = ctx.obj["config"]
    engine = get_engine(config)

    current = get_current_version(engine)
    migrations = get_migrations()

    click.echo(f"Current version: {current}")
    click.echo(f"Available migrations: {len(migrations)}")

    pending = [m for v, m in migrations if v > current]
    if pending:
        click.echo(f"Pending migrations: {len(pending)}")
        for m in pending:
            click.echo(f"  {m.VERSION}: {m.DESCRIPTION}")
    else:
        click.echo("No pending migrations")
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/migrations/__init__.py` | Package init |
| `src/zos/migrations/runner.py` | Migration execution logic |
| `src/zos/migrations/001_initial.py` | Initial schema creation |
| `src/zos/cli.py` | Add `db migrate` and `db status` commands |
| `tests/test_migrations.py` | Migration tests |

## Test Cases

1. Fresh database starts at version 0
2. `migrate` applies all pending migrations
3. Running `migrate` twice is idempotent
4. Version is tracked correctly
5. `status` shows correct pending count

## Definition of Done

- [ ] `zos db status` shows version info
- [ ] `zos db migrate` applies migrations
- [ ] Initial migration creates all tables
- [ ] Tests verify idempotency

---

**Requires**: Story 1.3 (database schema)
**Blocks**: Epic 2+ (all need migrated database)
