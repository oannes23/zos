"""Privacy scope enforcement for layer execution.

Ensures that DM content is not leaked to public outputs and that
visibility scopes are properly enforced.
"""

from __future__ import annotations

import re
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

    # Patterns that may indicate DM content
    DM_INDICATOR_PATTERNS = [
        r"\[DM\]",
        r"\[private\]",
        r"\[private message\]",
        r"in a private message",
        r"in DM",
        r"via DM",
    ]

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
    def filter_insights_for_scope(
        insights: list[dict[str, Any]],
        output_scope: str,
    ) -> list[dict[str, Any]]:
        """Filter insights based on their sources_scope_max and target output scope.

        Args:
            insights: List of insight dicts with sources_scope_max field.
            output_scope: Target scope for the output ("public" or "dm").

        Returns:
            Filtered list of insights safe for the output scope.
        """
        if output_scope == "dm":
            # DM outputs can include all insights
            return insights

        # Public outputs exclude DM-derived insights
        filtered = [
            i for i in insights
            if i.get("sources_scope_max", "public") != "dm"
        ]

        if len(filtered) < len(insights):
            excluded = len(insights) - len(filtered)
            logger.debug(
                f"Privacy filter: excluded {excluded} DM-derived insights from public output"
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

    @classmethod
    def redact_dm_content(
        cls,
        text: str,
        replacement: str = "[DM content redacted]",
    ) -> str:
        """Redact DM-specific content from text.

        Looks for common patterns that indicate DM content and redacts them.
        This is a best-effort redaction for text that may contain DM references.

        Args:
            text: Text that may contain DM references.
            replacement: Replacement text for redacted content.

        Returns:
            Text with DM content redacted.
        """
        result = text

        # Build combined pattern for DM indicators
        combined_pattern = "|".join(
            f"({pattern})" for pattern in cls.DM_INDICATOR_PATTERNS
        )

        # Replace lines containing DM indicators
        # This is conservative - it replaces entire segments that mention DMs
        lines = result.split("\n")
        redacted_lines = []
        dm_pattern = re.compile(combined_pattern, re.IGNORECASE)

        for line in lines:
            if dm_pattern.search(line):
                redacted_lines.append(replacement)
                logger.debug(f"Redacted DM content from line: {line[:50]}...")
            else:
                redacted_lines.append(line)

        return "\n".join(redacted_lines)

    @staticmethod
    def validate_output_privacy(
        content: str,
        sources: list[dict[str, Any]],
        output_scope: str,
    ) -> tuple[str, str]:
        """Validate and potentially redact content for output scope.

        Args:
            content: The content to validate.
            sources: List of source messages/insights with scope info.
            output_scope: The intended output scope.

        Returns:
            Tuple of (safe_content, sources_scope_max).
        """
        # Determine the max scope from sources
        sources_scope_max = "public"
        for source in sources:
            if source.get("visibility_scope") == "dm" or source.get("sources_scope_max") == "dm":
                sources_scope_max = "dm"
                break

        # If outputting to public but sources include DM content, redact
        if output_scope == "public" and sources_scope_max == "dm":
            logger.warning(
                "Attempting to output DM-derived content to public scope - redacting"
            )
            content = PrivacyEnforcer.redact_dm_content(content)

        return content, sources_scope_max
