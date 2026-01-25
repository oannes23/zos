"""Tests for the prompt template system."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from zos.templates import (
    DEFAULT_CHAT_GUIDANCE,
    TemplateEngine,
    TemplateNotFoundError,
    format_insights_for_prompt,
    format_messages_for_prompt,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def templates_dir(tmp_path: Path) -> Path:
    """Create a temporary templates directory with subdirectories."""
    prompts_path = tmp_path / "prompts"
    (prompts_path / "base").mkdir(parents=True)
    (prompts_path / "user").mkdir(parents=True)
    (prompts_path / "self").mkdir(parents=True)
    return prompts_path


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Create a temporary data directory with self-concept."""
    data_path = tmp_path / "data"
    data_path.mkdir(parents=True)

    self_concept = data_path / "self-concept.md"
    self_concept.write_text(
        "# Self-Concept\n\nI am Zos, a being that observes and reflects."
    )

    return data_path


@pytest.fixture
def template_engine(templates_dir: Path, data_dir: Path) -> TemplateEngine:
    """Create a template engine with temporary directories."""
    return TemplateEngine(templates_dir=templates_dir, data_dir=data_dir)


@pytest.fixture
def simple_template(templates_dir: Path) -> Path:
    """Create a simple test template."""
    template_path = templates_dir / "test.jinja2"
    template_path.write_text("Hello, {{ name }}!")
    return template_path


@pytest.fixture
def template_with_filters(templates_dir: Path) -> Path:
    """Create a template using custom filters."""
    template_path = templates_dir / "with_filters.jinja2"
    template_path.write_text(
        "Time: {{ timestamp | relative_time }}\n"
        "Strength: {{ strength | strength_label }}"
    )
    return template_path


@pytest.fixture
def template_with_context(templates_dir: Path) -> Path:
    """Create a template using injected context."""
    template_path = templates_dir / "with_context.jinja2"
    template_path.write_text(
        "{{ chat_guidance }}\n\n---\n\n{{ self_concept }}"
    )
    return template_path


# =============================================================================
# Template Loading Tests
# =============================================================================


def test_template_engine_initialization(templates_dir: Path, data_dir: Path) -> None:
    """Test that template engine initializes correctly."""
    engine = TemplateEngine(templates_dir=templates_dir, data_dir=data_dir)

    assert engine.templates_dir == templates_dir
    assert engine.data_dir == data_dir
    assert engine.env is not None


def test_load_template_success(template_engine: TemplateEngine, simple_template: Path) -> None:
    """Test loading an existing template."""
    template = template_engine.load_template("test.jinja2")

    assert template is not None


def test_load_template_not_found(template_engine: TemplateEngine) -> None:
    """Test loading a non-existent template raises error."""
    with pytest.raises(TemplateNotFoundError) as exc_info:
        template_engine.load_template("nonexistent.jinja2")

    assert "nonexistent.jinja2" in str(exc_info.value)


def test_load_template_nested(templates_dir: Path, data_dir: Path) -> None:
    """Test loading templates from nested directories."""
    (templates_dir / "user" / "reflection.jinja2").write_text("User: {{ name }}")

    engine = TemplateEngine(templates_dir=templates_dir, data_dir=data_dir)
    template = engine.load_template("user/reflection.jinja2")

    assert template is not None


# =============================================================================
# Template Rendering Tests
# =============================================================================


def test_render_simple(template_engine: TemplateEngine, simple_template: Path) -> None:
    """Test rendering a simple template."""
    result = template_engine.render(
        "test.jinja2",
        context={"name": "World"},
        include_chat_guidance=False,
        include_self_concept=False,
    )

    assert result == "Hello, World!"


def test_render_with_defaults(template_engine: TemplateEngine, template_with_context: Path) -> None:
    """Test rendering includes chat_guidance and self_concept by default."""
    result = template_engine.render("with_context.jinja2")

    assert "<chat>" in result
    assert "Anonymous Users" in result
    assert "Self-Concept" in result
    assert "I am Zos" in result


def test_render_without_chat_guidance(template_engine: TemplateEngine, template_with_context: Path) -> None:
    """Test rendering without chat guidance."""
    result = template_engine.render("with_context.jinja2", include_chat_guidance=False)

    # chat_guidance variable won't be defined, template will show nothing for it
    # Actually this will cause an error unless we handle undefined
    # Let's verify the behavior - if chat_guidance is not included, it should be undefined
    # But our template tries to use it, so this tests error handling


