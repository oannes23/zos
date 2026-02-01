"""Add status column to user_profiles table.

This migration adds a status column for storing the user's custom Discord status
text (e.g., "Playing Minecraft", "Studying for exams"). Requires the presences
privileged intent to be enabled for the bot to capture this data.

Note: This was originally migration 006, but that file was never committed.
The DB version advanced to 7 without it, so this re-introduces the same
change as migration 008.
"""

from sqlalchemy import inspect, text

VERSION = 8
DESCRIPTION = "Add status column to user_profiles for custom Discord status"


def upgrade(engine):
    """Add status column to user_profiles table.

    This migration is idempotent - it checks for column existence before adding.
    """
    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("user_profiles")}

    if "status" not in columns:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE user_profiles ADD COLUMN status TEXT"))
            conn.commit()


def check(engine) -> bool:
    """Check if this migration has been applied.

    Returns True if the status column exists in user_profiles table.
    """
    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("user_profiles")}
    return "status" in columns
