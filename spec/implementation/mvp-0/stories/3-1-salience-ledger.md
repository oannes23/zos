# Story 3.1: Salience Ledger Operations

**Epic**: Salience
**Status**: 🟢 Complete
**Estimated complexity**: Medium

## Goal

Implement the salience ledger with transaction recording and balance computation.

## Acceptance Criteria

- [x] Transactions recorded with all fields from spec
- [x] Balance computable from transaction sum
- [x] Transaction types: earn, spend, retain, decay, propagate, spillover, warm
- [x] Last activity timestamp tracked per topic
- [x] Full transaction history queryable
- [x] Topic creation on first earn (lazy)

## Technical Notes

### Ledger Operations

```python
# src/zos/salience.py
from zos.models import SalienceEntry, Topic, TransactionType
from zos.database import Database
from datetime import datetime
import structlog

log = structlog.get_logger()

class SalienceLedger:
    def __init__(self, db: Database, config: Config):
        self.db = db
        self.config = config

    async def earn(
        self,
        topic_key: str,
        amount: float,
        reason: str | None = None,
        source_topic: str | None = None,
    ) -> float:
        """Earn salience for a topic. Returns new balance."""
        # Ensure topic exists
        await self.ensure_topic(topic_key)

        # Get current balance and cap
        balance = await self.get_balance(topic_key)
        cap = self.get_cap(topic_key)

        # Calculate actual earn (may be limited by cap)
        actual_earn = min(amount, cap - balance)
        overflow = amount - actual_earn

        if actual_earn > 0:
            await self.record_transaction(
                topic_key=topic_key,
                transaction_type=TransactionType.EARN,
                amount=actual_earn,
                reason=reason,
                source_topic=source_topic,
            )

        # Update last activity
        await self.db.update_topic_activity(topic_key, datetime.utcnow())

        new_balance = balance + actual_earn

        log.debug(
            "salience_earned",
            topic=topic_key,
            amount=actual_earn,
            overflow=overflow,
            balance=new_balance,
        )

        return new_balance, overflow

    async def spend(
        self,
        topic_key: str,
        amount: float,
        reason: str | None = None,
    ) -> float:
        """Spend salience from a topic. Returns amount actually spent."""
        balance = await self.get_balance(topic_key)
        actual_spend = min(amount, balance)

        if actual_spend > 0:
            await self.record_transaction(
                topic_key=topic_key,
                transaction_type=TransactionType.SPEND,
                amount=-actual_spend,  # Negative for spend
                reason=reason,
            )

            # Apply retention
            retained = actual_spend * self.config.salience.retention_rate
            if retained > 0:
                await self.record_transaction(
                    topic_key=topic_key,
                    transaction_type=TransactionType.RETAIN,
                    amount=retained,
                    reason=f"retention from {reason}",
                )

        return actual_spend

    async def record_transaction(
        self,
        topic_key: str,
        transaction_type: TransactionType,
        amount: float,
        reason: str | None = None,
        source_topic: str | None = None,
    ) -> SalienceEntry:
        """Record a salience transaction."""
        entry = SalienceEntry(
            id=generate_id(),
            topic_key=topic_key,
            transaction_type=transaction_type,
            amount=amount,
            reason=reason,
            source_topic=source_topic,
            created_at=datetime.utcnow(),
        )
        await self.db.insert_salience_entry(entry)
        return entry
```

### Balance Computation

```python
    async def get_balance(self, topic_key: str) -> float:
        """Get current salience balance for a topic."""
        # Sum all transactions for this topic
        result = await self.db.execute(
            """
            SELECT COALESCE(SUM(amount), 0) as balance
            FROM salience_ledger
            WHERE topic_key = ?
            """,
            (topic_key,)
        )
        return result.scalar() or 0.0

    async def get_balances(self, topic_keys: list[str]) -> dict[str, float]:
        """Get balances for multiple topics efficiently."""
        if not topic_keys:
            return {}

        placeholders = ','.join('?' * len(topic_keys))
        result = await self.db.fetch_all(
            f"""
            SELECT topic_key, COALESCE(SUM(amount), 0) as balance
            FROM salience_ledger
            WHERE topic_key IN ({placeholders})
            GROUP BY topic_key
            """,
            topic_keys
        )
        return {row['topic_key']: row['balance'] for row in result}
```

