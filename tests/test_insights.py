"""Tests for insight storage and retrieval.

Covers:
- Insight insertion
- Different retrieval profiles
- Temporal formatting
- Quarantine handling
- Effective strength decay
- Global topic retrieval
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from zos.config import Config
from zos.database import (
    create_tables,
    generate_id,
    get_engine,
    insights as insights_table,
    layer_runs as layer_runs_table,
    salience_ledger,
    topics as topics_table,
)
from zos.models import TopicCategory
from zos.insights import (
    FormattedInsight,
    InsightRetriever,
    PROFILES,
    RetrievalProfile,
    get_insight,
    get_insights_by_category,
    get_insights_for_topic,
    insert_insight,
)
from zos.models import Insight, LayerRun, LayerRunStatus, utcnow, VisibilityScope


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
    """Create a test database engine with all tables."""
    eng = get_engine(test_config)
    create_tables(eng)
    return eng


@pytest.fixture
def retriever(engine, test_config: Config) -> InsightRetriever:
    """Create an InsightRetriever instance for testing."""
    return InsightRetriever(engine, test_config)


@pytest.fixture
def layer_run_id(engine) -> str:
    """Create a layer run for insights to reference."""
    run_id = generate_id()
    now = utcnow()

    run = LayerRun(
        id=run_id,
        layer_name="test_layer",
        layer_hash="abc123",
        started_at=now,
        completed_at=now,
        status=LayerRunStatus.SUCCESS,
        targets_matched=1,
        targets_processed=1,
        targets_skipped=0,
        insights_created=0,
    )

    with engine.connect() as conn:
        conn.execute(
            layer_runs_table.insert().values(
                id=run.id,
                layer_name=run.layer_name,
                layer_hash=run.layer_hash,
                started_at=run.started_at,
                completed_at=run.completed_at,
                status=run.status.value,
                targets_matched=run.targets_matched,
                targets_processed=run.targets_processed,
                targets_skipped=run.targets_skipped,
                insights_created=run.insights_created,
            )
        )
        conn.commit()

    return run_id


@pytest.fixture
def topic_key() -> str:
    """Return a test topic key."""
    return "server:123:user:456"


def ensure_topic_exists(engine, topic_key: str) -> None:
    """Ensure a topic exists in the database."""
    # Parse category from topic key
    parts = topic_key.split(":")
    if parts[0] == "server":
        category = parts[2]
        is_global = False
    else:
        category = parts[0]
        is_global = True

    # Map to category enum
    try:
        cat_enum = TopicCategory(category)
    except ValueError:
        cat_enum = TopicCategory.USER

    with engine.connect() as conn:
        # Check if exists
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


def create_test_insight(
    topic_key: str,
    layer_run_id: str,
    content: str = "Test insight content",
    strength: float = 5.0,
    created_at: datetime | None = None,
    quarantined: bool = False,
    original_topic_salience: float = 10.0,
) -> Insight:
    """Create a test insight with required fields."""
    return Insight(
        id=generate_id(),
        topic_key=topic_key,
        category="user_reflection",
        content=content,
        sources_scope_max=VisibilityScope.PUBLIC,
        created_at=created_at or utcnow(),
        layer_run_id=layer_run_id,
        quarantined=quarantined,
        salience_spent=5.0,
        strength_adjustment=1.0,
        strength=strength,
        original_topic_salience=original_topic_salience,
        confidence=0.8,
        importance=0.7,
        novelty=0.6,
        valence_curiosity=0.5,  # At least one valence required
    )


# =============================================================================
# Test: Insight Insertion
# =============================================================================


@pytest.mark.asyncio
async def test_insight_insertion(engine, layer_run_id: str, topic_key: str) -> None:
    """Test that insights can be inserted correctly."""
    ensure_topic_exists(engine, topic_key)
    insight = create_test_insight(topic_key, layer_run_id, content="Alice seems friendly")

    await insert_insight(engine, insight)

    # Verify it was stored
    retrieved = await get_insight(engine, insight.id)
    assert retrieved is not None
    assert retrieved.id == insight.id
    assert retrieved.content == "Alice seems friendly"
    assert retrieved.topic_key == topic_key
    assert retrieved.strength == 5.0


@pytest.mark.asyncio
async def test_insight_insertion_with_all_fields(
    engine, layer_run_id: str, topic_key: str
) -> None:
    """Test insertion with all optional fields populated."""
    ensure_topic_exists(engine, topic_key)
    insight = Insight(
        id=generate_id(),
        topic_key=topic_key,
        category="synthesis",
        content="Comprehensive insight",
        sources_scope_max=VisibilityScope.DM,
        created_at=utcnow(),
        layer_run_id=layer_run_id,
        supersedes="prev_insight_id",
        quarantined=False,
        salience_spent=10.0,
        strength_adjustment=1.5,
        strength=15.0,
        original_topic_salience=20.0,
        confidence=0.9,
        importance=0.8,
        novelty=0.7,
        valence_joy=0.8,
        valence_concern=0.2,
        valence_curiosity=0.6,
        valence_warmth=0.9,
        valence_tension=0.1,
        context_channel="channel_123",
        context_thread="thread_456",
        subject="friendship",
        participants=["user_a", "user_b"],
        conflicts_with=["conflict_id_1"],
        conflict_resolved=False,
        synthesis_source_ids=["source_1", "source_2"],
    )

    await insert_insight(engine, insight)

    retrieved = await get_insight(engine, insight.id)
    assert retrieved is not None
    assert retrieved.supersedes == "prev_insight_id"
    assert retrieved.context_channel == "channel_123"
    assert retrieved.participants == ["user_a", "user_b"]


# =============================================================================
# Test: Retrieval Profiles
# =============================================================================


@pytest.mark.asyncio
async def test_recent_profile_emphasizes_recency(
    retriever: InsightRetriever,
    engine,
    layer_run_id: str,
    topic_key: str,
) -> None:
    """Test that 'recent' profile prioritizes recent insights."""
    ensure_topic_exists(engine, topic_key)
    now = utcnow()

    # Create old but strong insight
    old_strong = create_test_insight(
        topic_key,
        layer_run_id,
        content="Old strong insight",
        strength=9.0,
        created_at=now - timedelta(days=30),
    )

    # Create recent but weak insight
    recent_weak = create_test_insight(
        topic_key,
        layer_run_id,
        content="Recent weak insight",
        strength=2.0,
        created_at=now - timedelta(hours=1),
    )

    await insert_insight(engine, old_strong)
    await insert_insight(engine, recent_weak)

    # Add some salience so effective strength can be computed
    with engine.connect() as conn:
        conn.execute(
            salience_ledger.insert().values(
                id=generate_id(),
                topic_key=topic_key,
                transaction_type="earn",
                amount=10.0,
                created_at=now,
            )
        )
        conn.commit()

    # Recent profile should get the recent one first
    results = await retriever.retrieve(topic_key, "recent", limit=2)

    assert len(results) == 2
    # With 80% recency weight, most of the budget goes to recent
    assert any(r.content == "Recent weak insight" for r in results)


@pytest.mark.asyncio
async def test_deep_profile_emphasizes_strength(
    retriever: InsightRetriever,
    engine,
    layer_run_id: str,
    topic_key: str,
) -> None:
    """Test that 'deep' profile prioritizes strong insights."""
    ensure_topic_exists(engine, topic_key)
    now = utcnow()

    # Create old but very strong insight
    old_strong = create_test_insight(
        topic_key,
        layer_run_id,
        content="Old strong insight",
        strength=9.0,
        created_at=now - timedelta(days=30),
    )

    # Create recent but weak insight
    recent_weak = create_test_insight(
        topic_key,
        layer_run_id,
        content="Recent weak insight",
        strength=1.0,
        created_at=now - timedelta(hours=1),
    )

    await insert_insight(engine, old_strong)
    await insert_insight(engine, recent_weak)

    # Add salience
    with engine.connect() as conn:
        conn.execute(
            salience_ledger.insert().values(
                id=generate_id(),
                topic_key=topic_key,
                transaction_type="earn",
                amount=10.0,
                created_at=now,
            )
        )
        conn.commit()

    # Deep profile should prioritize the strong one
    results = await retriever.retrieve(topic_key, "deep", limit=2)

    assert len(results) == 2
    # The old strong one should be retrieved
    assert any(r.content == "Old strong insight" for r in results)


@pytest.mark.asyncio
async def test_balanced_profile_gets_both(
    retriever: InsightRetriever,
    engine,
    layer_run_id: str,
    topic_key: str,
) -> None:
    """Test that 'balanced' profile gets mix of recent and strong."""
    ensure_topic_exists(engine, topic_key)
    now = utcnow()

    insights = [
        create_test_insight(
            topic_key,
            layer_run_id,
            content=f"Insight {i}",
            strength=i * 2.0,
            created_at=now - timedelta(days=i),
        )
        for i in range(5)
    ]

    for insight in insights:
        await insert_insight(engine, insight)

    # Add salience
    with engine.connect() as conn:
        conn.execute(
            salience_ledger.insert().values(
                id=generate_id(),
                topic_key=topic_key,
                transaction_type="earn",
                amount=10.0,
                created_at=now,
            )
        )
        conn.commit()

    results = await retriever.retrieve(topic_key, "balanced", limit=4)

    assert len(results) == 4


@pytest.mark.asyncio
async def test_comprehensive_profile_includes_quarantined(
    retriever: InsightRetriever,
    engine,
    layer_run_id: str,
    topic_key: str,
) -> None:
    """Test that 'comprehensive' profile includes quarantined insights."""
    ensure_topic_exists(engine, topic_key)
    now = utcnow()

    normal = create_test_insight(
        topic_key,
        layer_run_id,
        content="Normal insight",
        quarantined=False,
    )

    quarantined = create_test_insight(
        topic_key,
        layer_run_id,
        content="Quarantined insight",
        quarantined=True,
    )

    await insert_insight(engine, normal)
    await insert_insight(engine, quarantined)

    # Add salience
    with engine.connect() as conn:
        conn.execute(
            salience_ledger.insert().values(
                id=generate_id(),
                topic_key=topic_key,
                transaction_type="earn",
                amount=10.0,
                created_at=now,
            )
        )
        conn.commit()

    # Comprehensive should include both
    results = await retriever.retrieve(topic_key, "comprehensive", limit=10)

    assert len(results) == 2
    assert any(r.content == "Quarantined insight" for r in results)


# =============================================================================
# Test: Quarantine Handling
# =============================================================================


@pytest.mark.asyncio
async def test_quarantined_insights_excluded_by_default(
    retriever: InsightRetriever,
    engine,
    layer_run_id: str,
    topic_key: str,
) -> None:
    """Test that quarantined insights are excluded by default."""
    ensure_topic_exists(engine, topic_key)
    normal = create_test_insight(
        topic_key,
        layer_run_id,
        content="Normal insight",
        quarantined=False,
    )

    quarantined = create_test_insight(
        topic_key,
        layer_run_id,
        content="Quarantined insight",
        quarantined=True,
    )

    await insert_insight(engine, normal)
    await insert_insight(engine, quarantined)

    # Add salience
    with engine.connect() as conn:
        conn.execute(
            salience_ledger.insert().values(
                id=generate_id(),
                topic_key=topic_key,
                transaction_type="earn",
                amount=10.0,
                created_at=utcnow(),
            )
        )
        conn.commit()

    # Default (balanced) should exclude quarantined
    results = await retriever.retrieve(topic_key, "balanced", limit=10)

    assert len(results) == 1
    assert results[0].content == "Normal insight"


# =============================================================================
# Test: Temporal Formatting
# =============================================================================


def test_relative_time_just_now(retriever: InsightRetriever) -> None:
    """Test relative time for very recent timestamps."""
    now = utcnow()
    result = retriever._relative_time(now - timedelta(minutes=30))
    assert result == "just now"


def test_relative_time_hours(retriever: InsightRetriever) -> None:
    """Test relative time for hours ago."""
    now = utcnow()
    result = retriever._relative_time(now - timedelta(hours=5))
    assert result == "5 hours ago"


def test_relative_time_days(retriever: InsightRetriever) -> None:
    """Test relative time for days ago."""
    now = utcnow()
    result = retriever._relative_time(now - timedelta(days=3))
    assert result == "3 days ago"


def test_relative_time_weeks(retriever: InsightRetriever) -> None:
    """Test relative time for weeks ago."""
    now = utcnow()
    result = retriever._relative_time(now - timedelta(days=14))
    assert result == "2 weeks ago"


def test_relative_time_months(retriever: InsightRetriever) -> None:
    """Test relative time for months ago."""
    now = utcnow()
    result = retriever._relative_time(now - timedelta(days=60))
    assert result == "2 months ago"


def test_strength_label_strong(retriever: InsightRetriever) -> None:
    """Test strength label for strong memories."""
    assert retriever._strength_label(9.0) == "strong memory"
    assert retriever._strength_label(8.0) == "strong memory"


def test_strength_label_clear(retriever: InsightRetriever) -> None:
    """Test strength label for clear memories."""
    assert retriever._strength_label(6.0) == "clear memory"
    assert retriever._strength_label(5.0) == "clear memory"


def test_strength_label_fading(retriever: InsightRetriever) -> None:
    """Test strength label for fading memories."""
    assert retriever._strength_label(3.0) == "fading memory"
    assert retriever._strength_label(2.0) == "fading memory"


def test_strength_label_distant(retriever: InsightRetriever) -> None:
    """Test strength label for distant memories."""
    assert retriever._strength_label(1.0) == "distant memory"
    assert retriever._strength_label(0.5) == "distant memory"


@pytest.mark.asyncio
async def test_formatted_insight_has_temporal_marker(
    retriever: InsightRetriever,
    engine,
    layer_run_id: str,
    topic_key: str,
) -> None:
    """Test that formatted insights have proper temporal markers."""
    ensure_topic_exists(engine, topic_key)
    insight = create_test_insight(
        topic_key,
        layer_run_id,
        content="Test insight",
        strength=7.0,
        created_at=utcnow() - timedelta(days=2),
    )

    await insert_insight(engine, insight)

    # Add salience
    with engine.connect() as conn:
        conn.execute(
            salience_ledger.insert().values(
                id=generate_id(),
                topic_key=topic_key,
                transaction_type="earn",
                amount=10.0,
                created_at=utcnow(),
            )
        )
        conn.commit()

    results = await retriever.retrieve(topic_key, "balanced", limit=1)

    assert len(results) == 1
    assert "clear memory" in results[0].temporal_marker
    assert "2 days ago" in results[0].temporal_marker


# =============================================================================
# Test: Effective Strength Decay
# =============================================================================


@pytest.mark.asyncio
async def test_effective_strength_decays_with_salience(
    retriever: InsightRetriever,
    engine,
    layer_run_id: str,
    topic_key: str,
) -> None:
    """Test that effective strength decays when topic salience drops."""
    ensure_topic_exists(engine, topic_key)
    insight = create_test_insight(
        topic_key,
        layer_run_id,
        content="Test insight",
        strength=10.0,
        original_topic_salience=100.0,  # Created when topic had high salience
    )

    await insert_insight(engine, insight)

    # Current salience is only 50 (half of original)
    with engine.connect() as conn:
        conn.execute(
            salience_ledger.insert().values(
                id=generate_id(),
                topic_key=topic_key,
                transaction_type="earn",
                amount=50.0,
                created_at=utcnow(),
            )
        )
        conn.commit()

    results = await retriever.retrieve(topic_key, "balanced", limit=1)

    assert len(results) == 1
    # Effective strength should be 10.0 * (50/100) = 5.0
    assert results[0].strength == 10.0  # Base strength unchanged
    assert results[0].effective_strength == pytest.approx(5.0, rel=0.01)


@pytest.mark.asyncio
async def test_effective_strength_capped_at_base(
    retriever: InsightRetriever,
    engine,
    layer_run_id: str,
    topic_key: str,
) -> None:
    """Test that effective strength doesn't exceed base strength."""
    ensure_topic_exists(engine, topic_key)
    insight = create_test_insight(
        topic_key,
        layer_run_id,
        content="Test insight",
        strength=10.0,
        original_topic_salience=50.0,
    )

    await insert_insight(engine, insight)

    # Current salience is 100 (higher than original)
    with engine.connect() as conn:
        conn.execute(
            salience_ledger.insert().values(
                id=generate_id(),
                topic_key=topic_key,
                transaction_type="earn",
                amount=100.0,
                created_at=utcnow(),
            )
        )
        conn.commit()

    results = await retriever.retrieve(topic_key, "balanced", limit=1)

    assert len(results) == 1
    # Effective should be capped at base (ratio capped at 1.0)
    assert results[0].effective_strength == 10.0


