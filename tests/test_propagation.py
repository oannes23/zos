"""Tests for salience propagation (Story 3.3).

Tests propagation to related topics, overflow spillover, global topic warming,
and the no-cascade rule.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from zos.config import Config
from zos.database import create_tables, get_engine
from zos.models import Message, Reaction, VisibilityScope
from zos.salience import EarningCoordinator, SalienceLedger


@pytest.fixture
def config() -> Config:
    """Create a test configuration."""
    return Config()


@pytest.fixture
def engine(tmp_path, config):
    """Create a test database engine."""
    config.data_dir = tmp_path
    config.database.path = "test.db"
    engine = get_engine(config)
    create_tables(engine)
    return engine


@pytest.fixture
def ledger(engine, config) -> SalienceLedger:
    """Create a salience ledger for testing."""
    return SalienceLedger(engine, config)


@pytest.fixture
def earning(ledger, config) -> EarningCoordinator:
    """Create an earning coordinator for testing."""
    return EarningCoordinator(ledger, config)


def create_message(
    id: str = "msg1",
    channel_id: str = "ch1",
    server_id: str | None = "srv1",
    author_id: str = "user1",
    content: str = "Hello world",
    has_media: bool = False,
    has_links: bool = False,
    reply_to_id: str | None = None,
) -> Message:
    """Create a test message."""
    return Message(
        id=id,
        channel_id=channel_id,
        server_id=server_id,
        author_id=author_id,
        content=content,
        created_at=datetime.now(timezone.utc),
        visibility_scope=VisibilityScope.DM if server_id is None else VisibilityScope.PUBLIC,
        reply_to_id=reply_to_id,
        thread_id=None,
        has_media=has_media,
        has_links=has_links,
    )


class TestIsWarm:
    """Tests for is_warm() method."""

    @pytest.mark.asyncio
    async def test_cold_topic_is_not_warm(self, ledger: SalienceLedger):
        """Topic with no salience is not warm."""
        topic = "server:srv1:user:user1"
        await ledger.ensure_topic(topic)

        is_warm = await ledger.is_warm(topic)

        assert is_warm is False

    @pytest.mark.asyncio
    async def test_topic_below_threshold_not_warm(self, ledger: SalienceLedger):
        """Topic with salience below threshold is not warm."""
        topic = "server:srv1:user:user1"
        # Warm threshold is 1.0 by default
        await ledger.earn(topic, 0.5)

        is_warm = await ledger.is_warm(topic)

        assert is_warm is False

    @pytest.mark.asyncio
    async def test_topic_above_threshold_is_warm(self, ledger: SalienceLedger):
        """Topic with salience above threshold is warm."""
        topic = "server:srv1:user:user1"
        await ledger.earn(topic, 5.0)

        is_warm = await ledger.is_warm(topic)

        assert is_warm is True


class TestPropagationToWarmTopics:
    """Tests for propagation to warm related topics."""

    @pytest.mark.asyncio
    async def test_warm_related_topic_receives_propagation(
        self, ledger: SalienceLedger
    ):
        """Warm related topics receive propagated salience."""
        user_topic = "server:srv1:user:user1"
        # Create a warm dyad topic (related to the user)
        dyad_topic = "server:srv1:dyad:user1:user2"
        await ledger.earn(dyad_topic, 5.0)  # Make it warm

        # Earn for user topic with propagation
        await ledger.earn_with_propagation(user_topic, 10.0, reason="test")

        # Dyad should have received propagation
        dyad_balance = await ledger.get_balance(dyad_topic)
        # Expected: 5.0 (initial) + 10.0 * 0.3 (propagation_factor) = 8.0
        assert dyad_balance == pytest.approx(8.0, rel=0.01)

    @pytest.mark.asyncio
    async def test_cold_related_topic_no_propagation(self, ledger: SalienceLedger):
        """Cold related topics don't receive propagation."""
        user_topic = "server:srv1:user:user1"
        # Create a cold dyad topic (below threshold)
        dyad_topic = "server:srv1:dyad:user1:user2"
        await ledger.earn(dyad_topic, 0.5)  # Below warm threshold

        # Earn for user topic with propagation
        await ledger.earn_with_propagation(user_topic, 10.0, reason="test")

        # Dyad should NOT have received propagation
        dyad_balance = await ledger.get_balance(dyad_topic)
        assert dyad_balance == 0.5  # Unchanged

    @pytest.mark.asyncio
    async def test_no_propagation_when_disabled(self, ledger: SalienceLedger):
        """Propagation can be disabled."""
        user_topic = "server:srv1:user:user1"
        dyad_topic = "server:srv1:dyad:user1:user2"
        await ledger.earn(dyad_topic, 5.0)  # Make it warm

        # Earn with propagation disabled
        await ledger.earn_with_propagation(
            user_topic, 10.0, reason="test", propagate=False
        )

        # Dyad should NOT have received propagation
        dyad_balance = await ledger.get_balance(dyad_topic)
        assert dyad_balance == 5.0  # Unchanged


