"""Tests for Discord message repository."""

from datetime import UTC, datetime, timedelta

from zos.discord.repository import MessageRepository


class TestMessageRepository:
    """Tests for MessageRepository."""

    def test_upsert_message(self, message_repository: MessageRepository):
        """Test inserting a new message."""
        message_repository.upsert_message(
            message_id=1234567890,
            guild_id=987654321,
            guild_name="Test Guild",
            channel_id=555555555,
            channel_name="general",
            thread_id=None,
            parent_channel_id=None,
            author_id=123456789,
            author_name="TestUser",
            author_roles_snapshot="[111, 222]",
            content="Test content",
            created_at=datetime.now(UTC),
            visibility_scope="public",
            is_tracked=True,
        )

        assert message_repository.message_exists(1234567890)

    def test_upsert_message_idempotent(self, message_repository: MessageRepository):
        """Test that upsert is idempotent."""
        now = datetime.now(UTC)

        # Insert twice with same ID
        for _ in range(2):
            message_repository.upsert_message(
                message_id=1234567890,
                guild_id=987654321,
                guild_name="Test Guild",
                channel_id=555555555,
                channel_name="general",
                thread_id=None,
                parent_channel_id=None,
                author_id=123456789,
                author_name="TestUser",
                author_roles_snapshot="[]",
                content="Same content",
                created_at=now,
                visibility_scope="public",
            )

        # Should still only have one record
        result = message_repository.db.execute(
            "SELECT COUNT(*) FROM messages WHERE message_id = ?",
            (1234567890,),
        ).fetchone()
        assert result[0] == 1

    def test_upsert_updates_content_on_change(self, message_repository: MessageRepository):
        """Test that upsert updates content when it changes."""
        now = datetime.now(UTC)

        # Insert original
        message_repository.upsert_message(
            message_id=1234567890,
            guild_id=987654321,
            guild_name="Test Guild",
            channel_id=555555555,
            channel_name="general",
            thread_id=None,
            parent_channel_id=None,
            author_id=123456789,
            author_name="TestUser",
            author_roles_snapshot="[]",
            content="Original content",
            created_at=now,
            visibility_scope="public",
        )

        # Upsert with different content
        message_repository.upsert_message(
            message_id=1234567890,
            guild_id=987654321,
            guild_name="Test Guild",
            channel_id=555555555,
            channel_name="general",
            thread_id=None,
            parent_channel_id=None,
            author_id=123456789,
            author_name="TestUser",
            author_roles_snapshot="[]",
            content="Updated content",
            created_at=now,
            visibility_scope="public",
        )

        # Content should be updated
        result = message_repository.db.execute(
            "SELECT content, edited_at FROM messages WHERE message_id = ?",
            (1234567890,),
        ).fetchone()
        assert result["content"] == "Updated content"
        assert result["edited_at"] is not None

    def test_update_message_content(self, message_repository: MessageRepository):
        """Test updating message content directly."""
        now = datetime.now(UTC)

        # First insert
        message_repository.upsert_message(
            message_id=1234567890,
            guild_id=987654321,
            guild_name="Test Guild",
            channel_id=555555555,
            channel_name="general",
            thread_id=None,
            parent_channel_id=None,
            author_id=123456789,
            author_name="TestUser",
            author_roles_snapshot="[]",
            content="Original",
            created_at=now,
            visibility_scope="public",
        )

        # Update content
        message_repository.update_message_content(
            message_id=1234567890,
            content="Edited content",
            edited_at=now,
        )

        result = message_repository.db.execute(
            "SELECT content FROM messages WHERE message_id = ?",
            (1234567890,),
        ).fetchone()
        assert result["content"] == "Edited content"

    def test_soft_delete_message(self, message_repository: MessageRepository):
        """Test soft deleting a message."""
        # First insert
        message_repository.upsert_message(
            message_id=1234567890,
            guild_id=987654321,
            guild_name="Test Guild",
            channel_id=555555555,
            channel_name="general",
            thread_id=None,
            parent_channel_id=None,
            author_id=123456789,
            author_name="TestUser",
            author_roles_snapshot="[]",
            content="To be deleted",
            created_at=datetime.now(UTC),
            visibility_scope="public",
        )

        # Soft delete
        message_repository.soft_delete_message(1234567890)

        # Verify is_deleted flag
        result = message_repository.db.execute(
            "SELECT is_deleted, deleted_at FROM messages WHERE message_id = ?",
            (1234567890,),
        ).fetchone()
        assert result["is_deleted"] == 1
        assert result["deleted_at"] is not None

    def test_add_reaction(self, message_repository: MessageRepository):
        """Test adding a reaction."""
        # First insert the message
        message_repository.upsert_message(
            message_id=1234567890,
            guild_id=987654321,
            guild_name="Test Guild",
            channel_id=555555555,
            channel_name="general",
            thread_id=None,
            parent_channel_id=None,
            author_id=123456789,
            author_name="TestUser",
            author_roles_snapshot="[]",
            content="Test",
            created_at=datetime.now(UTC),
            visibility_scope="public",
        )

        # Add reaction
        message_repository.add_reaction(
            message_id=1234567890,
            emoji="👍",
            user_id=111111111,
            user_name="Reactor",
            created_at=datetime.now(UTC),
        )

        # Verify added
        result = message_repository.db.execute(
            "SELECT is_removed FROM reactions WHERE message_id = ? AND emoji = ?",
            (1234567890, "👍"),
        ).fetchone()
        assert result["is_removed"] == 0

    def test_remove_reaction(self, message_repository: MessageRepository):
        """Test removing a reaction."""
        # First insert the message
        message_repository.upsert_message(
            message_id=1234567890,
            guild_id=987654321,
            guild_name="Test Guild",
            channel_id=555555555,
            channel_name="general",
            thread_id=None,
            parent_channel_id=None,
            author_id=123456789,
            author_name="TestUser",
            author_roles_snapshot="[]",
            content="Test",
            created_at=datetime.now(UTC),
            visibility_scope="public",
        )

        # Add reaction
        message_repository.add_reaction(
            message_id=1234567890,
            emoji="👍",
            user_id=111111111,
            user_name="Reactor",
            created_at=datetime.now(UTC),
        )

        # Remove reaction
        message_repository.remove_reaction(
            message_id=1234567890,
            emoji="👍",
            user_id=111111111,
        )

        # Verify marked as removed
        result = message_repository.db.execute(
            "SELECT is_removed FROM reactions WHERE message_id = ? AND emoji = ?",
            (1234567890, "👍"),
        ).fetchone()
        assert result["is_removed"] == 1

    def test_reaction_idempotent(self, message_repository: MessageRepository):
        """Test that adding a reaction twice doesn't create duplicates."""
        # First insert the message
        message_repository.upsert_message(
            message_id=1234567890,
            guild_id=987654321,
            guild_name="Test Guild",
            channel_id=555555555,
            channel_name="general",
            thread_id=None,
            parent_channel_id=None,
            author_id=123456789,
            author_name="TestUser",
            author_roles_snapshot="[]",
            content="Test",
            created_at=datetime.now(UTC),
            visibility_scope="public",
        )

        now = datetime.now(UTC)
        # Add same reaction twice
        message_repository.add_reaction(
            message_id=1234567890,
            emoji="👍",
            user_id=111111111,
            user_name="Reactor",
            created_at=now,
        )
        message_repository.add_reaction(
            message_id=1234567890,
            emoji="👍",
            user_id=111111111,
            user_name="Reactor",
            created_at=now,
        )

        # Should only have one reaction
        result = message_repository.db.execute(
            "SELECT COUNT(*) FROM reactions WHERE message_id = ? AND emoji = ? AND user_id = ?",
            (1234567890, "👍", 111111111),
        ).fetchone()
        assert result[0] == 1


