"""Human-readable name resolution for API responses.

Transforms Discord snowflake IDs in topic keys to human-readable names,
making the introspection API more useful for operators reviewing data.
"""

from typing import TYPE_CHECKING

from sqlalchemy import select

from zos.database import channels, servers, user_profiles

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


class NameResolver:
    """Resolve Discord IDs to human-readable names.

    Uses a per-request cache to avoid redundant lookups. For batch operations,
    use prime_cache() to preload entities before resolving topic keys.
    """

    def __init__(self, db: "Engine"):
        """Initialize resolver with database connection.

        Args:
            db: SQLAlchemy engine instance.
        """
        self.db = db
        self._cache: dict[str, str | None] = {}

    async def resolve_topic_key(self, topic_key: str) -> tuple[str, str]:
        """Transform a topic key to human-readable form.

        Args:
            topic_key: The original topic key (e.g., "server:123:user:456").

        Returns:
            Tuple of (readable_key, original_key).
        """
        original = topic_key
        parts = topic_key.split(":")

        if not parts:
            return topic_key, original

        # Handle different topic key formats
        if parts[0] == "server" and len(parts) >= 2:
            # Server-scoped topics: server:<id>:...
            server_id = parts[1]
            server_name = await self._get_server_name(server_id)
            parts[1] = server_name or f"[unknown:{server_id}]"

            if len(parts) >= 4:
                entity_type = parts[2]

                # Handle dyads: server:<id>:dyad:<user1>:<user2>
                if entity_type == "dyad":
                    if len(parts) >= 4:
                        await self._resolve_entity(parts, 3, "user")
                    if len(parts) >= 5:
                        await self._resolve_entity(parts, 4, "user")
                else:
                    await self._resolve_entity(parts, 3, entity_type)

        elif parts[0] == "user" and len(parts) >= 2:
            # Global user topic: user:<id>
            user_name = await self._get_user_name(parts[1])
            parts[1] = user_name

        elif parts[0] == "dyad" and len(parts) >= 3:
            # Global dyad topic: dyad:<user1>:<user2>
            user1_name = await self._get_user_name(parts[1])
            user2_name = await self._get_user_name(parts[2])
            parts[1] = user1_name
            parts[2] = user2_name

        # self:zos and emoji topics stay as-is (emoji already readable)

        return ":".join(parts), original

    async def _resolve_entity(self, parts: list[str], index: int, entity_type: str) -> None:
        """Resolve an entity at a specific index in parts list.

        Args:
            parts: The topic key parts (modified in place).
            index: Index of the entity ID in parts.
            entity_type: Type of entity (user, channel, thread, etc.).
        """
        if index >= len(parts):
            return

        entity_id = parts[index]

        if entity_type == "user":
            name = await self._get_user_name(entity_id)
            parts[index] = name
        elif entity_type in ("channel", "thread"):
            name = await self._get_channel_name(entity_id)
            if name:
                parts[index] = f"#{name}"
            else:
                parts[index] = f"[unknown:{entity_id}]"
        # emoji: already human-readable in key
        # role: would need separate table, fallback to ID for now
        elif entity_type == "role":
            # Roles not stored in our tables, keep as ID
            pass

    async def _get_server_name(self, server_id: str) -> str | None:
        """Get server name by ID, using cache.

        Args:
            server_id: Discord server snowflake ID.

        Returns:
            Server name or None if not found.
        """
        cache_key = f"server:{server_id}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        with self.db.connect() as conn:
            stmt = select(servers.c.name).where(servers.c.id == server_id)
            row = conn.execute(stmt).fetchone()
            name = row.name if row else None

        self._cache[cache_key] = name
        return name

    async def _get_user_name(self, user_id: str) -> str:
        """Get user display name by ID, using cache.

        Falls back to username#discriminator if no display name.
        Returns [unknown:ID] if user not found.

        Args:
            user_id: Discord user snowflake ID.

        Returns:
            Human-readable user name.
        """
        cache_key = f"user:{user_id}"
        if cache_key in self._cache:
            return self._cache[cache_key] or f"[unknown:{user_id}]"

        with self.db.connect() as conn:
            # Try to find most recent profile for this user
            stmt = (
                select(
                    user_profiles.c.display_name,
                    user_profiles.c.username,
                    user_profiles.c.discriminator,
                )
                .where(user_profiles.c.user_id == user_id)
                .order_by(user_profiles.c.captured_at.desc())
                .limit(1)
            )
            row = conn.execute(stmt).fetchone()

            if row:
                if row.display_name:
                    name = row.display_name
                elif row.discriminator and row.discriminator != "0":
                    name = f"{row.username}#{row.discriminator}"
                else:
                    name = row.username
            else:
                name = None

        self._cache[cache_key] = name
        return name or f"[unknown:{user_id}]"

    async def _get_channel_name(self, channel_id: str) -> str | None:
        """Get channel name by ID, using cache.

        Args:
            channel_id: Discord channel snowflake ID.

        Returns:
            Channel name or None if not found.
        """
        cache_key = f"channel:{channel_id}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        with self.db.connect() as conn:
            stmt = select(channels.c.name).where(channels.c.id == channel_id)
            row = conn.execute(stmt).fetchone()
            name = row.name if row else None

        self._cache[cache_key] = name
        return name

    async def prime_cache(self, topic_keys: list[str]) -> None:
        """Preload cache with entities from multiple topic keys.

        Performs batch queries to minimize database round trips.

        Args:
            topic_keys: List of topic keys to extract entity IDs from.
        """
        server_ids: set[str] = set()
        user_ids: set[str] = set()
        channel_ids: set[str] = set()

        # Extract all IDs from topic keys
        for key in topic_keys:
            parts = key.split(":")
            if not parts:
                continue

            if parts[0] == "server" and len(parts) >= 2:
                server_ids.add(parts[1])
                if len(parts) >= 4:
                    entity_type = parts[2]
                    if entity_type == "user":
                        user_ids.add(parts[3])
                    elif entity_type in ("channel", "thread"):
                        channel_ids.add(parts[3])
                    elif entity_type == "dyad" and len(parts) >= 5:
                        user_ids.add(parts[3])
                        user_ids.add(parts[4])

            elif parts[0] == "user" and len(parts) >= 2:
                user_ids.add(parts[1])

            elif parts[0] == "dyad" and len(parts) >= 3:
                user_ids.add(parts[1])
                user_ids.add(parts[2])

        # Batch fetch all entities
        with self.db.connect() as conn:
            # Fetch servers
            if server_ids:
                stmt = select(servers.c.id, servers.c.name).where(
                    servers.c.id.in_(list(server_ids))
                )
                for row in conn.execute(stmt):
                    self._cache[f"server:{row.id}"] = row.name

            # Fetch users (most recent profile for each)
            if user_ids:
                # SQLite doesn't support DISTINCT ON, so we use a subquery
                from sqlalchemy import func

                # Get the max captured_at for each user_id
                subq = (
                    select(
                        user_profiles.c.user_id,
                        func.max(user_profiles.c.captured_at).label("max_captured"),
                    )
                    .where(user_profiles.c.user_id.in_(list(user_ids)))
                    .group_by(user_profiles.c.user_id)
                    .subquery()
                )

                # Join to get full profile data
                stmt = (
                    select(
                        user_profiles.c.user_id,
                        user_profiles.c.display_name,
                        user_profiles.c.username,
                        user_profiles.c.discriminator,
                    )
                    .join(
                        subq,
                        (user_profiles.c.user_id == subq.c.user_id)
                        & (user_profiles.c.captured_at == subq.c.max_captured),
                    )
                )

                for row in conn.execute(stmt):
                    if row.display_name:
                        name = row.display_name
                    elif row.discriminator and row.discriminator != "0":
                        name = f"{row.username}#{row.discriminator}"
                    else:
                        name = row.username
                    self._cache[f"user:{row.user_id}"] = name

            # Fetch channels
            if channel_ids:
                stmt = select(channels.c.id, channels.c.name).where(
                    channels.c.id.in_(list(channel_ids))
                )
                for row in conn.execute(stmt):
                    self._cache[f"channel:{row.id}"] = row.name

    async def resolve_batch(
        self, topic_keys: list[str]
    ) -> list[tuple[str, str]]:
        """Resolve multiple topic keys efficiently.

        Primes cache first, then resolves each key.

        Args:
            topic_keys: List of topic keys to resolve.

        Returns:
            List of (readable_key, original_key) tuples.
        """
        await self.prime_cache(topic_keys)
        results = []
        for key in topic_keys:
            readable, original = await self.resolve_topic_key(key)
            results.append((readable, original))
        return results