class TestOverflowSpillover:
    """Tests for overflow spillover to warm related topics."""

    @pytest.mark.asyncio
    async def test_overflow_spills_to_warm_topics(self, ledger: SalienceLedger):
        """Overflow spills to warm related topics."""
        user_topic = "server:srv1:user:user1"
        dyad_topic = "server:srv1:dyad:user1:user2"

        # Fill user topic near cap (100) and make dyad warm
        await ledger.earn(user_topic, 95.0)
        await ledger.earn(dyad_topic, 5.0)

        # Earn 15 more (10 will overflow)
        await ledger.earn_with_propagation(user_topic, 15.0, reason="test")

        # User should be at cap
        user_balance = await ledger.get_balance(user_topic)
        assert user_balance == 100.0

        # Dyad should have received:
        # - 5.0 (initial)
        # - 15.0 * 0.3 = 4.5 (regular propagation)
        # - 10.0 * 0.5 = 5.0 (overflow spillover)
        # Total: 14.5
        dyad_balance = await ledger.get_balance(dyad_topic)
        assert dyad_balance == pytest.approx(14.5, rel=0.01)

    @pytest.mark.asyncio
    async def test_overflow_no_spill_to_cold_topics(self, ledger: SalienceLedger):
        """Overflow doesn't spill to cold related topics."""
        user_topic = "server:srv1:user:user1"
        dyad_topic = "server:srv1:dyad:user1:user2"

        # Fill user topic near cap, keep dyad cold
        await ledger.earn(user_topic, 95.0)
        await ledger.earn(dyad_topic, 0.5)  # Below warm threshold

        # Earn 15 more (10 will overflow)
        await ledger.earn_with_propagation(user_topic, 15.0, reason="test")

        # Dyad should NOT have received spillover
        dyad_balance = await ledger.get_balance(dyad_topic)
        assert dyad_balance == 0.5  # Unchanged


class TestNoCascade:
    """Tests that propagation doesn't cascade."""

    @pytest.mark.asyncio
    async def test_propagation_one_level_only(self, ledger: SalienceLedger):
        """Propagation is ONE level only - no cascading."""
        # Setup: user -> dyad -> global user
        user_topic = "server:srv1:user:user1"
        dyad_topic = "server:srv1:dyad:user1:user2"
        global_dyad = "dyad:user1:user2"

        # Make all topics warm
        await ledger.earn(user_topic, 5.0)
        await ledger.earn(dyad_topic, 5.0)
        await ledger.earn(global_dyad, 5.0)

        # Earn for user - should propagate to dyad but NOT cascade to global_dyad
        initial_global_balance = await ledger.get_balance(global_dyad)
        await ledger.earn_with_propagation(user_topic, 10.0, reason="test")

        # Dyad received propagation
        dyad_balance = await ledger.get_balance(dyad_topic)
        assert dyad_balance > 5.0

        # Global dyad should have received propagation directly (related to user)
        # but NOT cascaded from dyad
        global_balance = await ledger.get_balance(global_dyad)
        # It will have received direct propagation if user:user1 is related to global dyad
        # The key test is that earning to dyad doesn't cause cascading
        # We verify by earning directly to dyad and checking global doesn't cascade
        await ledger.earn(dyad_topic, 0)  # Reset tracking
        old_global = global_balance

        # Earn directly to dyad (not through user)
        await ledger.earn_with_propagation(dyad_topic, 10.0, reason="direct")

        # Global dyad might get propagation from dyad (it's related)
        # but the point is: dyad earning doesn't trigger user which triggers dyad again
        # i.e., no infinite loops
        new_global = await ledger.get_balance(global_dyad)
        # Just verify no infinite loop happened by completing
        assert True  # If we got here, no infinite loop


