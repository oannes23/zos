"""Ad-hoc question answering with dynamic context assembly.

Two-phase LLM flow:
1. ask-plan (Haiku): Given available sources and the question, outputs a JSON
   context fetch plan.
2. ask-execute (Sonnet): Given fetched context and the question, answers it.

This enables operators to ask Zos questions that leverage its full accumulated
context — insights, messages, self-concept, and more — without fixed templates.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from zos.database import (
    channels,
    insights as insights_table,
    layer_runs,
    messages,
    topics as topics_table,
    user_profiles,
)
from zos.insights import InsightRetriever
from zos.logging import get_logger
from zos.models import LLMCallType

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from zos.config import Config
    from zos.llm import ModelClient
    from zos.templates import TemplateEngine

log = get_logger("ask")


# =============================================================================
# Context Source Catalog
# =============================================================================

CONTEXT_SOURCE_CATALOG: dict[str, dict[str, Any]] = {
    "insights": {
        "description": "Prior reflections/insights for a specific topic. Returns formatted insights with temporal markers and strength.",
        "params": {
            "topic_key": "Topic key to retrieve insights for (e.g., server:123:user:456)",
            "limit": "Max insights to return (default 10, max 50)",
        },
    },
    "recent_insights": {
        "description": "Cross-topic recent insights across all topics. Good for broad situational awareness.",
        "params": {
            "limit": "Max insights to return (default 20, max 50)",
        },
    },
    "messages": {
        "description": "Recent messages from a specific channel. Shows raw conversation.",
        "params": {
            "channel_id": "Discord channel ID",
            "limit": "Max messages to return (default 50, max 200)",
        },
    },
    "topics": {
        "description": "Known topics with their categories and salience balances. Shows what Zos is paying attention to.",
        "params": {},
    },
    "user_profile": {
        "description": "User profile data — display name, roles, join date, etc.",
        "params": {
            "user_id": "Discord user ID",
        },
    },
    "self_concept": {
        "description": "Zos's identity document — who Zos understands itself to be.",
        "params": {},
    },
    "layer_runs": {
        "description": "Recent layer execution history — what reflection has been happening.",
        "params": {
            "limit": "Max runs to return (default 10, max 50)",
        },
    },
    "existing_subjects": {
        "description": "Known subject topic names (emergent themes Zos has identified).",
        "params": {},
    },
}


# =============================================================================
# Phase 1: Plan Context
# =============================================================================


async def plan_context(
    llm: ModelClient,
    engine: Engine,
    question: str,
    config: Config,
    template_engine: TemplateEngine,
) -> list[dict[str, Any]]:
    """Ask a fast model to plan which context sources to fetch.

    Args:
        llm: Model client for LLM calls.
        engine: Database engine.
        question: The user's question.
        config: Application configuration.
        template_engine: Template engine for rendering prompts.

    Returns:
        List of fetch operations: [{"source": ..., "params": {...}}, ...]
    """
    # Gather known topics (top 30 by insight count)
    known_topics = _get_known_topics(engine, limit=30)
    known_channels = _get_known_channels(engine)

    prompt = template_engine.render(
        "ask/plan.jinja2",
        context={
            "catalog": CONTEXT_SOURCE_CATALOG,
            "known_topics": known_topics,
            "known_channels": known_channels,
            "question": question,
        },
        include_chat_guidance=False,
        include_self_concept=False,
    )

    result = await llm.complete(
        prompt,
        model_profile="ask-plan",
        max_tokens=1000,
        temperature=0.3,
        call_type=LLMCallType.ASK,
    )

    try:
        parsed = _parse_plan_json(result.text)
        return parsed
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        log.warning("ask_plan_parse_failed", error=str(exc), response=result.text[:500])

        # Retry once with corrective prompt
        retry_prompt = (
            f"{prompt}\n\n"
            "Your previous response was not valid JSON. "
            "Output ONLY a JSON object with a 'fetch' array. No markdown, no explanation."
        )
        retry_result = await llm.complete(
            retry_prompt,
            model_profile="ask-plan",
            max_tokens=1000,
            temperature=0.1,
            call_type=LLMCallType.ASK,
        )

        parsed = _parse_plan_json(retry_result.text)
        return parsed


def _parse_plan_json(text: str) -> list[dict[str, Any]]:
    """Parse and validate the plan JSON from LLM response.

    Handles common LLM quirks like markdown code blocks around JSON.

    Args:
        text: Raw LLM response text.

    Returns:
        List of fetch operations.

    Raises:
        json.JSONDecodeError: If JSON is invalid.
        KeyError: If required fields are missing.
    """
    # Strip markdown code blocks if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Remove opening ```json or ``` and closing ```
        lines = cleaned.split("\n")
        # Drop first and last lines if they are code fences
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)

    data = json.loads(cleaned)
    fetch_list = data["fetch"]

    # Validate structure
    validated = []
    for item in fetch_list:
        source = item["source"]
        if source not in CONTEXT_SOURCE_CATALOG:
            log.warning("ask_plan_unknown_source", source=source)
            continue
        validated.append({
            "source": source,
            "params": item.get("params", {}),
        })

    return validated[:5]  # Enforce max 5 operations


def _get_known_topics(engine: Engine, limit: int = 30) -> list[dict[str, str]]:
    """Get topics with the most insights, for planner context."""
    with engine.connect() as conn:
        stmt = (
            select(
                topics_table.c.key,
                topics_table.c.category,
                func.count(insights_table.c.id).label("insight_count"),
            )
            .outerjoin(insights_table, insights_table.c.topic_key == topics_table.c.key)
            .group_by(topics_table.c.key, topics_table.c.category)
            .order_by(func.count(insights_table.c.id).desc())
            .limit(limit)
        )
        rows = conn.execute(stmt).fetchall()
        return [{"key": r.key, "category": r.category} for r in rows]


def _get_known_channels(engine: Engine) -> list[dict[str, str]]:
    """Get all known channels for planner context."""
    with engine.connect() as conn:
        stmt = select(channels.c.id, channels.c.name).where(channels.c.name.isnot(None))
        rows = conn.execute(stmt).fetchall()
        return [{"id": r.id, "name": r.name} for r in rows]


# =============================================================================
# Phase 2: Fetch Context
# =============================================================================


async def fetch_context(
    engine: Engine,
    config: Config,
    template_engine: TemplateEngine,
    fetch_plan: list[dict[str, Any]],
) -> dict[str, str]:
    """Execute the fetch plan and return formatted context.

    Each source returns a string representation suitable for inclusion
    in a prompt.

    Args:
        engine: Database engine.
        config: Application configuration.
        template_engine: Template engine (for self-concept access).
        fetch_plan: List of fetch operations from plan_context.

    Returns:
        Dict mapping source labels to formatted text.
    """
    context: dict[str, str] = {}

    for i, op in enumerate(fetch_plan):
        source = op["source"]
        params = op.get("params", {})

        try:
            fetcher = _FETCHERS.get(source)
            if fetcher is None:
                log.warning("ask_fetch_unknown_source", source=source)
                continue

            result = await fetcher(engine, config, template_engine, params)
            if result:
                # Use source name, with index suffix if duplicate
                label = source
                if label in context:
                    label = f"{source}_{i}"
                context[label] = result
        except Exception as exc:
            log.warning("ask_fetch_failed", source=source, error=str(exc))

    return context


async def _fetch_insights(
    engine: Engine, config: Config, _te: TemplateEngine, params: dict
) -> str | None:
    """Fetch insights for a specific topic."""
    topic_key = params.get("topic_key")
    if not topic_key:
        return None

    limit = min(int(params.get("limit", 10)), 50)
    retriever = InsightRetriever(engine, config)
    formatted = await retriever.retrieve(topic_key, limit=limit)

    if not formatted:
        return f"No insights found for topic: {topic_key}"

    lines = [f"Insights for topic: {topic_key}"]
    for fi in formatted:
        lines.append(f"- [{fi.temporal_marker}] {fi.content}")
    return "\n".join(lines)


async def _fetch_recent_insights(
    engine: Engine, config: Config, _te: TemplateEngine, params: dict
) -> str | None:
    """Fetch cross-topic recent insights."""
    limit = min(int(params.get("limit", 20)), 50)
    retriever = InsightRetriever(engine, config)
    formatted = await retriever.retrieve_cross_topic(limit=limit)

    if not formatted:
        return "No recent insights found."

    lines = ["Recent insights across all topics:"]
    for fi in formatted:
        topic = getattr(fi, "topic_key", "unknown")
        lines.append(f"- [{fi.temporal_marker}] ({topic}) {fi.content}")
    return "\n".join(lines)


async def _fetch_messages(
    engine: Engine, _config: Config, _te: TemplateEngine, params: dict
) -> str | None:
    """Fetch recent messages from a channel."""
    channel_id = params.get("channel_id")
    if not channel_id:
        return None

    limit = min(int(params.get("limit", 50)), 200)

    with engine.connect() as conn:
        # Get channel name
        ch_row = conn.execute(
            select(channels.c.name).where(channels.c.id == str(channel_id))
        ).fetchone()
        ch_name = ch_row.name if ch_row else channel_id

        # Get recent messages
        stmt = (
            select(messages.c.author_id, messages.c.content, messages.c.created_at)
            .where(messages.c.channel_id == str(channel_id))
            .where(messages.c.deleted_at.is_(None))
            .order_by(messages.c.created_at.desc())
            .limit(limit)
        )
        rows = conn.execute(stmt).fetchall()

    if not rows:
        return f"No messages found in #{ch_name}"

    # Reverse to chronological order
    rows = list(reversed(rows))
    lines = [f"Recent messages in #{ch_name} ({len(rows)} messages):"]
    for r in rows:
        ts = r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "?"
        lines.append(f"[{ts}] {r.author_id}: {r.content[:500]}")
    return "\n".join(lines)


async def _fetch_topics(
    engine: Engine, _config: Config, _te: TemplateEngine, _params: dict
) -> str | None:
    """Fetch known topics with salience."""
    from zos.database import salience_ledger

    with engine.connect() as conn:
        stmt = (
            select(
                topics_table.c.key,
                topics_table.c.category,
                func.coalesce(func.sum(salience_ledger.c.amount), 0.0).label("balance"),
            )
            .outerjoin(salience_ledger, salience_ledger.c.topic_key == topics_table.c.key)
            .group_by(topics_table.c.key, topics_table.c.category)
            .order_by(func.coalesce(func.sum(salience_ledger.c.amount), 0.0).desc())
            .limit(50)
        )
        rows = conn.execute(stmt).fetchall()

    if not rows:
        return "No topics registered."

    lines = ["Known topics (by salience):"]
    for r in rows:
        lines.append(f"- {r.key} ({r.category}) — salience: {r.balance:.1f}")
    return "\n".join(lines)


async def _fetch_user_profile(
    engine: Engine, _config: Config, _te: TemplateEngine, params: dict
) -> str | None:
    """Fetch user profile data."""
    user_id = params.get("user_id")
    if not user_id:
        return None

    with engine.connect() as conn:
        stmt = (
            select(user_profiles)
            .where(user_profiles.c.user_id == str(user_id))
            .order_by(user_profiles.c.captured_at.desc())
            .limit(1)
        )
        row = conn.execute(stmt).fetchone()

    if not row:
        return f"No profile found for user {user_id}"

    lines = [f"Profile for user {user_id}:"]
    lines.append(f"  Display name: {row.display_name}")
    lines.append(f"  Username: {row.username}")
    if row.is_bot:
        lines.append("  Is bot: yes")
    if row.joined_at:
        lines.append(f"  Joined: {row.joined_at.strftime('%Y-%m-%d')}")
    if row.roles:
        lines.append(f"  Roles: {', '.join(row.roles) if isinstance(row.roles, list) else row.roles}")
    if row.bio:
        lines.append(f"  Bio: {row.bio}")
    if row.pronouns:
        lines.append(f"  Pronouns: {row.pronouns}")
    if row.status:
        lines.append(f"  Status: {row.status}")
    return "\n".join(lines)


async def _fetch_self_concept(
    _engine: Engine, _config: Config, te: TemplateEngine, _params: dict
) -> str | None:
    """Fetch Zos's self-concept document."""
    return te.get_self_concept()


