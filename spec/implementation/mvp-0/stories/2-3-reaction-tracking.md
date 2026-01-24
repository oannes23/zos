# Story 2.3: Reaction Tracking

**Epic**: Observation
**Status**: 🔴 Not Started
**Estimated complexity**: Medium

## Goal

Track reactions on messages, storing reactor/emoji/message associations for salience earning and social texture analysis.

## Acceptance Criteria

- [ ] Reactions stored with message_id, user_id, emoji
- [ ] Custom emoji distinguished from Unicode
- [ ] Only opted-in users' reactions tracked individually
- [ ] Reactions from `<chat>` users not individually tracked
- [ ] Reaction removal handled (delete from DB)
- [ ] Aggregate reaction counts updated on messages

## Technical Notes

### Reaction Fetching

Reactions are fetched per-message during polling:

```python
async def fetch_reactions(self, message: discord.Message, server_id: str):
    """Fetch and store reactions for a message."""
    for reaction in message.reactions:
        # Get users who reacted
        async for user in reaction.users():
            # Check privacy gate
            user_id = await self.resolve_author_id(user, server_id)

            # Skip anonymous users for individual tracking
            if user_id.startswith("<chat"):
                continue

            # Store reaction
            await self.store_reaction(
                message_id=str(message.id),
                user_id=user_id,
                emoji=self.serialize_emoji(reaction.emoji),
                is_custom=reaction.custom_emoji,
            )

    # Update aggregate on message
    await self.update_reaction_aggregate(message)
```

### Reaction Storage

```python
async def store_reaction(
    self,
    message_id: str,
    user_id: str,
    emoji: str,
    is_custom: bool,
) -> None:
    """Store a single reaction."""
    reaction = Reaction(
        id=generate_id(),
        message_id=message_id,
        user_id=user_id,
        emoji=emoji,
        is_custom=is_custom,
        created_at=datetime.utcnow(),
    )

    # Upsert to handle re-fetching
    await self.db.upsert_reaction(reaction)
```

### Emoji Serialization

```python
def serialize_emoji(self, emoji: discord.Emoji | str) -> str:
    """Serialize emoji to storable string."""
    if isinstance(emoji, str):
        # Unicode emoji
        return emoji
    else:
        # Custom emoji - store as <:name:id>
        return f"<:{emoji.name}:{emoji.id}>"

def is_custom_emoji(self, emoji_str: str) -> bool:
    """Check if serialized emoji is custom."""
    return emoji_str.startswith("<:")
```

### Aggregate Tracking

The `reactions_aggregate` field on messages provides quick counts:

```python
async def update_reaction_aggregate(self, message: discord.Message):
    """Update the aggregate reaction counts on a message."""
    aggregate = {}
    for reaction in message.reactions:
        emoji_str = self.serialize_emoji(reaction.emoji)
        aggregate[emoji_str] = reaction.count

    await self.db.update_message_reactions(
        message_id=str(message.id),
        aggregate=aggregate,
    )
```

### Reaction Removal

When polling, if a reaction is no longer present:

```python
async def sync_reactions(self, message: discord.Message, server_id: str):
    """Sync reactions, removing stale ones."""
    # Get current reactions from Discord
    current = set()
    for reaction in message.reactions:
        async for user in reaction.users():
            user_id = await self.resolve_author_id(user, server_id)
            if not user_id.startswith("<chat"):
                emoji = self.serialize_emoji(reaction.emoji)
                current.add((user_id, emoji))

    # Get stored reactions
    stored = await self.db.get_reactions_for_message(str(message.id))
    stored_set = {(r.user_id, r.emoji) for r in stored}

    # Remove reactions no longer present
    to_remove = stored_set - current
    for user_id, emoji in to_remove:
        await self.db.delete_reaction(
            message_id=str(message.id),
            user_id=user_id,
            emoji=emoji,
        )
```

### Database Queries

```python
# src/zos/database.py

async def upsert_reaction(self, reaction: Reaction):
    """Insert or update a reaction."""
    # Use INSERT OR REPLACE for SQLite
    stmt = reactions_table.insert().prefix_with("OR REPLACE").values(
        **model_to_dict(reaction)
    )
    await self.execute(stmt)

async def delete_reaction(self, message_id: str, user_id: str, emoji: str):
    """Delete a specific reaction."""
    stmt = reactions_table.delete().where(
        (reactions_table.c.message_id == message_id) &
        (reactions_table.c.user_id == user_id) &
        (reactions_table.c.emoji == emoji)
    )
    await self.execute(stmt)

async def get_reactions_for_message(self, message_id: str) -> list[Reaction]:
    """Get all reactions for a message."""
    stmt = reactions_table.select().where(
        reactions_table.c.message_id == message_id
    )
    rows = await self.fetch_all(stmt)
    return [row_to_model(r, Reaction) for r in rows]
```

## Reaction Model

```python
class Reaction(BaseModel):
    id: str  # ULID
    message_id: str
    user_id: str
    emoji: str  # Unicode or <:name:id>
    is_custom: bool
    created_at: datetime

    class Config:
        from_attributes = True
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/observation.py` | Reaction fetching and storage |
| `src/zos/models.py` | Reaction model |
| `src/zos/database.py` | Reaction table queries |
| `tests/test_reactions.py` | Reaction tracking tests |

## Test Cases

1. Unicode emoji stored correctly
2. Custom emoji stored with ID
3. Anonymous users skipped
4. Reaction removal synced
5. Aggregate counts accurate
6. Duplicate reactions handled (upsert)

## Definition of Done

- [ ] Reactions appear in database
- [ ] Custom emoji distinguishable
- [ ] Removal synced on re-poll
- [ ] Aggregates updated on messages

---

## Open Design Questions

### Q1: Reaction Removal Tracking — Delta or Final State?
On re-poll, we see current reactions but not *changes* — we don't know if Alice added then removed a reaction between polls. Should tracking:
- **Store final state only** (current) — reaction_changes is computed between polls
- **Attempt removal detection** — if previous poll had reaction Alice:👍 and current doesn't, record removal
- **Ignore removals** — only track additions, treat removal as "didn't happen"

Removal tracking matters if "unsaying" applies to reactions — removing a ❤️ might be meaningful signal.

### Q2: Reaction Aggregation Scope — Message vs Conversation?
`reactions_aggregate` is per-message. But reflection might care about reaction patterns across a conversation (e.g., "Alice's comments consistently get 👎"). Should aggregation be:
- **Per-message only** (current) — aggregation at conversation level happens in reflection
- **Pre-computed conversation aggregates** — store "total reactions received by author in thread"
- **Both levels** — message-level for detail, conversation-level for patterns

This affects whether salience earning from reactions uses per-message or broader patterns.

### Q3: Custom Emoji Namespacing — Server-Specific Semantics
`emoji_key` is `unicode:😀` or `custom:server_id:emoji_name`. But server-specific emoji can have server-specific meanings (`:pepe:` might be ironic in server A, earnest in server B). Should we:
- **Namespace strictly** (current) — same emoji, different servers = different keys
- **Attempt semantic grouping** — cluster similar custom emoji across servers
- **Defer to reflection** — let layers interpret emoji meaning in context

The spec mentions "emoji culture tracking" in salience — this intersects with whether emoji topics are global or server-scoped.

---

**Requires**: Story 2.2 (message polling)
**Blocks**: Epic 3 (reaction-based salience earning)
