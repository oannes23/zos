# Story 5.10: Human-Readable API Responses

**Epic**: Introspection
**Status**: 🟢 Complete
**Estimated complexity**: Low-Medium
**Implemented**: 2026-01-28

## Goal

Add optional human-readable name resolution to all introspection API endpoints, replacing Discord snowflake IDs with display names in topic keys and reference fields.

## Acceptance Criteria

- [ ] Query parameter `readable=true` available on all endpoints
- [ ] When enabled, topic keys transform: `server:123:user:456` → `server:My Server:user:JohnDoe#1234`
- [ ] Transformation covers: servers, channels, users, threads, roles
- [ ] Original IDs preserved in separate field when readable mode is on
- [ ] Response includes `_readable: true` flag when mode is active
- [ ] Graceful fallback to ID if name not found (e.g., `[unknown:123]`)
- [ ] Performance: name resolution is batched to minimize DB queries

## Technical Notes

### Query Parameter

All introspection endpoints accept:

```python
readable: bool = Query(False, description="Replace IDs with human-readable names")
```

### Response Model Extension

When `readable=true`, responses gain:

```python
class ReadableResponse(BaseModel):
    """Extended response with readable flag."""
    _readable: bool = True
    _original_ids: dict[str, str] | None = None  # Maps readable key → original ID
```

### Topic Key Transformation

Transform embedded IDs in topic keys:

| Original | Readable |
|----------|----------|
| `server:123:user:456` | `server:My Server:user:JohnDoe#1234` |
| `server:123:channel:789` | `server:My Server:channel:#general` |
| `server:123:dyad:456:789` | `server:My Server:dyad:JohnDoe#1234:JaneDoe#5678` |
| `user:456` | `user:JohnDoe#1234` |
| `self:zos` | `self:zos` (unchanged) |
| `server:123:emoji:💀` | `server:My Server:emoji:💀` |

### Name Resolution Sources

| Entity | Source | Display Format |
|--------|--------|----------------|
| Server | `servers.name` | Server name |
| Channel | `channels.name` | `#channel-name` |
| User | `user_profiles.display_name` or `username` | `DisplayName` or `username#discrim` |
| Role | Discord API (cached) | Role name |
| Thread | `channels.name` (type=thread) | Thread title |

### Transformation Helper

```python
# src/zos/api/readable.py

class NameResolver:
    """Resolve Discord IDs to human-readable names."""

    def __init__(self, db: Database):
        self.db = db
        self._cache: dict[str, str] = {}

    async def resolve_topic_key(self, topic_key: str) -> str:
        """Transform a topic key to human-readable form."""
        # Parse topic key structure
        parts = topic_key.split(":")

        if parts[0] == "server":
            server_id = parts[1]
            server_name = await self._get_server_name(server_id)
            parts[1] = server_name or f"[unknown:{server_id}]"

            if len(parts) > 2:
                entity_type = parts[2]
                if entity_type == "user":
                    user_name = await self._get_user_name(parts[3])
                    parts[3] = user_name
                elif entity_type == "channel":
                    channel_name = await self._get_channel_name(parts[3])
                    parts[3] = f"#{channel_name}" if channel_name else f"[unknown:{parts[3]}]"
                # ... handle other entity types

        elif parts[0] == "user":
            user_name = await self._get_user_name(parts[1])
            parts[1] = user_name

        return ":".join(parts)

    async def _get_server_name(self, server_id: str) -> str | None:
        if server_id in self._cache:
            return self._cache[server_id]
        server = await self.db.get_server(server_id)
        name = server.name if server else None
        self._cache[server_id] = name
        return name

    async def _get_user_name(self, user_id: str) -> str:
        if user_id in self._cache:
            return self._cache[user_id]
        profile = await self.db.fetch_profile(user_id)
        if profile:
            name = profile.display_name or f"{profile.username}#{profile.discriminator}"
        else:
            name = f"[unknown:{user_id}]"
        self._cache[user_id] = name
        return name

    async def _get_channel_name(self, channel_id: str) -> str | None:
        if channel_id in self._cache:
            return self._cache[channel_id]
        channel = await self.db.get_channel(channel_id)
        name = channel.name if channel else None
        self._cache[channel_id] = name
        return name
```

