"""Add status and error columns to media_analysis for failure tracking.

Enables recording failed media analyses so they can be retried later
via the /retry-media command.
"""

from sqlalchemy import inspect, text

VERSION = 10
DESCRIPTION = "Add status and error columns to media_analysis"


def upgrade(engine):
    """Add status and error columns to media_analysis table."""
    if check(engine):
        return

    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE media_analysis ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'"
        ))
        conn.execute(text(
            "ALTER TABLE media_analysis ADD COLUMN error TEXT"
        ))
        conn.commit()


def check(engine) -> bool:
    """Check if this migration has been applied.

    Returns True if the status column already exists in media_analysis.
    """
    inspector = inspect(engine)
    if "media_analysis" not in inspector.get_table_names():
        return False

    columns = {col["name"] for col in inspector.get_columns("media_analysis")}
    return "status" in columns