# =============================================================================
# Test: Max Age Handling
# =============================================================================


@pytest.mark.asyncio
async def test_max_age_days_filters_old_insights(
    retriever: InsightRetriever,
    engine,
    layer_run_id: str,
    topic_key: str,
) -> None:
    """Test that max_age_days filters out old insights."""
    ensure_topic_exists(engine, topic_key)
    now = utcnow()

    recent = create_test_insight(
        topic_key,
        layer_run_id,
        content="Recent",
        created_at=now - timedelta(days=5),
    )

    old = create_test_insight(
        topic_key,
        layer_run_id,
        content="Old",
        created_at=now - timedelta(days=30),
    )

    await insert_insight(engine, recent)
    await insert_insight(engine, old)

    # Add salience
    with engine.connect() as conn:
        conn.execute(
            salience_ledger.insert().values(
                id=generate_id(),
                topic_key=topic_key,
                transaction_type="earn",
                amount=10.0,
                created_at=now,
            )
        )
        conn.commit()

    # Create profile with 7-day max age
    profile = RetrievalProfile(
        recency_weight=0.5,
        strength_weight=0.5,
        max_age_days=7,
    )

    results = await retriever.retrieve(topic_key, profile, limit=10)

    assert len(results) == 1
    assert results[0].content == "Recent"


