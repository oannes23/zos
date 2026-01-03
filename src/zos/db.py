"""Database connection and migration management for Zos."""

import sqlite3
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from zos.config import DatabaseConfig, get_config
from zos.exceptions import DatabaseError, MigrationError
from zos.logging import get_logger

logger = get_logger("db")

# Current schema version
SCHEMA_VERSION = 8

# Base schema SQL
BASE_SCHEMA = """
-- Metadata table for tracking schema version and other info
CREATE TABLE IF NOT EXISTS zos_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Insert initial schema version
INSERT OR IGNORE INTO zos_metadata (key, value) VALUES ('schema_version', '0');
"""


# Migrations are functions that take a connection and upgrade from version N to N+1
MIGRATIONS: dict[int, str] = {
    # Migration from version 0 to 1: base tables
    1: """
    -- Schema version 1: Foundation tables

    -- Update schema version
    UPDATE zos_metadata SET value = '1', updated_at = datetime('now') WHERE key = 'schema_version';
    """,
    # Migration from version 1 to 2: Discord ingestion tables
    2: """
    -- Schema version 2: Discord ingestion tables

    -- Messages table
    CREATE TABLE IF NOT EXISTS messages (
        message_id INTEGER PRIMARY KEY,  -- Discord snowflake ID
        guild_id INTEGER,                -- NULL for DMs
        channel_id INTEGER NOT NULL,
        thread_id INTEGER,               -- NULL if not in thread
        author_id INTEGER NOT NULL,
        author_roles_snapshot TEXT NOT NULL DEFAULT '[]',  -- JSON array of role IDs
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,        -- ISO8601 timestamp
        edited_at TEXT,                  -- ISO8601 timestamp, NULL if never edited
        visibility_scope TEXT NOT NULL CHECK (visibility_scope IN ('public', 'dm')),
        is_deleted INTEGER NOT NULL DEFAULT 0,  -- Soft delete flag
        deleted_at TEXT                  -- ISO8601 timestamp when deleted
    );

    -- Indexes for common queries
    CREATE INDEX IF NOT EXISTS idx_messages_channel_id ON messages(channel_id);
    CREATE INDEX IF NOT EXISTS idx_messages_author_id ON messages(author_id);
    CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);
    CREATE INDEX IF NOT EXISTS idx_messages_guild_channel ON messages(guild_id, channel_id);

    -- Reactions table
    CREATE TABLE IF NOT EXISTS reactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id INTEGER NOT NULL,
        emoji TEXT NOT NULL,             -- Unicode or custom emoji (name:id)
        user_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,        -- ISO8601 timestamp
        is_removed INTEGER NOT NULL DEFAULT 0,  -- Track removal
        FOREIGN KEY (message_id) REFERENCES messages(message_id),
        UNIQUE(message_id, emoji, user_id)
    );

    CREATE INDEX IF NOT EXISTS idx_reactions_message_id ON reactions(message_id);
    CREATE INDEX IF NOT EXISTS idx_reactions_user_id ON reactions(user_id);

    -- Update schema version
    UPDATE zos_metadata SET value = '2', updated_at = datetime('now') WHERE key = 'schema_version';
    """,
    # Migration from version 2 to 3: Add name columns and tracking flag
    3: """
    -- Schema version 3: Name columns and user tracking

    -- Add name columns to messages table
    ALTER TABLE messages ADD COLUMN author_name TEXT;
    ALTER TABLE messages ADD COLUMN channel_name TEXT;
    ALTER TABLE messages ADD COLUMN guild_name TEXT;

    -- Add tracking flag (1 = user has opt-in role, 0 = they don't)
    -- Default 1 for backwards compatibility (existing messages treated as tracked)
    ALTER TABLE messages ADD COLUMN is_tracked INTEGER NOT NULL DEFAULT 1;

    -- Add user_name to reactions table
    ALTER TABLE reactions ADD COLUMN user_name TEXT;

    -- Index for querying by tracking status
    CREATE INDEX IF NOT EXISTS idx_messages_is_tracked ON messages(is_tracked);

    -- Update schema version
    UPDATE zos_metadata SET value = '3', updated_at = datetime('now') WHERE key = 'schema_version';
    """,
    # Migration from version 3 to 4: Salience ledger tables
    4: """
    -- Schema version 4: Salience ledger tables

    -- Salience earned from activity
    CREATE TABLE IF NOT EXISTS salience_earned (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_key TEXT NOT NULL,           -- Canonical key string (e.g., user:123)
        category TEXT NOT NULL,            -- user, channel, user_in_channel, dyad, dyad_in_channel
        timestamp TEXT NOT NULL,           -- ISO8601 when salience was earned
        amount REAL NOT NULL,              -- Amount earned (can be fractional)
        reason TEXT NOT NULL,              -- message, reaction_given, reaction_received, mention
        message_id INTEGER,                -- Source message ID (nullable for derived events)
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    -- Indexes for salience queries
    CREATE INDEX IF NOT EXISTS idx_salience_earned_topic ON salience_earned(topic_key);
    CREATE INDEX IF NOT EXISTS idx_salience_earned_category ON salience_earned(category);
    CREATE INDEX IF NOT EXISTS idx_salience_earned_timestamp ON salience_earned(timestamp);
    CREATE INDEX IF NOT EXISTS idx_salience_earned_category_timestamp ON salience_earned(category, timestamp);

    -- Salience spent during reflection runs
    CREATE TABLE IF NOT EXISTS salience_spent (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_key TEXT NOT NULL,
        category TEXT NOT NULL,
        run_id TEXT NOT NULL,              -- UUID of the reflection run
        layer TEXT NOT NULL,               -- Layer that spent this salience
        node TEXT,                         -- Optional: specific node within layer
        amount REAL NOT NULL,
        timestamp TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_salience_spent_topic ON salience_spent(topic_key);
    CREATE INDEX IF NOT EXISTS idx_salience_spent_run ON salience_spent(run_id);

    -- Update schema version
    UPDATE zos_metadata SET value = '4', updated_at = datetime('now') WHERE key = 'schema_version';
    """,
    # Migration from version 4 to 5: Budget allocation tables
    5: """
    -- Schema version 5: Budget allocation and LLM call tracking

    -- Token allocations per topic for a reflection run
    CREATE TABLE IF NOT EXISTS token_allocations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,               -- UUID of the reflection run
        topic_key TEXT NOT NULL,            -- Canonical key string
        category TEXT NOT NULL,             -- user, channel, etc.
        allocated_tokens INTEGER NOT NULL,  -- Tokens allocated to this topic
        spent_tokens INTEGER NOT NULL DEFAULT 0,  -- Tokens actually spent
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(run_id, topic_key)
    );

    CREATE INDEX IF NOT EXISTS idx_token_alloc_run ON token_allocations(run_id);
    CREATE INDEX IF NOT EXISTS idx_token_alloc_topic ON token_allocations(topic_key);

    -- Individual LLM call records
    CREATE TABLE IF NOT EXISTS llm_calls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,               -- UUID of the reflection run
        topic_key TEXT,                     -- Topic this call was for (nullable for run-level calls)
        layer TEXT NOT NULL,                -- Layer that made the call
        node TEXT,                          -- Specific node within layer
        model TEXT NOT NULL,                -- Model identifier used
        prompt_tokens INTEGER NOT NULL,     -- Input tokens
        completion_tokens INTEGER NOT NULL, -- Output tokens
        total_tokens INTEGER NOT NULL,      -- Total tokens (cached for convenience)
        estimated_cost_usd REAL,            -- Estimated cost in USD (nullable)
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_llm_calls_run ON llm_calls(run_id);
    CREATE INDEX IF NOT EXISTS idx_llm_calls_topic ON llm_calls(topic_key);

    -- Update schema version
    UPDATE zos_metadata SET value = '5', updated_at = datetime('now') WHERE key = 'schema_version';
    """,
    # Migration from version 5 to 6: Thread parent tracking and query indexes
    6: """
    -- Schema version 6: Thread parent tracking and message query indexes

    -- Add parent_channel_id for thread messages
    -- For regular channel messages: NULL
    -- For thread messages: the parent channel ID
    ALTER TABLE messages ADD COLUMN parent_channel_id INTEGER;

    -- Index for finding threads by parent channel
    CREATE INDEX IF NOT EXISTS idx_messages_parent_channel ON messages(parent_channel_id);

    -- Performance indexes for message queries (context assembly)
    CREATE INDEX IF NOT EXISTS idx_messages_channel_time ON messages(channel_id, created_at);
    CREATE INDEX IF NOT EXISTS idx_messages_author_time ON messages(author_id, created_at);

    -- Update schema version
    UPDATE zos_metadata SET value = '6', updated_at = datetime('now') WHERE key = 'schema_version';
    """,
    # Migration from version 6 to 7: Run management and scheduling
    7: """
    -- Schema version 7: Run management and scheduling

    -- Runs table - tracks each layer execution
    CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,           -- UUID from AllocationPlan
        layer_name TEXT NOT NULL,          -- Layer identifier
        triggered_by TEXT NOT NULL,        -- 'schedule', 'manual', 'api'
        schedule_expression TEXT,          -- Cron expression if scheduled

        -- Timing
        started_at TEXT NOT NULL,          -- ISO8601 when run began
        completed_at TEXT,                 -- ISO8601 when run finished (null if still running)

        -- Status
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
        error_message TEXT,                -- Error details if failed

        -- Execution window
        window_start TEXT NOT NULL,        -- ISO8601 start of time window for messages
        window_end TEXT NOT NULL,          -- ISO8601 end of time window (run start time)

        -- Metrics (populated on completion)
        targets_total INTEGER DEFAULT 0,   -- Total targets considered
        targets_processed INTEGER DEFAULT 0,
        targets_skipped INTEGER DEFAULT 0,

        -- Token and cost tracking
        tokens_used INTEGER DEFAULT 0,
        estimated_cost_usd REAL DEFAULT 0.0,

        -- Salience spent during this run
        salience_spent REAL DEFAULT 0.0,

        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_runs_layer ON runs(layer_name);
    CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
    CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at);
    CREATE INDEX IF NOT EXISTS idx_runs_layer_status ON runs(layer_name, status);

    -- Run traces - detailed execution log per node
    CREATE TABLE IF NOT EXISTS run_traces (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        node_name TEXT NOT NULL,
        topic_key TEXT,                    -- Target topic (nullable for non-target nodes)

        -- Execution result
        success INTEGER NOT NULL,          -- Boolean
        skipped INTEGER NOT NULL DEFAULT 0,
        skip_reason TEXT,
        error TEXT,

        -- Metrics
        tokens_used INTEGER DEFAULT 0,

        -- Timing
        executed_at TEXT NOT NULL,         -- ISO8601

        FOREIGN KEY (run_id) REFERENCES runs(run_id)
    );

    CREATE INDEX IF NOT EXISTS idx_run_traces_run ON run_traces(run_id);
    CREATE INDEX IF NOT EXISTS idx_run_traces_node ON run_traces(node_name);

    -- Update schema version
    UPDATE zos_metadata SET value = '7', updated_at = datetime('now') WHERE key = 'schema_version';
    """,
    # Migration from version 7 to 8: Insights storage
    8: """
    -- Schema version 8: Insights storage

    -- Insights table - stores reflection outputs
    CREATE TABLE IF NOT EXISTS insights (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        insight_id TEXT UNIQUE NOT NULL,      -- UUID for external reference
        topic_key TEXT NOT NULL,              -- Canonical key (e.g., "user:123")
        created_at TEXT NOT NULL,             -- ISO8601 timestamp
        summary TEXT NOT NULL,                -- Main insight text content
        payload TEXT,                         -- Optional JSON structured data
        source_refs TEXT NOT NULL DEFAULT '[]', -- JSON array of message IDs
        sources_scope_max TEXT NOT NULL DEFAULT 'public' CHECK (sources_scope_max IN ('public', 'dm')),
        run_id TEXT,                          -- UUID of generating run
        layer TEXT,                           -- Layer that generated this
        FOREIGN KEY (run_id) REFERENCES runs(run_id)
    );

    -- Indexes for common queries
    CREATE INDEX IF NOT EXISTS idx_insights_topic ON insights(topic_key);
    CREATE INDEX IF NOT EXISTS idx_insights_created ON insights(created_at);
    CREATE INDEX IF NOT EXISTS idx_insights_run ON insights(run_id);
    CREATE INDEX IF NOT EXISTS idx_insights_scope ON insights(sources_scope_max);
    CREATE INDEX IF NOT EXISTS idx_insights_topic_created ON insights(topic_key, created_at);

    -- Update schema version
    UPDATE zos_metadata SET value = '8', updated_at = datetime('now') WHERE key = 'schema_version';
    """,
}


