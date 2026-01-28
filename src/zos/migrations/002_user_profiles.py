"""Add user_profiles table for profile enrichment in reflections.

This migration adds a new table to store Discord user profile snapshots
including display names, usernames, roles, bio, pronouns, and join dates.
Profiles are used to enrich user reflections with identity context.
"""

from sqlalchemy import inspect

from zos.database import user_profiles

VERSION = 2
DESCRIPTION = "Add user_profiles table"


def upgrade(engine):
    """Create the user_profiles table."""
    user_profiles.create(engine, checkfirst=True)


def check(engine) -> bool:
    """Check if this migration has been applied.

    Returns True if the user_profiles table exists.
    """
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    return "user_profiles" in table_names
