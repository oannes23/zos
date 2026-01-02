"""Privacy scope enforcement for layer execution.

Ensures that DM content is not leaked to public outputs and that
visibility scopes are properly enforced.
"""

from __future__ import annotations

from typing import Any

from zos.logging import get_logger

logger = get_logger("layer.privacy")


class PrivacyEnforcer:
    """Enforces privacy rules for context assembly and outputs.

    Privacy rules:
    - DM messages (visibility_scope='dm') should not appear in public outputs
    - Derived insights from DMs should be tagged appropriately
    - Context assembly respects scope boundaries
    """

    @staticmethod
    def filter_messages_for_scope(
        messages: list[dict[str, Any]],
        output_scope: str,
    ) -> list[dict[str, Any]]:
        """Filter messages based on the intended output scope.

        Args:
            messages: List of message dicts from repository.
            output_scope: Target scope for the output ("public" or "dm").

        Returns:
            Filtered list of messages safe for the output scope.
        """
        if output_scope == "dm":
            # DM outputs can include all messages
            return messages

        # Public outputs exclude DM content
        filtered = [
            m for m in messages if m.get("visibility_scope") != "dm"
        ]

        if len(filtered) < len(messages):
            excluded = len(messages) - len(filtered)
            logger.debug(
                f"Privacy filter: excluded {excluded} DM messages from public output"
            )

        return filtered

    @staticmethod
    def get_max_scope(messages: list[dict[str, Any]]) -> str:
        """Determine the maximum privacy scope from a set of messages.

        Used to tag derived insights with appropriate scope.

        Args:
            messages: List of message dicts.

        Returns:
            "dm" if any DM messages present, otherwise "public".
        """
        for m in messages:
            if m.get("visibility_scope") == "dm":
                return "dm"
        return "public"

    @staticmethod
    def can_include_in_output(
        content_scope: str,
        output_scope: str,
    ) -> bool:
        """Check if content of a given scope can be included in an output.

        Args:
            content_scope: Scope of the content ("public" or "dm").
            output_scope: Scope of the intended output.

        Returns:
            True if inclusion is allowed.
        """
        if output_scope == "dm":
            # DM outputs can include anything
            return True

        # Public outputs cannot include DM content
        return content_scope != "dm"

    @staticmethod
    def redact_dm_content(
        text: str,
        replacement: str = "[DM content redacted]",  # noqa: ARG004
    ) -> str:
        """Redact DM-specific content from text.

        This is a placeholder for more sophisticated redaction.
        Full implementation will be in Phase 12 (DM Privacy).

        Args:
            text: Text that may contain DM references.
            replacement: Replacement text for redacted content.

        Returns:
            Text with DM content redacted.
        """
        # Phase 12 will implement actual redaction logic
        # For now, return text unchanged
        return text
