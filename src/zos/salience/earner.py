"""Salience earning logic for Discord events."""

from datetime import datetime
from typing import TYPE_CHECKING

from zos.config import EarningWeights
from zos.salience.repository import SalienceRepository
from zos.topics.extractor import MessageContext, extract_topic_keys
from zos.topics.topic_key import TopicKey

if TYPE_CHECKING:
    from zos.db import Database


class SalienceEarner:
    """Handles salience earning for Discord events."""

    def __init__(
        self,
        db: "Database",
        weights: EarningWeights,
    ) -> None:
        """Initialize the earner.

        Args:
            db: Database instance.
            weights: Earning weights configuration.
        """
        self.repository = SalienceRepository(db)
        self.weights = weights

    def earn_for_message(
        self,
        ctx: MessageContext,
        message_id: int,
        timestamp: datetime,
    ) -> int:
        """Earn salience for a message.

        Awards salience to all applicable topic keys extracted from the message.
        Dyad keys (from mentions/replies) get an additional mention bonus.

        Args:
            ctx: Message context with author, channel, content, and tracking info.
            message_id: The message ID.
            timestamp: When the message was created.

        Returns:
            Number of salience entries created.
        """
        if not ctx.is_tracked:
            return 0

        topic_keys = extract_topic_keys(ctx)
        if not topic_keys:
            return 0

        # Build batch entries
        entries: list[tuple[TopicKey, float, str, datetime, int | None]] = []

        for tk in topic_keys:
            # Base message points
            entries.append((tk, self.weights.message, "message", timestamp, message_id))

        # Mention bonus for dyad keys
        mention_keys = [tk for tk in topic_keys if "dyad" in tk.category.value]
        for tk in mention_keys:
            entries.append((tk, self.weights.mention, "mention", timestamp, message_id))

        self.repository.earn_batch(entries)
        return len(entries)

    def earn_for_reaction_given(
        self,
        reactor_id: int,
        channel_id: int,
        message_id: int,
        timestamp: datetime,
        is_tracked: bool = True,
    ) -> int:
        """Earn salience when a user gives a reaction.

        Awards salience to the reactor's user, channel, and user_in_channel keys.

        Args:
            reactor_id: The user who gave the reaction.
            channel_id: The channel where the reaction was given.
            message_id: The message that was reacted to.
            timestamp: When the reaction was added.
            is_tracked: Whether the reactor is tracked.

        Returns:
            Number of salience entries created.
        """
        if not is_tracked:
            return 0

        entries: list[tuple[TopicKey, float, str, datetime, int | None]] = []

        # Reactor earns salience
        entries.append((
            TopicKey.user(reactor_id),
            self.weights.reaction_given,
            "reaction_given",
            timestamp,
            message_id,
        ))
        entries.append((
            TopicKey.channel(channel_id),
            self.weights.reaction_given,
            "reaction_given",
            timestamp,
            message_id,
        ))
        entries.append((
            TopicKey.user_in_channel(channel_id, reactor_id),
            self.weights.reaction_given,
            "reaction_given",
            timestamp,
            message_id,
        ))

        self.repository.earn_batch(entries)
        return len(entries)

    def earn_for_reaction_received(
        self,
        author_id: int,
        reactor_id: int,
        channel_id: int,
        message_id: int,
        timestamp: datetime,
        is_author_tracked: bool = True,
    ) -> int:
        """Earn salience when a user receives a reaction.

        Awards salience to the message author's user and user_in_channel keys,
        plus dyad keys for the author-reactor relationship.

        Args:
            author_id: The message author who received the reaction.
            reactor_id: The user who gave the reaction.
            channel_id: The channel where the reaction was given.
            message_id: The message that was reacted to.
            timestamp: When the reaction was added.
            is_author_tracked: Whether the message author is tracked.

        Returns:
            Number of salience entries created.
        """
        if not is_author_tracked:
            return 0

        entries: list[tuple[TopicKey, float, str, datetime, int | None]] = []

        # Message author earns salience for receiving reaction
        entries.append((
            TopicKey.user(author_id),
            self.weights.reaction_received,
            "reaction_received",
            timestamp,
            message_id,
        ))
        entries.append((
            TopicKey.user_in_channel(channel_id, author_id),
            self.weights.reaction_received,
            "reaction_received",
            timestamp,
            message_id,
        ))

        # Dyad between reactor and author
        entries.append((
            TopicKey.dyad(author_id, reactor_id),
            self.weights.reaction_received,
            "reaction_received",
            timestamp,
            message_id,
        ))
        entries.append((
            TopicKey.dyad_in_channel(channel_id, author_id, reactor_id),
            self.weights.reaction_received,
            "reaction_received",
            timestamp,
            message_id,
        ))

        self.repository.earn_batch(entries)
        return len(entries)
