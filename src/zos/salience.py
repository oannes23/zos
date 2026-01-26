"""Salience ledger operations for Zos.

The salience system governs what Zos thinks about. Salience is a ledger, not a score:
it's earned through activity, spent during reflection, and flows between related topics.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import and_, func, or_, select, text, update

from zos.database import generate_id, salience_ledger, topics, user_server_tracking
from zos.models import SalienceEntry, Topic, TopicCategory, TransactionType, utcnow


# =============================================================================
# Budget Groups
# =============================================================================


class BudgetGroup(str, Enum):
    """Budget groups for reflection topic selection.

    Topics are organized into groups to ensure fair attention distribution.
    Each group receives a percentage of the total reflection budget.
    """

    SOCIAL = "social"  # server users, dyads, user_in_channel, dyad_in_channel (30%)
    GLOBAL = "global"  # global users, global dyads (15%)
    SPACES = "spaces"  # channels, threads (30%)
    SEMANTIC = "semantic"  # subjects, roles (15%)
    CULTURE = "culture"  # emoji topics (10%)
    SELF = "self"  # self:zos, server self-topics (separate pool)


def _ensure_utc(dt: datetime | None) -> datetime | None:
    """Ensure a datetime is timezone-aware (UTC).

    SQLite stores datetimes as naive. This helper adds UTC timezone info
    if the datetime is naive.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from zos.config import Config

log = structlog.get_logger()


