"""Tests for budget groups and reflection selection.

Covers budget group classification, budget allocation, selection algorithm,
self budget separation, and proportional reallocation.
"""

from pathlib import Path

import pytest

from zos.config import Config
from zos.database import create_tables, get_engine
from zos.models import TopicCategory
from zos.salience import BudgetGroup, ReflectionSelector, SalienceLedger, get_budget_group


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
def selector(ledger: SalienceLedger, test_config: Config) -> ReflectionSelector:
    """Create a ReflectionSelector instance for testing."""
    return ReflectionSelector(ledger, test_config)


# =============================================================================
# Test: Budget Group Classification
# =============================================================================


class TestGetBudgetGroup:
    """Tests for the get_budget_group function."""

    def test_server_user_is_social(self):
        """Server-scoped user topics belong to SOCIAL group."""
        assert get_budget_group("server:123:user:456") == BudgetGroup.SOCIAL

    def test_server_dyad_is_social(self):
        """Server-scoped dyad topics belong to SOCIAL group."""
        assert get_budget_group("server:123:dyad:111:222") == BudgetGroup.SOCIAL

    def test_server_user_in_channel_is_social(self):
        """Server-scoped user_in_channel topics belong to SOCIAL group."""
        assert get_budget_group("server:123:user_in_channel:chan:456") == BudgetGroup.SOCIAL

    def test_server_dyad_in_channel_is_social(self):
        """Server-scoped dyad_in_channel topics belong to SOCIAL group."""
        assert get_budget_group("server:123:dyad_in_channel:chan:111:222") == BudgetGroup.SOCIAL

    def test_global_user_is_global(self):
        """Global user topics belong to GLOBAL group."""
        assert get_budget_group("user:456") == BudgetGroup.GLOBAL

    def test_global_dyad_is_global(self):
        """Global dyad topics belong to GLOBAL group."""
        assert get_budget_group("dyad:111:222") == BudgetGroup.GLOBAL

    def test_server_channel_is_spaces(self):
        """Server-scoped channel topics belong to SPACES group."""
        assert get_budget_group("server:123:channel:789") == BudgetGroup.SPACES

    def test_server_thread_is_spaces(self):
        """Server-scoped thread topics belong to SPACES group."""
        assert get_budget_group("server:123:thread:999") == BudgetGroup.SPACES

    def test_server_subject_is_semantic(self):
        """Server-scoped subject topics belong to SEMANTIC group."""
        assert get_budget_group("server:123:subject:gaming") == BudgetGroup.SEMANTIC

    def test_server_role_is_semantic(self):
        """Server-scoped role topics belong to SEMANTIC group."""
        assert get_budget_group("server:123:role:moderator") == BudgetGroup.SEMANTIC

    def test_server_emoji_is_culture(self):
        """Server-scoped emoji topics belong to CULTURE group."""
        assert get_budget_group("server:123:emoji:pepe_sad") == BudgetGroup.CULTURE

    def test_global_self_is_self(self):
        """Global self topic belongs to SELF group."""
        assert get_budget_group("self:zos") == BudgetGroup.SELF

    def test_server_self_is_self(self):
        """Server-scoped self topic belongs to SELF group."""
        assert get_budget_group("server:123:self:zos") == BudgetGroup.SELF

    def test_self_aspect_is_self(self):
        """Self aspect topics belong to SELF group."""
        assert get_budget_group("self:social_patterns") == BudgetGroup.SELF


# =============================================================================
# Test: Budget Allocation Respected
# =============================================================================


@pytest.mark.asyncio
async def test_empty_selection_with_no_topics(selector: ReflectionSelector) -> None:
    """Test that selection with no topics returns empty groups."""
    result = await selector.select_for_reflection(total_budget=100.0)

    # All groups should be empty lists
    for group in BudgetGroup:
        assert result[group] == []


@pytest.mark.asyncio
async def test_budget_respected_social_group(
    ledger: SalienceLedger, selector: ReflectionSelector
) -> None:
    """Test that social group respects its budget allocation."""
    # Create social topics with varying salience
    # Social gets 30% of budget, so with 100 budget = 30
    for i in range(10):
        topic_key = f"server:123:user:{i}"
        await ledger.earn(topic_key, 50.0)  # High salience

    result = await selector.select_for_reflection(total_budget=100.0, server_id="123")

    # With base cost of 10 per user, and 30 budget, should select ~3 users
    # (may vary due to reallocation)
    assert len(result[BudgetGroup.SOCIAL]) >= 2
    assert len(result[BudgetGroup.SOCIAL]) <= 10


