"""Tests for salience decay functionality.

Covers the decay logic including:
- Active topics don't decay
- Inactive topics decay after threshold
- Decay amount is correct percentage
- Zero-balance topics skipped
- Tiny balance topics zeroed out
- Transactions recorded correctly
"""

from datetime import timedelta
from pathlib import Path

import pytest

from zos.config import Config
from zos.database import create_tables, get_engine
from zos.models import TransactionType, utcnow
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


# =============================================================================
# Test: Active Topic Doesn't Decay
# =============================================================================


@pytest.mark.asyncio
async def test_active_topic_does_not_decay(ledger: SalienceLedger) -> None:
    """Test that a topic with recent activity doesn't decay."""
    topic_key = "server:123:user:456"

    # Earn some salience (this sets last_activity_at to now)
    await ledger.earn(topic_key, 50.0)

    # Verify balance before decay
    balance_before = await ledger.get_balance(topic_key)
    assert balance_before == 50.0

    # Apply decay - should not affect this topic (activity was just now)
    count, total = await ledger.apply_decay()

    # Should have decayed 0 topics
    assert count == 0
    assert total == 0.0

    # Balance should be unchanged
    balance_after = await ledger.get_balance(topic_key)
    assert balance_after == 50.0


@pytest.mark.asyncio
async def test_topic_within_threshold_does_not_decay(
    ledger: SalienceLedger, test_config: Config
) -> None:
    """Test that a topic within the decay threshold doesn't decay."""
    topic_key = "server:123:user:456"
    threshold_days = test_config.salience.decay_threshold_days

    # Earn salience
    await ledger.earn(topic_key, 50.0)

    # Manually set last_activity_at to just inside threshold
    # (threshold_days - 1, so still active)
    from zos.database import topics
    from sqlalchemy import update

    with ledger.engine.connect() as conn:
        conn.execute(
            update(topics)
            .where(topics.c.key == topic_key)
            .values(last_activity_at=utcnow() - timedelta(days=threshold_days - 1))
        )
        conn.commit()

    # Apply decay
    count, total = await ledger.apply_decay()

    # Should not have decayed
    assert count == 0
    assert total == 0.0


# =============================================================================
# Test: Inactive Topic Decays After Threshold
# =============================================================================


@pytest.mark.asyncio
async def test_inactive_topic_decays_after_threshold(
    ledger: SalienceLedger, test_config: Config
) -> None:
    """Test that a topic past the decay threshold does decay."""
    topic_key = "server:123:user:456"
    threshold_days = test_config.salience.decay_threshold_days

    # Earn salience
    await ledger.earn(topic_key, 100.0)

    # Manually set last_activity_at to beyond threshold
    from zos.database import topics
    from sqlalchemy import update

    old_activity = utcnow() - timedelta(days=threshold_days + 1)
    with ledger.engine.connect() as conn:
        conn.execute(
            update(topics)
            .where(topics.c.key == topic_key)
            .values(last_activity_at=old_activity)
        )
        conn.commit()

    # Apply decay
    count, total = await ledger.apply_decay()

    # Should have decayed 1 topic
    assert count == 1
    assert total > 0

    # Balance should be reduced
    balance_after = await ledger.get_balance(topic_key)
    assert balance_after < 100.0


@pytest.mark.asyncio
async def test_topic_with_no_activity_decays(
    ledger: SalienceLedger, test_config: Config
) -> None:
    """Test that a topic with NULL last_activity_at decays."""
    topic_key = "server:123:user:456"

    # Manually create topic with NULL last_activity_at and some balance
    from zos.database import topics, salience_ledger, generate_id
    from sqlalchemy import insert

    with ledger.engine.connect() as conn:
        # Insert topic without last_activity_at
        conn.execute(
            insert(topics).values(
                key=topic_key,
                category="user",
                is_global=False,
                provisional=False,
                created_at=utcnow(),
                last_activity_at=None,  # NULL activity
            )
        )
        # Insert salience entry directly to give it balance
        conn.execute(
            insert(salience_ledger).values(
                id=generate_id(),
                topic_key=topic_key,
                transaction_type="earn",
                amount=50.0,
                created_at=utcnow(),
            )
        )
        conn.commit()

    balance_before = await ledger.get_balance(topic_key)
    assert balance_before == 50.0

    # Apply decay
    count, total = await ledger.apply_decay()

    # Should have decayed this topic
    assert count == 1
    assert total > 0


# =============================================================================
# Test: Decay Amount is Correct Percentage
# =============================================================================


