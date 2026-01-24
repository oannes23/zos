# Story 3.3: Salience Propagation

**Epic**: Salience
**Status**: 🔴 Not Started
**Estimated complexity**: Large

## Goal

Implement salience propagation to related topics, including warm-only rules, global topic warming, and overflow spillover.

## Acceptance Criteria

- [ ] Earning propagates to warm related topics
- [ ] Cold topics (salience = 0) don't receive propagation
- [ ] Overflow spills to related topics
- [ ] Global topics warm on DM or second-server activity
- [ ] Global ↔ server bidirectional propagation
- [ ] Propagation factor configurable
- [ ] No infinite propagation loops

## Technical Notes

### Propagation on Earn

Extend the `earn` method to handle propagation:

```python
# src/zos/salience.py

async def earn_with_propagation(
    self,
    topic_key: str,
    amount: float,
    reason: str | None = None,
    propagate: bool = True,
) -> tuple[float, float]:
    """Earn salience with propagation to related topics."""

    # Earn to primary topic
    new_balance, overflow = await self.earn(
        topic_key, amount, reason
    )

    if not propagate:
        return new_balance, overflow

    # Get related topics
    related = await self.get_related_topics(topic_key)

    # Normal propagation to warm topics
    propagation_factor = self.config.salience.propagation_factor
    for related_key in related:
        if await self.is_warm(related_key):
            factor = self.get_propagation_factor(topic_key, related_key)
            propagated = amount * factor
            await self.earn(
                related_key,
                propagated,
                reason=f"propagate:{topic_key}",
                source_topic=topic_key,
            )

    # Overflow spillover
    if overflow > 0:
        spillover_factor = self.config.salience.spillover_factor
        for related_key in related:
            if await self.is_warm(related_key):
                spilled = overflow * spillover_factor
                await self.record_transaction(
                    related_key,
                    TransactionType.SPILLOVER,
                    spilled,
                    reason=f"overflow:{topic_key}",
                    source_topic=topic_key,
                )

    return new_balance, overflow

async def is_warm(self, topic_key: str) -> bool:
    """Check if a topic is warm (has positive salience)."""
    balance = await self.get_balance(topic_key)
    return balance > 0
```

### Related Topics Mapping

```python
async def get_related_topics(self, topic_key: str) -> list[str]:
    """Get topics related to this one for propagation."""
    related = []
    parts = topic_key.split(':')

    # Server-scoped user
    if self.matches_pattern(topic_key, "server:*:user:*"):
        server_id = parts[1]
        user_id = parts[3]

        # Related dyads
        dyads = await self.get_dyads_for_user(server_id, user_id)
        related.extend(dyads)

        # Related user_in_channel
        uics = await self.get_user_in_channels(server_id, user_id)
        related.extend(uics)

        # Global user (if warm)
        global_user = f"user:{user_id}"
        related.append(global_user)

    # Server-scoped channel
    elif self.matches_pattern(topic_key, "server:*:channel:*"):
        server_id = parts[1]
        channel_id = parts[3]

        # Related user_in_channel
        uics = await self.get_channel_user_contexts(server_id, channel_id)
        related.extend(uics)

        # Related threads
        threads = await self.get_threads_for_channel(server_id, channel_id)
        related.extend(threads)

    # Server-scoped dyad
    elif self.matches_pattern(topic_key, "server:*:dyad:*:*"):
        server_id = parts[1]
        user_a = parts[3]
        user_b = parts[4]

        # Both users
        related.append(f"server:{server_id}:user:{user_a}")
        related.append(f"server:{server_id}:user:{user_b}")

        # Global dyad (if warm)
        global_dyad = f"dyad:{user_a}:{user_b}"
        related.append(global_dyad)

    # Server-scoped emoji
    elif self.matches_pattern(topic_key, "server:*:emoji:*"):
        server_id = parts[1]
        # Emoji propagates to users who use it (handled in earning)
        pass

    # Global user
    elif self.matches_pattern(topic_key, "user:*"):
        user_id = parts[1]

        # All server-scoped user topics (downward propagation)
        server_topics = await self.get_server_user_topics(user_id)
        related.extend(server_topics)

        # Global dyads involving this user
        global_dyads = await self.get_global_dyads_for_user(user_id)
        related.extend(global_dyads)

    return related
```