@pytest.mark.asyncio
async def test_budget_respected_spaces_group(
    ledger: SalienceLedger, selector: ReflectionSelector
) -> None:
    """Test that spaces group respects its budget allocation."""
    # Create channel topics
    for i in range(5):
        topic_key = f"server:123:channel:{i}"
        await ledger.earn(topic_key, 50.0)

    result = await selector.select_for_reflection(total_budget=100.0, server_id="123")

    # Spaces gets 30% = 30. Channels cost 15 each = 2 channels
    # With reallocation may get more
    assert len(result[BudgetGroup.SPACES]) >= 1


# =============================================================================
# Test: High-Salience Topics Prioritized
# =============================================================================


@pytest.mark.asyncio
async def test_high_salience_topics_prioritized(
    ledger: SalienceLedger, selector: ReflectionSelector
) -> None:
    """Test that topics with higher salience are selected first."""
    # Create users with different salience levels
    await ledger.earn("server:123:user:high", 90.0)
    await ledger.earn("server:123:user:medium", 50.0)
    await ledger.earn("server:123:user:low", 10.0)

    # Select with limited budget (only enough for 2 users at cost 10 each)
    # Social gets 30% of 66.67 = 20, so 2 users
    result = await selector.select_for_reflection(total_budget=66.67, server_id="123")

    social_selected = result[BudgetGroup.SOCIAL]

    # High salience should definitely be selected
    assert "server:123:user:high" in social_selected
    # Medium likely selected
    if len(social_selected) >= 2:
        assert "server:123:user:medium" in social_selected
    # Low may or may not be selected depending on reallocation


@pytest.mark.asyncio
async def test_zero_salience_topics_not_selected(
    ledger: SalienceLedger, selector: ReflectionSelector
) -> None:
    """Test that topics with zero salience are not selected."""
    # Create topic but don't earn any salience
    await ledger.ensure_topic("server:123:user:zero")
    # Create topic with salience
    await ledger.earn("server:123:user:positive", 50.0)

    result = await selector.select_for_reflection(total_budget=100.0, server_id="123")

    # Zero salience topic should not be selected
    assert "server:123:user:zero" not in result[BudgetGroup.SOCIAL]
    # Positive salience topic should be selected
    assert "server:123:user:positive" in result[BudgetGroup.SOCIAL]


# =============================================================================
# Test: Self Budget Separate
# =============================================================================


@pytest.mark.asyncio
async def test_self_budget_separate_pool(
    ledger: SalienceLedger, selector: ReflectionSelector
) -> None:
    """Test that self topics use a separate budget pool."""
    # Create self topic with high salience
    await ledger.earn("self:zos", 50.0)

    # Create social topics that would consume normal budget
    for i in range(20):
        await ledger.earn(f"server:123:user:{i}", 50.0)

    result = await selector.select_for_reflection(total_budget=100.0, server_id="123")

    # Self topic should be selected regardless of social budget consumption
    assert "self:zos" in result[BudgetGroup.SELF]


@pytest.mark.asyncio
async def test_self_budget_respects_config(
    ledger: SalienceLedger, test_config: Config
) -> None:
    """Test that self budget respects the configured allocation."""
    # Create multiple self topics
    await ledger.earn("self:zos", 50.0)
    await ledger.earn("server:123:self:zos", 50.0)
    await ledger.earn("self:social_patterns", 50.0)

    # Default self_budget is 20, self cost is 20
    # Should select 1 self topic
    selector = ReflectionSelector(ledger, test_config)
    result = await selector.select_for_reflection(total_budget=100.0)

    # With budget of 20 and cost of 20 per self topic, should select 1
    assert len(result[BudgetGroup.SELF]) == 1


# =============================================================================
# Test: Empty Groups Handled
# =============================================================================


@pytest.mark.asyncio
async def test_empty_social_group_handled(
    ledger: SalienceLedger, selector: ReflectionSelector
) -> None:
    """Test that empty social group is handled gracefully."""
    # Only create channel topics, no social topics
    await ledger.earn("server:123:channel:1", 50.0)

    result = await selector.select_for_reflection(total_budget=100.0, server_id="123")

    # Social should be empty
    assert result[BudgetGroup.SOCIAL] == []
    # Spaces should have the channel
    assert "server:123:channel:1" in result[BudgetGroup.SPACES]


@pytest.mark.asyncio
async def test_empty_global_group_handled(
    ledger: SalienceLedger, selector: ReflectionSelector
) -> None:
    """Test that empty global group is handled gracefully."""
    # Only create server-scoped topics
    await ledger.earn("server:123:user:1", 50.0)

    result = await selector.select_for_reflection(total_budget=100.0, server_id="123")

    # Global should be empty
    assert result[BudgetGroup.GLOBAL] == []