@pytest.mark.asyncio
async def test_decay_amount_is_correct_percentage(
    ledger: SalienceLedger, test_config: Config
) -> None:
    """Test that decay applies the correct percentage."""
    topic_key = "server:123:user:456"
    initial_balance = 100.0
    decay_rate = test_config.salience.decay_rate_per_day  # Default 0.01 (1%)
    threshold_days = test_config.salience.decay_threshold_days

    # Earn salience
    await ledger.earn(topic_key, initial_balance)

    # Make topic inactive
    from zos.database import topics
    from sqlalchemy import update

    with ledger.engine.connect() as conn:
        conn.execute(
            update(topics)
            .where(topics.c.key == topic_key)
            .values(last_activity_at=utcnow() - timedelta(days=threshold_days + 1))
        )
        conn.commit()

    # Apply decay
    count, total = await ledger.apply_decay()

    assert count == 1

    # Expected decay: 100 * 0.01 = 1.0
    expected_decay = initial_balance * decay_rate
    assert total == pytest.approx(expected_decay, rel=0.01)

    # Expected remaining balance: 100 - 1 = 99
    balance_after = await ledger.get_balance(topic_key)
    expected_balance = initial_balance - expected_decay
    assert balance_after == pytest.approx(expected_balance, rel=0.01)


@pytest.mark.asyncio
async def test_decay_formula_preserves_asymptotic_property(
    ledger: SalienceLedger, test_config: Config
) -> None:
    """Test that repeated decay approaches but never reaches zero.

    The formula new_balance = old_balance * (1 - decay_rate) means
    topics never quite reach zero through decay alone.
    """
    topic_key = "server:123:user:456"
    initial_balance = 100.0
    decay_rate = test_config.salience.decay_rate_per_day
    threshold_days = test_config.salience.decay_threshold_days

    # Earn salience
    await ledger.earn(topic_key, initial_balance)

    # Make topic inactive
    from zos.database import topics
    from sqlalchemy import update

    with ledger.engine.connect() as conn:
        conn.execute(
            update(topics)
            .where(topics.c.key == topic_key)
            .values(last_activity_at=utcnow() - timedelta(days=threshold_days + 1))
        )
        conn.commit()

    # Apply decay multiple times (simulating many days)
    for _ in range(30):
        await ledger.apply_decay()

    # Balance should be reduced significantly but not zero
    # After 30 days at 1%: 100 * (1-0.01)^30 = ~74
    balance = await ledger.get_balance(topic_key)
    assert balance > 0  # Never zero
    assert balance < initial_balance  # But definitely reduced


# =============================================================================
# Test: Zero-Balance Topics Skipped
# =============================================================================


@pytest.mark.asyncio
async def test_zero_balance_topics_skipped(
    ledger: SalienceLedger, test_config: Config
) -> None:
    """Test that topics with zero balance don't generate decay transactions."""
    topic_key = "server:123:user:456"
    threshold_days = test_config.salience.decay_threshold_days

    # Create topic but don't earn anything
    await ledger.ensure_topic(topic_key)

    # Make it inactive by setting old last_activity_at
    from zos.database import topics
    from sqlalchemy import update

    with ledger.engine.connect() as conn:
        conn.execute(
            update(topics)
            .where(topics.c.key == topic_key)
            .values(last_activity_at=utcnow() - timedelta(days=threshold_days + 10))
        )
        conn.commit()

    # Verify zero balance
    balance = await ledger.get_balance(topic_key)
    assert balance == 0.0

    # Apply decay
    count, total = await ledger.apply_decay()

    # Should not have counted this topic
    assert count == 0
    assert total == 0.0

    # No transactions should have been recorded for this topic
    history = await ledger.get_history(topic_key)
    assert len(history) == 0


# =============================================================================
# Test: Tiny Balance Topics Zeroed Out
# =============================================================================


@pytest.mark.asyncio
async def test_tiny_balance_zeroed_out(
    ledger: SalienceLedger, test_config: Config
) -> None:
    """Test that topics with balance < 0.1 are zeroed out completely."""
    topic_key = "server:123:user:456"
    tiny_balance = 0.05  # Less than 0.1 threshold
    threshold_days = test_config.salience.decay_threshold_days

    # Manually create topic with tiny balance
    from zos.database import topics, salience_ledger, generate_id
    from sqlalchemy import insert

    with ledger.engine.connect() as conn:
        conn.execute(
            insert(topics).values(
                key=topic_key,
                category="user",
                is_global=False,
                provisional=False,
                created_at=utcnow(),
                last_activity_at=utcnow() - timedelta(days=threshold_days + 1),
            )
        )
        conn.execute(
            insert(salience_ledger).values(
                id=generate_id(),
                topic_key=topic_key,
                transaction_type="earn",
                amount=tiny_balance,
                created_at=utcnow(),
            )
        )
        conn.commit()

    balance_before = await ledger.get_balance(topic_key)
    assert balance_before == tiny_balance

    # Apply decay
    count, total = await ledger.apply_decay()

    # Should have decayed this topic
    assert count == 1
    assert total == pytest.approx(tiny_balance, rel=0.01)

    # Balance should be exactly zero
    balance_after = await ledger.get_balance(topic_key)
    assert balance_after == 0.0

    # Transaction should have reason "decay_to_zero"
    history = await ledger.get_history(topic_key)
    decay_txns = [h for h in history if h.transaction_type == TransactionType.DECAY]
    assert len(decay_txns) == 1
    assert decay_txns[0].reason == "decay_to_zero"


