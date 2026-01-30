"""Tests for the salience ledger operations.

Covers all transaction types, balance computation, topic cap lookup,
lazy topic creation, and transaction history queries.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from zos.config import Config
from zos.database import create_tables, get_engine, salience_ledger, topics
from zos.models import TopicCategory, TransactionType, utcnow
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
    """Create a test database engine with all tables."""
    eng = get_engine(test_config)
    create_tables(eng)
    return eng


@pytest.fixture
def ledger(engine, test_config: Config) -> SalienceLedger:
    """Create a SalienceLedger instance for testing."""
    return SalienceLedger(engine, test_config)


@pytest.fixture
def now():
    """Return current time in UTC (timezone-aware)."""
    return utcnow()


# =============================================================================
# Test: Earn Records Positive Transaction
# =============================================================================


@pytest.mark.asyncio
async def test_earn_records_positive_transaction(ledger: SalienceLedger) -> None:
    """Test that earn records a positive transaction."""
    topic_key = "server:123:user:456"

    new_balance, overflow = await ledger.earn(
        topic_key=topic_key,
        amount=5.0,
        reason="message",
    )

    assert new_balance == 5.0
    assert overflow == 0.0

    # Verify transaction recorded
    history = await ledger.get_history(topic_key)
    assert len(history) == 1
    assert history[0].transaction_type == TransactionType.EARN
    assert history[0].amount == 5.0
    assert history[0].reason == "message"


@pytest.mark.asyncio
async def test_earn_multiple_times_accumulates(ledger: SalienceLedger) -> None:
    """Test that multiple earns accumulate correctly."""
    topic_key = "server:123:user:456"

    await ledger.earn(topic_key, 5.0)
    await ledger.earn(topic_key, 3.0)
    await ledger.earn(topic_key, 2.0)

    balance = await ledger.get_balance(topic_key)
    assert balance == 10.0


# =============================================================================
# Test: Earn Respects Cap (Overflow Returned)
# =============================================================================


@pytest.mark.asyncio
async def test_earn_respects_cap(ledger: SalienceLedger) -> None:
    """Test that earn respects topic cap and returns overflow."""
    topic_key = "server:123:user:456"

    # Default cap for server_user is 100
    # First earn 95
    await ledger.earn(topic_key, 95.0)

    # Try to earn 10 more, should only earn 5 (to reach cap)
    new_balance, overflow = await ledger.earn(topic_key, 10.0)

    assert new_balance == 100.0
    assert overflow == 5.0


@pytest.mark.asyncio
async def test_earn_at_cap_returns_full_overflow(ledger: SalienceLedger) -> None:
    """Test that earning when already at cap returns full amount as overflow."""
    topic_key = "server:123:user:456"

    # Earn to cap
    await ledger.earn(topic_key, 100.0)

    # Try to earn more
    new_balance, overflow = await ledger.earn(topic_key, 20.0)

    assert new_balance == 100.0
    assert overflow == 20.0


# =============================================================================
# Test: Spend Records Negative Transaction
# =============================================================================


@pytest.mark.asyncio
async def test_spend_records_negative_transaction(ledger: SalienceLedger) -> None:
    """Test that spend records a negative transaction."""
    topic_key = "server:123:user:456"

    # First earn some salience
    await ledger.earn(topic_key, 10.0)

    # Then spend
    actual_spent = await ledger.spend(topic_key, 5.0, reason="reflection")

    assert actual_spent == 5.0

    # Verify transaction recorded
    history = await ledger.get_history(topic_key)
    # Should have: earn, spend, retain (in reverse chronological order)
    assert len(history) == 3

    # Most recent is retain
    assert history[0].transaction_type == TransactionType.RETAIN
    assert history[0].amount > 0

    # Second is spend (negative)
    assert history[1].transaction_type == TransactionType.SPEND
    assert history[1].amount == -5.0


@pytest.mark.asyncio
async def test_spend_cannot_exceed_balance(ledger: SalienceLedger) -> None:
    """Test that spend cannot exceed current balance."""
    topic_key = "server:123:user:456"

    # Earn 5
    await ledger.earn(topic_key, 5.0)

    # Try to spend 10 (should only spend 5)
    actual_spent = await ledger.spend(topic_key, 10.0)

    assert actual_spent == 5.0


@pytest.mark.asyncio
async def test_spend_on_zero_balance_returns_zero(ledger: SalienceLedger) -> None:
    """Test that spending on zero balance returns zero."""
    topic_key = "server:123:user:456"

    # Create topic but don't earn
    await ledger.ensure_topic(topic_key)

    actual_spent = await ledger.spend(topic_key, 5.0)

    assert actual_spent == 0.0


# =============================================================================
# Test: Spend Applies Retention
# =============================================================================


@pytest.mark.asyncio
async def test_spend_applies_retention(ledger: SalienceLedger) -> None:
    """Test that spend applies retention (partial salience persists)."""
    topic_key = "server:123:user:456"

    # Earn 100
    await ledger.earn(topic_key, 100.0)

    # Spend 10 (with default 150% retention = 15 retained)
    await ledger.spend(topic_key, 10.0)

    # Balance should be: 100 - 10 + 15 = 105
    balance = await ledger.get_balance(topic_key)
    assert balance == pytest.approx(105.0, rel=0.01)


# =============================================================================
# Test: Reset After Reflection — Basic
# =============================================================================


@pytest.mark.asyncio
async def test_reset_after_reflection_basic(ledger: SalienceLedger) -> None:
    """After reflection, balance should be retention on cost only (not full balance)."""
    topic_key = "server:123:user:456"

    # Earn 100
    await ledger.earn(topic_key, 100.0)

    # Reflect with cost 2.0 (retention_rate=1.5 → retained = 3.0)
    spent = await ledger.reset_after_reflection(topic_key, 2.0, reason="test")

    assert spent == pytest.approx(2.0)
    # Balance: 100 - 2 (SPEND) - 98 (RESET) + 3.0 (RETAIN) = 3.0
    balance = await ledger.get_balance(topic_key)
    assert balance == pytest.approx(3.0, rel=0.01)


# =============================================================================
# Test: Reset After Reflection — Cost Exceeds Balance
# =============================================================================


@pytest.mark.asyncio
async def test_reset_after_reflection_cost_exceeds_balance(ledger: SalienceLedger) -> None:
    """When cost exceeds balance, spends full balance and retains on that."""
    topic_key = "server:123:user:456"

    # Earn only 1
    await ledger.earn(topic_key, 1.0)

    # Reflect with cost 5.0 — can only spend 1.0
    spent = await ledger.reset_after_reflection(topic_key, 5.0, reason="test")

    assert spent == pytest.approx(1.0)
    # Balance: 1 - 1 (SPEND) + 0 (no RESET, remaining=0) + 1.5 (RETAIN) = 1.5
    balance = await ledger.get_balance(topic_key)
    assert balance == pytest.approx(1.5, rel=0.01)


# =============================================================================
# Test: Reset After Reflection — Zero Balance
# =============================================================================


@pytest.mark.asyncio
async def test_reset_after_reflection_zero_balance(ledger: SalienceLedger) -> None:
    """Reflecting on a zero-balance topic returns 0 and creates no transactions."""
    topic_key = "server:123:user:456"
    await ledger.ensure_topic(topic_key)

    spent = await ledger.reset_after_reflection(topic_key, 2.0, reason="test")

    assert spent == 0.0
    balance = await ledger.get_balance(topic_key)
    assert balance == 0.0


# =============================================================================
# Test: Reset After Reflection — Transaction History
# =============================================================================


@pytest.mark.asyncio
async def test_reset_after_reflection_transactions(ledger: SalienceLedger) -> None:
    """Transaction history should show SPEND, RESET, and RETAIN entries."""
    topic_key = "server:123:user:456"

    await ledger.earn(topic_key, 100.0)
    await ledger.reset_after_reflection(topic_key, 2.0, reason="test")

    history = await ledger.get_history(topic_key)

    # Filter to just the post-earn transactions
    types = [e.transaction_type for e in history if e.transaction_type != TransactionType.EARN]

    assert TransactionType.SPEND in types
    assert TransactionType.RESET in types
    assert TransactionType.RETAIN in types


# =============================================================================
# Test: Balance is Sum of Transactions
# =============================================================================


@pytest.mark.asyncio
async def test_balance_is_sum_of_transactions(ledger: SalienceLedger) -> None:
    """Test that balance is computed as sum of all transactions."""
    topic_key = "server:123:user:456"

    # Multiple operations
    await ledger.earn(topic_key, 50.0)
    await ledger.earn(topic_key, 30.0)
    await ledger.spend(topic_key, 20.0)  # -20 + 30 retention = +10

    # Calculate expected: 50 + 30 - 20 + 30 = 90
    balance = await ledger.get_balance(topic_key)
    assert balance == pytest.approx(90.0, rel=0.01)


@pytest.mark.asyncio
async def test_get_balances_multiple_topics(ledger: SalienceLedger) -> None:
    """Test getting balances for multiple topics efficiently."""
    topics_list = [
        "server:123:user:1",
        "server:123:user:2",
        "server:123:user:3",
    ]

    # Earn different amounts
    await ledger.earn(topics_list[0], 10.0)
    await ledger.earn(topics_list[1], 20.0)
    await ledger.earn(topics_list[2], 30.0)

    balances = await ledger.get_balances(topics_list)

    assert balances[topics_list[0]] == 10.0
    assert balances[topics_list[1]] == 20.0
    assert balances[topics_list[2]] == 30.0


@pytest.mark.asyncio
async def test_get_balances_missing_topics(ledger: SalienceLedger) -> None:
    """Test that get_balances returns 0 for missing topics."""
    topics_list = [
        "server:123:user:1",
        "server:123:user:nonexistent",
    ]

    await ledger.earn(topics_list[0], 10.0)

    balances = await ledger.get_balances(topics_list)

    assert balances[topics_list[0]] == 10.0
    assert balances[topics_list[1]] == 0.0


@pytest.mark.asyncio
async def test_get_balances_empty_list(ledger: SalienceLedger) -> None:
    """Test that get_balances handles empty list."""
    balances = await ledger.get_balances([])
    assert balances == {}


# =============================================================================
# Test: Topic Created on First Earn (Lazy)
# =============================================================================


@pytest.mark.asyncio
async def test_topic_created_on_first_earn(ledger: SalienceLedger, engine) -> None:
    """Test that topic is created lazily on first earn."""
    topic_key = "server:123:user:789"

    # Verify topic doesn't exist yet
    topic = await ledger.get_topic(topic_key)
    assert topic is None

    # Earn should create it
    await ledger.earn(topic_key, 5.0)

    # Now it should exist
    topic = await ledger.get_topic(topic_key)
    assert topic is not None
    assert topic.key == topic_key
    assert topic.category == TopicCategory.USER
    assert topic.is_global is False


@pytest.mark.asyncio
async def test_topic_created_with_correct_category(ledger: SalienceLedger) -> None:
    """Test that created topics have correct category."""
    test_cases = [
        ("server:123:user:456", TopicCategory.USER, False),
        ("server:123:channel:789", TopicCategory.CHANNEL, False),
        ("server:123:dyad:111:222", TopicCategory.DYAD, False),
        ("server:123:thread:333", TopicCategory.THREAD, False),
        ("server:123:subject:gaming", TopicCategory.SUBJECT, False),
        ("server:123:emoji:444", TopicCategory.EMOJI, False),
        ("user:555", TopicCategory.USER, True),
        ("dyad:666:777", TopicCategory.DYAD, True),
        ("self:zos", TopicCategory.SELF, True),
    ]

    for topic_key, expected_category, expected_global in test_cases:
        await ledger.earn(topic_key, 1.0)
        topic = await ledger.get_topic(topic_key)
        assert topic.category == expected_category, f"Failed for {topic_key}"
        assert topic.is_global == expected_global, f"Failed for {topic_key}"


# =============================================================================
# Test: Last Activity Updated
# =============================================================================


@pytest.mark.asyncio
async def test_last_activity_updated_on_earn(ledger: SalienceLedger) -> None:
    """Test that last activity timestamp is updated on earn."""
    topic_key = "server:123:user:456"

    # First earn
    before = utcnow()
    await ledger.earn(topic_key, 5.0)
    after = utcnow()

    topic = await ledger.get_topic(topic_key)
    assert topic.last_activity_at is not None
    assert before <= topic.last_activity_at <= after


@pytest.mark.asyncio
async def test_last_activity_updated_on_warm(ledger: SalienceLedger) -> None:
    """Test that last activity timestamp is updated on warm."""
    topic_key = "user:456"

    before = utcnow()
    await ledger.warm(topic_key, 5.0, reason="dm_activity")
    after = utcnow()

    topic = await ledger.get_topic(topic_key)
    assert topic.last_activity_at is not None
    assert before <= topic.last_activity_at <= after


# =============================================================================
# Test: All Transaction Types Work
# =============================================================================


@pytest.mark.asyncio
async def test_decay_transaction(ledger: SalienceLedger) -> None:
    """Test decay transaction type."""
    topic_key = "server:123:user:456"

    await ledger.earn(topic_key, 100.0)
    decayed = await ledger.decay(topic_key, 10.0, reason="daily_decay")

    assert decayed == 10.0

    balance = await ledger.get_balance(topic_key)
    assert balance == 90.0

    # Verify transaction recorded
    history = await ledger.get_history(topic_key)
    decay_txn = [h for h in history if h.transaction_type == TransactionType.DECAY]
    assert len(decay_txn) == 1
    assert decay_txn[0].amount == -10.0


@pytest.mark.asyncio
async def test_decay_cannot_exceed_balance(ledger: SalienceLedger) -> None:
    """Test that decay cannot exceed current balance."""
    topic_key = "server:123:user:456"

    await ledger.earn(topic_key, 5.0)
    decayed = await ledger.decay(topic_key, 10.0)

    assert decayed == 5.0
    assert await ledger.get_balance(topic_key) == 0.0


@pytest.mark.asyncio
async def test_propagate_transaction(ledger: SalienceLedger) -> None:
    """Test propagate transaction type."""
    source_topic = "server:123:user:456"
    target_topic = "server:123:dyad:456:789"

    # Target must be warm to receive propagation
    await ledger.earn(target_topic, 5.0)

    # Propagate from source
    propagated = await ledger.propagate(
        target_topic, 3.0, source_topic=source_topic, reason="activity_propagation"
    )

    assert propagated == 3.0

    # Verify transaction recorded with source
    history = await ledger.get_history(target_topic)
    prop_txn = [h for h in history if h.transaction_type == TransactionType.PROPAGATE]
    assert len(prop_txn) == 1
    assert prop_txn[0].source_topic == source_topic


@pytest.mark.asyncio
async def test_propagate_skipped_for_cold_topic(ledger: SalienceLedger) -> None:
    """Test that propagation is skipped for cold topics."""
    source_topic = "server:123:user:456"
    target_topic = "server:123:dyad:456:789"

    # Target is cold (balance = 0)
    await ledger.ensure_topic(target_topic)

    propagated = await ledger.propagate(target_topic, 3.0, source_topic=source_topic)

    assert propagated == 0.0


@pytest.mark.asyncio
async def test_spillover_transaction(ledger: SalienceLedger) -> None:
    """Test spillover transaction type."""
    source_topic = "server:123:user:456"
    target_topic = "server:123:dyad:456:789"

    # Target must be warm
    await ledger.earn(target_topic, 5.0)

    spilled = await ledger.spillover(
        target_topic, 2.0, source_topic=source_topic, reason="overflow"
    )

    assert spilled == 2.0

    # Verify transaction recorded
    history = await ledger.get_history(target_topic)
    spill_txn = [h for h in history if h.transaction_type == TransactionType.SPILLOVER]
    assert len(spill_txn) == 1
    assert spill_txn[0].source_topic == source_topic


@pytest.mark.asyncio
async def test_warm_transaction(ledger: SalienceLedger) -> None:
    """Test warm transaction type for global topics."""
    topic_key = "user:456"

    warmed = await ledger.warm(topic_key, 5.0, reason="dm_activity")

    assert warmed == 5.0

    balance = await ledger.get_balance(topic_key)
    assert balance == 5.0

    # Verify transaction recorded
    history = await ledger.get_history(topic_key)
    warm_txn = [h for h in history if h.transaction_type == TransactionType.WARM]
    assert len(warm_txn) == 1
    assert warm_txn[0].reason == "dm_activity"


# =============================================================================
# Test: Topic Cap Lookup Based on Category
# =============================================================================


def test_get_cap_server_user(ledger: SalienceLedger) -> None:
    """Test cap for server-scoped user topic."""
    cap = ledger.get_cap("server:123:user:456")
    assert cap == 100  # Default server_user cap


def test_get_cap_channel(ledger: SalienceLedger) -> None:
    """Test cap for channel topic."""
    cap = ledger.get_cap("server:123:channel:456")
    assert cap == 150  # Default channel cap


def test_get_cap_thread(ledger: SalienceLedger) -> None:
    """Test cap for thread topic."""
    cap = ledger.get_cap("server:123:thread:456")
    assert cap == 50  # Default thread cap


def test_get_cap_dyad(ledger: SalienceLedger) -> None:
    """Test cap for dyad topic."""
    cap = ledger.get_cap("server:123:dyad:111:222")
    assert cap == 80  # Default dyad cap


def test_get_cap_subject(ledger: SalienceLedger) -> None:
    """Test cap for subject topic."""
    cap = ledger.get_cap("server:123:subject:gaming")
    assert cap == 60  # Default subject cap


def test_get_cap_emoji(ledger: SalienceLedger) -> None:
    """Test cap for emoji topic."""
    cap = ledger.get_cap("server:123:emoji:custom123")
    assert cap == 60  # Default emoji cap


def test_get_cap_global_user(ledger: SalienceLedger) -> None:
    """Test cap for global user topic."""
    cap = ledger.get_cap("user:456")
    assert cap == 100  # Uses server_user cap


def test_get_cap_global_dyad(ledger: SalienceLedger) -> None:
    """Test cap for global dyad topic."""
    cap = ledger.get_cap("dyad:111:222")
    assert cap == 80  # Uses dyad cap


def test_get_cap_self(ledger: SalienceLedger) -> None:
    """Test cap for self topic."""
    cap = ledger.get_cap("self:zos")
    assert cap == 100  # Default self cap


# =============================================================================
# Test: Extract Category
# =============================================================================


def test_extract_category_server_scoped(ledger: SalienceLedger) -> None:
    """Test category extraction for server-scoped topics."""
    assert ledger.extract_category("server:123:user:456") == "user"
    assert ledger.extract_category("server:123:channel:456") == "channel"
    assert ledger.extract_category("server:123:dyad:111:222") == "dyad"
    assert ledger.extract_category("server:123:subject:gaming") == "subject"
    assert ledger.extract_category("server:123:emoji:custom") == "emoji"
    assert ledger.extract_category("server:123:self:zos") == "self"


def test_extract_category_global(ledger: SalienceLedger) -> None:
    """Test category extraction for global topics."""
    assert ledger.extract_category("user:456") == "user"
    assert ledger.extract_category("dyad:111:222") == "dyad"
    assert ledger.extract_category("self:zos") == "self"


# =============================================================================
# Test: Is Global
# =============================================================================


def test_is_global(ledger: SalienceLedger) -> None:
    """Test global topic detection."""
    assert ledger.is_global("user:456") is True
    assert ledger.is_global("dyad:111:222") is True
    assert ledger.is_global("self:zos") is True

    assert ledger.is_global("server:123:user:456") is False
    assert ledger.is_global("server:123:channel:789") is False


# =============================================================================
# Test: Transaction History Query
# =============================================================================


@pytest.mark.asyncio
async def test_get_history_returns_recent_first(ledger: SalienceLedger) -> None:
    """Test that history is returned most recent first."""
    topic_key = "server:123:user:456"

    await ledger.earn(topic_key, 1.0, reason="first")
    await ledger.earn(topic_key, 2.0, reason="second")
    await ledger.earn(topic_key, 3.0, reason="third")

    history = await ledger.get_history(topic_key)

    # Most recent first
    assert history[0].reason == "third"
    assert history[1].reason == "second"
    assert history[2].reason == "first"


@pytest.mark.asyncio
async def test_get_history_with_limit(ledger: SalienceLedger) -> None:
    """Test history limit parameter."""
    topic_key = "server:123:user:456"

    for i in range(10):
        await ledger.earn(topic_key, 1.0)

    history = await ledger.get_history(topic_key, limit=5)

    assert len(history) == 5


@pytest.mark.asyncio
async def test_get_history_with_since(ledger: SalienceLedger) -> None:
    """Test history since parameter."""
    topic_key = "server:123:user:456"

    await ledger.earn(topic_key, 1.0, reason="before")

    cutoff = utcnow()

    await ledger.earn(topic_key, 2.0, reason="after")

    history = await ledger.get_history(topic_key, since=cutoff)

    assert len(history) == 1
    assert history[0].reason == "after"


@pytest.mark.asyncio
async def test_get_history_empty_topic(ledger: SalienceLedger) -> None:
    """Test history for topic with no transactions."""
    topic_key = "server:123:user:nonexistent"

    history = await ledger.get_history(topic_key)

    assert history == []


# =============================================================================
# Test: Ensure Topic (Lazy Creation)
# =============================================================================


@pytest.mark.asyncio
async def test_ensure_topic_creates_if_missing(ledger: SalienceLedger) -> None:
    """Test that ensure_topic creates topic if it doesn't exist."""
    topic_key = "server:123:user:456"

    topic = await ledger.ensure_topic(topic_key)

    assert topic.key == topic_key
    assert topic.category == TopicCategory.USER


