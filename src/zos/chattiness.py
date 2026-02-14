"""Per-topic impulse tracking for Zos conversation system.

Impulse is earned through observation (messages, reflections) and accumulates
per-topic. When impulse exceeds the configured threshold, Zos speaks — then
impulse resets to zero. The reset IS the rate limiting.
"""

from __future__ import annotations

from datetime import timedelta, timezone
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import func, select

from zos.database import chattiness_ledger, generate_id
from zos.models import ChattinessTransactionType, ImpulsePool, utcnow

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from zos.config import Config

log = structlog.get_logger()


def extract_category(topic_key: str) -> str | None:
    """Extract the topic category from a topic key.

    Returns 'channel', 'user', or 'subject' — or None if unrecognized.
    """
    if topic_key.startswith("server:") and ":channel:" in topic_key:
        return "channel"
    if topic_key.startswith("user:"):
        return "user"
    if topic_key.startswith("server:") and ":subject:" in topic_key:
        return "subject"
    if topic_key.startswith("subject:"):
        return "subject"
    return None


class ImpulseEngine:
    """Per-topic impulse tracking. Simple: earn, check, reset."""

    def __init__(self, engine: Engine, config: Config) -> None:
        self.engine = engine
        self.config = config

    def earn(self, topic_key: str, amount: float, trigger: str | None = None) -> None:
        """Add impulse to a topic. Writes to chattiness_ledger."""
        with self.engine.begin() as conn:
            conn.execute(
                chattiness_ledger.insert().values(
                    id=generate_id(),
                    pool=ImpulsePool.CONVERSATIONAL.value,
                    topic_key=topic_key,
                    transaction_type=ChattinessTransactionType.EARN.value,
                    amount=amount,
                    trigger=trigger,
                    created_at=utcnow(),
                )
            )
        log.debug("impulse_earned", topic_key=topic_key, amount=amount, trigger=trigger)

    def get_balance(self, topic_key: str) -> float:
        """SUM(amount) from chattiness_ledger for this topic."""
        with self.engine.connect() as conn:
            result = conn.execute(
                select(func.coalesce(func.sum(chattiness_ledger.c.amount), 0.0)).where(
                    chattiness_ledger.c.topic_key == topic_key
                )
            )
            return float(result.scalar())

    def reset(self, topic_key: str, trigger: str | None = None) -> None:
        """Zero out impulse by writing a negative transaction."""
        balance = self.get_balance(topic_key)
        if balance <= 0:
            return

        with self.engine.begin() as conn:
            conn.execute(
                chattiness_ledger.insert().values(
                    id=generate_id(),
                    pool=ImpulsePool.CONVERSATIONAL.value,
                    topic_key=topic_key,
                    transaction_type=ChattinessTransactionType.RESET.value,
                    amount=-balance,
                    trigger=trigger,
                    created_at=utcnow(),
                )
            )
        log.debug("impulse_reset", topic_key=topic_key, was=balance, trigger=trigger)

    def get_topics_above_threshold(self) -> list[tuple[str, float]]:
        """Query all topics where SUM(amount) > threshold. Used by heartbeat."""
        threshold = self.config.chattiness.threshold

        with self.engine.connect() as conn:
            result = conn.execute(
                select(
                    chattiness_ledger.c.topic_key,
                    func.sum(chattiness_ledger.c.amount).label("balance"),
                )
                .where(chattiness_ledger.c.topic_key.isnot(None))
                .group_by(chattiness_ledger.c.topic_key)
                .having(func.sum(chattiness_ledger.c.amount) > threshold)
            )
            return [(row.topic_key, float(row.balance)) for row in result]

    def apply_decay(self) -> int:
        """Decay impulse on topics with no recent earning. Run periodically.

        Returns number of topics decayed.
        """
        threshold_hours = self.config.chattiness.decay_threshold_hours
        decay_rate = self.config.chattiness.decay_rate_per_hour
        cutoff = utcnow() - timedelta(hours=threshold_hours)
        now = utcnow()
        decayed = 0

        # Find topics with positive balance and no recent earn
        with self.engine.connect() as conn:
            # Get all topics with positive balance
            balances = conn.execute(
                select(
                    chattiness_ledger.c.topic_key,
                    func.sum(chattiness_ledger.c.amount).label("balance"),
                    func.max(chattiness_ledger.c.created_at).label("last_activity"),
                )
                .where(chattiness_ledger.c.topic_key.isnot(None))
                .group_by(chattiness_ledger.c.topic_key)
                .having(func.sum(chattiness_ledger.c.amount) > 0)
            ).fetchall()

        for row in balances:
            last_activity = row.last_activity
            if last_activity and last_activity.tzinfo is None:
                last_activity = last_activity.replace(tzinfo=timezone.utc)

            if last_activity and last_activity < cutoff:
                hours_idle = (now - last_activity).total_seconds() / 3600
                decay_amount = row.balance * decay_rate * hours_idle
                decay_amount = min(decay_amount, row.balance)  # Don't go negative

                if decay_amount > 0.01:  # Skip negligible decay
                    with self.engine.begin() as conn:
                        conn.execute(
                            chattiness_ledger.insert().values(
                                id=generate_id(),
                                pool=ImpulsePool.CONVERSATIONAL.value,
                                topic_key=row.topic_key,
                                transaction_type=ChattinessTransactionType.DECAY.value,
                                amount=-decay_amount,
                                trigger="periodic_decay",
                                created_at=now,
                            )
                        )
                    decayed += 1

        if decayed:
            log.info("impulse_decay_applied", topics_decayed=decayed)
        return decayed
