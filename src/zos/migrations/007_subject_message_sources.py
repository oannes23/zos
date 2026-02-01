"""Create subject_message_sources junction table.

This migration creates a table that links subject topics to the Discord
messages that were in the context window when the subject was identified.
This replaces the broken keyword-search approach for subject reflections
with direct message associations.
"""

from sqlalchemy import inspect, text

VERSION = 7
DESCRIPTION = "Create subject_message_sources junction table for subject reflections"


def upgrade(engine):
    """Create subject_message_sources table with indexes.

    This migration is idempotent - it uses IF NOT EXISTS for all DDL.
    """
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS subject_message_sources (
                id TEXT PRIMARY KEY,
                subject_topic_key TEXT NOT NULL REFERENCES topics(key),
                message_id TEXT NOT NULL REFERENCES messages(id),
                source_topic_key TEXT NOT NULL,
                layer_run_id TEXT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_sms_subject_created
            ON subject_message_sources(subject_topic_key, created_at)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_sms_message
            ON subject_message_sources(message_id)
        """))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS ix_sms_unique
            ON subject_message_sources(subject_topic_key, message_id)
        """))
        conn.commit()


def check(engine) -> bool:
    """Check if this migration has been applied.

    Returns True if the subject_message_sources table exists.
    """
    inspector = inspect(engine)
    return "subject_message_sources" in inspector.get_table_names()