class TestGetLatestMessageId:
    """Tests for get_latest_message_id."""

    def test_returns_none_for_empty_channel(self, message_repository: MessageRepository):
        """Test that None is returned when no messages exist."""
        result = message_repository.get_latest_message_id(999999999)
        assert result is None

    def test_returns_latest_id(self, message_repository: MessageRepository):
        """Test that the latest message ID is returned."""
        now = datetime.now(UTC)

        # Insert multiple messages (IDs not in order)
        for msg_id in [100, 200, 150]:
            message_repository.upsert_message(
                message_id=msg_id,
                guild_id=1,
                guild_name="TestGuild",
                channel_id=555,
                channel_name="general",
                thread_id=None,
                parent_channel_id=None,
                author_id=1,
                author_name="TestUser",
                author_roles_snapshot="[]",
                content="Test",
                created_at=now,
                visibility_scope="public",
            )

        # Should return highest ID
        result = message_repository.get_latest_message_id(555)
        assert result == 200


class TestMessageCount:
    """Tests for get_message_count."""

    def test_count_all_messages(self, message_repository: MessageRepository):
        """Test counting all messages."""
        now = datetime.now(UTC)

        for msg_id in range(1, 6):
            message_repository.upsert_message(
                message_id=msg_id,
                guild_id=1,
                guild_name="TestGuild",
                channel_id=555,
                channel_name="general",
                thread_id=None,
                parent_channel_id=None,
                author_id=1,
                author_name="TestUser",
                author_roles_snapshot="[]",
                content="Test",
                created_at=now,
                visibility_scope="public",
            )

        assert message_repository.get_message_count() == 5

    def test_count_excludes_deleted(self, message_repository: MessageRepository):
        """Test that deleted messages are not counted."""
        now = datetime.now(UTC)

        for msg_id in range(1, 6):
            message_repository.upsert_message(
                message_id=msg_id,
                guild_id=1,
                guild_name="TestGuild",
                channel_id=555,
                channel_name="general",
                thread_id=None,
                parent_channel_id=None,
                author_id=1,
                author_name="TestUser",
                author_roles_snapshot="[]",
                content="Test",
                created_at=now,
                visibility_scope="public",
            )

        # Delete 2 messages
        message_repository.soft_delete_message(1)
        message_repository.soft_delete_message(2)

        assert message_repository.get_message_count() == 3

    def test_count_by_channel(self, message_repository: MessageRepository):
        """Test counting messages by channel."""
        now = datetime.now(UTC)

        # 3 messages in channel 555
        for msg_id in range(1, 4):
            message_repository.upsert_message(
                message_id=msg_id,
                guild_id=1,
                guild_name="TestGuild",
                channel_id=555,
                channel_name="general",
                thread_id=None,
                parent_channel_id=None,
                author_id=1,
                author_name="TestUser",
                author_roles_snapshot="[]",
                content="Test",
                created_at=now,
                visibility_scope="public",
            )

        # 2 messages in channel 666
        for msg_id in range(10, 12):
            message_repository.upsert_message(
                message_id=msg_id,
                guild_id=1,
                guild_name="TestGuild",
                channel_id=666,
                channel_name="other",
                thread_id=None,
                parent_channel_id=None,
                author_id=1,
                author_name="TestUser",
                author_roles_snapshot="[]",
                content="Test",
                created_at=now,
                visibility_scope="public",
            )

        assert message_repository.get_message_count(channel_id=555) == 3
        assert message_repository.get_message_count(channel_id=666) == 2