class SalienceLedger:
    """Manages salience transactions and balance computation.

    The salience ledger tracks attention-worthiness for topics. Operations include:
    - earn: Add salience from activity (messages, reactions, mentions)
    - spend: Consume salience when creating insights
    - retain: Partial retention after spending
    - decay: Gradual reduction after inactivity
    - propagate: Related topics receive a fraction
    - spillover: Overflow when cap is hit
    - warm: Initial salience for global topics
    """

    def __init__(self, engine: Engine, config: Config) -> None:
        """Initialize the salience ledger.

        Args:
            engine: SQLAlchemy database engine.
            config: Application configuration.
        """
        self.engine = engine
        self.config = config

    async def earn(
        self,
        topic_key: str,
        amount: float,
        reason: str | None = None,
        source_topic: str | None = None,
    ) -> tuple[float, float]:
        """Earn salience for a topic. Returns (new_balance, overflow).

        If the topic would exceed its cap, the excess is returned as overflow.
        Overflow can be used for spillover to related topics.

        Args:
            topic_key: The topic to earn salience for.
            amount: Amount of salience to earn.
            reason: What caused this (message_id, etc).
            source_topic: If propagation, which topic triggered this.

        Returns:
            Tuple of (new balance, overflow amount).
        """
        # Ensure topic exists (lazy creation)
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
        timestamp = utcnow()
        await self.update_topic_activity(topic_key, timestamp)

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
        """Spend salience from a topic. Returns amount actually spent.

        Spending applies partial retention - some salience persists after
        reflection to maintain momentum.

        Args:
            topic_key: The topic to spend from.
            amount: Amount to spend.
            reason: What caused this (layer_run_id, etc).

        Returns:
            Amount actually spent (may be less than requested if balance insufficient).
        """
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
                    reason=f"retention from {reason}" if reason else "retention",
                )

        log.debug(
            "salience_spent",
            topic=topic_key,
            requested=amount,
            actual=actual_spend,
            retained=retained if actual_spend > 0 else 0,
        )

        return actual_spend

    async def decay(
        self,
        topic_key: str,
        amount: float,
        reason: str | None = None,
    ) -> float:
        """Apply decay to a topic. Returns amount decayed.

        Args:
            topic_key: The topic to decay.
            amount: Amount to decay.
            reason: What caused this (e.g., "daily_decay").

        Returns:
            Amount actually decayed (never more than current balance).
        """
        balance = await self.get_balance(topic_key)
        actual_decay = min(amount, balance)

        if actual_decay > 0:
            await self.record_transaction(
                topic_key=topic_key,
                transaction_type=TransactionType.DECAY,
                amount=-actual_decay,
                reason=reason,
            )

        log.debug(
            "salience_decayed",
            topic=topic_key,
            amount=actual_decay,
        )

        return actual_decay

    async def propagate(
        self,
        topic_key: str,
        amount: float,
        source_topic: str,
        reason: str | None = None,
    ) -> float:
        """Propagate salience to a related topic. Returns amount propagated.

        Propagation only occurs to warm topics (salience > warm_threshold).

        Args:
            topic_key: The topic receiving propagated salience.
            amount: Amount to propagate.
            source_topic: The topic that triggered this propagation.
            reason: Additional context.

        Returns:
            Amount actually propagated (respects cap).
        """
        # Check if topic is warm
        balance = await self.get_balance(topic_key)
        if balance <= self.config.salience.warm_threshold:
            log.debug(
                "propagation_skipped_cold_topic",
                topic=topic_key,
                balance=balance,
                threshold=self.config.salience.warm_threshold,
            )
            return 0.0

        # Ensure topic exists
        await self.ensure_topic(topic_key)

        # Get cap and calculate actual propagation
        cap = self.get_cap(topic_key)
        actual_propagate = min(amount, cap - balance)

        if actual_propagate > 0:
            await self.record_transaction(
                topic_key=topic_key,
                transaction_type=TransactionType.PROPAGATE,
                amount=actual_propagate,
                reason=reason,
                source_topic=source_topic,
            )

        log.debug(
            "salience_propagated",
            topic=topic_key,
            amount=actual_propagate,
            source=source_topic,
        )

        return actual_propagate

    async def spillover(
        self,
        topic_key: str,
        amount: float,
        source_topic: str,
        reason: str | None = None,
    ) -> float:
        """Apply spillover from overflow. Returns amount spilled.

        Spillover occurs when a related topic hits its cap and the overflow
        needs somewhere to go.

        Args:
            topic_key: The topic receiving spillover.
            amount: Amount to spill.
            source_topic: The topic that overflowed.
            reason: Additional context.

        Returns:
            Amount actually spilled (respects cap).
        """
        # Check if topic is warm
        balance = await self.get_balance(topic_key)
        if balance <= self.config.salience.warm_threshold:
            return 0.0

        # Ensure topic exists
        await self.ensure_topic(topic_key)

        # Get cap and calculate actual spillover
        cap = self.get_cap(topic_key)
        actual_spillover = min(amount, cap - balance)

        if actual_spillover > 0:
            await self.record_transaction(
                topic_key=topic_key,
                transaction_type=TransactionType.SPILLOVER,
                amount=actual_spillover,
                reason=reason,
                source_topic=source_topic,
            )

        log.debug(
            "salience_spillover",
            topic=topic_key,
            amount=actual_spillover,
            source=source_topic,
        )

        return actual_spillover

    async def warm(
        self,
        topic_key: str,
        amount: float,
        reason: str | None = None,
    ) -> float:
        """Warm a global topic. Returns amount warmed.

        Used when a global topic transitions from cold to warm (e.g., DM activity
        or second-server sighting).

        Args:
            topic_key: The global topic to warm.
            amount: Initial warmth amount.
            reason: What triggered warming.

        Returns:
            Amount actually applied (respects cap).
        """
        # Ensure topic exists
        await self.ensure_topic(topic_key)

        # Get current balance and cap
        balance = await self.get_balance(topic_key)
        cap = self.get_cap(topic_key)
        actual_warm = min(amount, cap - balance)

        if actual_warm > 0:
            await self.record_transaction(
                topic_key=topic_key,
                transaction_type=TransactionType.WARM,
                amount=actual_warm,
                reason=reason,
            )

        # Update last activity
        timestamp = utcnow()
        await self.update_topic_activity(topic_key, timestamp)

        log.info(
            "global_topic_warmed",
            topic=topic_key,
            amount=actual_warm,
            reason=reason,
        )

        return actual_warm

    async def record_transaction(
        self,
        topic_key: str,
        transaction_type: TransactionType,
        amount: float,
        reason: str | None = None,
        source_topic: str | None = None,
    ) -> SalienceEntry:
        """Record a salience transaction.

        Args:
            topic_key: The topic this transaction affects.
            transaction_type: Type of transaction.
            amount: Amount (positive or negative).
            reason: What caused this.
            source_topic: For propagation/spillover, the source.

        Returns:
            The created SalienceEntry.
        """
        entry = SalienceEntry(
            id=generate_id(),
            topic_key=topic_key,
            transaction_type=transaction_type,
            amount=amount,
            reason=reason,
            source_topic=source_topic,
            created_at=utcnow(),
        )

        with self.engine.connect() as conn:
            stmt = salience_ledger.insert().values(
                id=entry.id,
                topic_key=entry.topic_key,
                transaction_type=entry.transaction_type.value,
                amount=entry.amount,
                reason=entry.reason,
                source_topic=entry.source_topic,
                created_at=entry.created_at,
            )
            conn.execute(stmt)
            conn.commit()

        return entry

    async def get_balance(self, topic_key: str) -> float:
        """Get current salience balance for a topic.

        Balance is computed as the sum of all transactions for this topic.

        Args:
            topic_key: The topic to get balance for.

        Returns:
            Current balance (0.0 if no transactions).
        """
        with self.engine.connect() as conn:
            result = conn.execute(
                select(func.coalesce(func.sum(salience_ledger.c.amount), 0.0)).where(
                    salience_ledger.c.topic_key == topic_key
                )
            )
            return float(result.scalar() or 0.0)

    async def get_balances(self, topic_keys: list[str]) -> dict[str, float]:
        """Get balances for multiple topics efficiently.

        Args:
            topic_keys: List of topic keys to query.

        Returns:
            Dict mapping topic_key to balance. Missing topics have balance 0.
        """
        if not topic_keys:
            return {}

        with self.engine.connect() as conn:
            result = conn.execute(
                select(
                    salience_ledger.c.topic_key,
                    func.coalesce(func.sum(salience_ledger.c.amount), 0.0).label(
                        "balance"
                    ),
                )
                .where(salience_ledger.c.topic_key.in_(topic_keys))
                .group_by(salience_ledger.c.topic_key)
            )
            balances = {row.topic_key: float(row.balance) for row in result}

        # Fill in zeros for missing topics
        for key in topic_keys:
            if key not in balances:
                balances[key] = 0.0

        return balances

    def get_cap(self, topic_key: str) -> float:
        """Get the salience cap for a topic based on its category.

        Args:
            topic_key: The topic key.

        Returns:
            The cap for this topic type.
        """
        category = self.extract_category(topic_key)
        caps = self.config.salience.caps

        cap_map = {
            "user": caps.server_user,
            "channel": caps.channel,
            "thread": caps.thread,
            "dyad": caps.dyad,
            "user_in_channel": caps.user_in_channel,
            "dyad_in_channel": caps.dyad_in_channel,
            "subject": caps.subject,
            "role": caps.role,
            "emoji": caps.emoji,
            "self": caps.self_topic,
        }

        # Global topics have different caps
        if self.is_global(topic_key):
            if topic_key.startswith("user:"):
                return float(caps.server_user)  # Use server_user cap for global users
            if topic_key.startswith("dyad:"):
                return float(caps.dyad)  # Use dyad cap for global dyads
            if topic_key == "self:zos" or topic_key.startswith("self:"):
                return float(caps.self_topic)

        return float(cap_map.get(category, 100))  # Default cap

    def extract_category(self, topic_key: str) -> str:
        """Extract category from topic key.

        Args:
            topic_key: The topic key string.

        Returns:
            The category string (e.g., "user", "channel", "dyad").
        """
        # server:X:user:Y -> user
        # server:X:dyad:A:B -> dyad
        # user:Y -> user (global)
        parts = topic_key.split(":")
        if parts[0] == "server":
            return parts[2]  # server:X:category:...
        return parts[0]  # global topic

    def is_global(self, topic_key: str) -> bool:
        """Check if topic is global (not server-scoped).

        Args:
            topic_key: The topic key string.

        Returns:
            True if this is a global topic.
        """
        return not topic_key.startswith("server:")

    async def ensure_topic(self, topic_key: str) -> Topic:
        """Ensure a topic exists, creating if necessary.

        This is lazy topic creation - topics are created on first earn.

        Args:
            topic_key: The topic key to ensure exists.

        Returns:
            The Topic instance.
        """
        # Try to get existing topic
        topic = await self.get_topic(topic_key)
        if topic:
            return topic

        # Create new topic
        category = self.extract_category(topic_key)
        is_global = self.is_global(topic_key)

        # Map category string to enum
        try:
            category_enum = TopicCategory(category)
        except ValueError:
            # Default to USER if unknown category
            category_enum = TopicCategory.USER

        topic = Topic(
            key=topic_key,
            category=category_enum,
            is_global=is_global,
            provisional=False,
            created_at=utcnow(),
        )

        with self.engine.connect() as conn:
            stmt = topics.insert().values(
                key=topic.key,
                category=topic.category.value,
                is_global=topic.is_global,
                provisional=topic.provisional,
                created_at=topic.created_at,
            )
            conn.execute(stmt)
            conn.commit()

        log.info("topic_created", topic_key=topic_key, category=category)
        return topic

    async def get_topic(self, topic_key: str) -> Topic | None:
        """Get a topic by key.

        Args:
            topic_key: The topic key to look up.

        Returns:
            The Topic if found, None otherwise.
        """
        with self.engine.connect() as conn:
            result = conn.execute(
                select(topics).where(topics.c.key == topic_key)
            ).fetchone()
            if result is None:
                return None

            return Topic(
                key=result.key,
                category=TopicCategory(result.category),
                is_global=result.is_global,
                provisional=result.provisional,
                created_at=_ensure_utc(result.created_at),
                last_activity_at=_ensure_utc(result.last_activity_at),
                metadata=result.metadata,
            )

    async def update_topic_activity(
        self, topic_key: str, timestamp: datetime
    ) -> None:
        """Update last activity timestamp for a topic.

        Args:
            topic_key: The topic to update.
            timestamp: The activity timestamp.
        """
        with self.engine.connect() as conn:
            stmt = (
                update(topics)
                .where(topics.c.key == topic_key)
                .values(last_activity_at=timestamp)
            )
            conn.execute(stmt)
            conn.commit()

    async def get_history(
        self,
        topic_key: str,
        limit: int = 100,
        since: datetime | None = None,
    ) -> list[SalienceEntry]:
        """Get transaction history for a topic.

        Args:
            topic_key: The topic to get history for.
            limit: Maximum number of entries to return.
            since: Only return entries after this timestamp.

        Returns:
            List of SalienceEntry, most recent first.
        """
        with self.engine.connect() as conn:
            query = select(salience_ledger).where(
                salience_ledger.c.topic_key == topic_key
            )

            if since:
                query = query.where(salience_ledger.c.created_at > since)

            query = query.order_by(salience_ledger.c.created_at.desc()).limit(limit)

            rows = conn.execute(query).fetchall()

            return [
                SalienceEntry(
                    id=row.id,
                    topic_key=row.topic_key,
                    transaction_type=TransactionType(row.transaction_type),
                    amount=row.amount,
                    reason=row.reason,
                    source_topic=row.source_topic,
                    created_at=_ensure_utc(row.created_at),
                )
                for row in rows
            ]

    async def get_inactive_topics(self, since: datetime) -> list[Topic]:
        """Get topics with no activity since the given date.

        Topics are considered inactive if their last_activity_at is before
        the threshold date, or if they have never had activity recorded.

        Args:
            since: The threshold date. Topics with last_activity_at before
                this date (or None) are considered inactive.

        Returns:
            List of inactive Topic instances.
        """
        with self.engine.connect() as conn:
            stmt = select(topics).where(
                or_(
                    topics.c.last_activity_at < since,
                    topics.c.last_activity_at.is_(None),
                )
            )
            rows = conn.execute(stmt).fetchall()

            return [
                Topic(
                    key=row.key,
                    category=TopicCategory(row.category),
                    is_global=row.is_global,
                    provisional=row.provisional,
                    created_at=_ensure_utc(row.created_at),
                    last_activity_at=_ensure_utc(row.last_activity_at),
                    metadata=row.metadata,
                )
                for row in rows
            ]

    async def apply_decay(self) -> tuple[int, float]:
        """Apply decay to all inactive topics.

        Decay follows an exponential model: new_balance = old_balance * (1 - decay_rate).
        This preserves the asymptotic property -- topics never quite reach zero
        through decay alone.

        Topics don't decay while active. Decay begins after threshold days
        of inactivity.

        Edge cases:
        - Topics with zero balance don't generate decay transactions
        - Topics with tiny balances (<0.1) are zeroed out completely

        Returns:
            Tuple of (topics_decayed, total_decayed).
        """
        threshold_days = self.config.salience.decay_threshold_days
        decay_rate = self.config.salience.decay_rate_per_day

        threshold_date = utcnow() - timedelta(days=threshold_days)

        # Get topics that haven't had activity since threshold
        inactive_topics = await self.get_inactive_topics(threshold_date)

        decayed_count = 0
        total_decayed = 0.0

        for topic in inactive_topics:
            balance = await self.get_balance(topic.key)

            if balance <= 0:
                continue  # Nothing to decay

            # Edge case: tiny balance - zero it out completely
            if balance < 0.1:
                await self.record_transaction(
                    topic_key=topic.key,
                    transaction_type=TransactionType.DECAY,
                    amount=-balance,
                    reason="decay_to_zero",
                )
                decayed_count += 1
                total_decayed += balance
                continue

            # Standard decay: percentage of current balance
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
            threshold_days=threshold_days,
            decay_rate=decay_rate,
        )

        return decayed_count, total_decayed

    # =========================================================================
    # Propagation Methods (Story 3.3)
    # =========================================================================

    async def earn_with_propagation(
        self,
        topic_key: str,
        amount: float,
        reason: str | None = None,
        propagate: bool = True,
    ) -> tuple[float, float]:
        """Earn salience with propagation to related topics.

        This is the primary earning method that handles propagation. It:
        1. Earns to the primary topic
        2. Propagates to warm related topics
        3. Handles overflow spillover

        Propagation only goes ONE level - it does not cascade.

        Args:
            topic_key: The topic to earn salience for.
            amount: Amount of salience to earn.
            reason: What caused this (message_id, etc).
            propagate: Whether to propagate to related topics.

        Returns:
            Tuple of (new balance, overflow amount).
        """
        # Earn to primary topic
        new_balance, overflow = await self.earn(topic_key, amount, reason)

        if not propagate:
            return new_balance, overflow

        # Get related topics
        related = await self.get_related_topics(topic_key)

        # Normal propagation to warm topics
        for related_key in related:
            if await self.is_warm(related_key):
                factor = self.get_propagation_factor(topic_key, related_key)
                propagated_amount = amount * factor

                # Record as propagation (uses propagate method which checks warmth again,
                # but we're sure it's warm so it will succeed)
                await self.propagate(
                    related_key,
                    propagated_amount,
                    source_topic=topic_key,
                    reason=f"propagate:{topic_key}" if reason is None else f"propagate:{reason}",
                )

        # Overflow spillover to warm related topics
        if overflow > 0:
            spillover_amount = overflow * self.config.salience.spillover_factor
            for related_key in related:
                if await self.is_warm(related_key):
                    await self.spillover(
                        related_key,
                        spillover_amount,
                        source_topic=topic_key,
                        reason=f"overflow:{topic_key}",
                    )

        return new_balance, overflow

    async def is_warm(self, topic_key: str) -> bool:
        """Check if a topic is warm (has salience above threshold).

        A warm topic is one with salience > warm_threshold. Cold topics
        (including new topics with 0 salience) do not receive propagation.

        Args:
            topic_key: The topic to check.

        Returns:
            True if the topic is warm.
        """
        balance = await self.get_balance(topic_key)
        return balance > self.config.salience.warm_threshold

    async def get_related_topics(self, topic_key: str) -> list[str]:
        """Get topics related to this one for propagation.

        Propagation relationships depend on topic type:
        - server:X:user:Y -> dyads, user_in_channels, global user:Y
        - server:X:channel:Y -> user_in_channels, threads
        - server:X:dyad:A:B -> both user topics, global dyad
        - user:X (global) -> all server:*:user:X topics, global dyads

        Propagation is ONE level only - no cascading.

        Args:
            topic_key: The topic to get related topics for.

        Returns:
            List of related topic keys.
        """
        related: list[str] = []
        parts = topic_key.split(":")

        # Server-scoped user
        if self._matches_pattern(topic_key, "server:*:user:*"):
            server_id = parts[1]
            user_id = parts[3]

            # Related dyads
            dyads = await self._get_dyads_for_user(server_id, user_id)
            related.extend(dyads)

            # Related user_in_channel
            uics = await self._get_user_in_channels(server_id, user_id)
            related.extend(uics)

            # Global user (if it exists and is warm, propagation will handle)
            global_user = f"user:{user_id}"
            related.append(global_user)

        # Server-scoped channel
        elif self._matches_pattern(topic_key, "server:*:channel:*"):
            server_id = parts[1]
            channel_id = parts[3]

            # Related user_in_channel topics
            uics = await self._get_channel_user_contexts(server_id, channel_id)
            related.extend(uics)

            # Related threads
            threads = await self._get_threads_for_channel(server_id, channel_id)
            related.extend(threads)

        # Server-scoped dyad
        elif self._matches_pattern(topic_key, "server:*:dyad:*:*"):
            server_id = parts[1]
            user_a = parts[3]
            user_b = parts[4]

            # Both user topics
            related.append(f"server:{server_id}:user:{user_a}")
            related.append(f"server:{server_id}:user:{user_b}")

            # Global dyad (if it exists and is warm, propagation will handle)
            global_dyad = f"dyad:{user_a}:{user_b}"
            related.append(global_dyad)

        # Server-scoped emoji (propagates to users who use it - handled in earning)
        elif self._matches_pattern(topic_key, "server:*:emoji:*"):
            # Emoji propagation to user is handled in earning, not here
            pass

        # Global user
        elif self._matches_pattern(topic_key, "user:*"):
            user_id = parts[1]

            # All server-scoped user topics (downward propagation)
            server_topics = await self._get_server_user_topics(user_id)
            related.extend(server_topics)

            # Global dyads involving this user
            global_dyads = await self._get_global_dyads_for_user(user_id)
            related.extend(global_dyads)

        # Global dyad
        elif self._matches_pattern(topic_key, "dyad:*:*"):
            user_a = parts[1]
            user_b = parts[2]

            # Both global user topics
            related.append(f"user:{user_a}")
            related.append(f"user:{user_b}")

            # All server-scoped dyads (downward propagation)
            server_dyads = await self._get_server_dyad_topics(user_a, user_b)
            related.extend(server_dyads)

        return related

    def get_propagation_factor(self, source: str, target: str) -> float:
        """Get the propagation factor for source -> target.

        Uses global_propagation_factor for server <-> global propagation,
        and regular propagation_factor otherwise.

        Args:
            source: The source topic key.
            target: The target topic key.

        Returns:
            The propagation factor to use.
        """
        # Use global factor for server <-> global propagation
        if self.is_global(source) != self.is_global(target):
            return self.config.salience.global_propagation_factor

        return self.config.salience.propagation_factor

    def _matches_pattern(self, topic_key: str, pattern: str) -> bool:
        """Check if a topic key matches a pattern with wildcards.

        Patterns use * for single segment wildcards.
        e.g., "server:*:user:*" matches "server:123:user:456"

        Args:
            topic_key: The topic key to check.
            pattern: Pattern with * wildcards.

        Returns:
            True if the topic matches the pattern.
        """
        key_parts = topic_key.split(":")
        pattern_parts = pattern.split(":")

        if len(key_parts) != len(pattern_parts):
            return False

        for key_part, pattern_part in zip(key_parts, pattern_parts):
            if pattern_part != "*" and key_part != pattern_part:
                return False

        return True

    # =========================================================================
    # Database Queries for Related Topics
    # =========================================================================

    async def _get_dyads_for_user(self, server_id: str, user_id: str) -> list[str]:
        """Get all dyad topics involving a user in a server.

        Args:
            server_id: The server ID.
            user_id: The user ID.

        Returns:
            List of dyad topic keys.
        """
        # Query topics table for dyads involving this user
        prefix = f"server:{server_id}:dyad:"

        with self.engine.connect() as conn:
            # Dyads can be server:X:dyad:user:other or server:X:dyad:other:user
            result = conn.execute(
                select(topics.c.key).where(
                    and_(
                        topics.c.key.like(f"{prefix}%"),
                        or_(
                            topics.c.key.like(f"{prefix}{user_id}:%"),
                            topics.c.key.like(f"{prefix}%:{user_id}"),
                        ),
                    )
                )
            )
            return [row.key for row in result]

    async def _get_user_in_channels(self, server_id: str, user_id: str) -> list[str]:
        """Get all user_in_channel topics for a user in a server.

        Args:
            server_id: The server ID.
            user_id: The user ID.

        Returns:
            List of user_in_channel topic keys.
        """
        # Pattern: server:X:user_in_channel:channel_id:user_id
        pattern = f"server:{server_id}:user_in_channel:%:{user_id}"

        with self.engine.connect() as conn:
            result = conn.execute(
                select(topics.c.key).where(topics.c.key.like(pattern))
            )
            return [row.key for row in result]

    async def _get_channel_user_contexts(
        self, server_id: str, channel_id: str
    ) -> list[str]:
        """Get all user_in_channel topics for a channel.

        Args:
            server_id: The server ID.
            channel_id: The channel ID.

        Returns:
            List of user_in_channel topic keys.
        """
        # Pattern: server:X:user_in_channel:channel_id:*
        pattern = f"server:{server_id}:user_in_channel:{channel_id}:%"

        with self.engine.connect() as conn:
            result = conn.execute(
                select(topics.c.key).where(topics.c.key.like(pattern))
            )
            return [row.key for row in result]

    async def _get_threads_for_channel(
        self, server_id: str, channel_id: str
    ) -> list[str]:
        """Get all thread topics for a channel.

        Note: This requires thread parent tracking in the topics metadata.
        For now, we return an empty list as thread-channel relationships
        need additional metadata tracking.

        Args:
            server_id: The server ID.
            channel_id: The channel ID.

        Returns:
            List of thread topic keys.
        """
        # TODO: Thread-channel relationship tracking needs metadata
        # For MVP, return empty list
        return []

    async def _get_server_user_topics(self, user_id: str) -> list[str]:
        """Get all server-scoped user topics for a user.

        Args:
            user_id: The user ID.

        Returns:
            List of server-scoped user topic keys.
        """
        # Pattern: server:*:user:user_id
        pattern = f"server:%:user:{user_id}"

        with self.engine.connect() as conn:
            result = conn.execute(
                select(topics.c.key).where(topics.c.key.like(pattern))
            )
            return [row.key for row in result]

    async def _get_global_dyads_for_user(self, user_id: str) -> list[str]:
        """Get all global dyad topics involving a user.

        Args:
            user_id: The user ID.

        Returns:
            List of global dyad topic keys.
        """
        with self.engine.connect() as conn:
            # Global dyads: dyad:user:other or dyad:other:user
            result = conn.execute(
                select(topics.c.key).where(
                    and_(
                        topics.c.key.like("dyad:%"),
                        or_(
                            topics.c.key.like(f"dyad:{user_id}:%"),
                            topics.c.key.like(f"dyad:%:{user_id}"),
                        ),
                    )
                )
            )
            return [row.key for row in result]

    async def _get_server_dyad_topics(self, user_a: str, user_b: str) -> list[str]:
        """Get all server-scoped dyad topics for a pair of users.

        Args:
            user_a: First user ID.
            user_b: Second user ID.

        Returns:
            List of server-scoped dyad topic keys.
        """
        # Dyads use sorted IDs
        sorted_ids = sorted([user_a, user_b])
        pattern = f"server:%:dyad:{sorted_ids[0]}:{sorted_ids[1]}"

        with self.engine.connect() as conn:
            result = conn.execute(
                select(topics.c.key).where(topics.c.key.like(pattern))
            )
            return [row.key for row in result]

    # =========================================================================
    # User Server Tracking (for Global Topic Warming)
    # =========================================================================

    async def track_user_server(self, user_id: str, server_id: str) -> None:
        """Track that a user has been seen in a server.

        Used for global topic warming - when a user is seen in 2+ servers,
        their global topic is warmed.

        Args:
            user_id: Discord user ID.
            server_id: Discord server ID.
        """
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        now = utcnow()

        with self.engine.connect() as conn:
            stmt = sqlite_insert(user_server_tracking).values(
                user_id=user_id,
                server_id=server_id,
                first_seen_at=now,
            )
            # On conflict, do nothing (already tracked)
            stmt = stmt.on_conflict_do_nothing()
            conn.execute(stmt)
            conn.commit()

    async def get_servers_for_user(self, user_id: str) -> list[str]:
        """Get all servers a user has been seen in.

        Args:
            user_id: Discord user ID.

        Returns:
            List of server IDs where user has been active.
        """
        with self.engine.connect() as conn:
            result = conn.execute(
                select(user_server_tracking.c.server_id).where(
                    user_server_tracking.c.user_id == user_id
                )
            )
            return [row.server_id for row in result]

    async def check_and_warm_global(self, user_id: str, server_id: str) -> bool:
        """Check if global topic should be warmed, and warm it if so.

        A global user topic is warmed when a user is seen in 2+ servers.
        This creates cross-server understanding.

        Args:
            user_id: Discord user ID.
            server_id: Current server ID (for tracking).

        Returns:
            True if the global topic was warmed (first time).
        """
        global_topic = f"user:{user_id}"

        # Already warm?
        if await self.is_warm(global_topic):
            return False

        # Track this server
        await self.track_user_server(user_id, server_id)

        # Check if user seen in multiple servers
        servers_seen = await self.get_servers_for_user(user_id)

        if len(servers_seen) >= 2:
            # Warm the global topic
            await self.warm(
                global_topic,
                self.config.salience.initial_global_warmth,
                reason=f"multi_server:{server_id}",
            )
            log.info(
                "global_topic_warmed",
                user_id=user_id,
                servers=len(servers_seen),
                trigger="multi_server",
            )
            return True

        return False

    async def warm_from_dm(self, user_id: str) -> bool:
        """Warm global topic from DM activity.

        DM activity directly warms the global user topic, enabling
        cross-server understanding.

        Args:
            user_id: Discord user ID.

        Returns:
            True if the global topic was warmed (first time).
        """
        global_topic = f"user:{user_id}"

        if await self.is_warm(global_topic):
            return False

        await self.warm(
            global_topic,
            self.config.salience.initial_global_warmth,
            reason="dm_activity",
        )
        log.info(
            "global_topic_warmed",
            user_id=user_id,
            trigger="dm",
        )
        return True

    async def check_and_warm_global_dyad(self, user_a: str, user_b: str) -> bool:
        """Check and warm global dyad if both users are warm.

        Per design decision: global dyad:A:B warms automatically when both
        user:A and user:B are warm. This is derived warmth.

        Args:
            user_a: First user ID.
            user_b: Second user ID.

        Returns:
            True if the global dyad was warmed (first time).
        """
        sorted_ids = sorted([user_a, user_b])
        global_dyad = f"dyad:{sorted_ids[0]}:{sorted_ids[1]}"

        # Already warm?
        if await self.is_warm(global_dyad):
            return False

        # Check if both users are warm
        user_a_warm = await self.is_warm(f"user:{sorted_ids[0]}")
        user_b_warm = await self.is_warm(f"user:{sorted_ids[1]}")

        if user_a_warm and user_b_warm:
            await self.warm(
                global_dyad,
                self.config.salience.initial_global_warmth,
                reason=f"both_users_warm:{sorted_ids[0]}:{sorted_ids[1]}",
            )
            log.info(
                "global_dyad_warmed",
                dyad=global_dyad,
                trigger="both_users_warm",
            )
            return True

        return False

    # =========================================================================
    # API Query Methods (Story 5.3)
    # =========================================================================

    async def get_top_topics(
        self,
        group: "BudgetGroup | None" = None,
        limit: int = 50,
    ) -> list["TopicWithBalance"]:
        """Get topics sorted by salience balance.

        Args:
            group: Optional budget group filter.
            limit: Maximum number of topics to return.

        Returns:
            List of TopicWithBalance objects sorted by balance descending.
        """
        # Subquery for balances
        balance_subquery = (
            select(
                salience_ledger.c.topic_key,
                func.sum(salience_ledger.c.amount).label("balance"),
            )
            .group_by(salience_ledger.c.topic_key)
            .subquery()
        )

        # Join with topics
        stmt = (
            select(
                topics,
                func.coalesce(balance_subquery.c.balance, 0.0).label("balance"),
            )
            .outerjoin(balance_subquery, topics.c.key == balance_subquery.c.topic_key)
            .where(func.coalesce(balance_subquery.c.balance, 0.0) > 0)
            .order_by(balance_subquery.c.balance.desc())
            .limit(limit)
        )

        if group:
            # Filter by budget group
            categories = self._group_to_categories(group)
            if group == BudgetGroup.GLOBAL:
                stmt = stmt.where(
                    and_(
                        topics.c.is_global == True,
                        topics.c.category.in_(categories),
                    )
                )
            elif group == BudgetGroup.SELF:
                stmt = stmt.where(topics.c.category == "self")
            else:
                stmt = stmt.where(
                    and_(
                        topics.c.is_global == False,
                        topics.c.category.in_(categories),
                    )
                )

        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()

            return [
                TopicWithBalance(
                    key=row.key,
                    category=TopicCategory(row.category),
                    is_global=row.is_global,
                    provisional=row.provisional,
                    created_at=_ensure_utc(row.created_at),
                    last_activity_at=_ensure_utc(row.last_activity_at),
                    metadata=row.metadata,
                    balance=float(row.balance) if row.balance else 0.0,
                )
                for row in rows
            ]

    def _group_to_categories(self, group: "BudgetGroup") -> list[str]:
        """Map budget group to topic categories.

        Args:
            group: The budget group.

        Returns:
            List of category strings for this group.
        """
        group_categories: dict[BudgetGroup, list[str]] = {
            BudgetGroup.SOCIAL: ["user", "dyad", "user_in_channel", "dyad_in_channel"],
            BudgetGroup.GLOBAL: ["user", "dyad"],
            BudgetGroup.SPACES: ["channel", "thread"],
            BudgetGroup.SEMANTIC: ["subject", "role"],
            BudgetGroup.CULTURE: ["emoji"],
            BudgetGroup.SELF: ["self"],
        }
        return group_categories.get(group, [])

    async def get_topics_by_group(
        self,
        group: "BudgetGroup",
        server_id: str | None = None,
    ) -> list[Topic]:
        """Get all topics in a budget group.

        Args:
            group: The budget group to query.
            server_id: Optional server ID to filter server-scoped topics.

        Returns:
            List of Topic instances in this group.
        """
        categories = self._group_to_categories(group)

        with self.engine.connect() as conn:
            if group == BudgetGroup.GLOBAL:
                # Global topics don't start with server:
                stmt = select(topics).where(
                    and_(
                        topics.c.is_global == True,
                        topics.c.category.in_(categories),
                    )
                )
            elif group == BudgetGroup.SELF:
                # Self topics can be global or server-scoped
                stmt = select(topics).where(topics.c.category == "self")
                if server_id:
                    # Include both global self and server-specific self
                    stmt = select(topics).where(
                        and_(
                            topics.c.category == "self",
                            or_(
                                topics.c.is_global == True,
                                topics.c.key.like(f"server:{server_id}:%"),
                            ),
                        )
                    )
            else:
                # Server-scoped topics
                stmt = select(topics).where(
                    and_(
                        topics.c.is_global == False,
                        topics.c.category.in_(categories),
                    )
                )
                if server_id:
                    stmt = stmt.where(topics.c.key.like(f"server:{server_id}:%"))

            rows = conn.execute(stmt).fetchall()

            return [
                Topic(
                    key=row.key,
                    category=TopicCategory(row.category),
                    is_global=row.is_global,
                    provisional=row.provisional,
                    created_at=_ensure_utc(row.created_at),
                    last_activity_at=_ensure_utc(row.last_activity_at),
                    metadata=row.metadata,
                )
                for row in rows
            ]


