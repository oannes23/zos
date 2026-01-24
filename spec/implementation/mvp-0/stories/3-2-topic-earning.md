# Story 3.2: Topic Earning

**Epic**: Salience
**Status**: 🔴 Not Started
**Estimated complexity**: Medium

## Goal

Implement earning rules that convert observed activity (messages, reactions, mentions) into salience for relevant topics.

## Acceptance Criteria

- [ ] Messages earn salience for author topic
- [ ] Reactions earn for author, reactor, and dyad
- [ ] Mentions earn boosted amount
- [ ] Replies earn for both parties
- [ ] Thread creation earns boosted amount
- [ ] Media/links apply boost multiplier
- [ ] Channels earn from all activity
- [ ] `<chat>` users don't earn individual salience
- [ ] DMs earn for global user topic

## Technical Notes

### Earning Coordinator

```python
# src/zos/salience.py

class EarningCoordinator:
    """Coordinates salience earning from observed activity."""

    def __init__(self, ledger: SalienceLedger, config: Config):
        self.ledger = ledger
        self.config = config
        self.weights = config.salience.weights

    async def process_message(self, message: Message) -> list[str]:
        """Process a message for salience earning. Returns topics that earned."""
        topics_earned = []

        # Skip anonymous users for individual earning
        if message.author_id.startswith('<chat'):
            # Channel still earns
            await self.earn_channel(message)
            return topics_earned

        server_id = message.server_id
        base_amount = self.weights.message

        # Apply media/link boost
        if message.has_media or message.has_links:
            base_amount *= self.weights.media_boost_factor

        # 1. Author earns
        if server_id:
            author_topic = f"server:{server_id}:user:{message.author_id}"
        else:
            # DM - earn to global topic
            author_topic = f"user:{message.author_id}"

        await self.ledger.earn(
            author_topic,
            base_amount,
            reason=f"message:{message.id}",
        )
        topics_earned.append(author_topic)

        # 2. Channel earns
        channel_topic = await self.earn_channel(message)
        if channel_topic:
            topics_earned.append(channel_topic)

        # 3. Reply creates dyad earning
        if message.reply_to_id:
            replied_to = await self.db.get_message(message.reply_to_id)
            if replied_to and not replied_to.author_id.startswith('<chat'):
                dyad_topic = await self.earn_dyad(
                    server_id,
                    message.author_id,
                    replied_to.author_id,
                    self.weights.reply,
                    reason=f"reply:{message.id}",
                )
                if dyad_topic:
                    topics_earned.append(dyad_topic)

        # 4. Mentions
        mentions = self.extract_mentions(message.content)
        for mentioned_id in mentions:
            await self.earn_mention(server_id, mentioned_id, message.id)

        return topics_earned

    async def earn_channel(self, message: Message) -> str | None:
        """Earn salience for the channel."""
        if not message.server_id:
            return None  # DMs don't have channel topics

        channel_topic = f"server:{message.server_id}:channel:{message.channel_id}"
        await self.ledger.earn(
            channel_topic,
            self.weights.message,
            reason=f"message:{message.id}",
        )
        return channel_topic
```

### Reaction Earning

```python
    async def process_reaction(
        self,
        reaction: Reaction,
        message: Message,
    ) -> list[str]:
        """Process a reaction for salience earning."""
        topics_earned = []
        server_id = message.server_id
        base_amount = self.weights.reaction

        # Skip if reactor is anonymous
        if reaction.user_id.startswith('<chat'):
            return topics_earned

        # 1. Message author earns (attention received)
        if not message.author_id.startswith('<chat'):
            if server_id:
                author_topic = f"server:{server_id}:user:{message.author_id}"
            else:
                author_topic = f"user:{message.author_id}"

            await self.ledger.earn(
                author_topic,
                base_amount,
                reason=f"reaction:{reaction.id}",
            )
            topics_earned.append(author_topic)

        # 2. Reactor earns (active engagement)
        if server_id:
            reactor_topic = f"server:{server_id}:user:{reaction.user_id}"
        else:
            reactor_topic = f"user:{reaction.user_id}"

        await self.ledger.earn(
            reactor_topic,
            base_amount,
            reason=f"reaction:{reaction.id}",
        )
        topics_earned.append(reactor_topic)

        # 3. Dyad earns (relationship signal)
        if not message.author_id.startswith('<chat'):
            dyad_topic = await self.earn_dyad(
                server_id,
                message.author_id,
                reaction.user_id,
                base_amount,
                reason=f"reaction:{reaction.id}",
            )
            if dyad_topic:
                topics_earned.append(dyad_topic)

        # 4. Custom emoji topic earns
        if reaction.is_custom and server_id:
            emoji_topic = f"server:{server_id}:emoji:{reaction.emoji}"
            await self.ledger.earn(
                emoji_topic,
                base_amount,
                reason=f"reaction:{reaction.id}",
            )
            topics_earned.append(emoji_topic)

        return topics_earned
```