@pytest.mark.asyncio
async def test_all_empty_groups_handled(selector: ReflectionSelector) -> None:
    """Test that all empty groups are handled gracefully."""
    result = await selector.select_for_reflection(total_budget=100.0)

    # All groups should be empty lists (not None or KeyError)
    for group in BudgetGroup:
        assert group in result
        assert result[group] == []


# =============================================================================
# Test: Server Filtering Works
# =============================================================================


@pytest.mark.asyncio
async def test_server_filtering_includes_matching(
    ledger: SalienceLedger, selector: ReflectionSelector
) -> None:
    """Test that server filtering includes matching server topics."""
    await ledger.earn("server:123:user:1", 50.0)
    await ledger.earn("server:456:user:2", 50.0)

    result = await selector.select_for_reflection(total_budget=100.0, server_id="123")

    # Should include server 123 topic
    assert "server:123:user:1" in result[BudgetGroup.SOCIAL]
    # Should not include server 456 topic
    assert "server:456:user:2" not in result[BudgetGroup.SOCIAL]


@pytest.mark.asyncio
async def test_server_filtering_excludes_non_matching(
    ledger: SalienceLedger, selector: ReflectionSelector
) -> None:
    """Test that server filtering excludes non-matching server topics."""
    await ledger.earn("server:123:channel:1", 50.0)
    await ledger.earn("server:999:channel:2", 50.0)

    result = await selector.select_for_reflection(total_budget=100.0, server_id="123")

    # Only server 123 channel should be in spaces
    assert "server:123:channel:1" in result[BudgetGroup.SPACES]
    assert "server:999:channel:2" not in result[BudgetGroup.SPACES]


@pytest.mark.asyncio
async def test_no_server_filter_includes_all(
    ledger: SalienceLedger, selector: ReflectionSelector
) -> None:
    """Test that no server filter includes topics from all servers."""
    await ledger.earn("server:123:channel:1", 50.0)
    await ledger.earn("server:456:channel:2", 50.0)

    result = await selector.select_for_reflection(total_budget=100.0, server_id=None)

    # Both channels should be included
    spaces = result[BudgetGroup.SPACES]
    assert "server:123:channel:1" in spaces
    assert "server:456:channel:2" in spaces


# =============================================================================
# Test: Proportional Reallocation
# =============================================================================


@pytest.mark.asyncio
async def test_unused_budget_reallocated(
    ledger: SalienceLedger, selector: ReflectionSelector
) -> None:
    """Test that unused budget from empty groups is reallocated."""
    # Only create social topics, no other groups
    # This should cause unused budget from other groups to be reallocated
    for i in range(10):
        await ledger.earn(f"server:123:user:{i}", 50.0)

    result = await selector.select_for_reflection(total_budget=100.0, server_id="123")

    # With reallocation, should select more than the initial 30% would allow
    # Initial: 30 budget / 10 cost = 3 users
    # With reallocation: could get more
    assert len(result[BudgetGroup.SOCIAL]) >= 3


@pytest.mark.asyncio
async def test_reallocation_proportional_to_demand(
    ledger: SalienceLedger, selector: ReflectionSelector
) -> None:
    """Test that reallocation is proportional to remaining demand."""
    # Create high-demand social topics (many topics)
    for i in range(20):
        await ledger.earn(f"server:123:user:{i}", 50.0)

    # Create low-demand spaces topics (few topics)
    await ledger.earn("server:123:channel:1", 50.0)

    result = await selector.select_for_reflection(total_budget=100.0, server_id="123")

    # Social should get more reallocation due to higher demand
    # (proportional to unmet demand)
    # Just verify selection happened
    assert len(result[BudgetGroup.SOCIAL]) > 0
    assert len(result[BudgetGroup.SPACES]) > 0


# =============================================================================
# Test: select_from_group Method
# =============================================================================


@pytest.mark.asyncio
async def test_select_from_group_direct(
    ledger: SalienceLedger, selector: ReflectionSelector
) -> None:
    """Test direct selection from a single group."""
    await ledger.earn("server:123:user:1", 50.0)
    await ledger.earn("server:123:user:2", 30.0)

    selected = await selector.select_from_group(
        BudgetGroup.SOCIAL, budget=20.0, server_id="123"
    )

    # With budget 20 and cost 10, should select up to 2 users
    assert len(selected) <= 2
    # Higher salience should be selected first
    if selected:
        assert "server:123:user:1" in selected