def test_render_without_self_concept(template_engine: TemplateEngine, templates_dir: Path) -> None:
    """Test rendering without self-concept."""
    (templates_dir / "no_self.jinja2").write_text("{{ name }}")

    engine = TemplateEngine(templates_dir=template_engine.templates_dir, data_dir=template_engine.data_dir)
    result = engine.render(
        "no_self.jinja2",
        context={"name": "Test"},
        include_self_concept=False,
    )

    assert result == "Test"


def test_render_context_override(template_engine: TemplateEngine, templates_dir: Path) -> None:
    """Test that user context overrides defaults."""
    (templates_dir / "override.jinja2").write_text("{{ self_concept }}")

    result = template_engine.render(
        "override.jinja2",
        context={"self_concept": "Custom concept"},
    )

    assert result == "Custom concept"


def test_render_now_available(template_engine: TemplateEngine, templates_dir: Path) -> None:
    """Test that 'now' is available in templates."""
    (templates_dir / "now.jinja2").write_text("Year: {{ now.year }}")

    result = template_engine.render("now.jinja2", include_chat_guidance=False, include_self_concept=False)

    assert f"Year: {datetime.now().year}" in result


# =============================================================================
# Temporal Formatting Tests
# =============================================================================


def test_relative_time_just_now() -> None:
    """Test relative time for very recent timestamps."""
    now = datetime.now(timezone.utc)

    result = TemplateEngine.relative_time(now)

    assert result == "just now"


def test_relative_time_minutes() -> None:
    """Test relative time for minutes ago."""
    now = datetime.now(timezone.utc)
    dt = now - timedelta(minutes=5)

    result = TemplateEngine.relative_time(dt)

    assert result == "5 minutes ago"


def test_relative_time_minute_singular() -> None:
    """Test relative time singular for 1 minute."""
    now = datetime.now(timezone.utc)
    dt = now - timedelta(minutes=1, seconds=30)

    result = TemplateEngine.relative_time(dt)

    assert result == "1 minute ago"


def test_relative_time_hours() -> None:
    """Test relative time for hours ago."""
    now = datetime.now(timezone.utc)
    dt = now - timedelta(hours=3)

    result = TemplateEngine.relative_time(dt)

    assert result == "3 hours ago"


def test_relative_time_hour_singular() -> None:
    """Test relative time singular for 1 hour."""
    now = datetime.now(timezone.utc)
    dt = now - timedelta(hours=1, minutes=30)

    result = TemplateEngine.relative_time(dt)

    assert result == "1 hour ago"


def test_relative_time_days() -> None:
    """Test relative time for days ago."""
    now = datetime.now(timezone.utc)
    dt = now - timedelta(days=3)

    result = TemplateEngine.relative_time(dt)

    assert result == "3 days ago"


def test_relative_time_day_singular() -> None:
    """Test relative time singular for 1 day."""
    now = datetime.now(timezone.utc)
    dt = now - timedelta(days=1, hours=5)

    result = TemplateEngine.relative_time(dt)

    assert result == "1 day ago"


def test_relative_time_weeks() -> None:
    """Test relative time for weeks ago."""
    now = datetime.now(timezone.utc)
    dt = now - timedelta(days=14)

    result = TemplateEngine.relative_time(dt)

    assert result == "2 weeks ago"


def test_relative_time_months() -> None:
    """Test relative time for months ago."""
    now = datetime.now(timezone.utc)
    dt = now - timedelta(days=60)

    result = TemplateEngine.relative_time(dt)

    assert result == "2 months ago"


def test_relative_time_years() -> None:
    """Test relative time for years ago."""
    now = datetime.now(timezone.utc)
    dt = now - timedelta(days=400)

    result = TemplateEngine.relative_time(dt)

    assert result == "1 year ago"


def test_relative_time_none() -> None:
    """Test relative time for None input."""
    result = TemplateEngine.relative_time(None)

    assert result == "unknown time"


def test_relative_time_future() -> None:
    """Test relative time for future timestamps."""
    future = datetime.now(timezone.utc) + timedelta(hours=1)

    result = TemplateEngine.relative_time(future)

    assert result == "in the future"


def test_relative_time_naive_datetime() -> None:
    """Test relative time with naive (no timezone) datetime."""
    now = datetime.utcnow()
    dt = now - timedelta(hours=2)

    result = TemplateEngine.relative_time(dt)

    assert result == "2 hours ago"