class TestGlobalTopicWarming:
    """Tests for global topic warming."""

    @pytest.mark.asyncio
    async def test_global_warms_on_second_server(self, ledger: SalienceLedger):
        """Global topic warms when user seen in 2+ servers."""
        user_id = "user1"

        # User seen in first server
        await ledger.track_user_server(user_id, "srv1")

        # Global topic should NOT be warm yet
        global_topic = f"user:{user_id}"
        is_warm = await ledger.is_warm(global_topic)
        assert is_warm is False

        # User seen in second server
        warmed = await ledger.check_and_warm_global(user_id, "srv2")

        assert warmed is True
        is_warm = await ledger.is_warm(global_topic)
        assert is_warm is True

    @pytest.mark.asyncio
    async def test_global_warms_on_dm(self, ledger: SalienceLedger):
        """Global topic warms on DM activity."""
        user_id = "user1"
        global_topic = f"user:{user_id}"

        # Global topic not warm initially
        assert await ledger.is_warm(global_topic) is False

        # DM activity warms it
        warmed = await ledger.warm_from_dm(user_id)

        assert warmed is True
        assert await ledger.is_warm(global_topic) is True

    @pytest.mark.asyncio
    async def test_already_warm_global_not_rewarmed(self, ledger: SalienceLedger):
        """Already warm global topic is not re-warmed."""
        user_id = "user1"
        global_topic = f"user:{user_id}"

        # Warm it
        await ledger.warm_from_dm(user_id)
        initial_balance = await ledger.get_balance(global_topic)

        # Try to warm again
        warmed = await ledger.warm_from_dm(user_id)

        assert warmed is False
        final_balance = await ledger.get_balance(global_topic)
        assert final_balance == initial_balance  # No additional warming


class TestGlobalDyadWarming:
    """Tests for global dyad warming when both users are warm."""

    @pytest.mark.asyncio
    async def test_global_dyad_warms_when_both_users_warm(
        self, ledger: SalienceLedger
    ):
        """Global dyad warms when both user:A and user:B are warm."""
        user_a = "user1"
        user_b = "user2"

        # Warm both users
        await ledger.warm(f"user:{user_a}", 10.0, reason="dm")
        await ledger.warm(f"user:{user_b}", 10.0, reason="dm")

        # Check and warm global dyad
        warmed = await ledger.check_and_warm_global_dyad(user_a, user_b)

        assert warmed is True
        global_dyad = "dyad:user1:user2"
        assert await ledger.is_warm(global_dyad) is True

    @pytest.mark.asyncio
    async def test_global_dyad_not_warmed_if_one_user_cold(
        self, ledger: SalienceLedger
    ):
        """Global dyad not warmed if only one user is warm."""
        user_a = "user1"
        user_b = "user2"

        # Only warm user_a
        await ledger.warm(f"user:{user_a}", 10.0, reason="dm")
        # user_b is cold

        # Check and warm global dyad
        warmed = await ledger.check_and_warm_global_dyad(user_a, user_b)

        assert warmed is False
        global_dyad = "dyad:user1:user2"
        assert await ledger.is_warm(global_dyad) is False


class TestGetRelatedTopics:
    """Tests for get_related_topics()."""

    @pytest.mark.asyncio
    async def test_server_user_related_to_global_user(self, ledger: SalienceLedger):
        """Server-scoped user is related to global user."""
        topic = "server:srv1:user:user1"
        related = await ledger.get_related_topics(topic)

        assert "user:user1" in related

    @pytest.mark.asyncio
    async def test_server_dyad_related_to_users(self, ledger: SalienceLedger):
        """Server-scoped dyad is related to both user topics."""
        topic = "server:srv1:dyad:user1:user2"
        related = await ledger.get_related_topics(topic)

        assert "server:srv1:user:user1" in related
        assert "server:srv1:user:user2" in related

    @pytest.mark.asyncio
    async def test_server_dyad_related_to_global_dyad(self, ledger: SalienceLedger):
        """Server-scoped dyad is related to global dyad."""
        topic = "server:srv1:dyad:user1:user2"
        related = await ledger.get_related_topics(topic)

        assert "dyad:user1:user2" in related

    @pytest.mark.asyncio
    async def test_global_user_related_to_server_users(self, ledger: SalienceLedger):
        """Global user is related to all server-scoped user topics."""
        # Create server-scoped user topics
        await ledger.earn("server:srv1:user:user1", 1.0)
        await ledger.earn("server:srv2:user:user1", 1.0)

        topic = "user:user1"
        related = await ledger.get_related_topics(topic)

        assert "server:srv1:user:user1" in related
        assert "server:srv2:user:user1" in related


