"""Tests for salience ledger."""

from datetime import UTC, datetime, timedelta

import pytest

from zos.config import EarningWeights
from zos.db import Database
from zos.salience.earner import SalienceEarner
from zos.salience.repository import SalienceRepository
from zos.topics.extractor import MessageContext
from zos.topics.topic_key import TopicCategory, TopicKey


@pytest.fixture
def salience_repo(test_db: Database) -> SalienceRepository:
    """Create a salience repository with test database."""
    return SalienceRepository(test_db)


@pytest.fixture
def salience_earner(test_db: Database) -> SalienceEarner:
    """Create a salience earner with test database."""
    return SalienceEarner(test_db, EarningWeights())


class TestSalienceRepository:
    """Tests for SalienceRepository."""

    def test_earn_salience(self, salience_repo: SalienceRepository) -> None:
        """Test earning salience for a topic."""
        tk = TopicKey.user(123)
        now = datetime.now(UTC)

        salience_repo.earn(tk, 5.0, "message", now, message_id=1)

        balance = salience_repo.get_balance(tk)
        assert balance == 5.0

    def test_earn_multiple(self, salience_repo: SalienceRepository) -> None:
        """Test earning salience multiple times accumulates."""
        tk = TopicKey.user(123)
        now = datetime.now(UTC)

        salience_repo.earn(tk, 5.0, "message", now)
        salience_repo.earn(tk, 3.0, "reaction_received", now)

        balance = salience_repo.get_balance(tk)
        assert balance == 8.0

    def test_spend_salience(self, salience_repo: SalienceRepository) -> None:
        """Test spending salience reduces balance."""
        tk = TopicKey.user(123)
        now = datetime.now(UTC)

        salience_repo.earn(tk, 10.0, "message", now)
        salience_repo.spend(tk, 3.0, "run-1", "channel_digest")

        balance = salience_repo.get_balance(tk)
        assert balance == 7.0

    def test_spend_with_node(self, salience_repo: SalienceRepository) -> None:
        """Test spending salience with node tracking."""
        tk = TopicKey.user(123)
        now = datetime.now(UTC)

        salience_repo.earn(tk, 10.0, "message", now)
        salience_repo.spend(tk, 3.0, "run-1", "channel_digest", "summarize")

        balance = salience_repo.get_balance(tk)
        assert balance == 7.0

    def test_batch_earn(self, salience_repo: SalienceRepository) -> None:
        """Test batch inserting salience entries."""
        now = datetime.now(UTC)
        entries = [
            (TopicKey.user(1), 1.0, "message", now, 100),
            (TopicKey.channel(100), 1.0, "message", now, 100),
            (TopicKey.user_in_channel(100, 1), 1.0, "message", now, 100),
        ]

        salience_repo.earn_batch(entries)

        assert salience_repo.get_balance(TopicKey.user(1)) == 1.0
        assert salience_repo.get_balance(TopicKey.channel(100)) == 1.0
        assert salience_repo.get_balance(TopicKey.user_in_channel(100, 1)) == 1.0

    def test_batch_earn_empty(self, salience_repo: SalienceRepository) -> None:
        """Test batch insert with empty list does nothing."""
        salience_repo.earn_batch([])
        # Should not raise

    def test_get_balance_unknown_topic(self, salience_repo: SalienceRepository) -> None:
        """Test balance for unknown topic is 0."""
        tk = TopicKey.user(999)
        balance = salience_repo.get_balance(tk)
        assert balance == 0.0

    def test_get_balance_since(self, salience_repo: SalienceRepository) -> None:
        """Test time-windowed balance queries."""
        tk = TopicKey.user(123)
        old = datetime.now(UTC) - timedelta(days=10)
        recent = datetime.now(UTC) - timedelta(hours=1)
        cutoff = datetime.now(UTC) - timedelta(days=5)

        salience_repo.earn(tk, 5.0, "message", old)
        salience_repo.earn(tk, 3.0, "message", recent)

        # Total balance is 8
        assert salience_repo.get_balance(tk) == 8.0

        # Balance since cutoff is only 3 (recent)
        assert salience_repo.get_balance_since(tk, cutoff) == 3.0

    def test_get_top_by_category(self, salience_repo: SalienceRepository) -> None:
        """Test getting top topics by category."""
        now = datetime.now(UTC)

        # Add salience for multiple users
        for user_id in [1, 2, 3]:
            tk = TopicKey.user(user_id)
            salience_repo.earn(tk, float(user_id * 10), "message", now)

        results = salience_repo.get_top_by_category(TopicCategory.USER, limit=2)

        assert len(results) == 2
        assert results[0].topic_key == "user:3"  # Highest (30)
        assert results[1].topic_key == "user:2"  # Second (20)
        assert results[0].balance == 30.0
        assert results[1].balance == 20.0

    def test_get_top_by_category_with_spending(
        self, salience_repo: SalienceRepository
    ) -> None:
        """Test top topics accounts for spending."""
        now = datetime.now(UTC)

        # User 1: earns 100, spends 90 = balance 10
        # User 2: earns 50, spends 0 = balance 50
        salience_repo.earn(TopicKey.user(1), 100.0, "message", now)
        salience_repo.spend(TopicKey.user(1), 90.0, "run-1", "test")
        salience_repo.earn(TopicKey.user(2), 50.0, "message", now)

        results = salience_repo.get_top_by_category(TopicCategory.USER)

        assert results[0].topic_key == "user:2"  # Higher balance after spending
        assert results[0].balance == 50.0
        assert results[1].topic_key == "user:1"
        assert results[1].balance == 10.0

    def test_get_top_by_category_since(self, salience_repo: SalienceRepository) -> None:
        """Test top topics with time filter."""
        old = datetime.now(UTC) - timedelta(days=10)
        recent = datetime.now(UTC) - timedelta(hours=1)
        cutoff = datetime.now(UTC) - timedelta(days=5)

        # Old salience (before cutoff)
        salience_repo.earn(TopicKey.user(1), 100.0, "message", old)

        # Recent salience
        salience_repo.earn(TopicKey.user(2), 10.0, "message", recent)

        results = salience_repo.get_top_by_category(TopicCategory.USER, since=cutoff)

        # Only user 2 should appear (user 1's salience is before cutoff)
        assert len(results) == 1
        assert results[0].topic_key == "user:2"

    def test_get_total_earned_by_category(
        self, salience_repo: SalienceRepository
    ) -> None:
        """Test getting total earned for a category."""
        now = datetime.now(UTC)

        salience_repo.earn(TopicKey.user(1), 10.0, "message", now)
        salience_repo.earn(TopicKey.user(2), 20.0, "message", now)
        salience_repo.earn(TopicKey.channel(100), 5.0, "message", now)

        total = salience_repo.get_total_earned_by_category(TopicCategory.USER)
        assert total == 30.0

        total = salience_repo.get_total_earned_by_category(TopicCategory.CHANNEL)
        assert total == 5.0