@pytest.mark.asyncio
async def test_ensure_topic_returns_existing(ledger: SalienceLedger) -> None:
    """Test that ensure_topic returns existing topic."""
    topic_key = "server:123:user:456"

    # Create topic first
    await ledger.ensure_topic(topic_key)

    # Ensure again should return same topic
    topic = await ledger.ensure_topic(topic_key)

    assert topic.key == topic_key


# =============================================================================
# Test: Edge Cases
# =============================================================================


@pytest.mark.asyncio
async def test_earn_with_source_topic(ledger: SalienceLedger) -> None:
    """Test earning with source_topic parameter."""
    topic_key = "server:123:user:456"
    source = "server:123:channel:789"

    await ledger.earn(topic_key, 5.0, source_topic=source)

    history = await ledger.get_history(topic_key)
    assert history[0].source_topic == source


@pytest.mark.asyncio
async def test_balance_of_nonexistent_topic(ledger: SalienceLedger) -> None:
    """Test that balance of nonexistent topic is 0."""
    balance = await ledger.get_balance("server:123:user:nonexistent")
    assert balance == 0.0


@pytest.mark.asyncio
async def test_propagate_respects_cap(ledger: SalienceLedger) -> None:
    """Test that propagation respects target topic cap."""
    target_topic = "server:123:user:456"

    # Earn to near cap (cap is 100)
    await ledger.earn(target_topic, 98.0)

    # Propagate 10, should only add 2
    propagated = await ledger.propagate(
        target_topic, 10.0, source_topic="server:123:channel:789"
    )

    assert propagated == 2.0
    assert await ledger.get_balance(target_topic) == 100.0