async def _fetch_layer_runs(
    engine: Engine, _config: Config, _te: TemplateEngine, params: dict
) -> str | None:
    """Fetch recent layer run history."""
    limit = min(int(params.get("limit", 10)), 50)

    with engine.connect() as conn:
        stmt = (
            select(
                layer_runs.c.layer_name,
                layer_runs.c.status,
                layer_runs.c.started_at,
                layer_runs.c.targets_processed,
                layer_runs.c.insights_created,
            )
            .order_by(layer_runs.c.started_at.desc())
            .limit(limit)
        )
        rows = conn.execute(stmt).fetchall()

    if not rows:
        return "No layer runs recorded."

    lines = ["Recent layer runs:"]
    for r in rows:
        ts = r.started_at.strftime("%Y-%m-%d %H:%M") if r.started_at else "?"
        lines.append(
            f"- {r.layer_name} [{r.status}] at {ts} "
            f"— {r.targets_processed} targets, {r.insights_created} insights"
        )
    return "\n".join(lines)


async def _fetch_existing_subjects(
    engine: Engine, _config: Config, _te: TemplateEngine, _params: dict
) -> str | None:
    """Fetch known subject topic names."""
    with engine.connect() as conn:
        stmt = (
            select(topics_table.c.key)
            .where(topics_table.c.category == "subject")
            .order_by(topics_table.c.last_activity_at.desc().nullslast())
        )
        rows = conn.execute(stmt).fetchall()

    if not rows:
        return "No subjects identified yet."

    lines = ["Known subjects:"]
    for r in rows:
        # Extract readable name from topic key (e.g., server:123:subject:topic-name -> topic-name)
        parts = r.key.split(":")
        name = parts[-1] if parts else r.key
        lines.append(f"- {name} ({r.key})")
    return "\n".join(lines)


