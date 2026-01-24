"""Integration tests for Zos components working together.

Tests the full workflow of configuration, database initialization, migrations,
and data persistence across the system. Exercises real code paths to verify
memory, configuration, and models form a coherent whole supporting Zos's operation.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text

from zos.config import Config
from zos.database import (
    channels,
    create_tables,
    generate_id,
    get_engine,
    insights,
    layer_runs,
    messages,
    reactions,
    salience_ledger,
    servers,
    topics,
    users,
)
from zos.migrations import get_current_version, migrate
from zos.models import (
    Channel,
    ChannelType,
    Insight,
    LayerRun,
    LayerRunStatus,
    Message,
    Reaction,
    SalienceEntry,
    Server,
    Topic,
    TopicCategory,
    TransactionType,
    User,
    VisibilityScope,
    row_to_model,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def test_config(tmp_path: Path) -> Config:
    """Create a test configuration with temp database."""
    return Config(
        data_dir=tmp_path,
        log_level="DEBUG",
    )


@pytest.fixture
def engine(test_config: Config):
    """Create a test database engine (fresh, no migrations yet)."""
    return get_engine(test_config)


@pytest.fixture
def migrated_engine(engine):
    """Create a test database engine with all migrations applied."""
    migrate(engine)
    return engine


# =============================================================================
# Scenario 1: Full Startup Flow
# =============================================================================


class TestStartupFlow:
    """Tests for: load config -> create engine -> run migrations -> verify schema."""

    def test_load_config_defaults(self, tmp_path: Path) -> None:
        """Full startup: Load config with defaults."""
        config = Config(data_dir=tmp_path)

        assert config.data_dir == tmp_path
        assert config.log_level == "INFO"
        assert config.database.path == "zos.db"

    def test_create_engine_creates_file(self, test_config: Config) -> None:
        """Full startup: Create engine initializes database file."""
        engine = get_engine(test_config)

        # File should exist
        assert test_config.database_path.exists()

    def test_engine_has_wal_mode(self, engine) -> None:
        """Full startup: Engine has WAL mode enabled."""
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA journal_mode")).scalar()
            assert result.lower() == "wal"

    def test_engine_has_foreign_keys_enabled(self, engine) -> None:
        """Full startup: Engine has foreign keys enabled."""
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA foreign_keys")).scalar()
            assert result == 1

    def test_run_migrations_creates_tables(self, engine) -> None:
        """Full startup: Migrations create all required tables."""
        # Before migration
        inspector = inspect(engine)
        assert "messages" not in inspector.get_table_names()

        # Run migrations
        version = migrate(engine)

        # After migration
        assert version >= 1
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())

        expected_tables = {
            "servers",
            "users",
            "user_server_tracking",
            "channels",
            "messages",
            "reactions",
            "poll_state",
            "media_analysis",
            "link_analysis",
            "topics",
            "salience_ledger",
            "insights",
            "layer_runs",
            "llm_calls",
            "chattiness_ledger",
            "speech_pressure",
            "conversation_log",
            "draft_history",
            "_schema_version",
        }

        assert expected_tables.issubset(table_names)

    def test_verify_schema_integrity(self, migrated_engine) -> None:
        """Full startup: Schema has correct structure after migration."""
        inspector = inspect(migrated_engine)

        # Verify insights table structure
        columns = {col["name"] for col in inspector.get_columns("insights")}
        required_columns = {
            "id",
            "topic_key",
            "category",
            "content",
            "layer_run_id",
            "valence_joy",
            "valence_concern",
            "valence_curiosity",
            "valence_warmth",
            "valence_tension",
        }
        assert required_columns.issubset(columns)

        # Verify indexes
        insight_indexes = {idx["name"] for idx in inspector.get_indexes("insights")}
        assert "ix_insights_topic_created" in insight_indexes
        assert "ix_insights_layer_run" in insight_indexes

    def test_verify_foreign_keys(self, migrated_engine) -> None:
        """Full startup: Foreign key relationships are configured."""
        inspector = inspect(migrated_engine)

        # Check messages -> channels foreign key
        fks = inspector.get_foreign_keys("messages")
        channel_fks = [fk for fk in fks if fk["constrained_columns"] == ["channel_id"]]
        assert len(channel_fks) > 0
        assert channel_fks[0]["referred_table"] == "channels"


# =============================================================================
# Scenario 2: Complete Message Flow
# =============================================================================


class TestMessageFlow:
    """Tests for: server -> channel -> message -> reaction."""

    def test_insert_server(self, migrated_engine) -> None:
        """Message flow: Insert server."""
        with migrated_engine.connect() as conn:
            server = Server(
                id="guild_123",
                name="Test Guild",
                threads_as_topics=True,
            )

            conn.execute(
                servers.insert().values(
                    id=server.id,
                    name=server.name,
                    threads_as_topics=server.threads_as_topics,
                    created_at=server.created_at,
                )
            )
            conn.commit()

            result = conn.execute(
                select(servers).where(servers.c.id == "guild_123")
            ).fetchone()

            assert result is not None
            assert result.name == "Test Guild"

    def test_insert_user(self, migrated_engine) -> None:
        """Message flow: Insert user."""
        with migrated_engine.connect() as conn:
            user = User(id="user_456")

            conn.execute(users.insert().values(id=user.id))
            conn.commit()

            result = conn.execute(
                select(users).where(users.c.id == "user_456")
            ).fetchone()

            assert result is not None

    def test_insert_channel(self, migrated_engine) -> None:
        """Message flow: Insert channel (requires server)."""
        with migrated_engine.connect() as conn:
            # Create server first
            conn.execute(
                servers.insert().values(
                    id="guild_1",
                    created_at=datetime.now(timezone.utc),
                )
            )

            # Create channel
            channel = Channel(
                id="channel_1",
                server_id="guild_1",
                name="general",
                type=ChannelType.TEXT,
            )

            conn.execute(
                channels.insert().values(
                    id=channel.id,
                    server_id=channel.server_id,
                    name=channel.name,
                    type=channel.type.value,
                    created_at=channel.created_at,
                )
            )
            conn.commit()

            result = conn.execute(
                select(channels).where(channels.c.id == "channel_1")
            ).fetchone()

            assert result is not None
            assert result.server_id == "guild_1"
            assert result.type == "text"

    def test_insert_message(self, migrated_engine) -> None:
        """Message flow: Insert message (requires channel and server)."""
        with migrated_engine.connect() as conn:
            # Create server
            conn.execute(
                servers.insert().values(
                    id="guild_2",
                    created_at=datetime.now(timezone.utc),
                )
            )

            # Create channel
            conn.execute(
                channels.insert().values(
                    id="channel_2",
                    server_id="guild_2",
                    type="text",
                    created_at=datetime.now(timezone.utc),
                )
            )

            # Create message
            message = Message(
                id="msg_1",
                channel_id="channel_2",
                server_id="guild_2",
                author_id="user_1",
                content="Hello, Zos!",
                created_at=datetime.now(timezone.utc),
                visibility_scope=VisibilityScope.PUBLIC,
            )

            conn.execute(
                messages.insert().values(
                    id=message.id,
                    channel_id=message.channel_id,
                    server_id=message.server_id,
                    author_id=message.author_id,
                    content=message.content,
                    created_at=message.created_at,
                    visibility_scope=message.visibility_scope.value,
                    has_media=message.has_media,
                    has_links=message.has_links,
                    ingested_at=message.ingested_at,
                )
            )
            conn.commit()

            result = conn.execute(
                select(messages).where(messages.c.id == "msg_1")
            ).fetchone()

            assert result is not None
            assert result.content == "Hello, Zos!"
            assert result.author_id == "user_1"

    def test_insert_reaction(self, migrated_engine) -> None:
        """Message flow: Insert reaction (requires message)."""
        with migrated_engine.connect() as conn:
            # Create prerequisites
            conn.execute(
                servers.insert().values(
                    id="guild_3",
                    created_at=datetime.now(timezone.utc),
                )
            )
            conn.execute(
                channels.insert().values(
                    id="channel_3",
                    server_id="guild_3",
                    type="text",
                    created_at=datetime.now(timezone.utc),
                )
            )
            conn.execute(
                messages.insert().values(
                    id="msg_2",
                    channel_id="channel_3",
                    server_id="guild_3",
                    author_id="user_2",
                    content="Test",
                    created_at=datetime.now(timezone.utc),
                    visibility_scope="public",
                    has_media=False,
                    has_links=False,
                    ingested_at=datetime.now(timezone.utc),
                )
            )

            # Create reaction
            reaction = Reaction(
                message_id="msg_2",
                user_id="user_3",
                emoji="thumbsup",
                is_custom=False,
            )

            conn.execute(
                reactions.insert().values(
                    id=reaction.id,
                    message_id=reaction.message_id,
                    user_id=reaction.user_id,
                    emoji=reaction.emoji,
                    is_custom=reaction.is_custom,
                    created_at=reaction.created_at,
                )
            )
            conn.commit()

            result = conn.execute(
                select(reactions).where(reactions.c.message_id == "msg_2")
            ).fetchone()

            assert result is not None
            assert result.emoji == "thumbsup"
            assert result.user_id == "user_3"

    def test_complete_message_flow_end_to_end(self, migrated_engine) -> None:
        """Message flow: Complete flow server -> channel -> message -> reaction."""
        now = datetime.now(timezone.utc)

        with migrated_engine.connect() as conn:
            # 1. Create server
            conn.execute(
                servers.insert().values(
                    id="guild_flow",
                    name="Flow Test Guild",
                    created_at=now,
                )
            )

            # 2. Create channel
            conn.execute(
                channels.insert().values(
                    id="chan_flow",
                    server_id="guild_flow",
                    name="flow-test",
                    type="text",
                    created_at=now,
                )
            )

            # 3. Create message
            conn.execute(
                messages.insert().values(
                    id="msg_flow",
                    channel_id="chan_flow",
                    server_id="guild_flow",
                    author_id="user_flow",
                    content="Integration test message",
                    created_at=now,
                    visibility_scope="public",
                    has_media=False,
                    has_links=False,
                    ingested_at=now,
                )
            )

            # 4. Create multiple reactions
            for i, emoji in enumerate(["thumbsup", "heart", "laughing"]):
                conn.execute(
                    reactions.insert().values(
                        id=generate_id(),
                        message_id="msg_flow",
                        user_id=f"reactor_{i}",
                        emoji=emoji,
                        is_custom=False,
                        created_at=now,
                    )
                )

            conn.commit()

            # Verify complete flow
            msg = conn.execute(
                select(messages).where(messages.c.id == "msg_flow")
            ).fetchone()
            assert msg is not None

            reacts = conn.execute(
                select(reactions).where(reactions.c.message_id == "msg_flow")
            ).fetchall()
            assert len(reacts) == 3
            emojis = {r.emoji for r in reacts}
            assert emojis == {"thumbsup", "heart", "laughing"}


# =============================================================================
# Scenario 3: Complete Insight Flow
# =============================================================================


class TestInsightFlow:
    """Tests for: topic -> layer_run -> insight with valence."""

    def test_create_topic(self, migrated_engine) -> None:
        """Insight flow: Create topic."""
        with migrated_engine.connect() as conn:
            topic = Topic(
                key="user:user_123",
                category=TopicCategory.USER,
                is_global=True,
            )

            conn.execute(
                topics.insert().values(
                    key=topic.key,
                    category=topic.category.value,
                    is_global=topic.is_global,
                    provisional=topic.provisional,
                    created_at=topic.created_at,
                )
            )
            conn.commit()

            result = conn.execute(
                select(topics).where(topics.c.key == "user:user_123")
            ).fetchone()

            assert result is not None
            assert result.category == "user"
            assert result.is_global is True

    def test_create_layer_run(self, migrated_engine) -> None:
        """Insight flow: Create layer run."""
        with migrated_engine.connect() as conn:
            layer_run = LayerRun(
                layer_name="user_reflection",
                layer_hash="abc123def456",
                started_at=datetime.now(timezone.utc),
                status=LayerRunStatus.SUCCESS,
                targets_matched=5,
                targets_processed=5,
                insights_created=2,
            )

            conn.execute(
                layer_runs.insert().values(
                    id=layer_run.id,
                    layer_name=layer_run.layer_name,
                    layer_hash=layer_run.layer_hash,
                    started_at=layer_run.started_at,
                    status=layer_run.status.value,
                    targets_matched=layer_run.targets_matched,
                    targets_processed=layer_run.targets_processed,
                    insights_created=layer_run.insights_created,
                )
            )
            conn.commit()

            result = conn.execute(
                select(layer_runs).where(layer_runs.c.id == layer_run.id)
            ).fetchone()

            assert result is not None
            assert result.layer_name == "user_reflection"
            assert result.status == "success"

    def test_create_insight_with_valence(self, migrated_engine) -> None:
        """Insight flow: Create insight with valence."""
        now = datetime.now(timezone.utc)

        with migrated_engine.connect() as conn:
            # Create topic first
            conn.execute(
                topics.insert().values(
                    key="user:insight_test",
                    category="user",
                    is_global=True,
                    provisional=False,
                    created_at=now,
                )
            )

            # Create layer run
            layer_id = generate_id()
            conn.execute(
                layer_runs.insert().values(
                    id=layer_id,
                    layer_name="reflection",
                    layer_hash="hash123",
                    started_at=now,
                    status="success",
                )
            )

            # Create insight with valence
            insight = Insight(
                topic_key="user:insight_test",
                category="user_reflection",
                content="User appears interested in technology discussions.",
                sources_scope_max=VisibilityScope.PUBLIC,
                created_at=now,
                layer_run_id=layer_id,
                salience_spent=10.0,
                strength_adjustment=1.5,
                strength=15.0,
                original_topic_salience=50.0,
                confidence=0.85,
                importance=0.75,
                novelty=0.6,
                valence_curiosity=0.8,  # Valence is set
                valence_warmth=0.3,
            )

            conn.execute(
                insights.insert().values(
                    id=insight.id,
                    topic_key=insight.topic_key,
                    category=insight.category,
                    content=insight.content,
                    sources_scope_max=insight.sources_scope_max.value,
                    created_at=insight.created_at,
                    layer_run_id=insight.layer_run_id,
                    salience_spent=insight.salience_spent,
                    strength_adjustment=insight.strength_adjustment,
                    strength=insight.strength,
                    original_topic_salience=insight.original_topic_salience,
                    confidence=insight.confidence,
                    importance=insight.importance,
                    novelty=insight.novelty,
                    valence_curiosity=insight.valence_curiosity,
                    valence_warmth=insight.valence_warmth,
                )
            )
            conn.commit()

            result = conn.execute(
                select(insights).where(insights.c.id == insight.id)
            ).fetchone()

            assert result is not None
            assert result.valence_curiosity == 0.8
            assert result.valence_warmth == 0.3
            assert result.content == "User appears interested in technology discussions."

    def test_complete_insight_flow_end_to_end(self, migrated_engine) -> None:
        """Insight flow: Complete flow topic -> layer_run -> insight."""
        now = datetime.now(timezone.utc)

        with migrated_engine.connect() as conn:
            # 1. Create topic
            topic_key = "user:flow_test_user"
            conn.execute(
                topics.insert().values(
                    key=topic_key,
                    category="user",
                    is_global=True,
                    provisional=False,
                    created_at=now,
                )
            )

            # 2. Create layer run
            layer_id = generate_id()
            conn.execute(
                layer_runs.insert().values(
                    id=layer_id,
                    layer_name="comprehensive_reflection",
                    layer_hash="hash_integration_test",
                    started_at=now,
                    completed_at=now,
                    status="success",
                    targets_matched=10,
                    targets_processed=10,
                    insights_created=3,
                )
            )

            # 3. Create multiple insights with different valences
            for i, (joy, concern) in enumerate(
                [(0.9, None), (0.2, 0.8), (0.5, 0.3)]
            ):
                insight_id = generate_id()
                conn.execute(
                    insights.insert().values(
                        id=insight_id,
                        topic_key=topic_key,
                        category="reflection",
                        content=f"Insight {i+1}: Understanding about user behavior",
                        sources_scope_max="public",
                        created_at=now,
                        layer_run_id=layer_id,
                        salience_spent=5.0,
                        strength_adjustment=1.0,
                        strength=5.0,
                        original_topic_salience=20.0,
                        confidence=0.8,
                        importance=0.7,
                        novelty=0.6,
                        valence_joy=joy,
                        valence_concern=concern,
                    )
                )

            conn.commit()

            # Verify complete flow
            topic = conn.execute(
                select(topics).where(topics.c.key == topic_key)
            ).fetchone()
            assert topic is not None

            layer_run = conn.execute(
                select(layer_runs).where(layer_runs.c.id == layer_id)
            ).fetchone()
            assert layer_run is not None
            assert layer_run.insights_created == 3

            insights_result = conn.execute(
                select(insights).where(insights.c.layer_run_id == layer_id)
            ).fetchall()
            assert len(insights_result) == 3

            # Verify valence variety
            valences = [
                (i.valence_joy, i.valence_concern) for i in insights_result
            ]
            assert (0.9, None) in valences
            assert (0.2, 0.8) in valences
            assert (0.5, 0.3) in valences


# =============================================================================
# Scenario 4: Salience Ledger Operations
# =============================================================================


class TestSalienceLedger:
    """Tests for: earn -> check balance."""

    def test_earn_salience(self, migrated_engine) -> None:
        """Salience: Earn salience on a topic."""
        now = datetime.now(timezone.utc)

        with migrated_engine.connect() as conn:
            # Create topic
            conn.execute(
                topics.insert().values(
                    key="user:earn_test",
                    category="user",
                    is_global=True,
                    provisional=False,
                    created_at=now,
                )
            )

            # Earn salience
            entry = SalienceEntry(
                topic_key="user:earn_test",
                transaction_type=TransactionType.EARN,
                amount=10.0,
                reason="message_from_user",
            )

            conn.execute(
                salience_ledger.insert().values(
                    id=entry.id,
                    topic_key=entry.topic_key,
                    transaction_type=entry.transaction_type.value,
                    amount=entry.amount,
                    reason=entry.reason,
                    created_at=entry.created_at,
                )
            )
            conn.commit()

            result = conn.execute(
                select(salience_ledger).where(
                    salience_ledger.c.topic_key == "user:earn_test"
                )
            ).fetchone()

            assert result is not None
            assert result.amount == 10.0
            assert result.transaction_type == "earn"

    def test_check_salience_balance(self, migrated_engine) -> None:
        """Salience: Calculate balance by summing transactions."""
        from sqlalchemy import func

        now = datetime.now(timezone.utc)

        with migrated_engine.connect() as conn:
            # Create topic
            conn.execute(
                topics.insert().values(
                    key="user:balance_test",
                    category="user",
                    is_global=True,
                    provisional=False,
                    created_at=now,
                )
            )

            # Earn salience
            for i, amount in enumerate([10.0, 5.0, 3.0]):
                conn.execute(
                    salience_ledger.insert().values(
                        id=generate_id(),
                        topic_key="user:balance_test",
                        transaction_type="earn",
                        amount=amount,
                        created_at=now,
                    )
                )

            # Spend salience (as negative amount)
            conn.execute(
                salience_ledger.insert().values(
                    id=generate_id(),
                    topic_key="user:balance_test",
                    transaction_type="spend",
                    amount=-5.0,
                    created_at=now,
                )
            )

            conn.commit()

            # Calculate balance - need fresh query after commit
            result = conn.execute(
                select(func.sum(salience_ledger.c.amount)).where(
                    salience_ledger.c.topic_key == "user:balance_test"
                )
            ).scalar()

            # 10 + 5 + 3 - 5 = 13
            assert result == 13.0

    def test_salience_ledger_decay_transaction(self, migrated_engine) -> None:
        """Salience: Record decay transaction."""
        now = datetime.now(timezone.utc)

        with migrated_engine.connect() as conn:
            # Create topic
            conn.execute(
                topics.insert().values(
                    key="user:decay_test",
                    category="user",
                    is_global=True,
                    provisional=False,
                    created_at=now,
                )
            )

            # Earn some salience
            conn.execute(
                salience_ledger.insert().values(
                    id=generate_id(),
                    topic_key="user:decay_test",
                    transaction_type="earn",
                    amount=50.0,
                    created_at=now,
                )
            )

            # Record decay
            decay_entry = SalienceEntry(
                topic_key="user:decay_test",
                transaction_type=TransactionType.DECAY,
                amount=-2.5,
                reason="daily_decay",
            )

            conn.execute(
                salience_ledger.insert().values(
                    id=decay_entry.id,
                    topic_key=decay_entry.topic_key,
                    transaction_type=decay_entry.transaction_type.value,
                    amount=decay_entry.amount,
                    reason=decay_entry.reason,
                    created_at=decay_entry.created_at,
                )
            )

            conn.commit()

            # Verify transactions
            results = conn.execute(
                select(salience_ledger).where(
                    salience_ledger.c.topic_key == "user:decay_test"
                )
            ).fetchall()

            assert len(results) == 2
            types = {r.transaction_type for r in results}
            assert types == {"earn", "decay"}

    def test_salience_propagation(self, migrated_engine) -> None:
        """Salience: Record propagation to related topic."""
        now = datetime.now(timezone.utc)

        with migrated_engine.connect() as conn:
            # Create two related topics
            for key in ["channel:general", "user:alice"]:
                conn.execute(
                    topics.insert().values(
                        key=key,
                        category="channel" if key.startswith("channel") else "user",
                        is_global=False,
                        provisional=False,
                        created_at=now,
                    )
                )

            # Earn on source topic
            conn.execute(
                salience_ledger.insert().values(
                    id=generate_id(),
                    topic_key="channel:general",
                    transaction_type="earn",
                    amount=20.0,
                    created_at=now,
                )
            )

            # Propagate to related topic
            propagate_entry = SalienceEntry(
                topic_key="user:alice",
                transaction_type=TransactionType.PROPAGATE,
                amount=6.0,  # 30% of 20
                reason="propagation_from_channel_message",
                source_topic="channel:general",
            )

            conn.execute(
                salience_ledger.insert().values(
                    id=propagate_entry.id,
                    topic_key=propagate_entry.topic_key,
                    transaction_type=propagate_entry.transaction_type.value,
                    amount=propagate_entry.amount,
                    reason=propagate_entry.reason,
                    source_topic=propagate_entry.source_topic,
                    created_at=propagate_entry.created_at,
                )
            )

            conn.commit()

            # Verify propagation chain
            source_balance = conn.execute(
                select(salience_ledger).where(
                    salience_ledger.c.topic_key == "channel:general"
                )
            ).fetchall()
            assert len(source_balance) == 1
            assert source_balance[0].amount == 20.0

            target_balance = conn.execute(
                select(salience_ledger).where(
                    salience_ledger.c.topic_key == "user:alice"
                )
            ).fetchall()
            assert len(target_balance) == 1
            assert target_balance[0].source_topic == "channel:general"

    def test_complete_salience_flow_end_to_end(self, migrated_engine) -> None:
        """Salience: Complete flow earn -> decay -> spend -> check balance."""
        from sqlalchemy import func

        now = datetime.now(timezone.utc)

        with migrated_engine.connect() as conn:
            topic_key = "user:complete_salience_test"

            # 1. Create topic
            conn.execute(
                topics.insert().values(
                    key=topic_key,
                    category="user",
                    is_global=True,
                    provisional=False,
                    created_at=now,
                )
            )

            # 2. Earn salience (message activity)
            conn.execute(
                salience_ledger.insert().values(
                    id=generate_id(),
                    topic_key=topic_key,
                    transaction_type="earn",
                    amount=25.0,
                    reason="user_message",
                    created_at=now,
                )
            )

            # 3. Earn more (reaction)
            conn.execute(
                salience_ledger.insert().values(
                    id=generate_id(),
                    topic_key=topic_key,
                    transaction_type="earn",
                    amount=10.0,
                    reason="user_reaction",
                    created_at=now,
                )
            )

            # 4. Spend on insight (negative amount)
            conn.execute(
                salience_ledger.insert().values(
                    id=generate_id(),
                    topic_key=topic_key,
                    transaction_type="spend",
                    amount=-15.0,
                    reason="insight_creation",
                    created_at=now,
                )
            )

            # 5. Record decay (negative amount)
            conn.execute(
                salience_ledger.insert().values(
                    id=generate_id(),
                    topic_key=topic_key,
                    transaction_type="decay",
                    amount=-2.0,
                    reason="daily_decay",
                    created_at=now,
                )
            )

            conn.commit()

            # Verify complete flow - calculate balance
            result = conn.execute(
                select(func.sum(salience_ledger.c.amount)).where(
                    salience_ledger.c.topic_key == topic_key
                )
            ).scalar()

            # 25 + 10 - 15 - 2 = 18
            assert result == 18.0

            # Verify transaction types are recorded
            transactions = conn.execute(
                select(salience_ledger).where(
                    salience_ledger.c.topic_key == topic_key
                )
            ).fetchall()

            types = {t.transaction_type for t in transactions}
            assert types == {"earn", "spend", "decay"}


# =============================================================================
# Scenario 5: Foreign Key Relationships End-to-End
# =============================================================================


class TestForeignKeyRelationships:
    """Tests for: foreign key relationships work correctly end-to-end."""

    def test_message_requires_channel(self, migrated_engine) -> None:
        """FK: Message insert fails without valid channel."""
        with migrated_engine.connect() as conn:
            pytest.importorskip("sqlalchemy.exc")
            from sqlalchemy.exc import IntegrityError

            with pytest.raises(IntegrityError):
                conn.execute(
                    messages.insert().values(
                        id="orphan_msg",
                        channel_id="nonexistent_channel",
                        author_id="user",
                        content="Orphan message",
                        created_at=datetime.now(timezone.utc),
                        visibility_scope="public",
                        has_media=False,
                        has_links=False,
                        ingested_at=datetime.now(timezone.utc),
                    )
                )
                conn.commit()

    def test_channel_requires_server(self, migrated_engine) -> None:
        """FK: Channel insert fails without valid server."""
        with migrated_engine.connect() as conn:
            pytest.importorskip("sqlalchemy.exc")
            from sqlalchemy.exc import IntegrityError

            with pytest.raises(IntegrityError):
                conn.execute(
                    channels.insert().values(
                        id="orphan_chan",
                        server_id="nonexistent_server",
                        type="text",
                        created_at=datetime.now(timezone.utc),
                    )
                )
                conn.commit()

    def test_reaction_requires_message(self, migrated_engine) -> None:
        """FK: Reaction insert fails without valid message."""
        with migrated_engine.connect() as conn:
            pytest.importorskip("sqlalchemy.exc")
            from sqlalchemy.exc import IntegrityError

            with pytest.raises(IntegrityError):
                conn.execute(
                    reactions.insert().values(
                        id=generate_id(),
                        message_id="nonexistent_msg",
                        user_id="user",
                        emoji="reaction",
                        is_custom=False,
                        created_at=datetime.now(timezone.utc),
                    )
                )
                conn.commit()

    def test_salience_entry_requires_topic(self, migrated_engine) -> None:
        """FK: Salience entry insert fails without valid topic."""
        with migrated_engine.connect() as conn:
            pytest.importorskip("sqlalchemy.exc")
            from sqlalchemy.exc import IntegrityError

            with pytest.raises(IntegrityError):
                conn.execute(
                    salience_ledger.insert().values(
                        id=generate_id(),
                        topic_key="nonexistent:topic",
                        transaction_type="earn",
                        amount=10.0,
                        created_at=datetime.now(timezone.utc),
                    )
                )
                conn.commit()

    def test_insight_requires_topic_and_layer_run(self, migrated_engine) -> None:
        """FK: Insight insert fails without valid topic and layer_run."""
        with migrated_engine.connect() as conn:
            pytest.importorskip("sqlalchemy.exc")
            from sqlalchemy.exc import IntegrityError

            # Topic exists, layer_run doesn't
            conn.execute(
                topics.insert().values(
                    key="user:fk_test",
                    category="user",
                    is_global=True,
                    provisional=False,
                    created_at=datetime.now(timezone.utc),
                )
            )
            conn.commit()

            # Try to insert insight with nonexistent layer_run
            with pytest.raises(IntegrityError):
                conn.execute(
                    insights.insert().values(
                        id=generate_id(),
                        topic_key="user:fk_test",
                        category="reflection",
                        content="Test",
                        sources_scope_max="public",
                        created_at=datetime.now(timezone.utc),
                        layer_run_id="nonexistent_layer",
                        salience_spent=5.0,
                        strength_adjustment=1.0,
                        strength=5.0,
                        original_topic_salience=10.0,
                        confidence=0.8,
                        importance=0.7,
                        novelty=0.5,
                        valence_joy=0.5,
                    )
                )
                conn.commit()

    def test_cascading_relationships(self, migrated_engine) -> None:
        """FK: Relationships cascade correctly through the hierarchy."""
        now = datetime.now(timezone.utc)

        with migrated_engine.connect() as conn:
            # Create complete chain: server -> channel -> message -> reaction
            server_id = "cascade_server"
            channel_id = "cascade_channel"
            message_id = "cascade_msg"

            conn.execute(
                servers.insert().values(
                    id=server_id,
                    created_at=now,
                )
            )
            conn.execute(
                channels.insert().values(
                    id=channel_id,
                    server_id=server_id,
                    type="text",
                    created_at=now,
                )
            )
            conn.execute(
                messages.insert().values(
                    id=message_id,
                    channel_id=channel_id,
                    server_id=server_id,
                    author_id="author",
                    content="Test",
                    created_at=now,
                    visibility_scope="public",
                    has_media=False,
                    has_links=False,
                    ingested_at=now,
                )
            )

            # Create reactions
            for i in range(3):
                conn.execute(
                    reactions.insert().values(
                        id=generate_id(),
                        message_id=message_id,
                        user_id=f"reactor_{i}",
                        emoji="emoji",
                        is_custom=False,
                        created_at=now,
                    )
                )

            conn.commit()

            # Verify complete chain exists
            reactions_result = conn.execute(
                select(reactions).where(reactions.c.message_id == message_id)
            ).fetchall()

            assert len(reactions_result) == 3

            # Verify they all reference the same message
            for reaction in reactions_result:
                assert reaction.message_id == message_id

                # Message references channel
                msg = conn.execute(
                    select(messages).where(messages.c.id == reaction.message_id)
                ).fetchone()
                assert msg.channel_id == channel_id

                # Channel references server
                chan = conn.execute(
                    select(channels).where(channels.c.id == msg.channel_id)
                ).fetchone()
                assert chan.server_id == server_id
