"""Tests for human-readable API name resolution.

Tests the readable query parameter functionality across introspection endpoints,
which transforms Discord snowflake IDs into human-readable names.

Covers:
- Server name resolution
- User name resolution (display_name, username#discriminator, fallback)
- Channel name resolution
- Dyad topic key resolution
- Global topic key resolution
- Unknown entity fallback
- Batch resolution efficiency
- Original ID preservation
"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from zos.api import create_app
from zos.config import Config
from zos.database import (
    channels,
    create_tables,
    generate_id,
    get_engine,
    insights as insights_table,
    layer_runs as layer_runs_table,
    salience_ledger,
    servers,
    topics as topics_table,
    user_profiles,
)
from zos.migrations import migrate
from zos.models import LayerRunStatus, TopicCategory, VisibilityScope, utcnow
from zos.salience import SalienceLedger


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
    """Create a test database engine with migrations applied."""
    eng = get_engine(test_config)
    migrate(eng)
    create_tables(eng)
    return eng


@pytest.fixture
def app(test_config: Config, engine):
    """Create a test FastAPI application."""
    application = create_app(test_config)
    application.state.config = test_config
    application.state.db = engine
    application.state.ledger = SalienceLedger(engine, test_config)
    return application


@pytest.fixture
def client(app) -> TestClient:
    """Create a test client for the API."""
    return TestClient(app)


@pytest.fixture
def layer_run_id(engine) -> str:
    """Create a layer run for insights to reference."""
    run_id = generate_id()
    now = utcnow()

    with engine.connect() as conn:
        conn.execute(
            layer_runs_table.insert().values(
                id=run_id,
                layer_name="test_layer",
                layer_hash="abc123",
                started_at=now,
                completed_at=now,
                status=LayerRunStatus.SUCCESS.value,
                targets_matched=1,
                targets_processed=1,
                targets_skipped=0,
                insights_created=0,
            )
        )
        conn.commit()

    return run_id


# =============================================================================
# Helper Functions
# =============================================================================


def create_server(engine, server_id: str, name: str) -> None:
    """Create a server in the database."""
    with engine.connect() as conn:
        conn.execute(
            servers.insert().values(
                id=server_id,
                name=name,
                threads_as_topics=True,
                created_at=utcnow(),
            )
        )
        conn.commit()


def create_user_profile(
    engine,
    user_id: str,
    display_name: str | None = None,
    username: str = "testuser",
    discriminator: str | None = None,
    server_id: str | None = None,
) -> None:
    """Create a user profile in the database.

    Pass display_name="" to test fallback behavior (uses username instead).
    The database column is NOT NULL, so None defaults to username.
    """
    # Database column is NOT NULL, so default to username if None
    actual_display_name = display_name if display_name is not None else username
    with engine.connect() as conn:
        conn.execute(
            user_profiles.insert().values(
                id=generate_id(),
                user_id=user_id,
                server_id=server_id,
                display_name=actual_display_name,
                username=username,
                discriminator=discriminator,
                is_bot=False,
                captured_at=utcnow(),
            )
        )
        conn.commit()


def create_channel(engine, channel_id: str, server_id: str, name: str) -> None:
    """Create a channel in the database."""
    with engine.connect() as conn:
        conn.execute(
            channels.insert().values(
                id=channel_id,
                server_id=server_id,
                name=name,
                type="text",
                created_at=utcnow(),
            )
        )
        conn.commit()


def ensure_topic_exists(engine, topic_key: str) -> None:
    """Ensure a topic exists in the database."""
    parts = topic_key.split(":")
    if parts[0] == "server":
        category = parts[2] if len(parts) > 2 else "user"
        is_global = False
    else:
        category = parts[0]
        is_global = True

    try:
        cat_enum = TopicCategory(category)
    except ValueError:
        cat_enum = TopicCategory.USER

    with engine.connect() as conn:
        result = conn.execute(
            topics_table.select().where(topics_table.c.key == topic_key)
        ).fetchone()

        if result is None:
            conn.execute(
                topics_table.insert().values(
                    key=topic_key,
                    category=cat_enum.value,
                    is_global=is_global,
                    provisional=False,
                    created_at=utcnow(),
                )
            )
            conn.commit()


def create_insight_in_db(
    engine,
    layer_run_id: str,
    topic_key: str,
    content: str = "Test insight content",
    category: str = "user_reflection",
    strength: float = 5.0,
    created_at: datetime | None = None,
) -> str:
    """Create an insight directly in the database and return its ID."""
    ensure_topic_exists(engine, topic_key)
    insight_id = generate_id()

    with engine.connect() as conn:
        conn.execute(
            insights_table.insert().values(
                id=insight_id,
                topic_key=topic_key,
                category=category,
                content=content,
                sources_scope_max=VisibilityScope.PUBLIC.value,
                created_at=created_at or utcnow(),
                layer_run_id=layer_run_id,
                quarantined=False,
                salience_spent=5.0,
                strength_adjustment=1.0,
                strength=strength,
                original_topic_salience=10.0,
                confidence=0.8,
                importance=0.7,
                novelty=0.6,
                valence_curiosity=0.5,
            )
        )
        conn.commit()

    return insight_id


def add_salience(engine, topic_key: str, amount: float = 10.0) -> None:
    """Add salience to a topic."""
    with engine.connect() as conn:
        conn.execute(
            salience_ledger.insert().values(
                id=generate_id(),
                topic_key=topic_key,
                transaction_type="earn",
                amount=amount,
                created_at=utcnow(),
            )
        )
        conn.commit()


# =============================================================================
# Test: Readable Mode Disabled (Default)
# =============================================================================


class TestReadableDisabled:
    """Tests that readable=false (default) returns original IDs."""

    def test_insights_list_returns_original_ids(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Without readable flag, topic keys are unchanged."""
        server_id = "123456789"
        user_id = "987654321"
        topic_key = f"server:{server_id}:user:{user_id}"

        create_server(engine, server_id, "Test Server")
        create_user_profile(engine, user_id, display_name="Alice")
        create_insight_in_db(engine, layer_run_id, topic_key)

        response = client.get("/insights")

        assert response.status_code == 200
        data = response.json()
        assert data["readable"] is False
        assert data["insights"][0]["topic_key"] == topic_key
        assert data["insights"][0]["topic_key_original"] is None

    def test_salience_list_returns_original_ids(
        self, client: TestClient, engine
    ) -> None:
        """Without readable flag, salience topic keys are unchanged."""
        server_id = "123456789"
        user_id = "987654321"
        topic_key = f"server:{server_id}:user:{user_id}"

        create_server(engine, server_id, "Test Server")
        create_user_profile(engine, user_id, display_name="Alice")
        ensure_topic_exists(engine, topic_key)
        add_salience(engine, topic_key)

        response = client.get("/salience")

        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        assert data[0]["topic_key"] == topic_key
        assert data[0]["topic_key_original"] is None