class TopicWithBalance:
    """Topic with computed salience balance."""

    def __init__(
        self,
        key: str,
        category: TopicCategory,
        is_global: bool,
        provisional: bool,
        created_at: datetime,
        last_activity_at: datetime | None,
        metadata: dict | None,
        balance: float,
    ):
        self.key = key
        self.category = category
        self.is_global = is_global
        self.provisional = provisional
        self.created_at = created_at
        self.last_activity_at = last_activity_at
        self.metadata = metadata
        self.balance = balance


class EarningCoordinator:
    """Coordinates salience earning from observed activity.

    Converts observed Discord activity (messages, reactions, mentions) into
    salience for relevant topics. This is the bridge between observation and
    the attention-budget system.

    Earning rules:
    - Messages earn for author topic and channel topic
    - Reactions earn for author, reactor, their dyad, and custom emoji topic
    - Mentions earn boosted amount for mentioned user
    - Replies earn for dyad between author and replied-to user
    - Thread creation earns boosted amount
    - Media/links apply a boost multiplier
    - DMs earn for global user topic
    - Anonymous users (<chat*) don't earn individual salience
    """

    # Discord mention pattern: <@123456789> or <@!123456789>
    MENTION_PATTERN = r"<@!?(\d+)>"

    def __init__(self, ledger: SalienceLedger, config: "Config") -> None:
        """Initialize the earning coordinator.

        Args:
            ledger: The salience ledger for recording earnings.
            config: Application configuration with weights.
        """
        self.ledger = ledger
        self.config = config
        self.weights = config.salience.weights

    async def process_message(
        self,
        message: "Message",
        propagate: bool = True,
    ) -> list[str]:
        """Process a message for salience earning with propagation.

        Earns salience for:
        - Author topic (server-scoped or global for DMs)
        - Channel topic
        - Dyad topic (if reply)
        - Mentioned users (boosted amount)

        Also handles:
        - Propagation to related warm topics
        - Global topic warming for server messages
        - Global topic warming for DMs

        Args:
            message: The Message model to process.
            propagate: Whether to propagate to related topics (default True).

        Returns:
            List of topic keys that earned salience.
        """
        import re
        from zos.models import Message

        topics_earned: list[str] = []

        # Skip anonymous users for individual earning
        # Channels still earn from anonymous activity
        if message.author_id.startswith("<chat"):
            await self.earn_channel(message, propagate=propagate)
            return topics_earned

        server_id = message.server_id
        base_amount = self.weights.message

        # Apply media/link boost
        if message.has_media or message.has_links:
            base_amount *= self.weights.media_boost_factor

        # 1. Author earns with propagation
        if server_id:
            author_topic = f"server:{server_id}:user:{message.author_id}"

            # Check and warm global topic if seen in multiple servers
            await self.ledger.check_and_warm_global(message.author_id, server_id)
        else:
            # DM - earn to global topic and warm it
            author_topic = f"user:{message.author_id}"
            await self.ledger.warm_from_dm(message.author_id)

        await self.ledger.earn_with_propagation(
            author_topic,
            base_amount,
            reason=f"message:{message.id}",
            propagate=propagate,
        )
        topics_earned.append(author_topic)

        # 2. Channel earns
        channel_topic = await self.earn_channel(message, propagate=propagate)
        if channel_topic:
            topics_earned.append(channel_topic)

        # 3. Reply creates dyad earning
        if message.reply_to_id:
            replied_to_author = await self._get_message_author(message.reply_to_id)
            if replied_to_author and not replied_to_author.startswith("<chat"):
                dyad_topic = await self.earn_dyad(
                    server_id,
                    message.author_id,
                    replied_to_author,
                    self.weights.reply,
                    reason=f"reply:{message.id}",
                    propagate=propagate,
                )
                if dyad_topic:
                    topics_earned.append(dyad_topic)

        # 4. Mentions
        mentions = self.extract_mentions(message.content)
        for mentioned_id in mentions:
            mention_topic = await self.earn_mention(
                server_id, mentioned_id, message.id, propagate=propagate
            )
            if mention_topic:
                topics_earned.append(mention_topic)

        return topics_earned

    async def earn_channel(
        self,
        message: "Message",
        propagate: bool = True,
    ) -> str | None:
        """Earn salience for the channel with propagation.

        DMs don't have channel topics. Server messages earn for the channel.

        Args:
            message: The Message model.
            propagate: Whether to propagate to related topics.

        Returns:
            The channel topic key if earned, None for DMs.
        """
        from zos.models import Message

        if not message.server_id:
            return None  # DMs don't have channel topics

        channel_topic = f"server:{message.server_id}:channel:{message.channel_id}"
        await self.ledger.earn_with_propagation(
            channel_topic,
            self.weights.message,
            reason=f"message:{message.id}",
            propagate=propagate,
        )
        return channel_topic

    async def process_reaction(
        self,
        reaction: "Reaction",
        message: "Message",
        propagate: bool = True,
    ) -> list[str]:
        """Process a reaction for salience earning with propagation.

        Earns salience for:
        - Message author (attention received)
        - Reactor (active engagement)
        - Dyad between author and reactor (relationship signal)
        - Custom emoji topic (if custom emoji used)

        Also handles global topic warming for server activity.

        Args:
            reaction: The Reaction model.
            message: The Message the reaction is on.
            propagate: Whether to propagate to related topics.

        Returns:
            List of topic keys that earned salience.
        """
        from zos.models import Message, Reaction

        topics_earned: list[str] = []
        server_id = message.server_id
        base_amount = self.weights.reaction

        # Skip if reactor is anonymous
        if reaction.user_id.startswith("<chat"):
            return topics_earned

        # 1. Message author earns (attention received)
        if not message.author_id.startswith("<chat"):
            if server_id:
                author_topic = f"server:{server_id}:user:{message.author_id}"
                # Check and warm global topic
                await self.ledger.check_and_warm_global(message.author_id, server_id)
            else:
                author_topic = f"user:{message.author_id}"
                await self.ledger.warm_from_dm(message.author_id)

            await self.ledger.earn_with_propagation(
                author_topic,
                base_amount,
                reason=f"reaction:{reaction.id}",
                propagate=propagate,
            )
            topics_earned.append(author_topic)

        # 2. Reactor earns (active engagement)
        if server_id:
            reactor_topic = f"server:{server_id}:user:{reaction.user_id}"
            # Check and warm global topic
            await self.ledger.check_and_warm_global(reaction.user_id, server_id)
        else:
            reactor_topic = f"user:{reaction.user_id}"
            await self.ledger.warm_from_dm(reaction.user_id)

        await self.ledger.earn_with_propagation(
            reactor_topic,
            base_amount,
            reason=f"reaction:{reaction.id}",
            propagate=propagate,
        )
        topics_earned.append(reactor_topic)

        # 3. Dyad earns (relationship signal)
        if not message.author_id.startswith("<chat"):
            dyad_topic = await self.earn_dyad(
                server_id,
                message.author_id,
                reaction.user_id,
                base_amount,
                reason=f"reaction:{reaction.id}",
                propagate=propagate,
            )
            if dyad_topic:
                topics_earned.append(dyad_topic)

                # Check and warm global dyad if both users are warm
                await self.ledger.check_and_warm_global_dyad(
                    message.author_id, reaction.user_id
                )

        # 4. Custom emoji topic earns
        if reaction.is_custom and server_id:
            emoji_topic = f"server:{server_id}:emoji:{reaction.emoji}"
            await self.ledger.earn_with_propagation(
                emoji_topic,
                base_amount,
                reason=f"reaction:{reaction.id}",
                propagate=propagate,
            )
            topics_earned.append(emoji_topic)

        return topics_earned

    async def earn_dyad(
        self,
        server_id: str | None,
        user_a: str,
        user_b: str,
        amount: float,
        reason: str,
        propagate: bool = True,
    ) -> str | None:
        """Earn salience for a dyad topic with propagation.

        Dyads use canonical sorted ordering of user IDs to ensure
        A->B and B->A interactions earn for the same topic.

        Args:
            server_id: Server ID, or None for global dyad.
            user_a: First user ID.
            user_b: Second user ID.
            amount: Amount to earn.
            reason: Reason for the earning.
            propagate: Whether to propagate to related topics.

        Returns:
            The dyad topic key if earned, None if self-dyad.
        """
        if user_a == user_b:
            return None  # No self-dyads

        # Canonical ordering for dyad key
        sorted_ids = sorted([user_a, user_b])

        if server_id:
            dyad_topic = f"server:{server_id}:dyad:{sorted_ids[0]}:{sorted_ids[1]}"
        else:
            dyad_topic = f"dyad:{sorted_ids[0]}:{sorted_ids[1]}"

        await self.ledger.earn_with_propagation(
            dyad_topic, amount, reason=reason, propagate=propagate
        )
        return dyad_topic

    async def earn_mention(
        self,
        server_id: str | None,
        mentioned_id: str,
        message_id: str,
        propagate: bool = True,
    ) -> str | None:
        """Earn salience for a mentioned user with propagation.

        Mentions earn a boosted amount for the mentioned user topic.

        Args:
            server_id: Server ID, or None for global.
            mentioned_id: Discord user ID of the mentioned user.
            message_id: ID of the message containing the mention.
            propagate: Whether to propagate to related topics.

        Returns:
            The topic key for the mentioned user.
        """
        if server_id:
            topic = f"server:{server_id}:user:{mentioned_id}"
            # Check and warm global topic
            await self.ledger.check_and_warm_global(mentioned_id, server_id)
        else:
            topic = f"user:{mentioned_id}"
            await self.ledger.warm_from_dm(mentioned_id)

        await self.ledger.earn_with_propagation(
            topic,
            self.weights.mention,
            reason=f"mention:{message_id}",
            propagate=propagate,
        )
        return topic

    def extract_mentions(self, content: str) -> list[str]:
        """Extract user IDs from mentions in content.

        Discord mention format: <@123456789> or <@!123456789>

        Args:
            content: Message content to parse.

        Returns:
            List of mentioned user IDs.
        """
        import re

        return re.findall(self.MENTION_PATTERN, content)

    async def process_thread_creation(
        self,
        thread_id: str,
        channel_id: str,
        creator_id: str,
        server_id: str,
        propagate: bool = True,
    ) -> list[str]:
        """Process thread creation for salience earning with propagation.

        Thread creation earns boosted amount for the creator and creates
        a thread topic.

        Args:
            thread_id: Discord thread ID.
            channel_id: Parent channel ID.
            creator_id: Discord user ID of thread creator.
            server_id: Discord server ID.
            propagate: Whether to propagate to related topics.

        Returns:
            List of topic keys that earned salience.
        """
        topics_earned: list[str] = []

        if creator_id.startswith("<chat"):
            return topics_earned

        # Check and warm global topic
        await self.ledger.check_and_warm_global(creator_id, server_id)

        # Thread creator earns boosted amount
        creator_topic = f"server:{server_id}:user:{creator_id}"
        await self.ledger.earn_with_propagation(
            creator_topic,
            self.weights.thread_create,
            reason=f"thread_create:{thread_id}",
            propagate=propagate,
        )
        topics_earned.append(creator_topic)

        # Thread topic created
        thread_topic = f"server:{server_id}:thread:{thread_id}"
        await self.ledger.earn_with_propagation(
            thread_topic,
            self.weights.thread_create,
            reason=f"thread_create:{thread_id}",
            propagate=propagate,
        )
        topics_earned.append(thread_topic)

        return topics_earned

    async def process_dm(
        self,
        message: "Message",
        propagate: bool = True,
    ) -> list[str]:
        """Process a DM for salience earning with propagation.

        DMs earn for the global user topic rather than a server-scoped topic.
        DM activity warms the global topic.

        Args:
            message: The DM Message model.
            propagate: Whether to propagate to related topics.

        Returns:
            List of topic keys that earned salience.
        """
        from zos.models import Message

        topics_earned: list[str] = []

        # Skip anonymous users (shouldn't happen in DMs but be safe)
        if message.author_id.startswith("<chat"):
            return topics_earned

        # Warm global topic from DM activity
        await self.ledger.warm_from_dm(message.author_id)

        # DMs earn for global user topic
        user_topic = f"user:{message.author_id}"

        amount = self.weights.dm_message
        if message.has_media or message.has_links:
            amount *= self.weights.media_boost_factor

        await self.ledger.earn_with_propagation(
            user_topic,
            amount,
            reason=f"dm:{message.id}",
            propagate=propagate,
        )
        topics_earned.append(user_topic)

        return topics_earned

    async def _get_message_author(self, message_id: str) -> str | None:
        """Get the author ID for a message by ID.

        Args:
            message_id: Discord message ID.

        Returns:
            Author ID if found, None otherwise.
        """
        from zos.database import messages

        with self.ledger.engine.connect() as conn:
            result = conn.execute(
                select(messages.c.author_id).where(messages.c.id == message_id)
            ).fetchone()
            if result:
                return result.author_id
            return None


