# Story 3.5: Budget Groups

**Epic**: Salience
**Status**: 🔴 Not Started
**Estimated complexity**: Medium

## Goal

Implement budget group allocation for reflection selection, ensuring fair attention distribution across topic categories.

## Acceptance Criteria

- [ ] Topics categorized into budget groups
- [ ] Budget percentages configurable
- [ ] Selection algorithm respects group budgets
- [ ] Self budget is separate pool
- [ ] `select_for_reflection` returns prioritized topics
- [ ] Groups: Social, Global, Spaces, Semantic, Culture, Self

## Technical Notes

### Budget Groups

From the spec:

| Group | Topics | Allocation |
|-------|--------|------------|
| Social | server users, dyads, user_in_channel, dyad_in_channel | 30% |
| Global | global users, global dyads | 15% |
| Spaces | channels, threads | 30% |
| Semantic | subjects, roles | 20% |
| Culture | emoji topics | 10% |
| Self | self:zos, server self-topics | Separate pool |

### Group Classification

```python
# src/zos/salience.py

class BudgetGroup(str, Enum):
    SOCIAL = "social"
    GLOBAL = "global"
    SPACES = "spaces"
    SEMANTIC = "semantic"
    CULTURE = "culture"
    SELF = "self"

def get_budget_group(topic_key: str) -> BudgetGroup:
    """Determine which budget group a topic belongs to."""
    parts = topic_key.split(':')

    # Self topics
    if 'self' in parts:
        return BudgetGroup.SELF

    # Global topics
    if not topic_key.startswith('server:'):
        if parts[0] in ('user', 'dyad'):
            return BudgetGroup.GLOBAL
        return BudgetGroup.SEMANTIC  # Shouldn't happen

    # Server-scoped topics
    category = parts[2]  # server:X:category:...

    if category in ('user', 'dyad', 'user_in_channel', 'dyad_in_channel'):
        return BudgetGroup.SOCIAL
    elif category in ('channel', 'thread'):
        return BudgetGroup.SPACES
    elif category in ('subject', 'role'):
        return BudgetGroup.SEMANTIC
    elif category == 'emoji':
        return BudgetGroup.CULTURE
    else:
        return BudgetGroup.SEMANTIC  # Default
```

### Selection Algorithm

```python
class ReflectionSelector:
    """Selects topics for reflection based on salience and budget."""

    def __init__(self, ledger: SalienceLedger, config: Config):
        self.ledger = ledger
        self.config = config

    async def select_for_reflection(
        self,
        total_budget: float,
        server_id: str | None = None,
    ) -> dict[BudgetGroup, list[str]]:
        """
        Select topics for reflection within budget constraints.
        Returns topics grouped by budget group.
        """
        budget_allocation = self.config.salience.budget
        selected = {group: [] for group in BudgetGroup}

        # Calculate budget per group
        group_budgets = {
            BudgetGroup.SOCIAL: total_budget * budget_allocation.social,
            BudgetGroup.GLOBAL: total_budget * budget_allocation.global_,
            BudgetGroup.SPACES: total_budget * budget_allocation.spaces,
            BudgetGroup.SEMANTIC: total_budget * budget_allocation.semantic,
            BudgetGroup.CULTURE: total_budget * budget_allocation.culture,
        }

        # Process each group
        for group, budget in group_budgets.items():
            topics = await self.select_from_group(
                group, budget, server_id
            )
            selected[group] = topics

        # Self has separate budget
        self_topics = await self.select_self_topics()
        selected[BudgetGroup.SELF] = self_topics

        return selected

    async def select_from_group(
        self,
        group: BudgetGroup,
        budget: float,
        server_id: str | None,
    ) -> list[str]:
        """Select topics from a single budget group."""
        # Get all topics in this group, sorted by salience
        topics = await self.get_topics_by_group(group, server_id)

        # Sort by salience descending
        balances = await self.ledger.get_balances([t.key for t in topics])
        sorted_topics = sorted(
            topics,
            key=lambda t: balances.get(t.key, 0),
            reverse=True,
        )

        # Greedy selection
        selected = []
        remaining_budget = budget

        for topic in sorted_topics:
            balance = balances.get(topic.key, 0)
            if balance <= 0:
                break  # No more salient topics

            estimated_cost = self.estimate_reflection_cost(topic)
            if estimated_cost <= remaining_budget:
                selected.append(topic.key)
                remaining_budget -= estimated_cost

        return selected

    def estimate_reflection_cost(self, topic: Topic) -> float:
        """Estimate the salience cost of reflecting on a topic."""
        # Simple estimate based on topic type
        # Could be refined with historical averages
        base_costs = {
            'user': 10,
            'dyad': 8,
            'channel': 15,
            'thread': 5,
            'subject': 12,
            'emoji': 5,
            'self': 20,
        }
        category = topic.category.value
        return base_costs.get(category, 10)
```