# =============================================================================
# Test: Category Retrieval
# =============================================================================


@pytest.mark.asyncio
async def test_get_insights_by_category(
    engine, layer_run_id: str, topic_key: str
) -> None:
    """Test retrieving insights by category."""
    ensure_topic_exists(engine, topic_key)
    user_insight = create_test_insight(
        topic_key,
        layer_run_id,
        content="User insight",
    )
    user_insight.category = "user_reflection"

    synthesis_insight = create_test_insight(
        topic_key,
        layer_run_id,
        content="Synthesis insight",
    )
    # Need to create with different category
    synthesis_insight = Insight(
        id=generate_id(),
        topic_key=topic_key,
        category="synthesis",
        content="Synthesis insight",
        sources_scope_max=VisibilityScope.PUBLIC,
        created_at=utcnow(),
        layer_run_id=layer_run_id,
        salience_spent=5.0,
        strength_adjustment=1.0,
        strength=5.0,
        original_topic_salience=10.0,
        confidence=0.8,
        importance=0.7,
        novelty=0.6,
        valence_curiosity=0.5,
    )

    await insert_insight(engine, user_insight)
    await insert_insight(engine, synthesis_insight)

    # Get only user reflections
    results = await get_insights_by_category(engine, "user_reflection")

    assert len(results) == 1
    assert results[0].content == "User insight"


