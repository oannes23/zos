"""FetchMessages node for retrieving messages from the database."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from zos.layer.nodes.base import BaseNode, NodeResult
from zos.logging import get_logger
from zos.topics.topic_key import TopicCategory, TopicKey

if TYPE_CHECKING:
    from zos.layer.context import PipelineContext
    from zos.layer.schema import FetchMessagesConfig

logger = get_logger("layer.nodes.fetch_messages")


class FetchMessagesNode(BaseNode):
    """Fetch messages for the current topic from the database.

    Retrieves messages based on the topic category:
    - user: Messages by that user
    - channel: Messages in that channel
    - user_in_channel: Messages by user in channel
    - dyad: Messages involving both users
    - dyad_in_channel: Messages involving both users in channel

    Stores the messages in context as "messages".
    Optionally includes reactions when include_reactions is True.
    """

    config: FetchMessagesConfig

    @property
    def node_type(self) -> str:
        return "fetch_messages"

    async def execute(self, context: PipelineContext) -> NodeResult:
        """Fetch messages for the current topic.

        Args:
            context: Pipeline context with topic and message repository.

        Returns:
            NodeResult with list of message dicts.
        """
        topic = context.current_topic
        if topic is None:
            return NodeResult.fail("No current topic set")

        # Calculate time range
        # Use window_start from context if set by scheduler (since last successful run),
        # otherwise fall back to lookback_hours from node config
        if context.window_start is not None:
            since = context.window_start
        else:
            since = context.run_start - timedelta(hours=self.config.lookback_hours)
        limit = self.config.max_messages

        # Fetch messages based on topic category
        messages = self._fetch_for_topic(context, topic, since, limit)

        # Filter by visibility scope
        if self.config.scope != "all":
            messages = [
                m for m in messages if m.get("visibility_scope") == self.config.scope
            ]

        # Include reactions if configured
        if self.config.include_reactions and messages:
            messages = self._attach_reactions(context, messages)

        # Store in context for downstream nodes
        context.set("messages", messages)

        reactions_info = ""
        if self.config.include_reactions:
            reactions_info = ", include_reactions=True"

        logger.debug(
            f"Fetched {len(messages)} messages for {topic.key} "
            f"(lookback={self.config.lookback_hours}h, scope={self.config.scope}{reactions_info})"
        )

        return NodeResult.ok(data=messages)

    def _attach_reactions(
        self,
        context: PipelineContext,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Attach reactions to messages and build reaction summary.

        Args:
            context: Pipeline context.
            messages: List of message dicts.

        Returns:
            Messages with reactions attached.
        """
        repo = context.message_repo
        message_ids = [m["message_id"] for m in messages]

        # Fetch all reactions for these messages
        reactions_by_msg = repo.get_reactions_for_messages(message_ids)

        # Attach reactions to each message
        for msg in messages:
            msg_id = msg["message_id"]
            msg["reactions"] = reactions_by_msg.get(msg_id, [])

        # Build reaction summary for context
        all_reactions: list[str] = []
        for reactions in reactions_by_msg.values():
            all_reactions.extend(r["emoji"] for r in reactions)

        emoji_counts = Counter(all_reactions)
        reaction_summary = "\n".join(
            f"  {emoji}: {count}" for emoji, count in emoji_counts.most_common(20)
        )
        if reaction_summary:
            reaction_summary = f"Reaction counts:\n{reaction_summary}"
        else:
            reaction_summary = "No reactions in this period."

        context.set("reaction_summary", reaction_summary)
        context.set("reaction_counts", dict(emoji_counts))

        return messages

    def _fetch_for_topic(
        self,
        context: PipelineContext,
        topic_key: TopicKey,
        since: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Fetch messages based on topic category.

        Routes to the appropriate repository method.
        """
        repo = context.message_repo

        if topic_key.category == TopicCategory.CHANNEL:
            assert topic_key.channel_id is not None
            return repo.get_messages_by_channel(
                channel_id=topic_key.channel_id,
                since=since,
                limit=limit,
            )
        elif topic_key.category == TopicCategory.USER:
            assert topic_key.user_id is not None
            return repo.get_messages_by_user(
                user_id=topic_key.user_id,
                since=since,
                limit=limit,
            )
        elif topic_key.category == TopicCategory.USER_IN_CHANNEL:
            assert topic_key.channel_id is not None
            assert topic_key.user_id is not None
            return repo.get_messages_by_user_in_channel(
                channel_id=topic_key.channel_id,
                user_id=topic_key.user_id,
                since=since,
                limit=limit,
            )
        elif topic_key.category == TopicCategory.DYAD:
            assert topic_key.user_a_id is not None
            assert topic_key.user_b_id is not None
            return repo.get_messages_involving_users(
                user_id_1=topic_key.user_a_id,
                user_id_2=topic_key.user_b_id,
                since=since,
                limit=limit,
            )
        elif topic_key.category == TopicCategory.DYAD_IN_CHANNEL:
            # For dyad_in_channel, we need to filter by channel too
            # The repository doesn't have this exact method, so we'll
            # fetch by channel and filter by users
            assert topic_key.channel_id is not None
            assert topic_key.user_a_id is not None
            assert topic_key.user_b_id is not None
            all_messages = repo.get_messages_by_channel(
                channel_id=topic_key.channel_id,
                since=since,
                limit=limit * 2,  # Fetch more to account for filtering
            )
            user_ids = {topic_key.user_a_id, topic_key.user_b_id}
            filtered = [m for m in all_messages if m.get("author_id") in user_ids]
            return filtered[:limit]
        else:
            logger.warning(f"Unknown topic category: {topic_key.category}")
            return []

    def validate(self, context: PipelineContext) -> list[str]:
        """Validate that topic is set."""
        errors = []
        if context.current_topic is None:
            errors.append("fetch_messages requires a current topic")
        return errors
