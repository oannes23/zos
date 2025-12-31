"""Tests for TopicKey module."""

import pytest

from zos.topics.topic_key import TopicCategory, TopicKey


class TestTopicKeyFactories:
    """Tests for TopicKey factory methods."""

    def test_user_key(self) -> None:
        tk = TopicKey.user(123)
        assert tk.key == "user:123"
        assert tk.category == TopicCategory.USER
        assert tk.user_id == 123
        assert tk.channel_id is None

    def test_channel_key(self) -> None:
        tk = TopicKey.channel(456)
        assert tk.key == "channel:456"
        assert tk.category == TopicCategory.CHANNEL
        assert tk.channel_id == 456
        assert tk.user_id is None

    def test_user_in_channel_key(self) -> None:
        tk = TopicKey.user_in_channel(456, 123)
        assert tk.key == "user_in_channel:456:123"
        assert tk.category == TopicCategory.USER_IN_CHANNEL
        assert tk.channel_id == 456
        assert tk.user_id == 123

    def test_dyad_key_sorted(self) -> None:
        """Dyad keys should have user IDs sorted."""
        tk1 = TopicKey.dyad(100, 200)
        tk2 = TopicKey.dyad(200, 100)
        assert tk1.key == tk2.key == "dyad:100:200"
        assert tk1.user_a_id == 100
        assert tk1.user_b_id == 200

    def test_dyad_in_channel_key_sorted(self) -> None:
        """Dyad-in-channel keys should have user IDs sorted."""
        tk = TopicKey.dyad_in_channel(999, 200, 100)
        assert tk.key == "dyad_in_channel:999:100:200"
        assert tk.channel_id == 999
        assert tk.user_a_id == 100
        assert tk.user_b_id == 200


class TestTopicKeyParsing:
    """Tests for TopicKey.parse()."""

    def test_parse_user(self) -> None:
        tk = TopicKey.parse("user:123")
        assert tk == TopicKey.user(123)

    def test_parse_channel(self) -> None:
        tk = TopicKey.parse("channel:456")
        assert tk == TopicKey.channel(456)

    def test_parse_user_in_channel(self) -> None:
        tk = TopicKey.parse("user_in_channel:456:123")
        assert tk == TopicKey.user_in_channel(456, 123)

    def test_parse_dyad(self) -> None:
        tk = TopicKey.parse("dyad:100:200")
        assert tk.user_a_id == 100
        assert tk.user_b_id == 200

    def test_parse_dyad_in_channel(self) -> None:
        tk = TopicKey.parse("dyad_in_channel:999:100:200")
        assert tk.channel_id == 999
        assert tk.user_a_id == 100
        assert tk.user_b_id == 200

    def test_parse_invalid_category(self) -> None:
        with pytest.raises(ValueError, match="Invalid topic key format"):
            TopicKey.parse("invalid:123")

    def test_parse_invalid_format(self) -> None:
        with pytest.raises(ValueError, match="Invalid topic key format"):
            TopicKey.parse("user")

    def test_parse_invalid_number(self) -> None:
        with pytest.raises(ValueError, match="Invalid topic key format"):
            TopicKey.parse("user:abc")


class TestTopicKeyProperties:
    """Tests for TopicKey properties."""

    def test_hashable(self) -> None:
        """TopicKey should be usable as dict key."""
        tk = TopicKey.user(123)
        d = {tk: "value"}
        assert d[tk] == "value"

    def test_set_membership(self) -> None:
        """TopicKey should work in sets."""
        tk1 = TopicKey.user(123)
        tk2 = TopicKey.user(123)
        tk3 = TopicKey.user(456)
        s = {tk1, tk2, tk3}
        assert len(s) == 2

    def test_str(self) -> None:
        """str() should return the canonical key."""
        tk = TopicKey.dyad(100, 200)
        assert str(tk) == "dyad:100:200"

    def test_equality(self) -> None:
        """Equal keys should be equal."""
        tk1 = TopicKey.user(123)
        tk2 = TopicKey.user(123)
        assert tk1 == tk2

    def test_inequality(self) -> None:
        """Different keys should not be equal."""
        tk1 = TopicKey.user(123)
        tk2 = TopicKey.user(456)
        assert tk1 != tk2

    def test_frozen(self) -> None:
        """TopicKey should be immutable."""
        tk = TopicKey.user(123)
        with pytest.raises(AttributeError):
            tk.user_id = 456  # type: ignore[misc]