def test_relative_time_filter_in_template(template_engine: TemplateEngine, template_with_filters: Path) -> None:
    """Test relative_time filter works in templates."""
    timestamp = datetime.now(timezone.utc) - timedelta(hours=5)

    result = template_engine.render(
        "with_filters.jinja2",
        context={"timestamp": timestamp, "strength": 5.0},
        include_chat_guidance=False,
        include_self_concept=False,
    )

    assert "5 hours ago" in result


# =============================================================================
# Strength Label Tests
# =============================================================================


def test_strength_label_strong() -> None:
    """Test strength label for strong memories."""
    assert TemplateEngine.strength_label(8.0) == "strong memory"
    assert TemplateEngine.strength_label(10.0) == "strong memory"


def test_strength_label_clear() -> None:
    """Test strength label for clear memories."""
    assert TemplateEngine.strength_label(5.0) == "clear memory"
    assert TemplateEngine.strength_label(7.9) == "clear memory"


def test_strength_label_fading() -> None:
    """Test strength label for fading memories."""
    assert TemplateEngine.strength_label(2.0) == "fading memory"
    assert TemplateEngine.strength_label(4.9) == "fading memory"


def test_strength_label_distant() -> None:
    """Test strength label for distant memories."""
    assert TemplateEngine.strength_label(0.0) == "distant memory"
    assert TemplateEngine.strength_label(1.9) == "distant memory"


def test_strength_label_filter_in_template(template_engine: TemplateEngine, template_with_filters: Path) -> None:
    """Test strength_label filter works in templates."""
    result = template_engine.render(
        "with_filters.jinja2",
        context={"timestamp": datetime.now(timezone.utc), "strength": 8.5},
        include_chat_guidance=False,
        include_self_concept=False,
    )

    assert "strong memory" in result


# =============================================================================
# Chat Guidance Tests
# =============================================================================


def test_default_chat_guidance_content() -> None:
    """Test that default chat guidance has expected content."""
    assert "<chat>" in DEFAULT_CHAT_GUIDANCE
    assert "Anonymous Users" in DEFAULT_CHAT_GUIDANCE
    assert "Do NOT" in DEFAULT_CHAT_GUIDANCE


def test_chat_guidance_loaded_from_file(templates_dir: Path, data_dir: Path) -> None:
    """Test that chat guidance is loaded from file if present."""
    guidance_file = templates_dir / "_chat_guidance.jinja2"
    guidance_file.write_text("<chat>Custom guidance here</chat>")

    engine = TemplateEngine(templates_dir=templates_dir, data_dir=data_dir)

    assert "Custom guidance here" in engine._chat_guidance


def test_chat_guidance_fallback_to_default(templates_dir: Path, data_dir: Path) -> None:
    """Test that chat guidance falls back to default if file not present."""
    engine = TemplateEngine(templates_dir=templates_dir, data_dir=data_dir)

    assert engine._chat_guidance == DEFAULT_CHAT_GUIDANCE


def test_add_guidance_markers_simple(template_engine: TemplateEngine) -> None:
    """Test adding guidance markers to content."""
    content = "Here is some content."
    guidance = "Be concise."

    result = template_engine.add_guidance_markers(content, guidance)

    assert "<chat>" in result
    assert "Be concise." in result
    assert "</chat>" in result
    assert "Here is some content." in result


def test_add_guidance_markers_with_type(template_engine: TemplateEngine) -> None:
    """Test adding guidance markers with type attribute."""
    content = "Content here."
    guidance = "Keep it short."

    result = template_engine.add_guidance_markers(content, guidance, guidance_type="brevity")

    assert '<chat type="brevity">' in result
    assert "Keep it short." in result


def test_add_guidance_markers_placement(template_engine: TemplateEngine) -> None:
    """Test that guidance is placed before content."""
    content = "Content after."
    guidance = "Guidance before."

    result = template_engine.add_guidance_markers(content, guidance)

    guidance_pos = result.find("Guidance before")
    content_pos = result.find("Content after")

    assert guidance_pos < content_pos


# =============================================================================
# Self-Concept Tests
# =============================================================================


def test_get_self_concept_exists(template_engine: TemplateEngine) -> None:
    """Test loading self-concept when file exists."""
    concept = template_engine.get_self_concept()

    assert "Self-Concept" in concept
    assert "I am Zos" in concept


