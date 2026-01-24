# Story 2.2: Message Polling

**Epic**: Observation
**Status**: 🔴 Not Started
**Estimated complexity**: Large

## Goal

Implement batch polling of Discord messages, storing them in the database with all required fields from the data model.

## Acceptance Criteria

- [ ] Poll configured channels on interval
- [ ] Store messages with all fields from data-model.md
- [ ] Track last-polled timestamp per channel (incremental)
- [ ] Handle message edits (update existing)
- [ ] Handle message deletes (mark or remove)
- [ ] Respect privacy gate role (mark non-opted users)
- [ ] `<chat>` users get anonymized author_id
- [ ] DMs handled separately from guild messages

## Technical Notes

### Polling Logic

```python
# src/zos/observation.py

async def poll_channel(self, channel: discord.TextChannel) -> int:
    """Poll a single channel for new messages. Returns count."""
    server_id = str(channel.guild.id)

    # Get last polled timestamp
    last_polled = await self.get_last_polled(channel.id)

    messages_stored = 0
    async for message in channel.history(
        after=last_polled,
        limit=self.config.observation.messages_per_poll,
        oldest_first=True,
    ):
        await self.store_message(message, server_id)
        messages_stored += 1

    # Update last polled
    if messages_stored > 0:
        await self.set_last_polled(channel.id, message.created_at)

    return messages_stored
```

### Message Storage

```python
async def store_message(
    self,
    message: discord.Message,
    server_id: str | None,
) -> None:
    """Store a Discord message in the database."""
    # Determine visibility scope
    is_dm = isinstance(message.channel, discord.DMChannel)
    scope = VisibilityScope.DM if is_dm else VisibilityScope.PUBLIC

    # Check privacy gate for author
    author_id = await self.resolve_author_id(message.author, server_id)

    # Check for media/links
    has_media = bool(message.attachments) or bool(message.embeds)
    has_links = self.contains_links(message.content)

    # Build message record
    msg = Message(
        id=str(message.id),
        channel_id=str(message.channel.id),
        server_id=server_id,
        author_id=author_id,
        content=message.content,
        created_at=message.created_at,
        visibility_scope=scope,
        reply_to_id=str(message.reference.message_id) if message.reference else None,
        thread_id=str(message.thread.id) if hasattr(message, 'thread') and message.thread else None,
        has_media=has_media,
        has_links=has_links,
    )

    # Upsert (handles edits)
    await self.db.upsert_message(msg)

    log.debug(
        "message_stored",
        message_id=msg.id,
        channel_id=msg.channel_id,
        author_anonymized=author_id.startswith("<chat"),
    )
```

### Privacy Gate Handling

```python
async def resolve_author_id(
    self,
    author: discord.User | discord.Member,
    server_id: str | None,
) -> str:
    """Resolve author ID, respecting privacy gate role."""
    if server_id is None:
        # DMs always use real ID (implicit consent)
        return str(author.id)

    server_config = self.config.servers.get(server_id)
    if not server_config or not server_config.privacy_gate_role:
        # No privacy gate, all users tracked
        return str(author.id)

    # Check if user has privacy gate role
    if isinstance(author, discord.Member):
        role_ids = [str(r.id) for r in author.roles]
        if server_config.privacy_gate_role in role_ids:
            return str(author.id)

    # User doesn't have role - anonymize
    # Use consistent anonymous ID within channel context
    return self.get_anonymous_id(author.id, server_id)

def get_anonymous_id(self, real_id: str, context_id: str) -> str:
    """Generate consistent anonymous ID for a user in a context."""
    # Hash to get consistent number
    h = hash((real_id, context_id)) % 1000
    return f"<chat_{h}>"
```

### Edit Handling

Messages are upserted by ID. When a message is edited:
1. Fetch returns updated content
2. Upsert overwrites with new content
3. Original content is not preserved (spec decision: respect "unsaying")

### Delete Handling

```python
async def handle_deleted_messages(self, channel_id: str):
    """Mark messages as deleted if no longer in Discord."""
    # Option 1: Mark with deleted_at timestamp
    # Option 2: Actually delete from DB
    # Spec says: "respect unsaying" - so delete
    pass
```

### Tracking Last Polled

```python
# New table for poll state
poll_state = Table(
    "poll_state",
    metadata,
    Column("channel_id", String, primary_key=True),
    Column("last_message_at", DateTime, nullable=False),
    Column("last_polled_at", DateTime, nullable=False),
)
```

### DM Handling

```python
async def poll_dms(self):
    """Poll DM channels separately."""
    for dm in self.private_channels:
        await self.poll_channel_dm(dm)

async def poll_channel_dm(self, channel: discord.DMChannel):
    """Poll a DM channel."""
    user_id = str(channel.recipient.id)

    # Check first-contact acknowledgment
    if not await self.has_dm_consent(user_id):
        # First DM - send acknowledgment, mark consent
        await self.send_first_contact(channel)
        await self.mark_dm_consent(user_id)

    # Poll messages (no privacy gate for DMs)
    await self.poll_channel(channel)
```

## Configuration

```yaml
discord:
  polling_interval_seconds: 60
  messages_per_poll: 100
  channels:
    # Explicit channel allowlist (optional)
    # If empty, poll all accessible channels
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/observation.py` | Polling logic, message storage |
| `src/zos/database.py` | Add poll_state table, message queries |
| `tests/test_polling.py` | Polling logic tests |

## Test Cases

1. New messages are stored correctly
2. Edited messages update existing records
3. Privacy gate role is respected
4. Anonymous IDs are consistent within context
5. DM consent flow works
6. Incremental polling only fetches new messages

## Definition of Done

- [ ] Messages appear in database after polling
- [ ] Privacy gate users are anonymized
- [ ] Edits update, deletes remove
- [ ] DM first-contact message sent once

---

## Design Decisions (Resolved 2026-01-23)

### Q1: Anonymous ID Stability
**Decision**: Stable per conversation window (reset daily or per reflection cycle)
- Same person = same `<chat_N>` within a day
- Resets between reflection cycles
- Preserves within-conversation coherence without cross-session tracking
- Anonymous users are genuinely anonymous across time

**Implementation**: Hash with date component: `hash((real_id, context_id, date_bucket)) % 1000`

### Q2: Delete Handling
**Decision**: Soft delete with tombstone
- Set `deleted_at` timestamp rather than removing row
- Deleted messages excluded from new reflection but preserved for audit
- Zos experiences deletions as "unsayings" — the retraction is recorded as an event
- Insights that referenced deleted content may be contextually incomplete but persist

**Schema addition**: `deleted_at` timestamp field on Message table

### Q3: First-Contact DM Acknowledgment
**Decision**: Single combined response (deferred to MVP 1)
- When user DMs Zos, respond to their message AND include acknowledgment woven in naturally
- More conversational, less robotic than separate acknowledgment
- Note: MVP 0 doesn't speak, so this is observation-only for now

---

**Requires**: Story 2.1 (Discord connection)
**Blocks**: Stories 2.3-2.5, Epic 3 (salience needs messages)
