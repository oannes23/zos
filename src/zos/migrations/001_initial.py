"""Initial schema - create all tables for MVP 0.

This migration creates all the core tables defined in the data model:
- Core entities: servers, users, channels, messages, reactions, etc.
- Topics and salience tracking
- Insights and layer runs
- Chattiness tables (MVP 1 prep)
- LLM call logging
"""

from sqlalchemy import inspect

from zos.database import create_tables, metadata

VERSION = 1
DESCRIPTION = "Initial schema with all MVP 0 tables"


def upgrade(engine):
    """Create all tables defined in the schema."""
    create_tables(engine)


def check(engine) -> bool:
    """Check if this migration has been applied.

    Returns True if the core tables exist.
    """
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    # Check for a few key tables
    required = {"servers", "messages", "topics", "insights", "layer_runs"}
    return required.issubset(table_names)
