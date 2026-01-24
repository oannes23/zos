"""Database migrations for Zos.

Migrations are forward-only Python scripts that evolve the database schema.
Each migration file follows the pattern: NNN_description.py

Migration file structure:
    VERSION = N  # Must match file prefix
    DESCRIPTION = "What this migration does"

    def upgrade(engine):
        '''Apply this migration.'''
        pass

    def check(engine) -> bool:
        '''Check if migration is already applied.'''
        return False
"""

from zos.migrations.runner import get_current_version, get_migrations, migrate

__all__ = ["get_current_version", "get_migrations", "migrate"]