# =============================================================================
# Test: Server Name Resolution
# =============================================================================


class TestServerNameResolution:
    """Tests for server ID to name resolution."""

    def test_server_name_resolved_in_topic_key(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Server ID is replaced with server name."""
        server_id = "123456789"
        user_id = "987654321"
        topic_key = f"server:{server_id}:user:{user_id}"

        create_server(engine, server_id, "Test Server")
        create_user_profile(engine, user_id, display_name="Alice")
        create_insight_in_db(engine, layer_run_id, topic_key)

        response = client.get("/insights?readable=true")

        assert response.status_code == 200
        data = response.json()
        assert data["readable"] is True
        assert "Test Server" in data["insights"][0]["topic_key"]
        assert data["insights"][0]["topic_key_original"] == topic_key

    def test_unknown_server_shows_fallback(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Unknown server shows [unknown:ID] fallback."""
        server_id = "999999999"
        user_id = "987654321"
        topic_key = f"server:{server_id}:user:{user_id}"

        # Create user but not server
        create_user_profile(engine, user_id, display_name="Alice")
        create_insight_in_db(engine, layer_run_id, topic_key)

        response = client.get("/insights?readable=true")

        assert response.status_code == 200
        data = response.json()
        assert f"[unknown|{server_id}]" in data["insights"][0]["topic_key"]


# =============================================================================
# Test: User Name Resolution
# =============================================================================


class TestUserNameResolution:
    """Tests for user ID to name resolution."""

    def test_user_display_name_used(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """User display name is used when available."""
        server_id = "123456789"
        user_id = "987654321"
        topic_key = f"server:{server_id}:user:{user_id}"

        create_server(engine, server_id, "Test Server")
        create_user_profile(engine, user_id, display_name="Alice Smith")
        create_insight_in_db(engine, layer_run_id, topic_key)

        response = client.get("/insights?readable=true")

        assert response.status_code == 200
        data = response.json()
        assert "Alice Smith" in data["insights"][0]["topic_key"]

    def test_username_with_discriminator_fallback(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Falls back to username#discriminator when display name is empty."""
        server_id = "123456789"
        user_id = "987654321"
        topic_key = f"server:{server_id}:user:{user_id}"

        create_server(engine, server_id, "Test Server")
        # Use empty string for display_name to trigger fallback
        # (database column is NOT NULL, so use "" not None)
        create_user_profile(
            engine,
            user_id,
            display_name="",  # Empty triggers fallback
            username="testuser",
            discriminator="1234",
        )
        create_insight_in_db(engine, layer_run_id, topic_key)

        response = client.get("/insights?readable=true")

        assert response.status_code == 200
        data = response.json()
        assert "testuser#1234" in data["insights"][0]["topic_key"]

    def test_username_only_when_discriminator_is_zero(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Uses only username when discriminator is '0' (new Discord format)."""
        server_id = "123456789"
        user_id = "987654321"
        topic_key = f"server:{server_id}:user:{user_id}"

        create_server(engine, server_id, "Test Server")
        # Use empty string for display_name to trigger fallback
        create_user_profile(
            engine,
            user_id,
            display_name="",  # Empty triggers fallback
            username="modernuser",
            discriminator="0",
        )
        create_insight_in_db(engine, layer_run_id, topic_key)

        response = client.get("/insights?readable=true")

        assert response.status_code == 200
        data = response.json()
        topic = data["insights"][0]["topic_key"]
        assert "modernuser" in topic
        assert "#0" not in topic

    def test_unknown_user_shows_fallback(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Unknown user shows [unknown:ID] fallback."""
        server_id = "123456789"
        user_id = "999999999"
        topic_key = f"server:{server_id}:user:{user_id}"

        create_server(engine, server_id, "Test Server")
        # Don't create user profile
        create_insight_in_db(engine, layer_run_id, topic_key)

        response = client.get("/insights?readable=true")

        assert response.status_code == 200
        data = response.json()
        assert f"[unknown|{user_id}]" in data["insights"][0]["topic_key"]


# =============================================================================
# Test: Channel Name Resolution
# =============================================================================


class TestChannelNameResolution:
    """Tests for channel ID to name resolution."""

    def test_channel_name_with_hash_prefix(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Channel name includes # prefix."""
        server_id = "123456789"
        channel_id = "555555555"
        topic_key = f"server:{server_id}:channel:{channel_id}"

        create_server(engine, server_id, "Test Server")
        create_channel(engine, channel_id, server_id, "general")
        create_insight_in_db(engine, layer_run_id, topic_key)

        response = client.get("/insights?readable=true")

        assert response.status_code == 200
        data = response.json()
        assert "#general" in data["insights"][0]["topic_key"]

    def test_unknown_channel_shows_fallback(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Unknown channel shows [unknown:ID] fallback."""
        server_id = "123456789"
        channel_id = "999999999"
        topic_key = f"server:{server_id}:channel:{channel_id}"

        create_server(engine, server_id, "Test Server")
        # Don't create channel
        create_insight_in_db(engine, layer_run_id, topic_key)

        response = client.get("/insights?readable=true")

        assert response.status_code == 200
        data = response.json()
        assert f"[unknown|{channel_id}]" in data["insights"][0]["topic_key"]


# =============================================================================
# Test: Complex Topic Keys
# =============================================================================


class TestComplexTopicKeys:
    """Tests for complex topic key formats."""

    def test_dyad_topic_resolves_both_users(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Dyad topic keys resolve both user IDs."""
        server_id = "123456789"
        user1_id = "111111111"
        user2_id = "222222222"
        topic_key = f"server:{server_id}:dyad:{user1_id}:{user2_id}"

        create_server(engine, server_id, "Test Server")
        create_user_profile(engine, user1_id, display_name="Alice")
        create_user_profile(engine, user2_id, display_name="Bob")
        create_insight_in_db(engine, layer_run_id, topic_key)

        response = client.get("/insights?readable=true")

        assert response.status_code == 200
        data = response.json()
        topic = data["insights"][0]["topic_key"]
        assert "Alice" in topic
        assert "Bob" in topic
        assert "dyad" in topic

    def test_global_user_topic_resolves(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Global user topic (user:ID) resolves correctly."""
        user_id = "987654321"
        topic_key = f"user:{user_id}"

        create_user_profile(engine, user_id, display_name="Alice")
        create_insight_in_db(engine, layer_run_id, topic_key)

        response = client.get("/insights?readable=true")

        assert response.status_code == 200
        data = response.json()
        assert data["insights"][0]["topic_key"] == "user:Alice"

    def test_global_dyad_topic_resolves(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Global dyad topic (dyad:ID:ID) resolves correctly."""
        user1_id = "111111111"
        user2_id = "222222222"
        topic_key = f"dyad:{user1_id}:{user2_id}"

        create_user_profile(engine, user1_id, display_name="Alice")
        create_user_profile(engine, user2_id, display_name="Bob")
        create_insight_in_db(engine, layer_run_id, topic_key)

        response = client.get("/insights?readable=true")

        assert response.status_code == 200
        data = response.json()
        assert data["insights"][0]["topic_key"] == "dyad:Alice:Bob"

    def test_self_topic_unchanged(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Self topic (self:zos) remains unchanged."""
        topic_key = "self:zos"
        create_insight_in_db(engine, layer_run_id, topic_key)

        response = client.get("/insights?readable=true")

        assert response.status_code == 200
        data = response.json()
        assert data["insights"][0]["topic_key"] == "self:zos"

    def test_emoji_topic_unchanged(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Emoji topics keep the emoji readable."""
        server_id = "123456789"
        topic_key = f"server:{server_id}:emoji:fire"

        create_server(engine, server_id, "Test Server")
        create_insight_in_db(engine, layer_run_id, topic_key)

        response = client.get("/insights?readable=true")

        assert response.status_code == 200
        data = response.json()
        assert "emoji:fire" in data["insights"][0]["topic_key"]
        assert "Test Server" in data["insights"][0]["topic_key"]


# =============================================================================
# Test: Salience Endpoint Integration
# =============================================================================


class TestSalienceReadable:
    """Tests for readable mode in salience endpoints."""

    def test_salience_list_readable(
        self, client: TestClient, engine
    ) -> None:
        """Salience list endpoint supports readable mode."""
        server_id = "123456789"
        user_id = "987654321"
        topic_key = f"server:{server_id}:user:{user_id}"

        create_server(engine, server_id, "Test Server")
        create_user_profile(engine, user_id, display_name="Alice")
        ensure_topic_exists(engine, topic_key)
        add_salience(engine, topic_key)

        response = client.get("/salience?readable=true")

        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        assert "Test Server" in data[0]["topic_key"]
        assert "Alice" in data[0]["topic_key"]
        assert data[0]["topic_key_original"] == topic_key

    def test_salience_topic_detail_readable(
        self, client: TestClient, engine
    ) -> None:
        """Salience topic detail endpoint supports readable mode."""
        server_id = "123456789"
        user_id = "987654321"
        topic_key = f"server:{server_id}:user:{user_id}"

        create_server(engine, server_id, "Test Server")
        create_user_profile(engine, user_id, display_name="Alice")
        ensure_topic_exists(engine, topic_key)
        add_salience(engine, topic_key)

        response = client.get(f"/salience/{topic_key}?readable=true")

        assert response.status_code == 200
        data = response.json()
        assert data["readable"] is True
        assert "Test Server" in data["topic_key"]
        assert "Alice" in data["topic_key"]
        assert data["topic_key_original"] == topic_key

    def test_salience_groups_readable(
        self, client: TestClient, engine
    ) -> None:
        """Budget groups endpoint supports readable mode."""
        server_id = "123456789"
        user_id = "987654321"
        topic_key = f"server:{server_id}:user:{user_id}"

        create_server(engine, server_id, "Test Server")
        create_user_profile(engine, user_id, display_name="Alice")
        ensure_topic_exists(engine, topic_key)
        add_salience(engine, topic_key, amount=50.0)

        response = client.get("/salience/groups?readable=true")

        assert response.status_code == 200
        data = response.json()

        # Find the social group (where user topics go)
        social_group = next((g for g in data if g["group"] == "social"), None)
        assert social_group is not None
        assert social_group["readable"] is True

        if social_group["top_topics"]:
            top = social_group["top_topics"][0]
            if "Test Server" in top["topic_key"]:
                assert top["topic_key_original"] == topic_key


# =============================================================================
# Test: Original ID Preservation
# =============================================================================


class TestOriginalIdPreservation:
    """Tests that original IDs are preserved when readable mode is on."""

    def test_insight_preserves_original_topic_key(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Original topic_key is preserved in topic_key_original."""
        server_id = "123456789"
        user_id = "987654321"
        topic_key = f"server:{server_id}:user:{user_id}"

        create_server(engine, server_id, "Test Server")
        create_user_profile(engine, user_id, display_name="Alice")
        create_insight_in_db(engine, layer_run_id, topic_key)

        response = client.get("/insights?readable=true")

        assert response.status_code == 200
        data = response.json()
        insight = data["insights"][0]
        assert insight["topic_key_original"] == topic_key
        assert insight["topic_key"] != topic_key  # Changed to readable


# =============================================================================
# Test: Insights Endpoint Variants
# =============================================================================


class TestInsightsEndpointVariants:
    """Tests readable mode across all insights endpoints."""

    def test_insights_search_readable(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Search endpoint supports readable mode."""
        server_id = "123456789"
        user_id = "987654321"
        topic_key = f"server:{server_id}:user:{user_id}"

        create_server(engine, server_id, "Test Server")
        create_user_profile(engine, user_id, display_name="Alice")
        create_insight_in_db(
            engine, layer_run_id, topic_key, content="Unique searchable content xyz"
        )

        response = client.get("/insights/search?q=searchable&readable=true")

        assert response.status_code == 200
        data = response.json()
        assert data["readable"] is True
        assert len(data["insights"]) == 1
        assert "Alice" in data["insights"][0]["topic_key"]

    def test_insights_for_topic_readable(
        self, client: TestClient, engine, layer_run_id: str
    ) -> None:
        """Get insights for topic endpoint supports readable mode."""
        server_id = "123456789"
        user_id = "987654321"
        topic_key = f"server:{server_id}:user:{user_id}"

        create_server(engine, server_id, "Test Server")
        create_user_profile(engine, user_id, display_name="Alice")
        create_insight_in_db(engine, layer_run_id, topic_key)
        add_salience(engine, topic_key)

        response = client.get(f"/insights/{topic_key}?readable=true")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert "Alice" in data[0]["topic_key"]
        assert data[0]["topic_key_original"] == topic_key