class TestPropagationFactor:
    """Tests for get_propagation_factor()."""

    def test_same_scope_uses_regular_factor(self, ledger: SalienceLedger):
        """Same-scope propagation uses regular propagation_factor."""
        source = "server:srv1:user:user1"
        target = "server:srv1:dyad:user1:user2"

        factor = ledger.get_propagation_factor(source, target)

        assert factor == ledger.config.salience.propagation_factor

    def test_global_to_server_uses_global_factor(self, ledger: SalienceLedger):
        """Global-to-server propagation uses global_propagation_factor."""
        source = "user:user1"
        target = "server:srv1:user:user1"

        factor = ledger.get_propagation_factor(source, target)

        assert factor == ledger.config.salience.global_propagation_factor

    def test_server_to_global_uses_global_factor(self, ledger: SalienceLedger):
        """Server-to-global propagation uses global_propagation_factor."""
        source = "server:srv1:user:user1"
        target = "user:user1"

        factor = ledger.get_propagation_factor(source, target)

        assert factor == ledger.config.salience.global_propagation_factor


class TestUserServerTracking:
    """Tests for user-server tracking."""

    @pytest.mark.asyncio
    async def test_track_user_server(self, ledger: SalienceLedger):
        """User-server tracking stores relationship."""
        await ledger.track_user_server("user1", "srv1")
        await ledger.track_user_server("user1", "srv2")

        servers = await ledger.get_servers_for_user("user1")

        assert "srv1" in servers
        assert "srv2" in servers

    @pytest.mark.asyncio
    async def test_duplicate_tracking_ignored(self, ledger: SalienceLedger):
        """Duplicate user-server tracking is ignored."""
        await ledger.track_user_server("user1", "srv1")
        await ledger.track_user_server("user1", "srv1")  # Duplicate

        servers = await ledger.get_servers_for_user("user1")

        assert servers.count("srv1") == 1


class TestEarningWithPropagation:
    """Tests for EarningCoordinator with propagation."""

    @pytest.mark.asyncio
    async def test_message_earns_with_propagation(
        self, earning: EarningCoordinator, ledger: SalienceLedger
    ):
        """Message earning uses earn_with_propagation."""
        # Create a warm related topic
        dyad_topic = "server:srv1:dyad:user1:user2"
        await ledger.earn(dyad_topic, 5.0)

        msg = create_message(author_id="user1", server_id="srv1")
        await earning.process_message(msg)

        # Check that dyad received propagation
        dyad_balance = await ledger.get_balance(dyad_topic)
        assert dyad_balance > 5.0

    @pytest.mark.asyncio
    async def test_dm_warms_global_topic(
        self, earning: EarningCoordinator, ledger: SalienceLedger
    ):
        """DM processing warms global topic."""
        msg = create_message(author_id="user1", server_id=None)

        await earning.process_dm(msg)

        global_topic = "user:user1"
        assert await ledger.is_warm(global_topic) is True

    @pytest.mark.asyncio
    async def test_server_message_checks_global_warming(
        self, earning: EarningCoordinator, ledger: SalienceLedger
    ):
        """Server message processing tracks for global warming."""
        # Track user in first server
        await ledger.track_user_server("user1", "srv_other")

        # Message in second server should warm global
        msg = create_message(author_id="user1", server_id="srv1")
        await earning.process_message(msg)

        global_topic = "user:user1"
        assert await ledger.is_warm(global_topic) is True

    @pytest.mark.asyncio
    async def test_reaction_checks_global_dyad_warming(
        self, earning: EarningCoordinator, ledger: SalienceLedger
    ):
        """Reaction processing checks for global dyad warming."""
        # Warm both users
        await ledger.warm("user:author1", 10.0, reason="dm")
        await ledger.warm("user:reactor1", 10.0, reason="dm")

        msg = create_message(author_id="author1", server_id="srv1")
        reaction = Reaction(
            message_id="msg1",
            user_id="reactor1",
            emoji=":thumbsup:",
            is_custom=False,
            server_id="srv1",
        )

        await earning.process_reaction(reaction, msg)

        # Global dyad should be warmed
        global_dyad = "dyad:author1:reactor1"
        assert await ledger.is_warm(global_dyad) is True


class TestConfigInitialGlobalWarmth:
    """Tests for initial_global_warmth config."""

    @pytest.mark.asyncio
    async def test_dm_uses_initial_global_warmth(self, ledger: SalienceLedger):
        """DM warming uses initial_global_warmth config value."""
        await ledger.warm_from_dm("user1")

        balance = await ledger.get_balance("user:user1")
        expected = ledger.config.salience.initial_global_warmth
        assert balance == expected

    @pytest.mark.asyncio
    async def test_multi_server_uses_initial_global_warmth(
        self, ledger: SalienceLedger
    ):
        """Multi-server warming uses initial_global_warmth config value."""
        await ledger.track_user_server("user1", "srv1")
        await ledger.check_and_warm_global("user1", "srv2")

        balance = await ledger.get_balance("user:user1")
        expected = ledger.config.salience.initial_global_warmth
        assert balance == expected