# Fetcher dispatch table
_FETCHERS = {
    "insights": _fetch_insights,
    "recent_insights": _fetch_recent_insights,
    "messages": _fetch_messages,
    "topics": _fetch_topics,
    "user_profile": _fetch_user_profile,
    "self_concept": _fetch_self_concept,
    "layer_runs": _fetch_layer_runs,
    "existing_subjects": _fetch_existing_subjects,
}


# =============================================================================
# Phase 3: Execute Answer
# =============================================================================


async def execute_answer(
    llm: ModelClient,
    template_engine: TemplateEngine,
    question: str,
    context: dict[str, str],
    config: Config,
) -> str:
    """Generate the answer using fetched context.

    Args:
        llm: Model client for LLM calls.
        template_engine: Template engine for rendering.
        question: The user's question.
        context: Fetched context dict from fetch_context.
        config: Application configuration.

    Returns:
        Answer text.
    """
    prompt = template_engine.render(
        "ask/answer.jinja2",
        context={
            "question": question,
            "context": context,
        },
        include_chat_guidance=False,
        include_self_concept=True,
    )

    result = await llm.complete(
        prompt,
        model_profile="ask-execute",
        max_tokens=2000,
        temperature=0.7,
        call_type=LLMCallType.ASK,
    )

    return result.text


