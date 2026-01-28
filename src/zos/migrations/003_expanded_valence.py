"""Add expanded valence dimensions and open_questions to insights table.

This migration adds five new emotional valence fields (awe, grief, longing, peace,
gratitude) for richer phenomenological texture, and an open_questions JSON field
for forward-looking curiosity.

Per spec: These dimensions capture experiences that the original five dimensions
couldn't adequately express - encountering the numinous, loss, desire, equanimity,
and appreciation.
"""

from sqlalchemy import inspect, text

VERSION = 3
DESCRIPTION = "Add expanded valence dimensions (awe, grief, longing, peace, gratitude) and open_questions"


def upgrade(engine):
    """Add new columns to insights table.

    This migration is idempotent - it checks for column existence before adding.
    This handles the case where a fresh database was created with the current
    schema (which already includes these columns).
    """
    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("insights")}

    new_columns = [
        ("valence_awe", "REAL"),
        ("valence_grief", "REAL"),
        ("valence_longing", "REAL"),
        ("valence_peace", "REAL"),
        ("valence_gratitude", "REAL"),
        ("open_questions", "TEXT"),
    ]

    with engine.connect() as conn:
        for col_name, col_type in new_columns:
            if col_name not in columns:
                conn.execute(text(f"ALTER TABLE insights ADD COLUMN {col_name} {col_type}"))
        conn.commit()

    # Note: SQLite doesn't support modifying CHECK constraints directly.
    # The new valence fields are optional additions to the existing constraint.
    # The Pydantic model will enforce the "at least one valence" rule,
    # and new databases will get the updated constraint from database.py.


def check(engine) -> bool:
    """Check if this migration has been applied.

    Returns True if the valence_awe column exists in insights table.
    """
    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("insights")}
    return "valence_awe" in columns
