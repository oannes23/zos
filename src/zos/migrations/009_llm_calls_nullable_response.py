"""Make llm_calls.response nullable for failed call recording.

The schema in database.py already defines response as nullable, but existing
databases created before that change still have a NOT NULL constraint.
SQLite cannot ALTER COLUMN, so we rebuild the table.
"""

from sqlalchemy import inspect, text

VERSION = 9
DESCRIPTION = "Make llm_calls.response nullable for failed call recording"


def upgrade(engine):
    """Rebuild llm_calls table with nullable response column.

    This migration is idempotent - it checks whether the column is already
    nullable before performing the rebuild.
    """
    if check(engine):
        return

    with engine.connect() as conn:
        # Create new table with nullable response
        conn.execute(text("""
            CREATE TABLE llm_calls_new (
                id VARCHAR PRIMARY KEY,
                layer_run_id VARCHAR REFERENCES layer_runs(id),
                topic_key VARCHAR,
                call_type VARCHAR NOT NULL,
                model_profile VARCHAR NOT NULL,
                model_provider VARCHAR NOT NULL,
                model_name VARCHAR NOT NULL,
                prompt TEXT NOT NULL,
                response TEXT,
                tokens_input INTEGER NOT NULL,
                tokens_output INTEGER NOT NULL,
                tokens_total INTEGER NOT NULL,
                estimated_cost_usd FLOAT,
                latency_ms INTEGER,
                success BOOLEAN NOT NULL DEFAULT 1,
                error_message VARCHAR,
                created_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP)
            )
        """))

        # Copy all existing data
        conn.execute(text("""
            INSERT INTO llm_calls_new
            SELECT * FROM llm_calls
        """))

        # Swap tables
        conn.execute(text("DROP TABLE llm_calls"))
        conn.execute(text("ALTER TABLE llm_calls_new RENAME TO llm_calls"))

        # Recreate indexes
        conn.execute(text(
            "CREATE INDEX ix_llm_calls_layer_run ON llm_calls (layer_run_id)"
        ))
        conn.execute(text(
            "CREATE INDEX ix_llm_calls_created ON llm_calls (created_at)"
        ))
        conn.execute(text(
            "CREATE INDEX ix_llm_calls_profile ON llm_calls (model_profile)"
        ))
        conn.execute(text(
            "CREATE INDEX ix_llm_calls_type_created ON llm_calls (call_type, created_at)"
        ))

        conn.commit()


def check(engine) -> bool:
    """Check if this migration has been applied.

    Returns True if the response column in llm_calls is already nullable.
    """
    inspector = inspect(engine)
    if "llm_calls" not in inspector.get_table_names():
        return False

    columns = inspector.get_columns("llm_calls")
    for col in columns:
        if col["name"] == "response":
            return col["nullable"] is True

    return False