# =============================================================================
# Budget Group Classification
# =============================================================================


def get_budget_group(topic_key: str) -> BudgetGroup:
    """Determine which budget group a topic belongs to.

    Budget groups organize topics for reflection selection, ensuring
    fair attention distribution across different topic types.

    Args:
        topic_key: The topic key to classify.

    Returns:
        The BudgetGroup this topic belongs to.
    """
    parts = topic_key.split(":")

    # Self topics (global or server-scoped)
    if "self" in parts:
        return BudgetGroup.SELF

    # Global topics (no server prefix)
    if not topic_key.startswith("server:"):
        if parts[0] in ("user", "dyad"):
            return BudgetGroup.GLOBAL
        # Fallback for unknown global topics
        return BudgetGroup.SEMANTIC

    # Server-scoped topics: server:X:category:...
    if len(parts) >= 3:
        category = parts[2]

        if category in ("user", "dyad", "user_in_channel", "dyad_in_channel"):
            return BudgetGroup.SOCIAL
        elif category in ("channel", "thread"):
            return BudgetGroup.SPACES
        elif category in ("subject", "role"):
            return BudgetGroup.SEMANTIC
        elif category == "emoji":
            return BudgetGroup.CULTURE

    # Default fallback
    return BudgetGroup.SEMANTIC