### Topic Cap Lookup

```python
    def get_cap(self, topic_key: str) -> float:
        """Get the salience cap for a topic based on its category."""
        category = self.extract_category(topic_key)
        caps = self.config.salience.caps

        cap_map = {
            'user': caps.server_user,
            'channel': caps.channel,
            'thread': caps.thread,
            'dyad': caps.server_dyad,
            'user_in_channel': caps.user_in_channel,
            'dyad_in_channel': caps.dyad_in_channel,
            'subject': caps.subject,
            'role': caps.role,
            'emoji': caps.emoji,
            'self': caps.server_self,
        }

        # Global topics have different caps
        if self.is_global(topic_key):
            if 'user:' in topic_key:
                return caps.global_user
            if 'dyad:' in topic_key:
                return caps.global_dyad
            if topic_key == 'self:zos':
                return caps.self

        return cap_map.get(category, 100)  # Default cap

    def extract_category(self, topic_key: str) -> str:
        """Extract category from topic key."""
        # server:X:user:Y -> user
        # server:X:dyad:A:B -> dyad
        # user:Y -> user (global)
        parts = topic_key.split(':')
        if parts[0] == 'server':
            return parts[2]  # server:X:category:...
        return parts[0]  # global topic

    def is_global(self, topic_key: str) -> bool:
        """Check if topic is global (not server-scoped)."""
        return not topic_key.startswith('server:')
```

### Lazy Topic Creation

```python
    async def ensure_topic(self, topic_key: str) -> Topic:
        """Ensure a topic exists, creating if necessary."""
        topic = await self.db.get_topic(topic_key)
        if topic:
            return topic

        # Create new topic
        category = self.extract_category(topic_key)
        is_global = self.is_global(topic_key)

        topic = Topic(
            key=topic_key,
            category=TopicCategory(category),
            is_global=is_global,
            provisional=False,
            created_at=datetime.utcnow(),
        )
        await self.db.insert_topic(topic)

        log.info("topic_created", topic_key=topic_key, category=category)
        return topic
```

### Transaction History Query

```python
    async def get_history(
        self,
        topic_key: str,
        limit: int = 100,
        since: datetime | None = None,
    ) -> list[SalienceEntry]:
        """Get transaction history for a topic."""
        query = """
            SELECT * FROM salience_ledger
            WHERE topic_key = ?
        """
        params = [topic_key]

        if since:
            query += " AND created_at > ?"
            params.append(since)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = await self.db.fetch_all(query, params)
        return [row_to_model(r, SalienceEntry) for r in rows]
```

## Database Queries

```python
# src/zos/database.py

async def insert_salience_entry(self, entry: SalienceEntry):
    """Insert a salience transaction."""
    stmt = salience_ledger.insert().values(**model_to_dict(entry))
    await self.execute(stmt)

async def update_topic_activity(self, topic_key: str, timestamp: datetime):
    """Update last activity timestamp for a topic."""
    stmt = topics.update().where(
        topics.c.key == topic_key
    ).values(last_activity_at=timestamp)
    await self.execute(stmt)
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/salience.py` | SalienceLedger class |
| `src/zos/database.py` | Salience queries |
| `tests/test_salience.py` | Ledger operation tests |

## Test Cases

1. Earn records positive transaction
2. Earn respects cap (overflow returned)
3. Spend records negative transaction
4. Spend applies retention
5. Balance is sum of transactions
6. Topic created on first earn
7. Last activity updated

## Definition of Done

- [x] All transaction types work
- [x] Balance computation accurate
- [x] Caps enforced
- [x] History queryable

---

**Requires**: Epic 1 complete
**Blocks**: Stories 3.2-3.5
