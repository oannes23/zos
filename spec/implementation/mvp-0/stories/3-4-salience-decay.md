# Story 3.4: Salience Decay

**Epic**: Salience
**Status**: 🔴 Not Started
**Estimated complexity**: Small

## Goal

Implement daily decay for inactive topics, allowing natural pruning of attention that hasn't been sustained.

## Acceptance Criteria

- [ ] Topics don't decay while active
- [ ] Decay begins after threshold days of inactivity
- [ ] Decay rate is configurable (default 1%/day)
- [ ] Decay runs daily via scheduler
- [ ] Decay transactions recorded in ledger
- [ ] Topics at zero don't generate decay transactions

## Technical Notes

### Decay Logic

```python
# src/zos/salience.py

async def apply_decay(self):
    """Apply decay to all inactive topics. Call daily."""
    threshold = self.config.salience.decay_threshold_days
    decay_rate = self.config.salience.decay_rate_per_day

    threshold_date = datetime.utcnow() - timedelta(days=threshold)

    # Get topics that haven't had activity since threshold
    inactive_topics = await self.db.get_inactive_topics(threshold_date)

    decayed_count = 0
    total_decayed = 0.0

    for topic in inactive_topics:
        balance = await self.get_balance(topic.key)

        if balance <= 0:
            continue  # Nothing to decay

        decay_amount = balance * decay_rate

        if decay_amount < 0.01:
            continue  # Skip trivial decay

        await self.record_transaction(
            topic_key=topic.key,
            transaction_type=TransactionType.DECAY,
            amount=-decay_amount,
            reason="daily_decay",
        )

        decayed_count += 1
        total_decayed += decay_amount

    log.info(
        "decay_applied",
        topics_decayed=decayed_count,
        total_decayed=total_decayed,
    )

    return decayed_count, total_decayed
```

### Inactive Topics Query

```python
# src/zos/database.py

async def get_inactive_topics(self, since: datetime) -> list[Topic]:
    """Get topics with no activity since the given date."""
    stmt = select(topics).where(
        (topics.c.last_activity_at < since) |
        (topics.c.last_activity_at.is_(None))
    )
    rows = await self.fetch_all(stmt)
    return [row_to_model(r, Topic) for r in rows]
```

### Scheduler Integration

```python
# src/zos/cli.py or scheduled task

from apscheduler.schedulers.asyncio import AsyncIOScheduler

def setup_scheduler(ledger: SalienceLedger) -> AsyncIOScheduler:
    """Setup scheduled tasks."""
    scheduler = AsyncIOScheduler()

    # Daily decay at 4 AM
    scheduler.add_job(
        ledger.apply_decay,
        'cron',
        hour=4,
        minute=0,
        id='daily_decay',
    )

    return scheduler
```

### Manual Decay Command

```python
# src/zos/cli.py

@cli.group()
def salience():
    """Salience management commands."""
    pass

@salience.command()
@click.pass_context
def decay(ctx):
    """Manually trigger salience decay."""
    config = ctx.obj["config"]
    ledger = SalienceLedger(get_db(config), config)

    async def run():
        count, total = await ledger.apply_decay()
        click.echo(f"Decayed {count} topics, total {total:.2f} salience")

    asyncio.run(run())
```

### Decay Calculation

The formula preserves the asymptotic property — topics never quite reach zero through decay alone:

```
new_balance = old_balance * (1 - decay_rate)
```

At 1%/day:
- Day 0: 100
- Day 7: 93.2
- Day 30: 74.0
- Day 60: 54.7
- Day 90: 40.5

This gradual decay allows inactive topics to fade while never completely disappearing if they were once significant.

### Edge Cases

```python
async def apply_decay(self):
    # ... main logic ...

    # Edge case: topic with tiny balance
    if balance < 0.1:
        # Just zero it out instead of decaying
        await self.record_transaction(
            topic_key=topic.key,
            transaction_type=TransactionType.DECAY,
            amount=-balance,
            reason="decay_to_zero",
        )
```

## Configuration Reference

```yaml
salience:
  decay_threshold_days: 7
  decay_rate_per_day: 0.01
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/salience.py` | `apply_decay` method |
| `src/zos/database.py` | Inactive topics query |
| `src/zos/cli.py` | Manual decay command |
| `tests/test_decay.py` | Decay logic tests |

## Test Cases

1. Active topic doesn't decay
2. Inactive topic decays after threshold
3. Decay amount is correct percentage
4. Zero-balance topics skipped
5. Transactions recorded correctly
6. Decay is idempotent (running twice in a day is fine)

## Definition of Done

- [ ] Decay runs daily via scheduler
- [ ] Only inactive topics decay
- [ ] Transactions recorded
- [ ] Manual trigger works

---

**Requires**: Story 3.1 (ledger for recording)
**Blocks**: None (parallel with 3.3, 3.5)