class TestMessageQueries:
    """Tests for message query methods."""

    def _insert_test_messages(
        self, repository: MessageRepository, now: datetime
    ) -> None:
        """Helper to insert test messages for query tests."""
        # User 1 in channel 100: 3 messages
        for i in range(3):
            repository.upsert_message(
                message_id=100 + i,
                guild_id=1,
                guild_name="TestGuild",
                channel_id=100,
                channel_name="general",
                thread_id=None,
                parent_channel_id=None,
                author_id=1,
                author_name="Alice",
                author_roles_snapshot="[]",
                content=f"Message {i} from Alice in general",
                created_at=now - timedelta(hours=i),
                visibility_scope="public",
            )
        # User 2 in channel 100: 2 messages
        for i in range(2):
            repository.upsert_message(
                message_id=200 + i,
                guild_id=1,
                guild_name="TestGuild",
                channel_id=100,
                channel_name="general",
                thread_id=None,
                parent_channel_id=None,
                author_id=2,
                author_name="Bob",
                author_roles_snapshot="[]",
                content=f"Message {i} from Bob in general",
                created_at=now - timedelta(hours=i + 3),
                visibility_scope="public",
            )
        # User 1 in channel 200: 2 messages
        for i in range(2):
            repository.upsert_message(
                message_id=300 + i,
                guild_id=1,
                guild_name="TestGuild",
                channel_id=200,
                channel_name="random",
                thread_id=None,
                parent_channel_id=None,
                author_id=1,
                author_name="Alice",
                author_roles_snapshot="[]",
                content=f"Message {i} from Alice in random",
                created_at=now - timedelta(hours=i + 5),
                visibility_scope="public",
            )

    def test_get_messages_by_channel(
        self, message_repository: MessageRepository
    ) -> None:
        """Test fetching messages by channel."""
        now = datetime.now(UTC)
        self._insert_test_messages(message_repository, now)

        messages = message_repository.get_messages_by_channel(100)
        assert len(messages) == 5  # 3 from Alice + 2 from Bob
        assert all(m["channel_id"] == 100 for m in messages)

    def test_get_messages_by_channel_with_time_filter(
        self, message_repository: MessageRepository
    ) -> None:
        """Test fetching messages by channel with time filter."""
        now = datetime.now(UTC)
        self._insert_test_messages(message_repository, now)

        # Only get messages from last 1.5 hours (excludes message at -2 hours)
        since = now - timedelta(hours=1, minutes=30)
        messages = message_repository.get_messages_by_channel(100, since=since)
        assert len(messages) == 2  # Only Alice's messages at 0 and -1 hours

    def test_get_messages_by_user(
        self, message_repository: MessageRepository
    ) -> None:
        """Test fetching messages by user."""
        now = datetime.now(UTC)
        self._insert_test_messages(message_repository, now)

        messages = message_repository.get_messages_by_user(1)
        assert len(messages) == 5  # 3 in channel 100 + 2 in channel 200
        assert all(m["author_id"] == 1 for m in messages)

    def test_get_messages_by_user_in_channel(
        self, message_repository: MessageRepository
    ) -> None:
        """Test fetching messages by user in a specific channel."""
        now = datetime.now(UTC)
        self._insert_test_messages(message_repository, now)

        messages = message_repository.get_messages_by_user_in_channel(100, 1)
        assert len(messages) == 3  # Alice's 3 messages in general
        assert all(m["channel_id"] == 100 and m["author_id"] == 1 for m in messages)

    def test_get_messages_involving_users(
        self, message_repository: MessageRepository
    ) -> None:
        """Test fetching messages involving two users."""
        now = datetime.now(UTC)
        self._insert_test_messages(message_repository, now)

        messages = message_repository.get_messages_involving_users(1, 2)
        # Should get all messages from both users
        assert len(messages) == 7  # 5 from Alice + 2 from Bob
        author_ids = {m["author_id"] for m in messages}
        assert author_ids == {1, 2}

    def test_get_messages_for_context(
        self, message_repository: MessageRepository
    ) -> None:
        """Test fetching messages for LLM context."""
        now = datetime.now(UTC)
        self._insert_test_messages(message_repository, now)

        # Get all messages since 10 hours ago
        since = now - timedelta(hours=10)
        messages = message_repository.get_messages_for_context(since)
        assert len(messages) == 7

    def test_get_messages_for_context_filtered_by_channels(
        self, message_repository: MessageRepository
    ) -> None:
        """Test fetching messages for context filtered by channels."""
        now = datetime.now(UTC)
        self._insert_test_messages(message_repository, now)

        since = now - timedelta(hours=10)
        messages = message_repository.get_messages_for_context(
            since, channel_ids=[100]
        )
        assert len(messages) == 5
        assert all(m["channel_id"] == 100 for m in messages)

    def test_get_messages_for_context_filtered_by_users(
        self, message_repository: MessageRepository
    ) -> None:
        """Test fetching messages for context filtered by users."""
        now = datetime.now(UTC)
        self._insert_test_messages(message_repository, now)

        since = now - timedelta(hours=10)
        messages = message_repository.get_messages_for_context(
            since, user_ids=[2]
        )
        assert len(messages) == 2
        assert all(m["author_id"] == 2 for m in messages)

    def test_get_messages_respects_limit(
        self, message_repository: MessageRepository
    ) -> None:
        """Test that limit is respected in query methods."""
        now = datetime.now(UTC)
        self._insert_test_messages(message_repository, now)

        messages = message_repository.get_messages_by_channel(100, limit=2)
        assert len(messages) == 2

    def test_get_messages_ordered_by_time(
        self, message_repository: MessageRepository
    ) -> None:
        """Test that messages are ordered by created_at ascending."""
        now = datetime.now(UTC)
        self._insert_test_messages(message_repository, now)

        messages = message_repository.get_messages_by_channel(100)
        # Check messages are in chronological order
        for i in range(len(messages) - 1):
            assert messages[i]["created_at"] <= messages[i + 1]["created_at"]
