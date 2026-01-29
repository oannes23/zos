"""Add local_path column to media_analysis table.

This migration adds a local_path column for storing the relative path to
saved image files on disk (under data/media/). This enables serving images
locally in the UI rather than relying on ephemeral Discord CDN URLs.
"""

from sqlalchemy import inspect, text

VERSION = 4
DESCRIPTION = "Add local_path column to media_analysis for local image storage"


def upgrade(engine):
    """Add local_path column to media_analysis table.

    This migration is idempotent - it checks for column existence before adding.
    """
    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("media_analysis")}

    if "local_path" not in columns:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE media_analysis ADD COLUMN local_path TEXT"))
            conn.commit()


def check(engine) -> bool:
    """Check if this migration has been applied.

    Returns True if the local_path column exists in media_analysis table.
    """
    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("media_analysis")}
    return "local_path" in columns
