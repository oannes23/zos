"""Add summary_error column to link_analysis table.

This migration adds a summary_error column for storing the error message when
LLM summarization fails after a successful page fetch. This makes the failure
visible in the UI instead of silently showing fetch_failed=False with summary=NULL.
"""

from sqlalchemy import inspect, text

VERSION = 5
DESCRIPTION = "Add summary_error column to link_analysis for summarization error tracking"


def upgrade(engine):
    """Add summary_error column to link_analysis table.

    This migration is idempotent - it checks for column existence before adding.
    """
    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("link_analysis")}

    if "summary_error" not in columns:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE link_analysis ADD COLUMN summary_error TEXT"))
            conn.commit()


def check(engine) -> bool:
    """Check if this migration has been applied.

    Returns True if the summary_error column exists in link_analysis table.
    """
    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("link_analysis")}
    return "summary_error" in columns