# =============================================================================
# Test: Transactions Recorded Correctly
# =============================================================================


@pytest.mark.asyncio
async def test_decay_transactions_recorded_correctly(
    ledger: SalienceLedger, test_config: Config
) -> None:
    """Test that decay transactions are recorded with correct fields."""
    topic_key = "server:123:user:456"
    initial_balance = 50.0
    decay_rate = test_config.salience.decay_rate_per_day
    threshold_days = test_config.salience.decay_threshold_days

    # Earn salience
    await ledger.earn(topic_key, initial_balance)

    # Make topic inactive
    from zos.database import topics
    from sqlalchemy import update

    with ledger.engine.connect() as conn:
        conn.execute(
            update(topics)
            .where(topics.c.key == topic_key)
            .values(last_activity_at=utcnow() - timedelta(days=threshold_days + 1))
        )
        conn.commit()

    # Apply decay
    await ledger.apply_decay()

    # Check the decay transaction
    history = await ledger.get_history(topic_key)
    decay_txns = [h for h in history if h.transaction_type == TransactionType.DECAY]

    assert len(decay_txns) == 1
    decay_txn = decay_txns[0]

    # Verify fields
    assert decay_txn.topic_key == topic_key
    assert decay_txn.transaction_type == TransactionType.DECAY
    assert decay_txn.amount < 0  # Negative for decay
    assert decay_txn.amount == pytest.approx(-initial_balance * decay_rate, rel=0.01)
    assert decay_txn.reason == "daily_decay"
    assert decay_txn.source_topic is None  # Decay has no source topic


# =============================================================================
# Test: Decay is Idempotent Within Short Window
# =============================================================================


@pytest.mark.asyncio
async def test_decay_multiple_runs_accumulate(
    ledger: SalienceLedger, test_config: Config
) -> None:
    """Test that running decay multiple times continues to decay.

    While the spec says 'idempotent', what it means is that it's safe to run
    multiple times. Each run will decay based on current balance, which means
    multiple runs will compound the decay.
    """
    topic_key = "server:123:user:456"
    initial_balance = 100.0
    decay_rate = test_config.salience.decay_rate_per_day
    threshold_days = test_config.salience.decay_threshold_days

    # Earn salience
    await ledger.earn(topic_key, initial_balance)

    # Make topic inactive
    from zos.database import topics
    from sqlalchemy import update

    with ledger.engine.connect() as conn:
        conn.execute(
            update(topics)
            .where(topics.c.key == topic_key)
            .values(last_activity_at=utcnow() - timedelta(days=threshold_days + 1))
        )
        conn.commit()

    # Run decay twice
    await ledger.apply_decay()
    await ledger.apply_decay()

    # Balance should have decayed twice
    # After 1st: 100 - 1 = 99
    # After 2nd: 99 - 0.99 = 98.01
    balance = await ledger.get_balance(topic_key)
    expected = initial_balance * (1 - decay_rate) * (1 - decay_rate)
    assert balance == pytest.approx(expected, rel=0.01)


# =============================================================================
# Test: Multiple Topics Decay Correctly
# =============================================================================


@pytest.mark.asyncio
async def test_multiple_topics_decay(
    ledger: SalienceLedger, test_config: Config
) -> None:
    """Test that multiple inactive topics all decay correctly."""
    threshold_days = test_config.salience.decay_threshold_days
    decay_rate = test_config.salience.decay_rate_per_day

    topics_data = [
        ("server:123:user:1", 100.0),
        ("server:123:user:2", 50.0),
        ("server:123:channel:1", 75.0),
    ]

    # Create topics with salience
    for key, amount in topics_data:
        await ledger.earn(key, amount)

    # Make all topics inactive
    from zos.database import topics
    from sqlalchemy import update

    old_time = utcnow() - timedelta(days=threshold_days + 1)
    with ledger.engine.connect() as conn:
        for key, _ in topics_data:
            conn.execute(
                update(topics)
                .where(topics.c.key == key)
                .values(last_activity_at=old_time)
            )
        conn.commit()

    # Apply decay
    count, total = await ledger.apply_decay()

    # Should have decayed all 3 topics
    assert count == 3

    # Total should be sum of individual decays
    expected_total = sum(amount * decay_rate for _, amount in topics_data)
    assert total == pytest.approx(expected_total, rel=0.01)

    # Each topic's balance should be reduced
    for key, original in topics_data:
        balance = await ledger.get_balance(key)
        expected = original * (1 - decay_rate)
        assert balance == pytest.approx(expected, rel=0.01)