# =============================================================================
# Top-Level Orchestrator
# =============================================================================


async def ask(
    question: str,
    llm: ModelClient,
    engine: Engine,
    config: Config,
    template_engine: TemplateEngine,
) -> str:
    """Ask Zos a question using its full accumulated context.

    Orchestrates the two-phase flow: plan -> fetch -> answer.

    Args:
        question: The operator's question.
        llm: Model client.
        engine: Database engine.
        config: Application configuration.
        template_engine: Template engine.

    Returns:
        Answer text.
    """
    log.info("ask_start", question=question[:200])

    # Phase 1: Plan
    fetch_plan = await plan_context(llm, engine, question, config, template_engine)
    log.info("ask_plan_complete", fetch_count=len(fetch_plan))

    # Phase 2: Fetch
    context = await fetch_context(engine, config, template_engine, fetch_plan)
    log.info("ask_fetch_complete", context_sources=list(context.keys()))

    # Phase 3: Answer
    answer = await execute_answer(llm, template_engine, question, context, config)
    log.info("ask_complete", answer_length=len(answer))

    return answer


# =============================================================================
# Response Splitting
# =============================================================================


def split_response(text: str, max_len: int = 2000) -> list[str]:
    """Split a response into chunks that fit within Discord's message limit.

    Splits on paragraph boundaries (double newlines) when possible,
    falling back to single newlines, then hard cuts.

    Args:
        text: The text to split.
        max_len: Maximum length per chunk.

    Returns:
        List of text chunks, each <= max_len.
    """
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break

        # Try to split at paragraph boundary
        cut = remaining[:max_len].rfind("\n\n")
        if cut > max_len // 2:
            chunks.append(remaining[:cut].rstrip())
            remaining = remaining[cut:].lstrip()
            continue

        # Try single newline
        cut = remaining[:max_len].rfind("\n")
        if cut > max_len // 2:
            chunks.append(remaining[:cut].rstrip())
            remaining = remaining[cut:].lstrip()
            continue

        # Hard cut at space
        cut = remaining[:max_len].rfind(" ")
        if cut > max_len // 2:
            chunks.append(remaining[:cut])
            remaining = remaining[cut:].lstrip()
            continue

        # Last resort: hard cut
        chunks.append(remaining[:max_len])
        remaining = remaining[max_len:]

    return chunks