### Endpoint Integration

Each endpoint applies transformation when `readable=True`:

```python
@router.get("/{topic_key:path}", response_model=list[InsightResponse])
async def get_insights_for_topic(
    topic_key: str,
    readable: bool = Query(False, description="Resolve IDs to names"),
    db: Database = Depends(get_db),
):
    insights = await retriever.retrieve(topic_key=topic_key, ...)

    if readable:
        resolver = NameResolver(db)
        for insight in insights:
            insight.topic_key = await resolver.resolve_topic_key(insight.topic_key)
            # Also resolve any other ID fields

    return insights
```

### Batch Resolution (Optimization)

For list endpoints, collect all unique IDs first:

```python
async def resolve_batch(self, topic_keys: list[str]) -> dict[str, str]:
    """Resolve multiple topic keys efficiently."""
    # Extract all unique IDs
    server_ids = set()
    user_ids = set()
    channel_ids = set()

    for key in topic_keys:
        # Parse and collect IDs...

    # Batch fetch all entities
    servers = await self.db.get_servers_batch(list(server_ids))
    users = await self.db.fetch_profiles_batch(list(user_ids))
    channels = await self.db.get_channels_batch(list(channel_ids))

    # Populate cache
    for s in servers: self._cache[s.id] = s.name
    for u in users: self._cache[u.user_id] = u.display_name
    for c in channels: self._cache[c.id] = c.name

    # Now resolve each key (cache hits)
    return {key: await self.resolve_topic_key(key) for key in topic_keys}
```

### Example Response

**GET /insights/server:123:user:456?readable=true**

```json
{
  "_readable": true,
  "insights": [
    {
      "id": "01HQXYZ...",
      "topic_key": "server:Zos Testing:user:JohnDoe#1234",
      "topic_key_original": "server:123456789:user:987654321",
      "category": "user_reflection",
      "content": "...",
      "temporal_marker": "strong memory from 2 days ago"
    }
  ]
}
```

**GET /salience?readable=true&limit=5**

```json
{
  "_readable": true,
  "salience": [
    {
      "topic_key": "server:Zos Testing:user:JaneDoe#5678",
      "topic_key_original": "server:123456789:user:111222333",
      "balance": 72.5,
      "budget_group": "social"
    }
  ]
}
```

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `src/zos/api/readable.py` | Name resolution helper |
| `src/zos/api/insights.py` | Add `readable` param |
| `src/zos/api/salience.py` | Add `readable` param |
| `src/zos/api/runs.py` | Add `readable` param |
| `src/zos/database.py` | Add batch fetch methods |
| `tests/test_api_readable.py` | Tests for name resolution |

## Test Cases

1. `readable=false` (default) returns original IDs
2. `readable=true` transforms server names
3. `readable=true` transforms user names
4. `readable=true` transforms channel names
5. Unknown entities show `[unknown:ID]` fallback
6. Global topics (`user:123`) resolve correctly
7. Complex keys (`server:A:dyad:B:C`) resolve all parts
8. Batch resolution is efficient (minimal DB queries)
9. Original ID preserved in `topic_key_original`
10. Response includes `_readable: true` flag

## Definition of Done

- [ ] Query parameter works on all introspection endpoints
- [ ] Names resolve correctly for all entity types
- [ ] Unknown entities degrade gracefully
- [ ] Performance is acceptable for large result sets
- [ ] Original IDs always preserved for programmatic access

---

**Requires**: Story 5.2, 5.3, 5.4 (existing endpoints)
**Blocks**: None