# =============================================================================
# Reflection Selector
# =============================================================================


class ReflectionSelector:
    """Selects topics for reflection based on salience and budget groups.

    The selector ensures fair attention distribution across topic types by:
    1. Allocating budget to each group based on configured percentages
    2. Selecting highest-salience topics from each group
    3. Reallocating unused budget proportionally to groups with demand

    Self topics use a separate budget pool that doesn't compete with
    community topics.
    """

    # Base cost estimates by topic category
    BASE_COSTS: dict[str, float] = {
        "user": 10.0,
        "dyad": 8.0,
        "channel": 15.0,
        "thread": 5.0,
        "subject": 12.0,
        "emoji": 5.0,
        "self": 20.0,
        "role": 10.0,
        "user_in_channel": 6.0,
        "dyad_in_channel": 6.0,
    }

    def __init__(self, ledger: SalienceLedger, config: "Config") -> None:
        """Initialize the reflection selector.

        Args:
            ledger: The salience ledger for balance queries.
            config: Application configuration with budget settings.
        """
        self.ledger = ledger
        self.config = config

    async def select_for_reflection(
        self,
        total_budget: float,
        server_id: str | None = None,
    ) -> dict[BudgetGroup, list[str]]:
        """Select topics for reflection within budget constraints.

        Implements a two-phase selection algorithm:
        1. Allocate initial budget per group and select topics
        2. Reallocate unused budget proportionally to groups with remaining demand

        Args:
            total_budget: Total salience budget available for reflection.
            server_id: Optional server ID to filter topics.

        Returns:
            Dictionary mapping budget groups to lists of selected topic keys.
        """
        budget_config = self.config.salience.budget

        # Phase 1: Initial allocation and selection
        group_budgets = {
            BudgetGroup.SOCIAL: total_budget * budget_config.social,
            BudgetGroup.GLOBAL: total_budget * budget_config.global_group,
            BudgetGroup.SPACES: total_budget * budget_config.spaces,
            BudgetGroup.SEMANTIC: total_budget * budget_config.semantic,
            BudgetGroup.CULTURE: total_budget * budget_config.culture,
        }

        selected: dict[BudgetGroup, list[str]] = {group: [] for group in BudgetGroup}
        remaining_budgets: dict[BudgetGroup, float] = {}
        group_demands: dict[BudgetGroup, float] = {}

        for group, budget in group_budgets.items():
            topics_selected, remaining, demand = await self._select_from_group_with_stats(
                group, budget, server_id
            )
            selected[group] = topics_selected
            remaining_budgets[group] = remaining
            group_demands[group] = demand

        # Phase 2: Proportional reallocation of unused budget
        total_unused = sum(remaining_budgets.values())
        total_demand = sum(group_demands.values())

        if total_unused > 0 and total_demand > 0:
            # Distribute unused budget proportionally to groups with remaining demand
            for group in group_budgets:
                if group_demands[group] > 0:
                    extra_budget = total_unused * (group_demands[group] / total_demand)
                    additional_topics = await self._select_additional_from_group(
                        group, extra_budget, server_id, exclude=selected[group]
                    )
                    selected[group].extend(additional_topics)

        # Self topics use separate budget pool
        self_topics = await self.select_self_topics()
        selected[BudgetGroup.SELF] = self_topics

        log.info(
            "reflection_selection_complete",
            total_budget=total_budget,
            server_id=server_id,
            topics_selected={g.value: len(t) for g, t in selected.items()},
        )

        return selected

    async def _select_from_group_with_stats(
        self,
        group: BudgetGroup,
        budget: float,
        server_id: str | None,
    ) -> tuple[list[str], float, float]:
        """Select topics from a group and return selection stats.

        Args:
            group: The budget group to select from.
            budget: Budget allocated to this group.
            server_id: Optional server filter.

        Returns:
            Tuple of (selected_topic_keys, remaining_budget, remaining_demand).
        """
        topics_list = await self.get_topics_by_group(group, server_id)

        if not topics_list:
            return [], budget, 0.0

        # Get balances for all topics
        topic_keys = [t.key for t in topics_list]
        balances = await self.ledger.get_balances(topic_keys)

        # Sort by balance descending (highest salience first)
        # Only include topics with positive balance
        sorted_topics = sorted(
            [(t, balances.get(t.key, 0.0)) for t in topics_list if balances.get(t.key, 0.0) > 0],
            key=lambda x: x[1],
            reverse=True,
        )

        # Greedy selection
        selected: list[str] = []
        remaining_budget = budget

        for topic, balance in sorted_topics:
            estimated_cost = self.estimate_reflection_cost(topic)
            if estimated_cost <= remaining_budget:
                selected.append(topic.key)
                remaining_budget -= estimated_cost

        # Calculate remaining demand (cost of topics we couldn't select)
        remaining_demand = sum(
            self.estimate_reflection_cost(t)
            for t, _ in sorted_topics
            if t.key not in selected
        )

        return selected, remaining_budget, remaining_demand

    async def _select_additional_from_group(
        self,
        group: BudgetGroup,
        budget: float,
        server_id: str | None,
        exclude: list[str],
    ) -> list[str]:
        """Select additional topics from a group using extra budget.

        Args:
            group: The budget group to select from.
            budget: Additional budget available.
            server_id: Optional server filter.
            exclude: Topic keys already selected (to exclude).

        Returns:
            List of additional selected topic keys.
        """
        topics_list = await self.get_topics_by_group(group, server_id)

        if not topics_list:
            return []

        # Filter out already selected topics
        excluded_set = set(exclude)
        topics_list = [t for t in topics_list if t.key not in excluded_set]

        if not topics_list:
            return []

        # Get balances
        topic_keys = [t.key for t in topics_list]
        balances = await self.ledger.get_balances(topic_keys)

        # Sort by balance descending, filter positive balance
        sorted_topics = sorted(
            [(t, balances.get(t.key, 0.0)) for t in topics_list if balances.get(t.key, 0.0) > 0],
            key=lambda x: x[1],
            reverse=True,
        )

        # Greedy selection with extra budget
        selected: list[str] = []
        remaining = budget

        for topic, _ in sorted_topics:
            cost = self.estimate_reflection_cost(topic)
            if cost <= remaining:
                selected.append(topic.key)
                remaining -= cost

        return selected

    async def select_from_group(
        self,
        group: BudgetGroup,
        budget: float,
        server_id: str | None,
    ) -> list[str]:
        """Select topics from a single budget group.

        This is a simpler interface for when you don't need reallocation stats.

        Args:
            group: The budget group to select from.
            budget: Budget allocated to this group.
            server_id: Optional server filter.

        Returns:
            List of selected topic keys.
        """
        selected, _, _ = await self._select_from_group_with_stats(group, budget, server_id)
        return selected

    async def select_self_topics(self) -> list[str]:
        """Select self topics using separate budget pool.

        Self topics don't compete with community topics for attention.
        They have their own daily allocation.

        Returns:
            List of selected self topic keys.
        """
        self_budget = self.config.salience.self_budget

        # Get all self topics (both global and server-scoped)
        self_topics = await self.get_topics_by_group(BudgetGroup.SELF, server_id=None)

        if not self_topics:
            return []

        # Get balances
        topic_keys = [t.key for t in self_topics]
        balances = await self.ledger.get_balances(topic_keys)

        # Sort by balance descending, filter positive balance
        sorted_topics = sorted(
            [(t, balances.get(t.key, 0.0)) for t in self_topics if balances.get(t.key, 0.0) > 0],
            key=lambda x: x[1],
            reverse=True,
        )

        # Greedy selection within self budget
        selected: list[str] = []
        remaining = self_budget

        for topic, _ in sorted_topics:
            cost = self.estimate_reflection_cost(topic)
            if cost <= remaining:
                selected.append(topic.key)
                remaining -= cost

        log.debug(
            "self_topics_selected",
            budget=self_budget,
            topics_selected=len(selected),
        )

        return selected

    def estimate_reflection_cost(self, topic: Topic) -> float:
        """Estimate the salience cost of reflecting on a topic.

        This is a simple estimate based on topic type. Could be refined
        with historical averages in the future.

        Args:
            topic: The topic to estimate cost for.

        Returns:
            Estimated salience cost for reflection.
        """
        category = topic.category.value
        return self.BASE_COSTS.get(category, 10.0)

    async def get_topics_by_group(
        self,
        group: BudgetGroup,
        server_id: str | None = None,
    ) -> list[Topic]:
        """Get all topics in a budget group.

        Args:
            group: The budget group to query.
            server_id: Optional server ID to filter server-scoped topics.

        Returns:
            List of Topic instances in this group.
        """
        # Map group to categories
        group_categories: dict[BudgetGroup, list[str]] = {
            BudgetGroup.SOCIAL: ["user", "dyad", "user_in_channel", "dyad_in_channel"],
            BudgetGroup.GLOBAL: ["user", "dyad"],  # Non-server-scoped
            BudgetGroup.SPACES: ["channel", "thread"],
            BudgetGroup.SEMANTIC: ["subject", "role"],
            BudgetGroup.CULTURE: ["emoji"],
            BudgetGroup.SELF: ["self"],
        }

        categories = group_categories[group]

        with self.ledger.engine.connect() as conn:
            if group == BudgetGroup.GLOBAL:
                # Global topics don't start with server:
                stmt = select(topics).where(
                    and_(
                        topics.c.is_global == True,
                        topics.c.category.in_(categories),
                    )
                )
            elif group == BudgetGroup.SELF:
                # Self topics can be global or server-scoped
                stmt = select(topics).where(topics.c.category == "self")
                if server_id:
                    # Include both global self and server-specific self
                    stmt = select(topics).where(
                        and_(
                            topics.c.category == "self",
                            or_(
                                topics.c.is_global == True,
                                topics.c.key.like(f"server:{server_id}:%"),
                            ),
                        )
                    )
            else:
                # Server-scoped topics
                stmt = select(topics).where(
                    and_(
                        topics.c.is_global == False,
                        topics.c.category.in_(categories),
                    )
                )
                if server_id:
                    stmt = stmt.where(topics.c.key.like(f"server:{server_id}:%"))

            rows = conn.execute(stmt).fetchall()

            return [
                Topic(
                    key=row.key,
                    category=TopicCategory(row.category),
                    is_global=row.is_global,
                    provisional=row.provisional,
                    created_at=_ensure_utc(row.created_at),
                    last_activity_at=_ensure_utc(row.last_activity_at),
                    metadata=row.metadata,
                )
                for row in rows
            ]