### Global Topic Warming

```python
async def check_and_warm_global(
    self,
    user_id: str,
    server_id: str,
):
    """Check if global topic should be warmed, and warm it."""
    global_topic = f"user:{user_id}"

    # Already warm?
    if await self.is_warm(global_topic):
        return

    # Check if user seen in multiple servers
    servers_seen = await self.get_servers_for_user(user_id)

    if len(servers_seen) >= 2:
        # Warm the global topic
        await self.record_transaction(
            global_topic,
            TransactionType.WARM,
            self.config.salience.initial_global_warmth,
            reason=f"multi_server:{server_id}",
        )
        log.info(
            "global_topic_warmed",
            user_id=user_id,
            servers=len(servers_seen),
        )

async def warm_from_dm(self, user_id: str):
    """Warm global topic from DM activity."""
    global_topic = f"user:{user_id}"

    if not await self.is_warm(global_topic):
        await self.record_transaction(
            global_topic,
            TransactionType.WARM,
            self.config.salience.initial_global_warmth,
            reason="dm_activity",
        )
        log.info("global_topic_warmed", user_id=user_id, reason="dm")
```

### Propagation Factor Selection

```python
def get_propagation_factor(
    self,
    source: str,
    target: str,
) -> float:
    """Get the propagation factor for source -> target."""
    # Use global factor for server <-> global propagation
    if self.is_global(source) != self.is_global(target):
        return self.config.salience.global_propagation_factor

    return self.config.salience.propagation_factor
```

### User Server Tracking

```python
async def track_user_server(self, user_id: str, server_id: str):
    """Track that a user has been seen in a server."""
    await self.db.upsert_user_server_tracking(
        user_id=user_id,
        server_id=server_id,
        first_seen_at=datetime.utcnow(),
    )

async def get_servers_for_user(self, user_id: str) -> list[str]:
    """Get all servers a user has been seen in."""
    return await self.db.get_user_servers(user_id)
```

### Loop Prevention

Propagation doesn't cascade — each earn only propagates one level:

```python
# In earn_with_propagation
await self.earn(
    related_key,
    propagated,
    reason=f"propagate:{topic_key}",
    source_topic=topic_key,
)
# Note: This calls earn(), not earn_with_propagation()
# Propagation doesn't cascade
```

## Configuration Reference

```yaml
salience:
  propagation_factor: 0.3
  global_propagation_factor: 0.3
  spillover_factor: 0.5
  initial_global_warmth: 5.0
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/salience.py` | Propagation logic |
| `src/zos/database.py` | User-server tracking queries |
| `tests/test_propagation.py` | Propagation tests |

## Test Cases

1. Warm topic receives propagation
2. Cold topic doesn't receive propagation
3. Overflow spills correctly
4. Global topic warms on second server
5. Global topic warms on DM
6. Bidirectional global ↔ server works
7. No infinite loops

## Definition of Done

- [ ] Propagation to warm topics works
- [ ] Warm-only rule enforced
- [ ] Global warming triggers correctly
- [ ] Spillover on cap hit

---

## Design Decisions (Resolved 2026-01-23)

### Q1: "Warm" Threshold
**Decision**: Minimum threshold (salience > 1.0)
- Topics must have meaningful attention to receive propagation
- `is_warm(topic_key)` returns `balance > config.warm_threshold`
- Default `warm_threshold = 1.0` (configurable)
- Cleaner distinction between "cold" and "barely noticed"

**Config addition**: `salience.warm_threshold: 1.0`

### Q2: Propagation Timing
**Decision**: Synchronous inline (current)
- Immediate propagation, simple implementation
- SQLite can handle the write volume for MVP
- Batching adds complexity without clear benefit
- Revisit if performance becomes an issue

### Q3: Global Dyad Warming
**Decision**: When both constituent global users are warm
- If `user:A` and `user:B` are both warm, `dyad:A:B` becomes warm automatically
- Derived warmth — relationship understanding becomes cross-server when both people are
- Check global user warmth before propagating to global dyad
- Implementation: warm check in propagation, not separate trigger

---

**Requires**: Story 3.2 (earning to trigger propagation)
**Blocks**: Story 3.5 (budget groups use propagated salience)