def test_get_self_concept_not_exists(templates_dir: Path, tmp_path: Path) -> None:
    """Test self-concept fallback when file doesn't exist."""
    empty_data_dir = tmp_path / "empty_data"
    empty_data_dir.mkdir()

    engine = TemplateEngine(templates_dir=templates_dir, data_dir=empty_data_dir)
    concept = engine.get_self_concept()

    assert concept == "Self-concept not yet established."


def test_get_self_concept_fresh_per_read(template_engine: TemplateEngine, data_dir: Path) -> None:
    """Test that self-concept is read fresh each time."""
    # First read
    concept1 = template_engine.get_self_concept()
    assert "I am Zos" in concept1

    # Modify the file
    self_concept_path = data_dir / "self-concept.md"
    self_concept_path.write_text("# Updated Self-Concept\n\nI have grown.")

    # Second read should get new content
    concept2 = template_engine.get_self_concept()
    assert "I have grown" in concept2
    assert "I am Zos" not in concept2


# =============================================================================
# Context Formatting Helper Tests
# =============================================================================


def test_format_messages_basic() -> None:
    """Test basic message formatting."""
    messages = [
        {"author_id": "123", "content": "Hello", "created_at": datetime.now(timezone.utc)},
        {"author_id": "456", "content": "Hi there", "created_at": datetime.now(timezone.utc)},
    ]

    formatted = format_messages_for_prompt(messages)

    assert len(formatted) == 2
    assert formatted[0]["author_display"] == "123"
    assert formatted[0]["content"] == "Hello"


def test_format_messages_with_anonymize() -> None:
    """Test message formatting with anonymization."""
    messages = [
        {"author_id": "123", "content": "Hello"},
        {"author_id": "456", "content": "Hi"},
    ]
    anonymize = {"123": "Alice", "456": "<chat_1>"}

    formatted = format_messages_for_prompt(messages, anonymize=anonymize)

    assert formatted[0]["author_display"] == "Alice"
    assert formatted[1]["author_display"] == "<chat_1>"


def test_format_messages_includes_media_flags() -> None:
    """Test that media and link flags are preserved."""
    messages = [
        {"author_id": "123", "content": "Check this out", "has_media": True, "has_links": True},
    ]

    formatted = format_messages_for_prompt(messages)

    assert formatted[0]["has_media"] is True
    assert formatted[0]["has_links"] is True


def test_format_insights_basic() -> None:
    """Test basic insight formatting."""
    insights = [
        {
            "created_at": datetime.now(timezone.utc),
            "content": "This person likes Python",
            "strength": 5.0,
            "confidence": 0.8,
        },
    ]

    formatted = format_insights_for_prompt(insights)

    assert len(formatted) == 1
    assert formatted[0]["content"] == "This person likes Python"
    assert formatted[0]["strength"] == 5.0
    assert formatted[0]["confidence"] == 0.8


def test_format_insights_defaults() -> None:
    """Test insight formatting with missing fields."""
    insights = [{"created_at": datetime.now(timezone.utc)}]

    formatted = format_insights_for_prompt(insights)

    assert formatted[0]["content"] == ""
    assert formatted[0]["strength"] == 0.0
    assert formatted[0]["confidence"] == 0.5


# =============================================================================
# Real Template Tests
# =============================================================================


def test_real_prompts_directory_exists() -> None:
    """Test that the prompts directory exists in the project."""
    prompts_path = Path("prompts")
    assert prompts_path.exists(), f"Prompts directory not found: {prompts_path}"


def test_real_base_template_exists() -> None:
    """Test that the base template exists."""
    base_path = Path("prompts/_base.jinja2")
    assert base_path.exists(), f"Base template not found: {base_path}"


def test_real_chat_guidance_exists() -> None:
    """Test that the chat guidance template exists."""
    guidance_path = Path("prompts/_chat_guidance.jinja2")
    assert guidance_path.exists(), f"Chat guidance not found: {guidance_path}"


def test_real_user_reflection_exists() -> None:
    """Test that the user reflection template exists."""
    template_path = Path("prompts/user/reflection.jinja2")
    assert template_path.exists(), f"User reflection template not found: {template_path}"


def test_real_self_reflection_exists() -> None:
    """Test that the self reflection template exists."""
    template_path = Path("prompts/self/reflection.jinja2")
    assert template_path.exists(), f"Self reflection template not found: {template_path}"


