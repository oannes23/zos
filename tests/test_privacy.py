"""Tests for privacy enforcement."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from zos.layer.privacy import PrivacyEnforcer


# --- PrivacyEnforcer Tests ---


class TestPrivacyEnforcer:
    """Tests for the PrivacyEnforcer class."""

    def test_filter_messages_excludes_dm_from_public(self):
        """Test that DM messages are excluded from public outputs."""
        messages = [
            {"message_id": 1, "content": "Public message", "visibility_scope": "public"},
            {"message_id": 2, "content": "DM message", "visibility_scope": "dm"},
            {"message_id": 3, "content": "Another public", "visibility_scope": "public"},
        ]

        filtered = PrivacyEnforcer.filter_messages_for_scope(messages, "public")

        assert len(filtered) == 2
        assert all(m["visibility_scope"] == "public" for m in filtered)
        assert not any(m["message_id"] == 2 for m in filtered)

    def test_filter_messages_includes_all_for_dm_output(self):
        """Test that all messages are included for DM outputs."""
        messages = [
            {"message_id": 1, "content": "Public message", "visibility_scope": "public"},
            {"message_id": 2, "content": "DM message", "visibility_scope": "dm"},
            {"message_id": 3, "content": "Another public", "visibility_scope": "public"},
        ]

        filtered = PrivacyEnforcer.filter_messages_for_scope(messages, "dm")

        assert len(filtered) == 3

    def test_get_max_scope_returns_dm_when_dm_present(self):
        """Test that max scope returns 'dm' when any DM message is present."""
        messages = [
            {"message_id": 1, "visibility_scope": "public"},
            {"message_id": 2, "visibility_scope": "dm"},
            {"message_id": 3, "visibility_scope": "public"},
        ]

        max_scope = PrivacyEnforcer.get_max_scope(messages)

        assert max_scope == "dm"

    def test_get_max_scope_returns_public_when_no_dm(self):
        """Test that max scope returns 'public' when no DM messages."""
        messages = [
            {"message_id": 1, "visibility_scope": "public"},
            {"message_id": 2, "visibility_scope": "public"},
        ]

        max_scope = PrivacyEnforcer.get_max_scope(messages)

        assert max_scope == "public"

    def test_get_max_scope_empty_messages(self):
        """Test that max scope returns 'public' for empty message list."""
        max_scope = PrivacyEnforcer.get_max_scope([])

        assert max_scope == "public"

    def test_can_include_in_output_public_to_public(self):
        """Test that public content can be included in public output."""
        assert PrivacyEnforcer.can_include_in_output("public", "public") is True

    def test_can_include_in_output_dm_to_public(self):
        """Test that DM content cannot be included in public output."""
        assert PrivacyEnforcer.can_include_in_output("dm", "public") is False

    def test_can_include_in_output_dm_to_dm(self):
        """Test that DM content can be included in DM output."""
        assert PrivacyEnforcer.can_include_in_output("dm", "dm") is True

    def test_can_include_in_output_public_to_dm(self):
        """Test that public content can be included in DM output."""
        assert PrivacyEnforcer.can_include_in_output("public", "dm") is True


class TestFilterInsightsForScope:
    """Tests for insight filtering by scope."""

    def test_filter_insights_excludes_dm_from_public(self):
        """Test that DM-derived insights are excluded from public outputs."""
        insights = [
            {"insight_id": "1", "summary": "Public insight", "sources_scope_max": "public"},
            {"insight_id": "2", "summary": "DM insight", "sources_scope_max": "dm"},
            {"insight_id": "3", "summary": "Another public", "sources_scope_max": "public"},
        ]

        filtered = PrivacyEnforcer.filter_insights_for_scope(insights, "public")

        assert len(filtered) == 2
        assert all(i["sources_scope_max"] == "public" for i in filtered)

    def test_filter_insights_includes_all_for_dm(self):
        """Test that all insights are included for DM outputs."""
        insights = [
            {"insight_id": "1", "summary": "Public insight", "sources_scope_max": "public"},
            {"insight_id": "2", "summary": "DM insight", "sources_scope_max": "dm"},
        ]

        filtered = PrivacyEnforcer.filter_insights_for_scope(insights, "dm")

        assert len(filtered) == 2

    def test_filter_insights_handles_missing_scope(self):
        """Test that insights without sources_scope_max default to public."""
        insights = [
            {"insight_id": "1", "summary": "No scope field"},
            {"insight_id": "2", "summary": "DM insight", "sources_scope_max": "dm"},
        ]

        filtered = PrivacyEnforcer.filter_insights_for_scope(insights, "public")

        # First insight should pass (defaults to public)
        # Second insight should be filtered out
        assert len(filtered) == 1
        assert filtered[0]["insight_id"] == "1"


class TestRedactDMContent:
    """Tests for DM content redaction."""

    def test_redact_dm_content_basic(self):
        """Test basic DM content redaction."""
        text = "User said [DM] something private"

        redacted = PrivacyEnforcer.redact_dm_content(text)

        assert "[DM]" not in redacted
        assert "[DM content redacted]" in redacted

    def test_redact_dm_content_case_insensitive(self):
        """Test that redaction is case insensitive."""
        text = "User mentioned in dm that they like cats"

        redacted = PrivacyEnforcer.redact_dm_content(text)

        assert "in dm" not in redacted.lower() or "[DM content redacted]" in redacted

    def test_redact_dm_content_multiple_lines(self):
        """Test redaction across multiple lines."""
        text = """First line is public