@pytest.mark.asyncio
async def test_spillover_respects_cap(ledger: SalienceLedger) -> None:
    """Test that spillover respects target topic cap."""
    target_topic = "server:123:user:456"

    # Earn to near cap
    await ledger.earn(target_topic, 95.0)

    # Spillover 10, should only add 5
    spilled = await ledger.spillover(
        target_topic, 10.0, source_topic="server:123:channel:789"
    )

    assert spilled == 5.0


@pytest.mark.asyncio
async def test_warm_respects_cap(ledger: SalienceLedger) -> None:
    """Test that warm respects topic cap."""
    topic_key = "user:456"

    # Try to warm with huge amount
    warmed = await ledger.warm(topic_key, 1000.0)

    # Should be capped
    assert warmed == 100.0  # Cap for global user


# =============================================================================
# Test: EarningCoordinator Self-Mention
# =============================================================================


@pytest.fixture
def earning_coordinator(ledger: SalienceLedger, test_config: "Config"):
    """Create an EarningCoordinator with a bot user ID."""
    from zos.salience import EarningCoordinator

    return EarningCoordinator(ledger, test_config, bot_user_id="999888777")


@pytest.mark.asyncio
async def test_self_mention_earns_to_server_self_topic(
    earning_coordinator, ledger: SalienceLedger
) -> None:
    """Test that self-mention earns salience to server-scoped self topic."""
    from zos.models import Message, VisibilityScope, utcnow

    # Create a message that mentions the bot (user ID 999888777)
    message = Message(
        id="msg123",
        channel_id="channel456",
        server_id="server789",
        author_id="user111",
        content="Hey <@999888777> can you help me?",
        created_at=utcnow(),
        visibility_scope=VisibilityScope.PUBLIC,
    )

    topics = await earning_coordinator.process_message(message)

    # Should include the server-scoped self topic
    assert "server:server789:self:zos" in topics

    # Verify salience was actually earned
    balance = await ledger.get_balance("server:server789:self:zos")
    assert balance > 0  # Should have earned self_mention weight (default 5.0)