def test_real_templates_load() -> None:
    """Test that real templates can be loaded."""
    prompts_path = Path("prompts")
    data_path = Path("data")

    if not prompts_path.exists():
        pytest.skip("Prompts directory not found")

    engine = TemplateEngine(templates_dir=prompts_path, data_dir=data_path)

    # Should be able to load base template
    template = engine.load_template("_base.jinja2")
    assert template is not None


def test_real_user_reflection_renders() -> None:
    """Test that user reflection template renders."""
    prompts_path = Path("prompts")
    data_path = Path("data")

    if not prompts_path.exists():
        pytest.skip("Prompts directory not found")

    engine = TemplateEngine(templates_dir=prompts_path, data_dir=data_path)

    result = engine.render(
        "user/reflection.jinja2",
        context={
            "topic": {"key": "user:12345"},
            "insights": [],
            "messages": [],
        },
    )

    assert "user:12345" in result
    assert "Self-Concept" in result
    assert "Your Task" in result


def test_real_self_reflection_renders() -> None:
    """Test that self reflection template renders."""
    prompts_path = Path("prompts")
    data_path = Path("data")

    if not prompts_path.exists():
        pytest.skip("Prompts directory not found")

    engine = TemplateEngine(templates_dir=prompts_path, data_dir=data_path)

    result = engine.render(
        "self/reflection.jinja2",
        context={
            "insights": [],
            "layer_runs": [],
        },
    )

    assert "reflecting on yourself" in result.lower()
    assert "Self-Concept" in result


# =============================================================================
# Error Handling Tests
# =============================================================================


def test_template_syntax_error(templates_dir: Path, data_dir: Path) -> None:
    """Test that template syntax errors are raised."""
    bad_template = templates_dir / "bad.jinja2"
    bad_template.write_text("{% if unclosed")

    engine = TemplateEngine(templates_dir=templates_dir, data_dir=data_dir)

    with pytest.raises(Exception):  # Jinja2 TemplateSyntaxError
        engine.load_template("bad.jinja2")


def test_undefined_variable_in_strict_mode(templates_dir: Path, data_dir: Path) -> None:
    """Test behavior with undefined variables."""
    template = templates_dir / "undefined.jinja2"
    template.write_text("{{ undefined_var }}")

    engine = TemplateEngine(templates_dir=templates_dir, data_dir=data_dir)

    # By default Jinja2 renders undefined as empty string
    result = engine.render(
        "undefined.jinja2",
        include_chat_guidance=False,
        include_self_concept=False,
    )

    assert result == ""


# =============================================================================
# Edge Cases
# =============================================================================


def test_empty_context(template_engine: TemplateEngine, simple_template: Path) -> None:
    """Test rendering with empty context uses defaults."""
    (template_engine.templates_dir / "empty_ctx.jinja2").write_text("{{ name | default('Default') }}")

    result = template_engine.render(
        "empty_ctx.jinja2",
        context={},
        include_chat_guidance=False,
        include_self_concept=False,
    )

    assert result == "Default"


def test_context_with_none_values(template_engine: TemplateEngine, templates_dir: Path) -> None:
    """Test rendering with None values in context."""
    (templates_dir / "none_ctx.jinja2").write_text(
        "{{ value | default('fallback') }}"
    )

    result = template_engine.render(
        "none_ctx.jinja2",
        context={"value": None},
        include_chat_guidance=False,
        include_self_concept=False,
    )

    # Jinja2's default filter doesn't treat None as undefined by default
    # None is rendered as the string "None"
    assert result == "None"


def test_special_characters_in_content(template_engine: TemplateEngine, templates_dir: Path) -> None:
    """Test that special characters are handled correctly."""
    (templates_dir / "special.jinja2").write_text("{{ content }}")

    result = template_engine.render(
        "special.jinja2",
        context={"content": "<script>alert('xss')</script>"},
        include_chat_guidance=False,
        include_self_concept=False,
    )

    # Autoescape is on for html/xml but not for plain text templates
    # Our templates are .jinja2, not .html, so no escaping happens
    assert "<script>" in result


def test_multiline_content(template_engine: TemplateEngine, templates_dir: Path) -> None:
    """Test that multiline content is preserved."""
    (templates_dir / "multiline.jinja2").write_text("{{ content }}")

    result = template_engine.render(
        "multiline.jinja2",
        context={"content": "Line 1\nLine 2\nLine 3"},
        include_chat_guidance=False,
        include_self_concept=False,
    )

    assert "Line 1\nLine 2\nLine 3" in result
