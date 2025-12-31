"""Extract TopicKeys from Discord messages."""

import re
from dataclasses import dataclass

from zos.topics.topic_key import TopicKey

# Discord mention pattern: <@123456789> or <@!123456789>
MENTION_PATTERN = re.compile(r"<@!?(\d+)>")


@dataclass
class MessageContext:
    """Context for extracting topic keys from a message."""

    author_id: int
    channel_id: int
    content: str
    reply_to_author_id: int | None = None  # If this is a reply
    is_tracked: bool = True  # Only tracked users earn salience


def extract_topic_keys(ctx: MessageContext) -> list[TopicKey]:
    """Extract all applicable TopicKeys from a message.

    Returns topic keys for:
    - user (author)
    - channel
    - user_in_channel (author in this channel)
    - dyad (for each mentioned user or reply target)
    - dyad_in_channel (for each mentioned user or reply target in this channel)

    Only tracked users generate salience-earning topic keys.

    Args:
        ctx: Message context containing author, channel, content, and tracking info.

    Returns:
        List of TopicKeys that should earn salience from this message.
    """
    if not ctx.is_tracked:
        return []

    keys: list[TopicKey] = []

    # Base keys from message author
    keys.append(TopicKey.user(ctx.author_id))
    keys.append(TopicKey.channel(ctx.channel_id))
    keys.append(TopicKey.user_in_channel(ctx.channel_id, ctx.author_id))

    # Collect interaction partners (mentions + reply target)
    partners: set[int] = set()

    # Parse mentions from content
    for match in MENTION_PATTERN.finditer(ctx.content):
        mentioned_id = int(match.group(1))
        if mentioned_id != ctx.author_id:  # Exclude self-mentions
            partners.add(mentioned_id)

    # Add reply target
    if ctx.reply_to_author_id and ctx.reply_to_author_id != ctx.author_id:
        partners.add(ctx.reply_to_author_id)

    # Generate dyad keys for each partner
    for partner_id in partners:
        keys.append(TopicKey.dyad(ctx.author_id, partner_id))
        keys.append(TopicKey.dyad_in_channel(ctx.channel_id, ctx.author_id, partner_id))

    return keys