### Dyad Earning

```python
    async def earn_dyad(
        self,
        server_id: str | None,
        user_a: str,
        user_b: str,
        amount: float,
        reason: str,
    ) -> str | None:
        """Earn salience for a dyad."""
        if user_a == user_b:
            return None  # No self-dyads

        # Canonical ordering for dyad key
        sorted_ids = sorted([user_a, user_b])

        if server_id:
            dyad_topic = f"server:{server_id}:dyad:{sorted_ids[0]}:{sorted_ids[1]}"
        else:
            dyad_topic = f"dyad:{sorted_ids[0]}:{sorted_ids[1]}"

        await self.ledger.earn(dyad_topic, amount, reason=reason)
        return dyad_topic
```

### Mention Earning

```python
    async def earn_mention(
        self,
        server_id: str | None,
        mentioned_id: str,
        message_id: str,
    ):
        """Earn salience for a mentioned user."""
        if server_id:
            topic = f"server:{server_id}:user:{mentioned_id}"
        else:
            topic = f"user:{mentioned_id}"

        await self.ledger.earn(
            topic,
            self.weights.mention,
            reason=f"mention:{message_id}",
        )

    def extract_mentions(self, content: str) -> list[str]:
        """Extract user IDs from mentions in content."""
        # Discord mention format: <@123456789>
        import re
        pattern = r'<@!?(\d+)>'
        return re.findall(pattern, content)
```

### Thread Creation

```python
    async def process_thread_creation(
        self,
        thread_id: str,
        channel_id: str,
        creator_id: str,
        server_id: str,
    ):
        """Process thread creation for salience earning."""
        if creator_id.startswith('<chat'):
            return

        # Thread creator earns boosted amount
        creator_topic = f"server:{server_id}:user:{creator_id}"
        await self.ledger.earn(
            creator_topic,
            self.weights.thread_create,
            reason=f"thread_create:{thread_id}",
        )

        # Thread topic created
        thread_topic = f"server:{server_id}:thread:{thread_id}"
        await self.ledger.earn(
            thread_topic,
            self.weights.thread_create,
            reason=f"thread_create:{thread_id}",
        )
```

### DM Earning

```python
    async def process_dm(self, message: Message):
        """Process a DM for salience earning."""
        # DMs earn for global user topic
        user_topic = f"user:{message.author_id}"

        amount = self.weights.dm_message
        if message.has_media or message.has_links:
            amount *= self.weights.media_boost_factor

        await self.ledger.earn(
            user_topic,
            amount,
            reason=f"dm:{message.id}",
        )
```

## Configuration Reference

```yaml
salience:
  weights:
    message: 1.0
    reaction: 0.5
    mention: 2.0
    reply: 1.5
    thread_create: 2.0
    dm_message: 1.5
    emoji_use: 0.5
    media_boost_factor: 1.2
```

## Integration with Observation

Call earning from message polling:

```python
# In observation.py, after storing message
async def store_message(self, message, server_id):
    # ... store message ...

    # Earn salience
    await self.earning.process_message(msg)
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/salience.py` | EarningCoordinator class |
| `src/zos/observation.py` | Integration with polling |
| `tests/test_earning.py` | Earning rule tests |

## Test Cases

1. Message earns for author
2. Message with media earns boosted
3. Reaction earns for author, reactor, dyad
4. Custom emoji earns for emoji topic
5. Anonymous users don't earn individual
6. Channels earn from all messages
7. DMs earn for global topic
8. Mentions earn boosted

## Definition of Done

- [ ] All earning rules implemented
- [ ] Weights configurable
- [ ] Anonymous users handled correctly
- [ ] Integrated with observation

---

**Requires**: Story 3.1 (ledger), Story 2.2 (messages to process)
**Blocks**: Story 3.3 (propagation needs earning)
