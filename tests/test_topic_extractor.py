"""Tests for topic key extraction."""

from zos.topics.extractor import MessageContext, extract_topic_keys
from zos.topics.topic_key import TopicCategory


class TestExtractTopicKeys:
    """Tests for extract_topic_keys."""

    def test_basic_message_keys(self) -> None:
        """Basic message should generate user, channel, user_in_channel keys."""
        ctx = MessageContext(
            author_id=123,
            channel_id=456,
            content="Hello world",
        )
        keys = extract_topic_keys(ctx)

        key_strs = {k.key for k in keys}
        assert "user:123" in key_strs
        assert "channel:456" in key_strs
        assert "user_in_channel:456:123" in key_strs
        assert len(keys) == 3

    def test_mention_creates_dyad(self) -> None:
        """Mentioning a user should create dyad keys."""
        ctx = MessageContext(
            author_id=123,
            channel_id=456,
            content="Hey <@789>!",
        )
        keys = extract_topic_keys(ctx)

        key_strs = {k.key for k in keys}
        assert "dyad:123:789" in key_strs
        assert "dyad_in_channel:456:123:789" in key_strs

    def test_mention_with_nickname_format(self) -> None:
        """Nickname mention format (<@!id>) should also work."""
        ctx = MessageContext(
            author_id=123,
            channel_id=456,
            content="Hey <@!789>!",
        )
        keys = extract_topic_keys(ctx)

        key_strs = {k.key for k in keys}
        assert "dyad:123:789" in key_strs

    def test_multiple_mentions(self) -> None:
        """Multiple mentions should create multiple dyad pairs."""
        ctx = MessageContext(
            author_id=123,
            channel_id=456,
            content="Hey <@789> and <@101112>!",
        )
        keys = extract_topic_keys(ctx)

        key_strs = {k.key for k in keys}
        assert "dyad:123:789" in key_strs
        assert "dyad:123:101112" in key_strs
        assert "dyad_in_channel:456:123:789" in key_strs
        assert "dyad_in_channel:456:123:101112" in key_strs

    def test_reply_creates_dyad(self) -> None:
        """Replying to a user should create dyad keys."""
        ctx = MessageContext(
            author_id=123,
            channel_id=456,
            content="I agree",
            reply_to_author_id=789,
        )
        keys = extract_topic_keys(ctx)

        key_strs = {k.key for k in keys}
        assert "dyad:123:789" in key_strs
        assert "dyad_in_channel:456:123:789" in key_strs

    def test_reply_and_mention_combined(self) -> None:
        """Reply target and mentions should be combined."""
        ctx = MessageContext(
            author_id=123,
            channel_id=456,
            content="<@555> check this out",
            reply_to_author_id=789,
        )
        keys = extract_topic_keys(ctx)

        key_strs = {k.key for k in keys}
        # Dyad with reply target
        assert "dyad:123:789" in key_strs
        # Dyad with mention
        assert "dyad:123:555" in key_strs

    def test_self_mention_ignored(self) -> None:
        """Self-mentions should not create dyad keys."""
        ctx = MessageContext(
            author_id=123,
            channel_id=456,
            content="<@123> talking to myself",
        )
        keys = extract_topic_keys(ctx)

        dyad_keys = [k for k in keys if k.category == TopicCategory.DYAD]
        assert len(dyad_keys) == 0

    def test_self_reply_ignored(self) -> None:
        """Replying to self should not create dyad keys."""
        ctx = MessageContext(
            author_id=123,
            channel_id=456,
            content="Follow up to my own message",
            reply_to_author_id=123,
        )
        keys = extract_topic_keys(ctx)

        dyad_keys = [k for k in keys if k.category == TopicCategory.DYAD]
        assert len(dyad_keys) == 0

    def test_untracked_user_no_keys(self) -> None:
        """Untracked users should not generate any keys."""
        ctx = MessageContext(
            author_id=123,
            channel_id=456,
            content="Hello <@789>",
            is_tracked=False,
        )
        keys = extract_topic_keys(ctx)

        assert len(keys) == 0

    def test_duplicate_mention_deduped(self) -> None:
        """Same user mentioned multiple times should only create one dyad."""
        ctx = MessageContext(
            author_id=123,
            channel_id=456,
            content="<@789> hey <@789> look at this",
        )
        keys = extract_topic_keys(ctx)

        dyad_keys = [k for k in keys if k.category == TopicCategory.DYAD]
        assert len(dyad_keys) == 1

    def test_mention_same_as_reply_deduped(self) -> None:
        """Mentioning the reply target should not duplicate dyad."""
        ctx = MessageContext(
            author_id=123,
            channel_id=456,
            content="<@789> exactly!",
            reply_to_author_id=789,
        )
        keys = extract_topic_keys(ctx)

        dyad_keys = [k for k in keys if k.category == TopicCategory.DYAD]
        assert len(dyad_keys) == 1