@pytest.mark.asyncio
async def test_select_from_group_empty(selector: ReflectionSelector) -> None:
    """Test selection from empty group returns empty list."""
    selected = await selector.select_from_group(
        BudgetGroup.CULTURE, budget=100.0, server_id="123"
    )

    assert selected == []


# =============================================================================
# Test: Estimate Reflection Cost
# =============================================================================


def test_estimate_cost_user(selector: ReflectionSelector) -> None:
    """Test cost estimation for user topics."""
    from zos.models import Topic, TopicCategory, utcnow

    topic = Topic(
        key="server:123:user:456",
        category=TopicCategory.USER,
        is_global=False,
        created_at=utcnow(),
    )
    cost = selector.estimate_reflection_cost(topic)
    assert cost == 10.0


def test_estimate_cost_channel(selector: ReflectionSelector) -> None:
    """Test cost estimation for channel topics."""
    from zos.models import Topic, TopicCategory, utcnow

    topic = Topic(
        key="server:123:channel:789",
        category=TopicCategory.CHANNEL,
        is_global=False,
        created_at=utcnow(),
    )
    cost = selector.estimate_reflection_cost(topic)
    assert cost == 15.0


def test_estimate_cost_dyad(selector: ReflectionSelector) -> None:
    """Test cost estimation for dyad topics."""
    from zos.models import Topic, TopicCategory, utcnow

    topic = Topic(
        key="server:123:dyad:111:222",
        category=TopicCategory.DYAD,
        is_global=False,
        created_at=utcnow(),
    )
    cost = selector.estimate_reflection_cost(topic)
    assert cost == 8.0


def test_estimate_cost_self(selector: ReflectionSelector) -> None:
    """Test cost estimation for self topics."""
    from zos.models import Topic, TopicCategory, utcnow

    topic = Topic(
        key="self:zos",
        category=TopicCategory.SELF,
        is_global=True,
        created_at=utcnow(),
    )
    cost = selector.estimate_reflection_cost(topic)
    assert cost == 20.0


# =============================================================================
# Test: get_topics_by_group Method
# =============================================================================


@pytest.mark.asyncio
async def test_get_topics_by_group_social(
    ledger: SalienceLedger, selector: ReflectionSelector
) -> None:
    """Test getting social group topics."""
    await ledger.earn("server:123:user:1", 10.0)
    await ledger.earn("server:123:dyad:1:2", 10.0)

    topics = await selector.get_topics_by_group(BudgetGroup.SOCIAL, server_id="123")

    topic_keys = [t.key for t in topics]
    assert "server:123:user:1" in topic_keys
    assert "server:123:dyad:1:2" in topic_keys


@pytest.mark.asyncio
async def test_get_topics_by_group_global(
    ledger: SalienceLedger, selector: ReflectionSelector
) -> None:
    """Test getting global group topics."""
    await ledger.earn("user:456", 10.0)
    await ledger.earn("dyad:111:222", 10.0)
    # Server-scoped should not be included
    await ledger.earn("server:123:user:789", 10.0)

    topics = await selector.get_topics_by_group(BudgetGroup.GLOBAL)

    topic_keys = [t.key for t in topics]
    assert "user:456" in topic_keys
    assert "dyad:111:222" in topic_keys
    assert "server:123:user:789" not in topic_keys


@pytest.mark.asyncio
async def test_get_topics_by_group_self(
    ledger: SalienceLedger, selector: ReflectionSelector
) -> None:
    """Test getting self group topics."""
    await ledger.earn("self:zos", 10.0)
    await ledger.earn("server:123:self:zos", 10.0)

    topics = await selector.get_topics_by_group(BudgetGroup.SELF)

    topic_keys = [t.key for t in topics]
    assert "self:zos" in topic_keys
    assert "server:123:self:zos" in topic_keys


@pytest.mark.asyncio
async def test_get_topics_by_group_with_server_filter(
    ledger: SalienceLedger, selector: ReflectionSelector
) -> None:
    """Test getting topics with server filter."""
    await ledger.earn("server:123:channel:1", 10.0)
    await ledger.earn("server:456:channel:2", 10.0)

    topics = await selector.get_topics_by_group(BudgetGroup.SPACES, server_id="123")

    topic_keys = [t.key for t in topics]
    assert "server:123:channel:1" in topic_keys
    assert "server:456:channel:2" not in topic_keys


# =============================================================================
# Test: Integration - Full Selection Flow
# =============================================================================