@pytest.mark.asyncio
async def test_get_insights_by_category_with_since(
    engine, layer_run_id: str, topic_key: str
) -> None:
    """Test category retrieval with since filter."""
    ensure_topic_exists(engine, topic_key)
    now = utcnow()

    old = create_test_insight(
        topic_key,
        layer_run_id,
        content="Old",
        created_at=now - timedelta(days=10),
    )

    recent = create_test_insight(
        topic_key,
        layer_run_id,
        content="Recent",
        created_at=now - timedelta(hours=1),
    )

    await insert_insight(engine, old)
    await insert_insight(engine, recent)

    since = now - timedelta(days=1)
    results = await get_insights_by_category(engine, "user_reflection", since=since)

    assert len(results) == 1
    assert results[0].content == "Recent"


# =============================================================================
# Test: Global Topic Retrieval
# =============================================================================


@pytest.mark.asyncio
async def test_global_topic_retrieval_includes_server_scoped(
    retriever: InsightRetriever,
    engine,
    layer_run_id: str,
) -> None:
    """Test that global topic retrieval includes server-scoped insights."""
    global_topic = "user:456"
    server_topic = "server:123:user:456"

    ensure_topic_exists(engine, global_topic)
    ensure_topic_exists(engine, server_topic)

    global_insight = create_test_insight(
        global_topic,
        layer_run_id,
        content="Global insight",
    )

    server_insight = create_test_insight(
        server_topic,
        layer_run_id,
        content="Server insight",
    )

    await insert_insight(engine, global_insight)
    await insert_insight(engine, server_insight)

    # Add salience for both topics
    with engine.connect() as conn:
        conn.execute(
            salience_ledger.insert().values(
                id=generate_id(),
                topic_key=global_topic,
                transaction_type="earn",
                amount=10.0,
                created_at=utcnow(),
            )
        )
        conn.execute(
            salience_ledger.insert().values(
                id=generate_id(),
                topic_key=server_topic,
                transaction_type="earn",
                amount=10.0,
                created_at=utcnow(),
            )
        )
        conn.commit()

    results = await retriever.retrieve_for_global_topic(global_topic, limit=10)

    # Should get both
    contents = [r.content for r in results]
    assert "Global insight" in contents
    assert "Server insight" in contents