@pytest.mark.asyncio
async def test_self_mention_in_dm_earns_to_global_self_topic(
    earning_coordinator, ledger: SalienceLedger
) -> None:
    """Test that self-mention in DM earns salience to global self topic."""
    from zos.models import Message, VisibilityScope, utcnow

    # Create a DM message that mentions the bot
    message = Message(
        id="msg123",
        channel_id="dm_channel",
        server_id=None,  # DMs have no server
        author_id="user111",
        content="<@999888777> hello!",
        created_at=utcnow(),
        visibility_scope=VisibilityScope.DM,
    )

    topics = await earning_coordinator.process_message(message)

    # Should include the global self topic
    assert "self:zos" in topics

    # Verify salience was earned
    balance = await ledger.get_balance("self:zos")
    assert balance > 0


@pytest.mark.asyncio
async def test_no_self_mention_when_bot_not_tagged(
    earning_coordinator, ledger: SalienceLedger
) -> None:
    """Test that self topic doesn't earn when bot is not mentioned."""
    from zos.models import Message, VisibilityScope, utcnow

    # Create a message that doesn't mention the bot
    message = Message(
        id="msg123",
        channel_id="channel456",
        server_id="server789",
        author_id="user111",
        content="Hey <@222333444> check this out!",
        created_at=utcnow(),
        visibility_scope=VisibilityScope.PUBLIC,
    )

    topics = await earning_coordinator.process_message(message)

    # Should NOT include any self topic
    assert "server:server789:self:zos" not in topics
    assert "self:zos" not in topics