Second line mentions [DM] private content
Third line is public again
Fourth mentions via DM some secret"""

        redacted = PrivacyEnforcer.redact_dm_content(text)

        lines = redacted.split("\n")
        assert lines[0] == "First line is public"
        assert "[DM content redacted]" in lines[1]
        assert lines[2] == "Third line is public again"
        assert "[DM content redacted]" in lines[3]

    def test_redact_dm_content_no_dm_unchanged(self):
        """Test that text without DM indicators is unchanged."""
        text = "This is a completely public message with no private content."

        redacted = PrivacyEnforcer.redact_dm_content(text)

        assert redacted == text

    def test_redact_dm_content_private_message_pattern(self):
        """Test redaction of 'private message' pattern."""
        text = "In a private message, they said hello"

        redacted = PrivacyEnforcer.redact_dm_content(text)

        assert "private message" not in redacted.lower()

    def test_redact_dm_content_custom_replacement(self):
        """Test custom replacement text."""
        text = "User said [DM] something"

        redacted = PrivacyEnforcer.redact_dm_content(text, replacement="[HIDDEN]")

        assert "[HIDDEN]" in redacted


class TestValidateOutputPrivacy:
    """Tests for output privacy validation."""

    def test_validate_public_sources_to_public_output(self):
        """Test validation with public sources to public output."""
        content = "Some content"
        sources = [
            {"visibility_scope": "public"},
            {"visibility_scope": "public"},
        ]

        safe_content, scope = PrivacyEnforcer.validate_output_privacy(
            content, sources, "public"
        )

        assert safe_content == content
        assert scope == "public"

    def test_validate_dm_sources_to_public_output_redacts(self):
        """Test that DM sources to public output triggers redaction."""
        content = "This mentions [DM] private content"
        sources = [
            {"visibility_scope": "public"},
            {"visibility_scope": "dm"},
        ]

        safe_content, scope = PrivacyEnforcer.validate_output_privacy(
            content, sources, "public"
        )

        assert scope == "dm"
        # Content should be redacted if it contains DM indicators
        if "[DM]" in content:
            assert "[DM content redacted]" in safe_content

    def test_validate_dm_sources_to_dm_output(self):
        """Test that DM sources to DM output is allowed."""
        content = "This mentions [DM] private content"
        sources = [{"visibility_scope": "dm"}]

        safe_content, scope = PrivacyEnforcer.validate_output_privacy(
            content, sources, "dm"
        )

        assert safe_content == content
        assert scope == "dm"

    def test_validate_insight_sources_scope_max(self):
        """Test that insight sources_scope_max is checked."""
        content = "Summary content"
        sources = [
            {"sources_scope_max": "dm"},  # Insight with DM scope
        ]

        safe_content, scope = PrivacyEnforcer.validate_output_privacy(
            content, sources, "public"
        )

        assert scope == "dm"


# --- Privacy in Conversation Tests ---


class TestPrivacyInConversation:
    """Tests for privacy enforcement in conversation context."""

    @pytest.fixture
    def test_db(self, temp_dir):
        """Create a test database."""
        from zos.config import DatabaseConfig
        from zos.db import Database

        config = DatabaseConfig(path=temp_dir / "test.db")
        db = Database(config)
        db.initialize()
        yield db
        db.close()

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_public_response_excludes_dm_insights(self, test_db):
        """Test that public conversation responses exclude DM-derived insights."""
        from zos.config import ConversationConfig, ResponseConfig, TriggerConfig
        from zos.conversation.responder import Responder
        from zos.conversation.triggers import TriggerResult, TriggerType
        from zos.discord.repository import MessageRepository
        from zos.insights.repository import InsightRepository
        from zos.topics.topic_key import TopicKey

        # Create repositories
        message_repo = MessageRepository(test_db)
        insight_repo = InsightRepository(test_db)

        # Store insights with different scopes
        insight_repo.store(
            topic_key=TopicKey.channel(123456),
            summary="Public insight about the channel",
            sources_scope_max="public",
        )
        insight_repo.store(
            topic_key=TopicKey.channel(123456),
            summary="DM-derived insight",
            sources_scope_max="dm",
        )

        # Create responder
        config = ConversationConfig(
            enabled=True,
            triggers=TriggerConfig(),
            response=ResponseConfig(include_insights=True),
        )

        responder = Responder(
            config=config,
            db=test_db,
            message_repo=message_repo,
            insight_repo=insight_repo,
            llm_client=MagicMock(),
        )

        # Fetch insights for a public conversation
        insights = responder._fetch_relevant_insights(
            channel_id=123456,
            user_id=99999,
            is_dm=False,  # Public conversation
        )

        # Only public insights should be included
        assert len(insights) == 1
        assert insights[0]["sources_scope_max"] == "public"

    def test_dm_response_includes_all_insights(self, test_db):
        """Test that DM conversation responses include all relevant insights."""
        from zos.config import ConversationConfig, ResponseConfig, TriggerConfig
        from zos.conversation.responder import Responder
        from zos.discord.repository import MessageRepository
        from zos.insights.repository import InsightRepository
        from zos.topics.topic_key import TopicKey

        # Create repositories
        message_repo = MessageRepository(test_db)
        insight_repo = InsightRepository(test_db)

        # Store insights with different scopes
        insight_repo.store(
            topic_key=TopicKey.user(99999),
            summary="Public insight about user",
            sources_scope_max="public",
        )
        insight_repo.store(
            topic_key=TopicKey.user(99999),
            summary="DM-derived insight about user",
            sources_scope_max="dm",
        )

        # Create responder
        config = ConversationConfig(
            enabled=True,
            triggers=TriggerConfig(),
            response=ResponseConfig(include_insights=True),
        )

        responder = Responder(
            config=config,
            db=test_db,
            message_repo=message_repo,
            insight_repo=insight_repo,
            llm_client=MagicMock(),
        )

        # Fetch insights for a DM conversation
        insights = responder._fetch_relevant_insights(
            channel_id=88888,  # DM channel
            user_id=99999,
            is_dm=True,  # DM conversation
        )

        # Both insights should be included
        assert len(insights) == 2


# --- Privacy Pattern Detection Tests ---


class TestPrivacyPatternDetection:
    """Tests for DM indicator pattern detection."""

    @pytest.mark.parametrize(
        "text,should_redact",
        [
            ("Hello [DM] world", True),
            ("In a private message, user said", True),
            ("via DM they mentioned", True),
            ("[private] content here", True),
            ("Just a normal message", False),
            ("The DMV is closed", False),  # False positive check
            ("Random content", False),
        ],
    )
    def test_dm_pattern_detection(self, text: str, should_redact: bool):
        """Test that DM patterns are correctly detected."""
        redacted = PrivacyEnforcer.redact_dm_content(text)

        if should_redact:
            assert redacted != text, f"Expected redaction for: {text}"
        else:
            assert redacted == text, f"Unexpected redaction for: {text}"