class Database:
    """SQLite database manager with connection pooling and migrations."""

    def __init__(self, config: DatabaseConfig | None = None) -> None:
        """Initialize the database manager.

        Args:
            config: Database configuration. If None, uses global config.
        """
        if config is None:
            config = get_config().database
        self.db_path = Path(config.path).expanduser()
        self._connection: sqlite3.Connection | None = None

    def _ensure_directory(self) -> None:
        """Ensure the database directory exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create the database connection."""
        if self._connection is None:
            self._ensure_directory()
            self._connection = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                isolation_level="DEFERRED",  # Use deferred transactions
            )
            self._connection.row_factory = sqlite3.Row
            # Enable foreign keys
            self._connection.execute("PRAGMA foreign_keys = ON")
            # Enable WAL mode for better concurrency
            self._connection.execute("PRAGMA journal_mode = WAL")
        return self._connection

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for database transactions.

        Yields:
            The database connection within a transaction.
        """
        conn = self._get_connection()
        # Save current isolation level and switch to manual mode
        old_isolation = conn.isolation_level
        conn.isolation_level = None  # Autocommit off, manual control
        try:
            conn.execute("BEGIN")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.isolation_level = old_isolation

    def execute(
        self, sql: str, params: tuple[Any, ...] | dict[str, Any] | None = None
    ) -> sqlite3.Cursor:
        """Execute a SQL statement.

        Args:
            sql: SQL statement to execute.
            params: Optional parameters for the statement.

        Returns:
            The cursor from the execution.
        """
        conn = self._get_connection()
        if params is None:
            return conn.execute(sql)
        return conn.execute(sql, params)

    def executemany(
        self, sql: str, params_list: Sequence[tuple[Any, ...]] | Sequence[dict[str, Any]]
    ) -> sqlite3.Cursor:
        """Execute a SQL statement with multiple parameter sets.

        Args:
            sql: SQL statement to execute.
            params_list: List of parameter sets.

        Returns:
            The cursor from the execution.
        """
        conn = self._get_connection()
        return conn.executemany(sql, params_list)

    def executescript(self, sql: str) -> None:
        """Execute a SQL script (multiple statements).

        Args:
            sql: SQL script to execute.
        """
        conn = self._get_connection()
        conn.executescript(sql)

    def get_schema_version(self) -> int:
        """Get the current schema version.

        Returns:
            The current schema version number.
        """
        try:
            result = self.execute(
                "SELECT value FROM zos_metadata WHERE key = 'schema_version'"
            ).fetchone()
            if result:
                return int(result[0])
            return 0
        except sqlite3.OperationalError:
            # Table doesn't exist yet
            return 0

    def initialize(self) -> None:
        """Initialize the database with base schema if needed."""
        logger.info(f"Initializing database at {self.db_path}")
        self.executescript(BASE_SCHEMA)
        self.migrate()

    def migrate(self) -> None:
        """Run any pending migrations."""
        current_version = self.get_schema_version()
        target_version = SCHEMA_VERSION

        if current_version >= target_version:
            logger.debug(f"Database already at version {current_version}")
            return

        logger.info(f"Migrating database from version {current_version} to {target_version}")

        for version in range(current_version + 1, target_version + 1):
            if version not in MIGRATIONS:
                raise MigrationError(f"Missing migration for version {version}")

            logger.info(f"Applying migration {version}")
            try:
                # executescript handles its own transaction
                self.executescript(MIGRATIONS[version])
            except Exception as e:
                raise MigrationError(f"Failed to apply migration {version}: {e}") from e

        logger.info(f"Database migrated to version {target_version}")

    def close(self) -> None:
        """Close the database connection."""
        if self._connection:
            self._connection.close()
            self._connection = None


# Global database instance
_db: Database | None = None


def get_db() -> Database:
    """Get the global database instance.

    Returns:
        The global Database instance.

    Raises:
        DatabaseError: If database is not initialized.
    """
    global _db
    if _db is None:
        raise DatabaseError("Database not initialized. Call init_db() first.")
    return _db


def init_db(config: DatabaseConfig | None = None) -> Database:
    """Initialize the global database.

    Args:
        config: Optional database configuration.

    Returns:
        The initialized Database instance.
    """
    global _db
    _db = Database(config)
    _db.initialize()
    return _db


def close_db() -> None:
    """Close the global database connection."""
    global _db
    if _db:
        _db.close()
        _db = None