@pytest.mark.asyncio
async def test_self_mention_with_nickname_format(
    earning_coordinator, ledger: SalienceLedger
) -> None:
    """Test self-mention detection with nickname format (<@!ID>)."""
    from zos.models import Message, VisibilityScope, utcnow

    # Create a message using the nickname format
    message = Message(
        id="msg123",
        channel_id="channel456",
        server_id="server789",
        author_id="user111",
        content="Hello <@!999888777>!",  # Nickname format with !
        created_at=utcnow(),
        visibility_scope=VisibilityScope.PUBLIC,
    )

    topics = await earning_coordinator.process_message(message)

    # Should still detect and earn for self topic
    assert "server:server789:self:zos" in topics


@pytest.mark.asyncio
async def test_earning_coordinator_without_bot_id_skips_self_mention(
    ledger: SalienceLedger, test_config
) -> None:
    """Test that EarningCoordinator without bot_user_id doesn't earn self-mentions."""
    from zos.models import Message, VisibilityScope, utcnow
    from zos.salience import EarningCoordinator

    # Create coordinator without bot_user_id
    coordinator = EarningCoordinator(ledger, test_config, bot_user_id=None)

    message = Message(
        id="msg123",
        channel_id="channel456",
        server_id="server789",
        author_id="user111",
        content="<@999888777> hello!",
        created_at=utcnow(),
        visibility_scope=VisibilityScope.PUBLIC,
    )

    topics = await coordinator.process_message(message)

    # Should not include self topic when bot_user_id is None
    assert "server:server789:self:zos" not in topics
    assert "self:zos" not in topics


