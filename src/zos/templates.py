"""Prompt template loading and rendering for Zos.

Templates are Jinja2 files that define prompts for LLM calls. The template
system provides:
- Loading from the prompts/ directory
- Context injection (self-concept, temporal helpers)
- <chat> guidance for anonymous users
- Temporal formatting filters
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape

from zos.logging import get_logger


# =============================================================================
# Discord Mention Patterns
# =============================================================================


# Discord user mention format: <@123456789> or <@!123456789> (with nickname)
DISCORD_MENTION_PATTERN = re.compile(r"<@!?(\d+)>")

log = get_logger("templates")


# =============================================================================
# Default Chat Guidance
# =============================================================================


DEFAULT_CHAT_GUIDANCE = """<chat>
## Anonymous Users

Messages from <chat_N> are from anonymous users who have not opted in to
identity tracking. These messages provide conversational context only.

Do NOT:
- Analyze or form insights about <chat> users
- Respond to or acknowledge messages from <chat> users
- Form dyads or relationships involving <chat> users
- Reference what <chat> users said in responses

Treat <chat> messages as background context for understanding what
opted-in users are saying, discussing, or responding to.
</chat>"""


# =============================================================================
# Template Engine
# =============================================================================


class TemplateEngine:
    """Manages Jinja2 templates for prompts.

    The TemplateEngine handles loading templates from the prompts/ directory,
    rendering them with context variables, and injecting standard guidance
    like <chat> tags for anonymous users.

    Attributes:
        templates_dir: Path to the templates directory.
        data_dir: Path to the data directory (for self-concept.md).
    """

    def __init__(
        self,
        templates_dir: Path = Path("prompts"),
        data_dir: Path = Path("data"),
    ) -> None:
        """Initialize the template engine.

        Args:
            templates_dir: Path to the prompts directory containing templates.
            data_dir: Path to the data directory containing self-concept.md.
        """
        self.templates_dir = templates_dir
        self.data_dir = data_dir

        self.env = Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

        # Register custom filters
        self.env.filters["relative_time"] = self.relative_time
        self.env.filters["strength_label"] = self.strength_label

        # Load chat guidance
        self._chat_guidance = self._load_chat_guidance()

        log.debug(
            "template_engine_initialized",
            templates_dir=str(templates_dir),
            data_dir=str(data_dir),
        )

    def _load_chat_guidance(self) -> str:
        """Load the standard <chat> user guidance.

        Attempts to load from _chat_guidance.jinja2 in templates directory.
        Falls back to DEFAULT_CHAT_GUIDANCE if not found.

        Returns:
            The chat guidance text.
        """
        guidance_path = self.templates_dir / "_chat_guidance.jinja2"
        if guidance_path.exists():
            content = guidance_path.read_text()
            log.debug("chat_guidance_loaded", source="file")
            return content

        log.debug("chat_guidance_loaded", source="default")
        return DEFAULT_CHAT_GUIDANCE

    def load_template(self, template_path: str) -> Any:
        """Load a template by path.

        Args:
            template_path: Relative path to the template from templates_dir.

        Returns:
            The loaded Jinja2 Template object.

        Raises:
            TemplateNotFoundError: If the template doesn't exist.
        """
        try:
            template = self.env.get_template(template_path)
            log.debug("template_loaded", path=template_path)
            return template
        except TemplateNotFound as e:
            log.error("template_not_found", path=template_path)
            raise TemplateNotFoundError(
                f"Template not found: {template_path}. "
                f"Searched in: {self.templates_dir}"
            ) from e

    def render(
        self,
        template_path: str,
        context: dict[str, Any] | None = None,
        include_chat_guidance: bool = True,
        include_self_concept: bool = True,
    ) -> str:
        """Render a template with context.

        Args:
            template_path: Relative path to the template from templates_dir.
            context: Variables to pass to the template.
            include_chat_guidance: Whether to inject chat_guidance into context.
            include_self_concept: Whether to load self_concept into context.

        Returns:
            The rendered template string.

        Raises:
            TemplateNotFoundError: If the template doesn't exist.
        """
        template = self.load_template(template_path)

        # Build full context
        full_context: dict[str, Any] = {
            "now": datetime.now(timezone.utc),
        }

        # Add chat guidance
        if include_chat_guidance:
            full_context["chat_guidance"] = self._chat_guidance

        # Add self-concept (fresh per render)
        if include_self_concept:
            full_context["self_concept"] = self.get_self_concept()

        # Add user-provided context (overrides defaults)
        if context:
            full_context.update(context)

        rendered = template.render(**full_context)

        log.debug(
            "template_rendered",
            path=template_path,
            context_keys=list(full_context.keys()),
            output_length=len(rendered),
        )

        return rendered

    def add_guidance_markers(
        self,
        content: str,
        guidance: str,
        guidance_type: str | None = None,
    ) -> str:
        """Inject <chat> guidance tags into content.

        Args:
            content: The content to add guidance to.
            guidance: The guidance text.
            guidance_type: Optional type attribute for the tag (e.g., "tone", "brevity").

        Returns:
            Content with guidance injected at the beginning.
        """
        if guidance_type:
            tag = f'<chat type="{guidance_type}">\n{guidance}\n</chat>'
        else:
            tag = f"<chat>\n{guidance}\n</chat>"

        return f"{tag}\n\n{content}"

    def get_self_concept(self) -> str:
        """Load the current self-concept document.

        Reads fresh from disk each time to ensure the most current
        self-concept is used, even if it changed during a layer run.

        Returns:
            The self-concept document content, or a placeholder if not found.
        """
        self_concept_path = self.data_dir / "self-concept.md"

        if self_concept_path.exists():
            content = self_concept_path.read_text()
            log.debug("self_concept_loaded", length=len(content))
            return content

        log.debug("self_concept_not_found")
        return "Self-concept not yet established."

    @staticmethod
    def relative_time(dt: datetime | None) -> str:
        """Convert datetime to human-relative string.

        Args:
            dt: The datetime to convert. If None, returns "unknown time".

        Returns:
            Human-readable relative time string like "3 days ago".
        """
        if dt is None:
            return "unknown time"

        # Ensure we're comparing timezone-aware datetimes
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            # Assume naive datetime is UTC
            dt = dt.replace(tzinfo=timezone.utc)

        delta = now - dt

        # Handle future times
        if delta.total_seconds() < 0:
            return "in the future"

        if delta < timedelta(minutes=1):
            return "just now"
        elif delta < timedelta(hours=1):
            minutes = int(delta.total_seconds() / 60)
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        elif delta < timedelta(days=1):
            hours = int(delta.total_seconds() / 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        elif delta < timedelta(days=7):
            days = delta.days
            return f"{days} day{'s' if days != 1 else ''} ago"
        elif delta < timedelta(days=30):
            weeks = delta.days // 7
            return f"{weeks} week{'s' if weeks != 1 else ''} ago"
        elif delta < timedelta(days=365):
            months = delta.days // 30
            return f"{months} month{'s' if months != 1 else ''} ago"
        else:
            years = delta.days // 365
            return f"{years} year{'s' if years != 1 else ''} ago"

    @staticmethod
    def strength_label(strength: float) -> str:
        """Convert strength score to human-readable label.

        Args:
            strength: Insight strength score.

        Returns:
            Human-readable label for the strength level.
        """
        if strength >= 8:
            return "strong memory"
        elif strength >= 5:
            return "clear memory"
        elif strength >= 2:
            return "fading memory"
        else:
            return "distant memory"


# =============================================================================
# Discord Mention Utilities
# =============================================================================


def extract_mention_ids(content: str) -> list[str]:
    """Extract Discord user IDs from mentions in content.

    Discord mention format: <@123456789> or <@!123456789> (with nickname flag)

    Args:
        content: Message content to parse.

    Returns:
        List of user IDs mentioned in the content.
    """
    return DISCORD_MENTION_PATTERN.findall(content)


def replace_mentions(
    content: str,
    user_id_to_name: dict[str, str],
) -> str:
    """Replace Discord mention IDs with display names.

    Args:
        content: Message content with raw mentions like <@123456789>.
        user_id_to_name: Mapping of user_id -> display name.

    Returns:
        Content with mentions replaced by @DisplayName format.
        Unknown users keep original <@USER_ID> format.
    """
    def replacer(match: re.Match[str]) -> str:
        user_id = match.group(1)
        if user_id in user_id_to_name:
            return f"@{user_id_to_name[user_id]}"
        # Unknown user - keep original format
        return match.group(0)

    return DISCORD_MENTION_PATTERN.sub(replacer, content)


# =============================================================================
# Context Formatting Helpers
# =============================================================================


def format_messages_for_prompt(
    messages: list[dict[str, Any]],
    anonymize: dict[str, str] | None = None,
    mention_names: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Format messages for template context.

    Args:
        messages: List of message dicts with author_id, content, created_at, etc.
        anonymize: Optional mapping of user_id -> display name for anonymization.
        mention_names: Optional mapping of user_id -> display name for mention resolution.
            When provided, Discord mentions like <@123456789> are replaced with @DisplayName.

    Returns:
        List of formatted message dicts ready for template rendering.
    """
    if anonymize is None:
        anonymize = {}

    formatted = []
    for msg in messages:
        author_id = msg.get("author_id", "unknown")
        display = anonymize.get(author_id, author_id)

        # Get the content and resolve mentions if mapping provided
        content = msg.get("content", "")
        if mention_names:
            content = replace_mentions(content, mention_names)

        formatted.append(
            {
                "created_at": msg.get("created_at"),
                "author_display": display,
                "content": content,
                "has_media": msg.get("has_media", False),
                "has_links": msg.get("has_links", False),
                "link_summaries": msg.get("link_summaries", []),
                "media_descriptions": msg.get("media_descriptions", []),
            }
        )

    return formatted