# =============================================================================
# Test: Conflict Detection Placeholder
# =============================================================================


@pytest.mark.asyncio
async def test_check_conflicts_returns_empty_for_mvp(
    retriever: InsightRetriever, layer_run_id: str, topic_key: str
) -> None:
    """Test that conflict detection returns empty list for MVP."""
    insight = create_test_insight(topic_key, layer_run_id)

    conflicts = await retriever.check_conflicts(insight)

    assert conflicts == []


# =============================================================================
# Test: Profile Defaults
# =============================================================================


def test_profiles_exist() -> None:
    """Test that default profiles are defined."""
    assert "recent" in PROFILES
    assert "balanced" in PROFILES
    assert "deep" in PROFILES
    assert "comprehensive" in PROFILES


def test_recent_profile_weights() -> None:
    """Test recent profile has correct weights."""
    profile = PROFILES["recent"]
    assert profile.recency_weight == 0.8
    assert profile.strength_weight == 0.2


def test_balanced_profile_weights() -> None:
    """Test balanced profile has equal weights."""
    profile = PROFILES["balanced"]
    assert profile.recency_weight == 0.5
    assert profile.strength_weight == 0.5


def test_deep_profile_weights() -> None:
    """Test deep profile emphasizes strength."""
    profile = PROFILES["deep"]
    assert profile.recency_weight == 0.3
    assert profile.strength_weight == 0.7
    assert profile.max_age_days is None


def test_comprehensive_profile_includes_conflicting() -> None:
    """Test comprehensive profile includes conflicting insights."""
    profile = PROFILES["comprehensive"]
    assert profile.include_conflicting is True


# =============================================================================
# Test: Empty Results
# =============================================================================


@pytest.mark.asyncio
async def test_retrieve_empty_topic(
    retriever: InsightRetriever, topic_key: str
) -> None:
    """Test retrieval from topic with no insights."""
    results = await retriever.retrieve(topic_key, "balanced", limit=10)
    assert results == []


@pytest.mark.asyncio
async def test_get_insight_nonexistent(engine) -> None:
    """Test getting nonexistent insight returns None."""
    result = await get_insight(engine, "nonexistent_id")
    assert result is None