# =============================================================================
# Test: Bot Mention Does NOT Earn to user:{bot_id} Topic
# =============================================================================


@pytest.mark.asyncio
async def test_bot_mention_does_not_earn_to_bot_user_topic(
    earning_coordinator, ledger: SalienceLedger
) -> None:
    """Test that mentioning the bot does NOT earn salience to user:{bot_id} topic."""
    from zos.models import Message, VisibilityScope, utcnow

    message = Message(
        id="msg_bot_skip",
        channel_id="channel456",
        server_id="server789",
        author_id="user111",
        content="Hey <@999888777> what do you think?",
        created_at=utcnow(),
        visibility_scope=VisibilityScope.PUBLIC,
    )

    topics = await earning_coordinator.process_message(message)

    # Bot user topic should NOT appear in earned topics
    assert "server:server789:user:999888777" not in topics

    # Bot user topic should have zero balance
    balance = await ledger.get_balance("server:server789:user:999888777")
    assert balance == 0.0

    # But the self topic SHOULD have earned
    assert "server:server789:self:zos" in topics
    self_balance = await ledger.get_balance("server:server789:self:zos")
    assert self_balance > 0


# =============================================================================
# Test: Redistribution Moves Salience from Bot User Topics to Self Topics
# =============================================================================


@pytest.mark.asyncio
async def test_redistribute_bot_user_salience(ledger: SalienceLedger) -> None:
    """Test that redistribution moves salience from bot user topics to self topics."""
    bot_id = "999888777"

    # Simulate salience that was incorrectly accumulated on bot user topics
    await ledger.earn(f"server:s1:user:{bot_id}", 20.0)
    await ledger.earn(f"server:s2:user:{bot_id}", 10.0)

    # Verify it's there
    assert await ledger.get_balance(f"server:s1:user:{bot_id}") == 20.0
    assert await ledger.get_balance(f"server:s2:user:{bot_id}") == 10.0

    # Redistribute
    count = await ledger.redistribute_bot_user_salience(bot_id)

    assert count == 2

    # Bot user topics should now be zero
    assert await ledger.get_balance(f"server:s1:user:{bot_id}") == 0.0
    assert await ledger.get_balance(f"server:s2:user:{bot_id}") == 0.0

    # Self topics should have received the salience
    assert await ledger.get_balance("server:s1:self:zos") == 20.0
    assert await ledger.get_balance("server:s2:self:zos") == 10.0


# =============================================================================
# Test: Redistribution Is Idempotent
# =============================================================================


@pytest.mark.asyncio
async def test_redistribute_bot_user_salience_idempotent(ledger: SalienceLedger) -> None:
    """Test that running redistribution twice is a no-op the second time."""
    bot_id = "999888777"

    # Simulate stale salience
    await ledger.earn(f"server:s1:user:{bot_id}", 15.0)

    # First redistribution
    count1 = await ledger.redistribute_bot_user_salience(bot_id)
    assert count1 == 1
    assert await ledger.get_balance("server:s1:self:zos") == 15.0

    # Second redistribution — should be a no-op
    count2 = await ledger.redistribute_bot_user_salience(bot_id)
    assert count2 == 0

    # Self topic balance unchanged
    assert await ledger.get_balance("server:s1:self:zos") == 15.0