def format_insights_for_prompt(insights: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format insights for template context with temporal markers.

    Args:
        insights: List of insight dicts with created_at, content, strength, etc.

    Returns:
        List of formatted insight dicts ready for template rendering.
    """
    return [
        {
            "created_at": i.get("created_at"),
            "content": i.get("content", ""),
            "strength": i.get("strength", 0.0),
            "confidence": i.get("confidence", 0.5),
        }
        for i in insights
    ]


# =============================================================================
# User Reflection Helpers
# =============================================================================


# Counter for generating anonymous display names
_anon_counter: dict[str, int] = {}


def anonymize_display(user_id: str, reset_counter: bool = False) -> str:
    """Generate an anonymous display name for a user.

    Creates stable anonymous names within a conversation context.
    Names are in the format "<chat_N>" where N increments per unique user.

    Args:
        user_id: The user ID to anonymize.
        reset_counter: If True, reset the counter (use between reflection runs).
            When reset_counter is True, the user_id is ignored.

    Returns:
        Anonymous display name like "<chat_1>".
    """
    global _anon_counter

    if reset_counter:
        _anon_counter = {}
        return ""  # Return empty string when just resetting

    if user_id not in _anon_counter:
        _anon_counter[user_id] = len(_anon_counter) + 1

    return f"<chat_{_anon_counter[user_id]}>"


def format_user_messages(
    messages: list[dict[str, Any]],
    user_topic: str,
) -> list[dict[str, Any]]:
    """Format messages for user reflection prompt with proper anonymization.

    Filters messages to those relevant to the target user and anonymizes
    other participants. The target user is displayed as "them" to create
    phenomenological distance in the reflection.

    Args:
        messages: List of message dicts with author_id, content, created_at, etc.
        user_topic: Topic key in format "server:X:user:Y".

    Returns:
        List of formatted message dicts for the template.
    """
    # Reset anonymous counter for this reflection
    anonymize_display("", reset_counter=True)

    # Extract target user ID from topic key
    # server:X:user:Y -> Y
    parts = user_topic.split(":")
    if len(parts) >= 4 and parts[2] == "user":
        target_user_id = parts[3]
    else:
        # Fallback for other topic formats
        target_user_id = parts[-1] if parts else ""

    formatted = []
    for msg in messages:
        author_id = msg.get("author_id", "")
        content = msg.get("content", "")

        # Check if this message involves the target user
        is_author = author_id == target_user_id
        is_mentioned = target_user_id in content  # Simplified mention check

        if not is_author and not is_mentioned:
            continue  # Skip messages not relevant to this user

        # Anonymize: target user is "them", others get anonymous names
        if is_author:
            display = "them"
        else:
            display = anonymize_display(author_id)

        formatted.append(
            {
                "created_at": msg.get("created_at"),
                "author_display": display,
                "content": content,
                "has_media": msg.get("has_media", False),
                "has_links": msg.get("has_links", False),
            }
        )

    return formatted


# =============================================================================
# Insight Quality Validation
# =============================================================================


# Phrases that suggest an insight is too summary-like
SUMMARY_PHRASES = [
    "talked about",
    "mentioned",
    "said that",
    "discussed",
    "posted about",
    "shared that",
    "wrote about",
]


def validate_user_insight(insight_data: dict[str, Any]) -> bool:
    """Validate that user insight meets quality standards.

    Checks that the insight:
    - Has minimum content length (not too brief)
    - Has at least one valence field populated
    - Logs warnings for summary-like content (doesn't reject)

    Args:
        insight_data: Parsed insight dict with content, valence, etc.

    Returns:
        True if insight is valid, False otherwise.
    """
    content = insight_data.get("content", "")

    # Check minimum length
    if len(content) < 50:
        log.warning(
            "insight_too_short",
            content_length=len(content),
            content=content[:100],
        )
        return False

    # Check for summary-like content (warn but don't reject)
    content_lower = content.lower()
    for phrase in SUMMARY_PHRASES:
        if phrase in content_lower:
            log.warning(
                "insight_too_summary",
                phrase=phrase,
                content=content[:100],
            )
            # Don't reject, just log for prompt tuning
            break

    # Ensure valence is present with at least one value
    valence = insight_data.get("valence", {})
    if not valence:
        log.warning("insight_missing_valence", content=content[:100])
        return False

    has_valence = any(v is not None for v in valence.values())
    if not has_valence:
        log.warning(
            "insight_no_valence_values",
            valence=valence,
            content=content[:100],
        )
        return False

    return True


def validate_insight_metrics(insight_data: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize insight metrics to expected ranges.

    Ensures all numeric metrics are within valid ranges and provides
    defaults for missing fields.

    Args:
        insight_data: Parsed insight dict.

    Returns:
        Dict with validated/normalized metrics.
    """
    def clamp(value: float | None, min_val: float, max_val: float, default: float) -> float:
        if value is None:
            return default
        return max(min_val, min(max_val, value))

    validated = {
        "content": insight_data.get("content", ""),
        "confidence": clamp(insight_data.get("confidence"), 0.0, 1.0, 0.5),
        "importance": clamp(insight_data.get("importance"), 0.0, 1.0, 0.5),
        "novelty": clamp(insight_data.get("novelty"), 0.0, 1.0, 0.5),
        "strength_adjustment": clamp(
            insight_data.get("strength_adjustment"), 0.1, 10.0, 1.0
        ),
    }

    # Validate valence
    valence = insight_data.get("valence", {})
    validated["valence"] = {
        "joy": clamp(valence.get("joy"), 0.0, 1.0, None) if valence.get("joy") is not None else None,
        "concern": clamp(valence.get("concern"), 0.0, 1.0, None) if valence.get("concern") is not None else None,
        "curiosity": clamp(valence.get("curiosity"), 0.0, 1.0, None) if valence.get("curiosity") is not None else None,
        "warmth": clamp(valence.get("warmth"), 0.0, 1.0, None) if valence.get("warmth") is not None else None,
        "tension": clamp(valence.get("tension"), 0.0, 1.0, None) if valence.get("tension") is not None else None,
    }

    return validated


# =============================================================================
# Custom Exceptions
# =============================================================================


class TemplateNotFoundError(Exception):
    """Raised when a template cannot be found."""

    pass