class TestSalienceEarner:
    """Tests for SalienceEarner."""

    def test_earn_for_message_basic(self, salience_earner: SalienceEarner) -> None:
        """Test earning salience for a basic message."""
        ctx = MessageContext(
            author_id=123,
            channel_id=456,
            content="Hello world",
            is_tracked=True,
        )
        now = datetime.now(UTC)

        count = salience_earner.earn_for_message(ctx, message_id=1, timestamp=now)

        # Should create 3 entries: user, channel, user_in_channel
        assert count == 3

        assert salience_earner.repository.get_balance(TopicKey.user(123)) == 1.0
        assert salience_earner.repository.get_balance(TopicKey.channel(456)) == 1.0
        assert (
            salience_earner.repository.get_balance(TopicKey.user_in_channel(456, 123))
            == 1.0
        )

    def test_earn_for_message_with_mention(
        self, salience_earner: SalienceEarner
    ) -> None:
        """Test earning salience for a message with mentions."""
        ctx = MessageContext(
            author_id=123,
            channel_id=456,
            content="Hey <@789>!",
            is_tracked=True,
        )
        now = datetime.now(UTC)

        count = salience_earner.earn_for_message(ctx, message_id=1, timestamp=now)

        # 3 base keys + 2 dyad keys = 5 entries for message points
        # Plus 2 mention bonus entries for dyad keys
        # Total = 7
        assert count == 7

        # Dyad gets both message points (1.0) and mention bonus (0.5)
        assert salience_earner.repository.get_balance(TopicKey.dyad(123, 789)) == 1.5

    def test_earn_for_message_untracked(
        self, salience_earner: SalienceEarner
    ) -> None:
        """Test untracked users don't earn salience."""
        ctx = MessageContext(
            author_id=123,
            channel_id=456,
            content="Hello",
            is_tracked=False,
        )
        now = datetime.now(UTC)

        count = salience_earner.earn_for_message(ctx, message_id=1, timestamp=now)

        assert count == 0
        assert salience_earner.repository.get_balance(TopicKey.user(123)) == 0.0

    def test_earn_for_reaction_given(self, salience_earner: SalienceEarner) -> None:
        """Test earning salience for giving a reaction."""
        now = datetime.now(UTC)

        count = salience_earner.earn_for_reaction_given(
            reactor_id=123,
            channel_id=456,
            message_id=1,
            timestamp=now,
            is_tracked=True,
        )

        # 3 entries: user, channel, user_in_channel
        assert count == 3
        assert salience_earner.repository.get_balance(TopicKey.user(123)) == 0.5
        assert salience_earner.repository.get_balance(TopicKey.channel(456)) == 0.5

    def test_earn_for_reaction_given_untracked(
        self, salience_earner: SalienceEarner
    ) -> None:
        """Test untracked reactors don't earn salience."""
        now = datetime.now(UTC)

        count = salience_earner.earn_for_reaction_given(
            reactor_id=123,
            channel_id=456,
            message_id=1,
            timestamp=now,
            is_tracked=False,
        )

        assert count == 0

    def test_earn_for_reaction_received(
        self, salience_earner: SalienceEarner
    ) -> None:
        """Test earning salience for receiving a reaction."""
        now = datetime.now(UTC)

        count = salience_earner.earn_for_reaction_received(
            author_id=123,
            reactor_id=789,
            channel_id=456,
            message_id=1,
            timestamp=now,
            is_author_tracked=True,
        )

        # 4 entries: user, user_in_channel, dyad, dyad_in_channel
        assert count == 4
        assert salience_earner.repository.get_balance(TopicKey.user(123)) == 0.3
        assert salience_earner.repository.get_balance(TopicKey.dyad(123, 789)) == 0.3

    def test_earn_for_reaction_received_untracked(
        self, salience_earner: SalienceEarner
    ) -> None:
        """Test untracked authors don't earn salience from reactions."""
        now = datetime.now(UTC)

        count = salience_earner.earn_for_reaction_received(
            author_id=123,
            reactor_id=789,
            channel_id=456,
            message_id=1,
            timestamp=now,
            is_author_tracked=False,
        )

        assert count == 0

    def test_custom_weights(self, test_db: Database) -> None:
        """Test custom earning weights are applied."""
        weights = EarningWeights(message=5.0, mention=2.0)
        earner = SalienceEarner(test_db, weights)

        ctx = MessageContext(
            author_id=123,
            channel_id=456,
            content="Hey <@789>!",
            is_tracked=True,
        )
        now = datetime.now(UTC)

        earner.earn_for_message(ctx, message_id=1, timestamp=now)

        # User gets 5 points (message weight)
        assert earner.repository.get_balance(TopicKey.user(123)) == 5.0

        # Dyad gets 5 (message) + 2 (mention) = 7
        assert earner.repository.get_balance(TopicKey.dyad(123, 789)) == 7.0