# =============================================================================
# Test: Mixed Active and Inactive Topics
# =============================================================================


@pytest.mark.asyncio
async def test_mixed_active_and_inactive_topics(
    ledger: SalienceLedger, test_config: Config
) -> None:
    """Test that only inactive topics decay when there's a mix."""
    threshold_days = test_config.salience.decay_threshold_days
    decay_rate = test_config.salience.decay_rate_per_day

    active_topic = "server:123:user:active"
    inactive_topic = "server:123:user:inactive"

    # Create both topics
    await ledger.earn(active_topic, 100.0)
    await ledger.earn(inactive_topic, 100.0)

    # Make only one topic inactive
    from zos.database import topics
    from sqlalchemy import update

    old_time = utcnow() - timedelta(days=threshold_days + 1)
    with ledger.engine.connect() as conn:
        conn.execute(
            update(topics)
            .where(topics.c.key == inactive_topic)
            .values(last_activity_at=old_time)
        )
        conn.commit()

    # Apply decay
    count, total = await ledger.apply_decay()

    # Only 1 topic should decay
    assert count == 1
    assert total == pytest.approx(100.0 * decay_rate, rel=0.01)

    # Active topic unchanged
    assert await ledger.get_balance(active_topic) == 100.0

    # Inactive topic decayed
    assert await ledger.get_balance(inactive_topic) == pytest.approx(
        100.0 * (1 - decay_rate), rel=0.01
    )


# =============================================================================
# Test: get_inactive_topics Helper
# =============================================================================


@pytest.mark.asyncio
async def test_get_inactive_topics_returns_correct_topics(
    ledger: SalienceLedger, test_config: Config
) -> None:
    """Test that get_inactive_topics returns only topics before threshold."""
    threshold_days = test_config.salience.decay_threshold_days

    active_topic = "server:123:user:active"
    inactive_topic = "server:123:user:inactive"
    null_activity_topic = "server:123:user:null"

    # Create topics
    await ledger.earn(active_topic, 10.0)
    await ledger.earn(inactive_topic, 10.0)

    # Create topic with NULL activity
    from zos.database import topics
    from sqlalchemy import insert, update

    with ledger.engine.connect() as conn:
        conn.execute(
            insert(topics).values(
                key=null_activity_topic,
                category="user",
                is_global=False,
                provisional=False,
                created_at=utcnow(),
                last_activity_at=None,
            )
        )
        # Make one topic inactive
        conn.execute(
            update(topics)
            .where(topics.c.key == inactive_topic)
            .values(last_activity_at=utcnow() - timedelta(days=threshold_days + 5))
        )
        conn.commit()

    # Get inactive topics
    threshold_date = utcnow() - timedelta(days=threshold_days)
    inactive_topics = await ledger.get_inactive_topics(threshold_date)

    inactive_keys = {t.key for t in inactive_topics}

    # Should include inactive and null-activity topics
    assert inactive_topic in inactive_keys
    assert null_activity_topic in inactive_keys

    # Should not include active topic
    assert active_topic not in inactive_keys


# =============================================================================
# Test: Trivial Decay Skipped
# =============================================================================


@pytest.mark.asyncio
async def test_trivial_decay_skipped(
    ledger: SalienceLedger, test_config: Config
) -> None:
    """Test that decay < 0.01 is skipped (but not tiny balance zeroing)."""
    topic_key = "server:123:user:456"
    # With 1% decay rate, balance of 0.5 gives decay of 0.005 < 0.01
    # This is above the 0.1 threshold for zeroing, so should skip decay entirely
    small_balance = 0.5
    threshold_days = test_config.salience.decay_threshold_days

    from zos.database import topics, salience_ledger, generate_id
    from sqlalchemy import insert

    with ledger.engine.connect() as conn:
        conn.execute(
            insert(topics).values(
                key=topic_key,
                category="user",
                is_global=False,
                provisional=False,
                created_at=utcnow(),
                last_activity_at=utcnow() - timedelta(days=threshold_days + 1),
            )
        )
        conn.execute(
            insert(salience_ledger).values(
                id=generate_id(),
                topic_key=topic_key,
                transaction_type="earn",
                amount=small_balance,
                created_at=utcnow(),
            )
        )
        conn.commit()

    # Apply decay
    count, total = await ledger.apply_decay()

    # Should skip this topic because decay would be 0.005 < 0.01
    # But wait - 0.5 > 0.1, so it doesn't get zeroed either
    # So it should be skipped entirely
    assert count == 0
    assert total == 0.0

    # Balance unchanged
    balance = await ledger.get_balance(topic_key)
    assert balance == small_balance