### Self Budget

```python
    async def select_self_topics(self) -> list[str]:
        """Select self topics using separate budget."""
        self_budget = self.config.salience.self_budget.daily_allocation

        # Get all self topics
        self_topics = await self.db.get_topics_by_category('self')

        # Sort by salience
        balances = await self.ledger.get_balances([t.key for t in self_topics])
        sorted_topics = sorted(
            self_topics,
            key=lambda t: balances.get(t.key, 0),
            reverse=True,
        )

        # Select within budget
        selected = []
        remaining = self_budget

        for topic in sorted_topics:
            cost = self.estimate_reflection_cost(topic)
            if cost <= remaining:
                selected.append(topic.key)
                remaining -= cost

        return selected
```

### Topics by Group Query

```python
# src/zos/database.py

async def get_topics_by_group(
    self,
    group: BudgetGroup,
    server_id: str | None = None,
) -> list[Topic]:
    """Get all topics in a budget group."""
    # Map group to categories
    group_categories = {
        BudgetGroup.SOCIAL: ['user', 'dyad', 'user_in_channel', 'dyad_in_channel'],
        BudgetGroup.GLOBAL: ['user', 'dyad'],  # Non-server-scoped
        BudgetGroup.SPACES: ['channel', 'thread'],
        BudgetGroup.SEMANTIC: ['subject', 'role'],
        BudgetGroup.CULTURE: ['emoji'],
        BudgetGroup.SELF: ['self'],
    }

    categories = group_categories[group]

    if group == BudgetGroup.GLOBAL:
        # Global topics don't start with server:
        stmt = select(topics).where(
            topics.c.is_global == True,
            topics.c.category.in_(categories),
        )
    else:
        # Server-scoped topics
        stmt = select(topics).where(
            topics.c.is_global == False,
            topics.c.category.in_(categories),
        )
        if server_id:
            stmt = stmt.where(topics.c.key.like(f"server:{server_id}:%"))

    rows = await self.fetch_all(stmt)
    return [row_to_model(r, Topic) for r in rows]
```

## Configuration Reference

```yaml
salience:
  budget:
    social: 0.30
    global: 0.15
    spaces: 0.30
    semantic: 0.20
    culture: 0.10

  self_budget:
    daily_allocation: 50
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/salience.py` | ReflectionSelector, BudgetGroup |
| `src/zos/database.py` | Topics by group query |
| `tests/test_budget.py` | Budget selection tests |

## Test Cases

1. Topics correctly classified into groups
2. Budget allocation respected
3. High-salience topics prioritized
4. Self budget separate
5. Empty groups handled
6. Server filtering works

## Definition of Done

- [ ] Topics classified into groups
- [ ] Selection respects budgets
- [ ] Self budget separate
- [ ] Integration with reflection (Epic 4)

---

## Open Design Questions

### Q1: Budget Exhaustion — Skip or Borrow?
If the Social group (30%) has high-salience topics but exhausts its budget, while Semantic (20%) has spare capacity, should the system:
- **Strict boundaries** (current) — each group spends only its allocation
- **Overflow borrowing** — excess demand in one group can borrow from underutilized groups
- **Proportional reallocation** — at selection time, redistribute unused budget

Strict boundaries enforce diversity but might leave compute unused. Borrowing maximizes output but undermines group purpose.

### Q2: Self Budget — Triggered or Scheduled?
The self budget is described as "separate pool" with `daily_allocation: 50`. But self-reflection can also trigger via `trigger_threshold: 10` (10+ new self-insights). How do these interact?
- **Budget limits both** — whether scheduled or triggered, spend from same pool
- **Scheduled uses budget, triggered is free** — threshold triggers don't consume budget
- **Separate budgets** — weekly scheduled has one budget, threshold triggers have another

This affects whether self-reflection can "interrupt" if something significant happens.

### Q3: Cold Start — No Salience, No Reflection?
Selection requires salience. On day one, no topics have salience (no activity processed yet). How does reflection bootstrap?
- **Wait for salience** — first reflection runs after enough activity accumulates
- **Minimum seed** — config specifies initial topics to reflect on
- **Zero-salience reflection** — if no salience, reflect on random/all topics

The first reflection cycle is special — there are no prior insights either. Should there be explicit bootstrap logic?

---

**Requires**: Stories 3.1-3.3 (salience data to select from)
**Blocks**: Epic 4 (reflection uses selection)