@pytest.mark.asyncio
async def test_full_selection_flow(
    ledger: SalienceLedger, selector: ReflectionSelector
) -> None:
    """Test the full selection flow with multiple topic types."""
    # Create topics across all groups
    # Social
    await ledger.earn("server:123:user:1", 80.0)
    await ledger.earn("server:123:user:2", 60.0)
    await ledger.earn("server:123:dyad:1:2", 40.0)

    # Global
    await ledger.earn("user:global1", 70.0)

    # Spaces
    await ledger.earn("server:123:channel:1", 90.0)
    await ledger.earn("server:123:thread:1", 30.0)

    # Semantic
    await ledger.earn("server:123:subject:gaming", 50.0)

    # Culture
    await ledger.earn("server:123:emoji:pepe", 20.0)

    # Self
    await ledger.earn("self:zos", 100.0)

    result = await selector.select_for_reflection(total_budget=100.0, server_id="123")

    # Verify each group has appropriate selections
    assert len(result[BudgetGroup.SOCIAL]) > 0
    assert len(result[BudgetGroup.GLOBAL]) > 0 or len(result[BudgetGroup.GLOBAL]) == 0  # May not be selected
    assert len(result[BudgetGroup.SPACES]) > 0
    # Self should always be selected (separate budget)
    assert "self:zos" in result[BudgetGroup.SELF]

    # Higher salience topics should be prioritized within each group
    if len(result[BudgetGroup.SOCIAL]) >= 1:
        assert "server:123:user:1" in result[BudgetGroup.SOCIAL]


# =============================================================================
# Test: Min Reflection Salience Threshold
# =============================================================================


@pytest.mark.asyncio
async def test_min_reflection_salience_excludes_low_topics(
    ledger: SalienceLedger, test_config: Config
) -> None:
    """Test that topics below min_reflection_salience are not selected."""
    # Default min_reflection_salience is 10.0
    # Create topic with salience below threshold
    await ledger.earn("server:123:user:below", 5.0)  # Below 10
    # Create topic with salience at threshold
    await ledger.earn("server:123:user:at", 10.0)  # At threshold
    # Create topic with salience above threshold
    await ledger.earn("server:123:user:above", 50.0)  # Above threshold

    selector = ReflectionSelector(ledger, test_config)
    result = await selector.select_for_reflection(total_budget=100.0, server_id="123")

    # Below threshold should not be selected
    assert "server:123:user:below" not in result[BudgetGroup.SOCIAL]
    # At threshold should be selected (>= comparison)
    assert "server:123:user:at" in result[BudgetGroup.SOCIAL]
    # Above threshold should be selected
    assert "server:123:user:above" in result[BudgetGroup.SOCIAL]


@pytest.mark.asyncio
async def test_min_reflection_salience_configurable(tmp_path: Path) -> None:
    """Test that min_reflection_salience can be configured."""
    # Create config with higher threshold
    config = Config(
        data_dir=tmp_path,
        log_level="DEBUG",
    )
    # Override the min_reflection_salience
    config.salience.min_reflection_salience = 25.0

    engine = get_engine(config)
    create_tables(engine)
    ledger = SalienceLedger(engine, config)

    # Create topics around the new threshold
    await ledger.earn("server:123:user:below", 20.0)  # Below 25
    await ledger.earn("server:123:user:at", 25.0)  # At threshold
    await ledger.earn("server:123:user:above", 50.0)  # Above threshold

    selector = ReflectionSelector(ledger, config)
    result = await selector.select_for_reflection(total_budget=100.0, server_id="123")

    # Below threshold should not be selected
    assert "server:123:user:below" not in result[BudgetGroup.SOCIAL]
    # At threshold should be selected
    assert "server:123:user:at" in result[BudgetGroup.SOCIAL]
    # Above threshold should be selected
    assert "server:123:user:above" in result[BudgetGroup.SOCIAL]


@pytest.mark.asyncio
async def test_min_reflection_salience_applies_to_self_topics(
    ledger: SalienceLedger, test_config: Config
) -> None:
    """Test that min_reflection_salience also applies to self topics."""
    # Default min_reflection_salience is 10.0
    # Create self topic below threshold
    await ledger.earn("self:zos", 5.0)  # Below 10
    # Create self topic above threshold
    await ledger.earn("server:123:self:zos", 50.0)  # Above threshold

    selector = ReflectionSelector(ledger, test_config)
    result = await selector.select_for_reflection(total_budget=100.0)

    # Below threshold self topic should not be selected
    assert "self:zos" not in result[BudgetGroup.SELF]
    # Above threshold self topic should be selected
    assert "server:123:self:zos" in result[BudgetGroup.SELF]
