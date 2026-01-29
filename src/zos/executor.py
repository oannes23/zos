"""Sequential Layer Executor for Zos.

Executes layer pipelines sequentially, passing context between nodes.
Implements fail-forward behavior: errors in one topic don't stop processing
of others.

Key concepts:
- ExecutionContext: State passed through node execution
- NodeHandler: Protocol for node handlers
- LayerExecutor: Main executor class that coordinates node execution
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy import and_, select

from zos.database import (
    channels as channels_table,
    generate_id,
    insights as insights_table,
    layer_runs as layer_runs_table,
    media_analysis as media_analysis_table,
    messages as messages_table,
    reactions as reactions_table,
    topics as topics_table,
    user_profiles as user_profiles_table,
)
from zos.insights import FormattedInsight, InsightRetriever, insert_insight
from zos.layers import Layer, LayerLoader, Node, NodeType
from zos.llm import CompletionResult, ModelClient, estimate_cost
from zos.logging import get_logger
from zos.models import (
    Insight,
    LayerRun,
    LayerRunStatus,
    LLMCallType,
    Message,
    Topic,
    TopicCategory,
    UserProfile,
    VisibilityScope,
    row_to_model,
    utcnow,
)
from zos.salience import SalienceLedger
from zos.templates import (
    TemplateEngine,
    extract_channel_mention_ids,
    extract_mention_ids,
    format_insights_for_prompt,
    format_messages_for_prompt,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from zos.config import Config

log = get_logger("executor")


# =============================================================================
# Constants
# =============================================================================


# Default metrics when JSON parsing fails
DEFAULT_METRICS = {
    "confidence": 0.6,
    "importance": 0.5,
    "novelty": 0.5,
    "strength_adjustment": 1.0,
    "valence": {"curiosity": 0.5},
}

# Maximum retry attempts per topic
MAX_RETRY_ATTEMPTS = 3


# =============================================================================
# Execution Context
# =============================================================================


@dataclass
class ExecutionContext:
    """Context passed between nodes during execution.

    Accumulates data as nodes execute: messages, insights, LLM responses.
    Also tracks token usage and errors for the layer run audit.

    Attributes:
        topic: The topic being processed.
        layer: The layer being executed.
        run_id: Unique identifier for this layer run.
        messages: Accumulated messages from fetch_messages node.
        insights: Accumulated insights from fetch_insights node.
        layer_runs: Accumulated layer runs from fetch_layer_runs node.
        llm_response: Response from the most recent llm_call node.
        reduced_results: Results from reduce node.
        output_content: Final output content.
        tokens_input: Total input tokens used.
        tokens_output: Total output tokens used.
        errors: List of errors encountered.
        dry_run: Whether this is a dry run (skip LLM and DB writes).
        model_provider: Provider used for LLM calls.
        model_name: Model name used for LLM calls.
    """

    topic: Topic
    layer: Layer
    run_id: str

    # Accumulated data
    messages: list[Message] = field(default_factory=list)
    insights: list[FormattedInsight] = field(default_factory=list)
    individual_insights: list[FormattedInsight] = field(default_factory=list)
    reactions: list[dict[str, Any]] = field(default_factory=list)
    layer_runs: list[LayerRun] = field(default_factory=list)
    llm_response: str | None = None
    reduced_results: list[Any] = field(default_factory=list)
    output_content: str | None = None

    # Tracking
    tokens_input: int = 0
    tokens_output: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    dry_run: bool = False

    # Model info (set by LLM call)
    model_provider: str | None = None
    model_name: str | None = None

    def add_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """Add token usage from an LLM call.

        Args:
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.
        """
        self.tokens_input += input_tokens
        self.tokens_output += output_tokens


# =============================================================================
# Node Handler Protocol
# =============================================================================


class NodeHandler(Protocol):
    """Protocol for node handlers.

    Node handlers take a node definition and execution context,
    perform their operation, and update the context.
    """

    async def __call__(self, node: Node, ctx: ExecutionContext) -> None:
        """Execute the node.

        Args:
            node: The node to execute.
            ctx: The execution context.
        """
        ...


# =============================================================================
# Layer Executor
# =============================================================================


class LayerExecutor:
    """Executes layer pipelines sequentially.

    Coordinates node execution, maintains context between nodes,
    handles errors with fail-forward behavior, and records layer runs.

    Attributes:
        engine: SQLAlchemy database engine.
        ledger: Salience ledger for spending operations.
        templates: Template engine for prompt rendering.
        llm: Model client for LLM calls.
        config: Application configuration.
        loader: Layer loader (for hash lookup).
    """

    def __init__(
        self,
        engine: "Engine",
        ledger: SalienceLedger,
        templates: TemplateEngine,
        llm: ModelClient,
        config: "Config",
        loader: LayerLoader | None = None,
    ) -> None:
        """Initialize the layer executor.

        Args:
            engine: SQLAlchemy database engine.
            ledger: Salience ledger for spending operations.
            templates: Template engine for prompt rendering.
            llm: Model client for LLM calls.
            config: Application configuration.
            loader: Optional layer loader for hash lookup.
        """
        self.engine = engine
        self.ledger = ledger
        self.templates = templates
        self.llm = llm
        self.config = config
        self.loader = loader or LayerLoader()

        # Initialize insight retriever
        self.insight_retriever = InsightRetriever(engine, config)

        # Node handlers
        self.handlers: dict[NodeType, NodeHandler] = {
            NodeType.FETCH_MESSAGES: self._handle_fetch_messages,
            NodeType.FETCH_INSIGHTS: self._handle_fetch_insights,
            NodeType.FETCH_REACTIONS: self._handle_fetch_reactions,
            NodeType.FETCH_LAYER_RUNS: self._handle_fetch_layer_runs,
            NodeType.LLM_CALL: self._handle_llm_call,
            NodeType.STORE_INSIGHT: self._handle_store_insight,
            NodeType.REDUCE: self._handle_reduce,
            NodeType.OUTPUT: self._handle_output,
            NodeType.SYNTHESIZE_TO_GLOBAL: self._handle_synthesize_to_global,
            NodeType.UPDATE_SELF_CONCEPT: self._handle_update_self_concept,
        }

    async def execute_layer(
        self,
        layer: Layer,
        topics: list[str],
        dry_run: bool = False,
    ) -> LayerRun:
        """Execute a layer for the given topics.

        Args:
            layer: The layer to execute.
            topics: List of topic keys to process.
            dry_run: If True, skip LLM calls and database writes.

        Returns:
            LayerRun record with execution results.
        """
        run_id = generate_id()
        started_at = utcnow()

        # Get layer hash and model profile upfront
        layer_hash = self.loader.get_hash(layer.name) or "unknown"
        model_profile = self._get_primary_model_profile(layer)

        # Insert a preliminary layer_run record so insights can reference it
        # (insights table has FK constraint on layer_run_id)
        preliminary_run = LayerRun(
            id=run_id,
            layer_name=layer.name,
            layer_hash=layer_hash,
            started_at=started_at,
            completed_at=None,
            status=LayerRunStatus.DRY,  # Placeholder until complete
            targets_matched=len(topics),
            targets_processed=0,
            targets_skipped=0,
            insights_created=0,
            model_profile=model_profile,
        )
        await self._insert_layer_run(preliminary_run)

        insights_created = 0
        targets_processed = 0
        targets_skipped = 0
        all_errors: list[dict[str, Any]] = []

        total_tokens_input = 0
        total_tokens_output = 0

        model_provider: str | None = None
        model_name: str | None = None

        for topic_key in topics:
            current_node: Node | None = None
            try:
                # Ensure topic exists (creates if needed)
                topic = await self.ledger.ensure_topic(topic_key)

                ctx = ExecutionContext(
                    topic=topic,
                    layer=layer,
                    run_id=run_id,
                    dry_run=dry_run,
                )

                # Execute each node in sequence
                for node in layer.nodes:
                    current_node = node
                    await self._execute_node(node, ctx)

                targets_processed += 1
                total_tokens_input += ctx.tokens_input
                total_tokens_output += ctx.tokens_output

                # Track model info from context
                if ctx.model_provider:
                    model_provider = ctx.model_provider
                if ctx.model_name:
                    model_name = ctx.model_name

                # Count insights created for this topic
                # Only count if not a dry run and there was an LLM response
                if not dry_run and ctx.llm_response:
                    insights_created += 1

            except Exception as e:
                log.warning(
                    "topic_execution_failed",
                    topic=topic_key,
                    layer=layer.name,
                    error=str(e),
                    node=current_node.name if current_node else None,
                )
                targets_skipped += 1
                all_errors.append({
                    "topic": topic_key,
                    "error": str(e),
                    "node": current_node.name if current_node else None,
                })
                # Continue with next topic (fail-forward)

        # Determine status
        if targets_skipped == len(topics) and len(topics) > 0:
            status = LayerRunStatus.FAILED
        elif targets_skipped > 0:
            status = LayerRunStatus.PARTIAL
        elif insights_created == 0 or dry_run:
            status = LayerRunStatus.DRY
        else:
            status = LayerRunStatus.SUCCESS

        # Estimate cost
        estimated_cost = estimate_cost(
            provider=model_provider or "anthropic",
            model=model_name or "unknown",
            input_tokens=total_tokens_input,
            output_tokens=total_tokens_output,
        )

        # Create final run record (updates the preliminary one)
        run = LayerRun(
            id=run_id,
            layer_name=layer.name,
            layer_hash=layer_hash,
            started_at=started_at,
            completed_at=utcnow(),
            status=status,
            targets_matched=len(topics),
            targets_processed=targets_processed,
            targets_skipped=targets_skipped,
            insights_created=insights_created,
            model_profile=model_profile,
            model_provider=model_provider,
            model_name=model_name,
            tokens_input=total_tokens_input,
            tokens_output=total_tokens_output,
            tokens_total=total_tokens_input + total_tokens_output,
            estimated_cost_usd=estimated_cost,
            errors=all_errors if all_errors else None,
        )

        # Update the layer run record with final stats
        await self._update_layer_run(run)

        log.info(
            "layer_executed",
            layer=layer.name,
            status=status.value,
            targets=targets_processed,
            insights=insights_created,
            dry_run=dry_run,
        )

        return run

    async def _execute_node(self, node: Node, ctx: ExecutionContext) -> None:
        """Execute a single node.

        Args:
            node: The node to execute.
            ctx: The execution context.

        Raises:
            ValueError: If the node type is unknown.
        """
        handler = self.handlers.get(node.type)
        if not handler:
            raise ValueError(f"Unknown node type: {node.type}")

        log.debug(
            "executing_node",
            node=node.name,
            type=node.type.value,
            topic=ctx.topic.key,
        )

        await handler(node, ctx)

    # =========================================================================
    # Node Handlers
    # =========================================================================

    async def _handle_fetch_messages(self, node: Node, ctx: ExecutionContext) -> None:
        """Fetch messages for the topic.

        Args:
            node: The node with params.
            ctx: The execution context.
        """
        params = node.params
        lookback_hours = params.get("lookback_hours", 24)
        limit = params.get("limit_per_channel", 50)

        since = utcnow() - timedelta(hours=lookback_hours)

        messages = await self._get_messages_for_topic(
            ctx.topic.key,
            since=since,
            limit=limit,
        )

        ctx.messages = messages

        log.debug(
            "messages_fetched",
            topic=ctx.topic.key,
            count=len(messages),
            lookback_hours=lookback_hours,
        )

    async def _handle_fetch_insights(self, node: Node, ctx: ExecutionContext) -> None:
        """Fetch prior insights for the topic.

        Supports `members_of_topic` param for dyad reflection: fetches individual
        user insights for each member of the dyad.

        Args:
            node: The node with params.
            ctx: The execution context.
        """
        params = node.params
        profile = params.get("retrieval_profile", "balanced")
        max_per_topic = params.get("max_per_topic", 5)
        members_of_topic = params.get("members_of_topic", False)
        categories = params.get("categories")

        if members_of_topic and ctx.topic.category == TopicCategory.DYAD:
            # Fetch individual insights for each dyad member
            user_id_1, user_id_2, server_id = self._extract_dyad_from_topic(
                ctx.topic.key
            )
            individual_insights: list[FormattedInsight] = []

            for user_id in [user_id_1, user_id_2]:
                if user_id:
                    # Construct user topic key
                    if server_id:
                        user_topic = f"server:{server_id}:user:{user_id}"
                    else:
                        user_topic = f"user:{user_id}"

                    user_insights = await self.insight_retriever.retrieve(
                        user_topic,
                        profile=profile,
                        limit=max_per_topic,
                    )

                    # Filter by category if specified
                    if categories:
                        user_insights = [
                            i for i in user_insights if i.category in categories
                        ]

                    # Add topic_key to each insight for template access
                    for insight in user_insights:
                        # Store the topic key in a way templates can access
                        insight.topic_key = user_topic  # type: ignore[attr-defined]

                    individual_insights.extend(user_insights)

            ctx.individual_insights = individual_insights

            log.debug(
                "individual_insights_fetched",
                topic=ctx.topic.key,
                count=len(individual_insights),
                profile=profile,
            )
        else:
            # Standard insight fetch for the topic
            insights = await self.insight_retriever.retrieve(
                ctx.topic.key,
                profile=profile,
                limit=max_per_topic,
            )

            ctx.insights = insights

            log.debug(
                "insights_fetched",
                topic=ctx.topic.key,
                count=len(insights),
                profile=profile,
            )

    async def _handle_fetch_layer_runs(
        self, node: Node, ctx: ExecutionContext
    ) -> None:
        """Fetch layer run history for self-reflection.

        Retrieves recent layer runs to provide operational context for
        self-reflection. Errors are framed as "felt experience" - friction
        in operation that becomes material for self-understanding.

        Args:
            node: The node with params.
            ctx: The execution context.
        """
        params = node.params
        limit = params.get("limit", 10)
        layer_name = params.get("layer_name")  # Optional filter
        since_days = params.get("since_days", 7)
        include_errors = params.get("include_errors", True)

        layer_runs = await self._get_layer_runs(
            limit=limit,
            layer_name=layer_name,
            since_days=since_days,
            include_errors=include_errors,
        )

        ctx.layer_runs = layer_runs

        # Count errors for logging context
        error_count = sum(
            len(run.errors) if run.errors else 0
            for run in layer_runs
        )

        log.debug(
            "layer_runs_fetched",
            count=len(layer_runs),
            layer_name=layer_name,
            since_days=since_days,
            error_count=error_count,
        )

    async def _handle_fetch_reactions(
        self, node: Node, ctx: ExecutionContext
    ) -> None:
        """Fetch emoji reaction patterns for a user topic.

        Retrieves reactions made by the user, grouped by emoji for pattern
        analysis. This enables reflection on how users express themselves
        through reactions.

        Args:
            node: The node with params.
            ctx: The execution context.
        """
        params = node.params
        lookback_days = params.get("lookback_days", 7)
        min_reactions = params.get("min_reactions", 5)

        # Extract user_id from topic
        user_id, server_id = self._extract_user_from_topic(ctx.topic.key)
        if not user_id:
            log.warning(
                "fetch_reactions_no_user",
                topic=ctx.topic.key,
            )
            return

        reactions = await self._get_reactions_for_user(
            user_id=user_id,
            server_id=server_id,
            lookback_days=lookback_days,
        )

        # Only proceed if user has enough reactions
        if len(reactions) < min_reactions:
            log.debug(
                "fetch_reactions_insufficient",
                user_id=user_id,
                count=len(reactions),
                min_required=min_reactions,
            )
            ctx.reactions = []
            return

        # Group reactions by emoji for pattern analysis
        emoji_counts: dict[str, int] = {}
        emoji_examples: dict[str, list[str]] = {}

        for reaction in reactions:
            emoji = reaction["emoji"]
            emoji_counts[emoji] = emoji_counts.get(emoji, 0) + 1

            # Store a few example message contexts
            if emoji not in emoji_examples:
                emoji_examples[emoji] = []
            if len(emoji_examples[emoji]) < 3 and reaction.get("message_content"):
                emoji_examples[emoji].append(
                    reaction["message_content"][:100]
                )

        # Format for template consumption
        formatted_reactions = [
            {
                "emoji": emoji,
                "count": count,
                "examples": emoji_examples.get(emoji, []),
            }
            for emoji, count in sorted(
                emoji_counts.items(), key=lambda x: x[1], reverse=True
            )
        ]

        ctx.reactions = formatted_reactions

        log.debug(
            "reactions_fetched",
            user_id=user_id,
            total_reactions=len(reactions),
            unique_emojis=len(emoji_counts),
        )

    async def _get_reactions_for_user(
        self,
        user_id: str,
        server_id: str | None,
        lookback_days: int,
    ) -> list[dict[str, Any]]:
        """Get reactions made by a user.

        Args:
            user_id: Discord user ID.
            server_id: Server ID (None for global lookup).
            lookback_days: How many days to look back.

        Returns:
            List of reaction dictionaries with emoji and context.
        """
        since = utcnow() - timedelta(days=lookback_days)

        with self.engine.connect() as conn:
            # Join reactions with messages to get context
            conditions = [
                reactions_table.c.user_id == user_id,
                reactions_table.c.created_at >= since,
                reactions_table.c.removed_at.is_(None),
            ]

            if server_id:
                conditions.append(reactions_table.c.server_id == server_id)

            stmt = (
                select(
                    reactions_table.c.emoji,
                    reactions_table.c.is_custom,
                    reactions_table.c.created_at,
                    messages_table.c.content.label("message_content"),
                    messages_table.c.author_id.label("message_author"),
                )
                .select_from(
                    reactions_table.join(
                        messages_table,
                        reactions_table.c.message_id == messages_table.c.id,
                    )
                )
                .where(and_(*conditions))
                .order_by(reactions_table.c.created_at.desc())
                .limit(500)  # Cap for performance
            )

            rows = conn.execute(stmt).fetchall()

            return [
                {
                    "emoji": row.emoji,
                    "is_custom": row.is_custom,
                    "created_at": row.created_at,
                    "message_content": row.message_content,
                    "message_author": row.message_author,
                }
                for row in rows
            ]

    def _extract_user_from_topic(self, topic_key: str) -> tuple[str | None, str | None]:
        """Extract user_id and server_id from a user topic key.

        Args:
            topic_key: Topic key (e.g., "user:<id>" or "server:<sid>:user:<id>").

        Returns:
            (user_id, server_id) tuple. server_id is None for global user topics.
        """
        # Global user topic: "user:<user_id>"
        if topic_key.startswith("user:"):
            user_id = topic_key.split(":", 1)[1]
            return (user_id, None)

        # Server-scoped user topic: "server:<server_id>:user:<user_id>"
        if ":user:" in topic_key:
            parts = topic_key.split(":")
            # Find server_id (after "server:")
            server_id = None
            if parts[0] == "server" and len(parts) >= 2:
                server_id = parts[1]
            # Find user_id (after ":user:")
            user_idx = parts.index("user") if "user" in parts else -1
            if user_idx >= 0 and user_idx + 1 < len(parts):
                user_id = parts[user_idx + 1]
                return (user_id, server_id)

        return (None, None)

    def _extract_dyad_from_topic(
        self, topic_key: str
    ) -> tuple[str | None, str | None, str | None]:
        """Extract user IDs and server_id from a dyad topic key.

        Args:
            topic_key: Topic key (e.g., "dyad:<id1>:<id2>" or "server:<sid>:dyad:<id1>:<id2>").

        Returns:
            (user_id_1, user_id_2, server_id) tuple. server_id is None for global dyad topics.
        """
        # Global dyad topic: "dyad:<user_id_1>:<user_id_2>"
        if topic_key.startswith("dyad:"):
            parts = topic_key.split(":")
            if len(parts) >= 3:
                return (parts[1], parts[2], None)
            return (None, None, None)

        # Server-scoped dyad topic: "server:<server_id>:dyad:<user_id_1>:<user_id_2>"
        if ":dyad:" in topic_key:
            parts = topic_key.split(":")
            # Find server_id (after "server:")
            server_id = None
            if parts[0] == "server" and len(parts) >= 2:
                server_id = parts[1]
            # Find user IDs (after ":dyad:")
            dyad_idx = parts.index("dyad") if "dyad" in parts else -1
            if dyad_idx >= 0 and dyad_idx + 2 < len(parts):
                user_id_1 = parts[dyad_idx + 1]
                user_id_2 = parts[dyad_idx + 2]
                return (user_id_1, user_id_2, server_id)

        return (None, None, None)

    def _extract_channel_from_topic(
        self, topic_key: str
    ) -> tuple[str | None, str | None]:
        """Extract channel_id and server_id from a channel topic key.

        Args:
            topic_key: Topic key (e.g., "server:<sid>:channel:<cid>").

        Returns:
            (channel_id, server_id) tuple.
        """
        # Server-scoped channel topic: "server:<server_id>:channel:<channel_id>"
        if ":channel:" in topic_key:
            parts = topic_key.split(":")
            server_id = None
            if parts[0] == "server" and len(parts) >= 2:
                server_id = parts[1]
            channel_idx = parts.index("channel") if "channel" in parts else -1
            if channel_idx >= 0 and channel_idx + 1 < len(parts):
                channel_id = parts[channel_idx + 1]
                return (channel_id, server_id)

        return (None, None)

    async def _get_channel_info(
        self,
        channel_id: str,
    ) -> dict[str, Any] | None:
        """Get channel metadata.

        Args:
            channel_id: Discord channel ID.

        Returns:
            Dictionary with channel name, type, parent_id, or None if not found.
        """
        with self.engine.connect() as conn:
            result = conn.execute(
                select(channels_table).where(channels_table.c.id == channel_id)
            ).fetchone()

            if result:
                return {
                    "id": result.id,
                    "name": result.name,
                    "type": result.type,
                    "parent_id": result.parent_id,
                    "server_id": result.server_id,
                }
            return None

    async def _get_user_profile(
        self,
        user_id: str,
        server_id: str | None,
    ) -> UserProfile | None:
        """Get most recent profile snapshot for user.

        Args:
            user_id: Discord user ID.
            server_id: Server ID (None for global profile lookup).

        Returns:
            UserProfile if found, None otherwise.
        """
        with self.engine.connect() as conn:
            query = select(user_profiles_table).where(
                user_profiles_table.c.user_id == user_id
            )

            # Match server-specific or global profile
            if server_id:
                query = query.where(user_profiles_table.c.server_id == server_id)
            else:
                query = query.where(user_profiles_table.c.server_id.is_(None))

            result = conn.execute(
                query.order_by(user_profiles_table.c.captured_at.desc()).limit(1)
            ).fetchone()

            if result:
                return row_to_model(result, UserProfile)
            return None

    async def _resolve_mention_names(
        self,
        messages: list[Message],
    ) -> dict[str, str]:
        """Resolve Discord user IDs from mentions to display names.

        Extracts all mentioned user IDs from message content and batch queries
        the user_profiles table to get display names.

        Args:
            messages: List of Message models to extract mentions from.

        Returns:
            Dictionary mapping user_id -> display_name.
            Name resolution priority: display_name > username#discriminator > username.
            Users not found in profiles are omitted from the result.
        """
        # Extract all unique mentioned user IDs
        mentioned_ids: set[str] = set()
        for msg in messages:
            if msg.content:
                mentioned_ids.update(extract_mention_ids(msg.content))

        if not mentioned_ids:
            return {}

        # Batch query user_profiles for most recent profile per user
        # Use a subquery to get the most recent profile for each user
        with self.engine.connect() as conn:
            # Query all profiles for the mentioned users, ordered by captured_at desc
            # We'll group by user_id in Python to get the most recent
            query = (
                select(
                    user_profiles_table.c.user_id,
                    user_profiles_table.c.display_name,
                    user_profiles_table.c.username,
                    user_profiles_table.c.discriminator,
                    user_profiles_table.c.captured_at,
                )
                .where(user_profiles_table.c.user_id.in_(mentioned_ids))
                .order_by(
                    user_profiles_table.c.user_id,
                    user_profiles_table.c.captured_at.desc(),
                )
            )

            rows = conn.execute(query).fetchall()

        # Build mapping, taking the most recent profile for each user
        user_id_to_name: dict[str, str] = {}
        seen_users: set[str] = set()

        for row in rows:
            user_id = row.user_id
            if user_id in seen_users:
                # Already have most recent profile for this user
                continue
            seen_users.add(user_id)

            # Name resolution priority
            if row.display_name:
                user_id_to_name[user_id] = row.display_name
            elif row.discriminator and row.discriminator != "0":
                # Old Discord format: username#discriminator
                user_id_to_name[user_id] = f"{row.username}#{row.discriminator}"
            elif row.username:
                user_id_to_name[user_id] = row.username
            # If no name found, don't include in mapping (mention will be kept as-is)

        log.debug(
            "mention_names_resolved",
            mentioned_count=len(mentioned_ids),
            resolved_count=len(user_id_to_name),
        )

        return user_id_to_name

    async def _resolve_channel_mention_names(
        self,
        messages: list[Message],
    ) -> dict[str, str]:
        """Resolve Discord channel IDs from mentions to channel names.

        Extracts all mentioned channel IDs from message content and batch queries
        the channels table to get names.

        Args:
            messages: List of Message models to extract channel mentions from.

        Returns:
            Dictionary mapping channel_id -> channel_name.
            Channels not found in the database are omitted from the result.
        """
        # Extract all unique mentioned channel IDs
        mentioned_ids: set[str] = set()
        for msg in messages:
            if msg.content:
                mentioned_ids.update(extract_channel_mention_ids(msg.content))

        if not mentioned_ids:
            return {}

        # Batch query channels table
        with self.engine.connect() as conn:
            query = (
                select(
                    channels_table.c.id,
                    channels_table.c.name,
                )
                .where(channels_table.c.id.in_(mentioned_ids))
            )

            rows = conn.execute(query).fetchall()

        # Build mapping
        channel_id_to_name: dict[str, str] = {}
        for row in rows:
            if row.name:
                channel_id_to_name[row.id] = row.name

        log.debug(
            "channel_mention_names_resolved",
            mentioned_count=len(mentioned_ids),
            resolved_count=len(channel_id_to_name),
        )

        return channel_id_to_name

    async def _handle_llm_call(self, node: Node, ctx: ExecutionContext) -> None:
        """Call the LLM with rendered prompt.

        Args:
            node: The node with params.
            ctx: The execution context.

        Raises:
            ValueError: If prompt_template is not specified.
        """
        params = node.params
        template_path = params.get("prompt_template")
        if not template_path:
            raise ValueError("llm_call node requires prompt_template param")

        model_profile = params.get("model", "simple")
        max_tokens = params.get("max_tokens", 500)

        # Skip LLM call in dry run mode
        if ctx.dry_run:
            ctx.llm_response = "[DRY RUN - LLM call skipped]"
            log.debug("llm_call_skipped_dry_run", topic=ctx.topic.key)
            return

        # Prepare message data for template
        messages_data = [
            {
                "author_id": m.author_id,
                "content": m.content,
                "created_at": m.created_at,
                "has_media": m.has_media,
                "has_links": m.has_links,
            }
            for m in ctx.messages
        ]

        # Enrich messages with link and media analyses
        message_ids_with_links = [m.id for m in ctx.messages if m.has_links]
        message_ids_with_media = [m.id for m in ctx.messages if m.has_media]

        link_analyses_map: dict = {}
        media_analyses_map: dict = {}

        if message_ids_with_links:
            from zos.links import get_link_analyses_for_messages

            link_analyses_map = get_link_analyses_for_messages(
                self.engine, message_ids_with_links
            )

        if message_ids_with_media:
            media_analyses_map = self._get_media_analyses_for_messages(
                message_ids_with_media
            )

        # Attach link/media summaries to message dicts
        for i, m in enumerate(ctx.messages):
            link_summaries = []
            for la in link_analyses_map.get(m.id, []):
                if not la.fetch_failed:
                    link_summaries.append({
                        "domain": la.domain,
                        "title": la.title,
                        "summary": la.summary,
                        "is_youtube": la.is_youtube,
                    })
            messages_data[i]["link_summaries"] = link_summaries

            media_descriptions = []
            for ma in media_analyses_map.get(m.id, []):
                media_descriptions.append({
                    "media_type": ma.get("media_type", "image"),
                    "filename": ma.get("filename"),
                    "description": ma.get("description"),
                })
            messages_data[i]["media_descriptions"] = media_descriptions

        # Resolve Discord mention IDs to display names
        mention_names = await self._resolve_mention_names(ctx.messages)

        # Resolve Discord channel mention IDs to channel names
        channel_names = await self._resolve_channel_mention_names(ctx.messages)

        # Prepare insights data for template
        insights_data = [
            {
                "content": i.content,
                "created_at": i.created_at,
                "strength": i.strength,
                "confidence": i.confidence,
                "temporal_marker": i.temporal_marker,
            }
            for i in ctx.insights
        ]

        # Fetch user profile(s) for user and dyad reflections
        user_profile = None
        user_profiles = None
        if ctx.topic.category == TopicCategory.USER:
            # Extract user_id and server_id from topic key
            # User topic keys: "user:<user_id>" (global) or "server:<server_id>:user:<user_id>"
            user_id, server_id = self._extract_user_from_topic(ctx.topic.key)
            if user_id:
                user_profile = await self._get_user_profile(user_id, server_id)
        elif ctx.topic.category == TopicCategory.DYAD:
            # Extract both user IDs and server_id from topic key
            # Dyad topic keys: "dyad:<id1>:<id2>" (global) or "server:<sid>:dyad:<id1>:<id2>"
            user_id_1, user_id_2, server_id = self._extract_dyad_from_topic(ctx.topic.key)
            if user_id_1 and user_id_2:
                profile_1 = await self._get_user_profile(user_id_1, server_id)
                profile_2 = await self._get_user_profile(user_id_2, server_id)
                # Only include profiles if both are found
                if profile_1 and profile_2:
                    user_profiles = [profile_1, profile_2]

        # Fetch channel info for channel reflections
        channel_info = None
        if ctx.topic.category == TopicCategory.CHANNEL:
            channel_id, server_id = self._extract_channel_from_topic(ctx.topic.key)
            if channel_id:
                channel_info = await self._get_channel_info(channel_id)

        # Render template
        prompt = self.templates.render(
            template_path,
            {
                "topic": ctx.topic,
                "user_profile": user_profile,
                "user_profiles": user_profiles,
                "channel_info": channel_info,
                "messages": format_messages_for_prompt(
                    messages_data, {}, mention_names=mention_names,
                    channel_names=channel_names,
                ),
                "insights": format_insights_for_prompt(insights_data),
                "individual_insights": ctx.individual_insights,
                "reactions": ctx.reactions,
                "layer_runs": ctx.layer_runs,
                "llm_response": ctx.llm_response,  # Prior LLM response (for chained calls)
            },
        )

        # Call LLM
        result = await self.llm.complete(
            prompt=prompt,
            model_profile=model_profile,
            max_tokens=max_tokens,
            layer_run_id=ctx.run_id,
            topic_key=ctx.topic.key,
            call_type=LLMCallType.REFLECTION,
        )

        ctx.llm_response = result.text
        ctx.add_tokens(result.usage.input_tokens, result.usage.output_tokens)
        ctx.model_provider = result.provider
        ctx.model_name = result.model

        log.debug(
            "llm_call_complete",
            topic=ctx.topic.key,
            tokens_in=result.usage.input_tokens,
            tokens_out=result.usage.output_tokens,
        )

    async def _handle_store_insight(self, node: Node, ctx: ExecutionContext) -> None:
        """Parse LLM response and store insight.

        Args:
            node: The node with params.
            ctx: The execution context.

        Raises:
            ValueError: If no LLM response is available.
        """
        params = node.params
        category = params.get("category", ctx.layer.category.value)

        if not ctx.llm_response:
            raise ValueError("No LLM response to store")

        # Skip storage in dry run mode
        if ctx.dry_run:
            log.debug("store_insight_skipped_dry_run", topic=ctx.topic.key)
            return

        # Parse JSON from response
        insight_data = self._parse_insight_response(ctx.llm_response)

        # Get current topic salience
        current_salience = await self.ledger.get_balance(ctx.topic.key)

        # Calculate salience cost (tokens * cost per token)
        salience_cost = ctx.tokens_input * self.config.salience.cost_per_token

        # Spend salience (only on success)
        salience_spent = await self.ledger.spend(
            ctx.topic.key,
            salience_cost,
            reason=f"reflection:{ctx.run_id}",
        )

        # Determine scope from messages
        sources_scope = self._determine_scope(ctx.messages)

        # Extract valence
        valence = insight_data.get("valence", {})
        if not valence:
            valence = {"curiosity": 0.5}

        # Extract open_questions (forward-looking curiosity)
        open_questions = insight_data.get("open_questions")

        # Create insight
        strength_adjustment = insight_data.get("strength_adjustment", 1.0)
        insight = Insight(
            id=generate_id(),
            topic_key=ctx.topic.key,
            category=category,
            content=insight_data["content"],
            sources_scope_max=sources_scope,
            created_at=utcnow(),
            layer_run_id=ctx.run_id,
            salience_spent=salience_spent,
            strength_adjustment=strength_adjustment,
            strength=salience_spent * strength_adjustment,
            original_topic_salience=current_salience,
            confidence=insight_data.get("confidence", 0.6),
            importance=insight_data.get("importance", 0.5),
            novelty=insight_data.get("novelty", 0.5),
            valence_joy=valence.get("joy"),
            valence_concern=valence.get("concern"),
            valence_curiosity=valence.get("curiosity"),
            valence_warmth=valence.get("warmth"),
            valence_tension=valence.get("tension"),
            # Expanded valence dimensions (🟡 per spec)
            valence_awe=valence.get("awe"),
            valence_grief=valence.get("grief"),
            valence_longing=valence.get("longing"),
            valence_peace=valence.get("peace"),
            valence_gratitude=valence.get("gratitude"),
            # Prospective curiosity
            open_questions=open_questions,
        )

        await insert_insight(self.engine, insight)

        log.info(
            "insight_stored",
            insight_id=insight.id,
            topic=ctx.topic.key,
            category=category,
            strength=insight.strength,
        )

    async def _handle_reduce(self, node: Node, ctx: ExecutionContext) -> None:
        """Aggregate results from prior nodes.

        Args:
            node: The node with params.
            ctx: The execution context.
        """
        params = node.params
        operation = params.get("operation", "collect")

        if operation == "collect":
            # Collect LLM response into reduced_results
            if ctx.llm_response:
                ctx.reduced_results.append(ctx.llm_response)
        elif operation == "concat":
            # Concatenate all accumulated results
            if ctx.reduced_results:
                ctx.llm_response = "\n\n".join(str(r) for r in ctx.reduced_results)
        else:
            log.warning("unknown_reduce_operation", operation=operation)

        log.debug(
            "reduce_complete",
            operation=operation,
            results_count=len(ctx.reduced_results),
        )

    async def _handle_output(self, node: Node, ctx: ExecutionContext) -> None:
        """Format and emit final output.

        Args:
            node: The node with params.
            ctx: The execution context.
        """
        params = node.params
        destination = params.get("destination", "log")
        format_type = params.get("format", "text")

        # Format output
        if format_type == "json" and ctx.llm_response:
            try:
                parsed = self._parse_json_from_response(ctx.llm_response)
                ctx.output_content = json.dumps(parsed, indent=2)
            except (json.JSONDecodeError, ValueError):
                ctx.output_content = ctx.llm_response
        else:
            ctx.output_content = ctx.llm_response

        # Emit to destination
        if destination == "log":
            log.info(
                "layer_output",
                topic=ctx.topic.key,
                layer=ctx.layer.name,
                content_length=len(ctx.output_content) if ctx.output_content else 0,
            )
        # Future: other destinations like channel, file, etc.

        log.debug(
            "output_complete",
            destination=destination,
            format=format_type,
        )

    async def _handle_synthesize_to_global(
        self, node: Node, ctx: ExecutionContext
    ) -> None:
        """Create global insight from server insights.

        Args:
            node: The node with params.
            ctx: The execution context.
        """
        params = node.params
        global_topic_key = params.get("global_topic")

        if not global_topic_key:
            # Derive global topic from server-scoped topic
            global_topic_key = self._extract_global_topic(ctx.topic.key)

        if not global_topic_key:
            log.warning(
                "cannot_synthesize_no_global_topic",
                topic=ctx.topic.key,
            )
            return

        if ctx.dry_run:
            log.debug(
                "synthesize_to_global_skipped_dry_run",
                topic=ctx.topic.key,
                global_topic=global_topic_key,
            )
            return

        # The actual synthesis happens via store_insight with the global topic
        # This node just updates the context for the next store_insight
        log.debug(
            "synthesize_to_global",
            source_topic=ctx.topic.key,
            global_topic=global_topic_key,
        )

    async def _handle_update_self_concept(
        self, node: Node, ctx: ExecutionContext
    ) -> None:
        """Conditionally update the self-concept document.

        Zos has autonomous control over its identity document. Updates happen
        without blocking approval - the operator reviews via git history
        retroactively. This is consistent with the phenomenological principle:
        Zos experiences and updates its own identity.

        Args:
            node: The node with params.
            ctx: The execution context.
        """
        params = node.params
        document_path = Path(params.get("document_path", "data/self-concept.md"))
        conditional = params.get("conditional", False)

        if not ctx.llm_response:
            log.warning("update_self_concept_no_response")
            return

        if ctx.dry_run:
            log.debug(
                "update_self_concept_skipped_dry_run",
                path=str(document_path),
            )
            return

        # If conditional, check if previous LLM call said to update
        if conditional:
            decision = self._parse_json_from_response(ctx.llm_response)
            if not decision:
                log.warning("could_not_parse_update_decision")
                return

            should_update = decision.get("should_update", False)
            reason = decision.get("reason", "No reason provided")

            if not should_update:
                log.info(
                    "self_concept_update_skipped",
                    reason=reason,
                )
                return

            log.info(
                "self_concept_update_approved",
                reason=reason,
                suggested_changes=decision.get("suggested_changes", ""),
            )

        # Generate the updated document via another LLM call
        update_prompt = self._render_concept_update_prompt(ctx, document_path)

        result = await self.llm.complete(
            prompt=update_prompt,
            model_profile="complex",
            max_tokens=2000,
            layer_run_id=ctx.run_id,
            topic_key=ctx.topic.key,
            call_type=LLMCallType.REFLECTION,
        )

        ctx.add_tokens(result.usage.input_tokens, result.usage.output_tokens)

        new_concept = result.text

        # Write the update
        document_path.write_text(new_concept)

        log.info(
            "self_concept_updated",
            path=str(document_path),
            content_length=len(new_concept),
        )

    def _render_concept_update_prompt(
        self, ctx: ExecutionContext, document_path: Path
    ) -> str:
        """Render prompt for generating updated self-concept.

        Args:
            ctx: The execution context with recent reflection.
            document_path: Path to the current self-concept document.

        Returns:
            Prompt string for generating the updated self-concept.
        """
        current = document_path.read_text() if document_path.exists() else ""

        # Get the decision with suggested changes if available
        decision = self._parse_json_from_response(ctx.llm_response) or {}
        suggested_changes = decision.get("suggested_changes", "")

        return f"""You are updating your self-concept document based on recent reflection.

Current document:
{current}

Suggested changes:
{suggested_changes}

Write the updated self-concept document. Preserve the overall structure but integrate new understanding. Keep what's still true, evolve what has changed, acknowledge new uncertainties.

The document should feel like *you* - not a clinical report, but a living expression of identity.

Begin the document with "# Self-Concept" and maintain the existing sections where appropriate. You may add new sections if your understanding has expanded in new directions."""

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _parse_insight_response(self, response: str) -> dict[str, Any]:
        """Parse JSON insight from LLM response.

        Attempts to extract JSON from the response. Falls back to treating
        the response as plain text content with default metrics if parsing fails.

        Args:
            response: The LLM response text.

        Returns:
            Dictionary with insight data including content, confidence, etc.
        """
        parsed = self._parse_json_from_response(response)
        if parsed and "content" in parsed:
            # Merge with defaults for any missing fields
            result = {**DEFAULT_METRICS, **parsed}
            return result

        # Fallback: use response as content with defaults
        log.debug("insight_parse_fallback", response_length=len(response))
        return {
            "content": response,
            **DEFAULT_METRICS,
        }

    def _parse_json_from_response(self, response: str) -> dict[str, Any] | None:
        """Extract JSON from response.

        Looks for JSON in code blocks first, then tries parsing the whole response.

        Args:
            response: The LLM response text.

        Returns:
            Parsed dictionary or None if parsing fails.
        """
        # Try to find JSON in code block
        json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find JSON without code block markers
        json_match = re.search(r"\{.*\}", response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        # Try parsing whole response as JSON
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return None

    def _determine_scope(self, messages: list[Message]) -> VisibilityScope:
        """Determine the maximum scope of source messages.

        Args:
            messages: List of source messages.

        Returns:
            The highest scope level present in messages.
        """
        if not messages:
            return VisibilityScope.PUBLIC

        for msg in messages:
            if msg.visibility_scope == VisibilityScope.DM:
                return VisibilityScope.DM

        return VisibilityScope.PUBLIC

    def _get_primary_model_profile(self, layer: Layer) -> str | None:
        """Get the primary model profile used by a layer.

        Looks for the first llm_call node and returns its model param.

        Args:
            layer: The layer to inspect.

        Returns:
            Model profile name or None.
        """
        for node in layer.nodes:
            if node.type == NodeType.LLM_CALL:
                return node.params.get("model", "simple")
        return None

    def _extract_global_topic(self, topic_key: str) -> str | None:
        """Extract global topic from server-scoped topic.

        E.g., server:123:user:456 -> user:456

        Args:
            topic_key: The server-scoped topic key.

        Returns:
            Global topic key or None if not applicable.
        """
        parts = topic_key.split(":")
        if len(parts) >= 4 and parts[0] == "server":
            # server:X:category:id -> category:id
            category = parts[2]
            if category in ("user", "dyad"):
                return ":".join(parts[2:])
        return None

    # =========================================================================
    # Database Operations
    # =========================================================================

    async def _get_topic(self, topic_key: str) -> Topic | None:
        """Get a topic by key.

        Args:
            topic_key: The topic key.

        Returns:
            Topic if found, None otherwise.
        """
        with self.engine.connect() as conn:
            result = conn.execute(
                select(topics_table).where(topics_table.c.key == topic_key)
            ).fetchone()

            if result is None:
                return None

            return Topic(
                key=result.key,
                category=TopicCategory(result.category),
                is_global=result.is_global,
                provisional=result.provisional,
                created_at=result.created_at,
                last_activity_at=result.last_activity_at,
                metadata=result.metadata,
            )

    async def _get_messages_for_topic(
        self,
        topic_key: str,
        since: datetime,
        limit: int,
    ) -> list[Message]:
        """Get messages for a topic based on topic type.

        Args:
            topic_key: The topic key.
            since: Only return messages after this time.
            limit: Maximum number of messages.

        Returns:
            List of Message objects.
        """
        parts = topic_key.split(":")
        category = self._extract_category(topic_key)

        with self.engine.connect() as conn:
            if category == "channel" and len(parts) >= 4:
                # server:X:channel:Y -> messages where channel_id == Y
                channel_id = parts[3]
                stmt = (
                    select(messages_table)
                    .where(
                        and_(
                            messages_table.c.channel_id == channel_id,
                            messages_table.c.created_at >= since,
                            messages_table.c.deleted_at.is_(None),
                        )
                    )
                    .order_by(messages_table.c.created_at.desc())
                    .limit(limit)
                )
            elif category == "user" and len(parts) >= 4:
                # server:X:user:Y -> messages by user Y in server X
                server_id = parts[1]
                user_id = parts[3]
                stmt = (
                    select(messages_table)
                    .where(
                        and_(
                            messages_table.c.author_id == user_id,
                            messages_table.c.server_id == server_id,
                            messages_table.c.created_at >= since,
                            messages_table.c.deleted_at.is_(None),
                        )
                    )
                    .order_by(messages_table.c.created_at.desc())
                    .limit(limit)
                )
            elif category == "dyad" and len(parts) >= 5:
                # server:X:dyad:A:B -> messages between A and B in server X
                server_id = parts[1]
                user_a = parts[3]
                user_b = parts[4]
                # Messages by A replying to B or B replying to A
                stmt = (
                    select(messages_table)
                    .where(
                        and_(
                            messages_table.c.server_id == server_id,
                            messages_table.c.author_id.in_([user_a, user_b]),
                            messages_table.c.created_at >= since,
                            messages_table.c.deleted_at.is_(None),
                        )
                    )
                    .order_by(messages_table.c.created_at.desc())
                    .limit(limit)
                )
            else:
                # Default: return empty list for unknown topic types
                return []

            rows = conn.execute(stmt).fetchall()

            return [
                Message(
                    id=row.id,
                    channel_id=row.channel_id,
                    server_id=row.server_id,
                    author_id=row.author_id,
                    content=row.content,
                    created_at=row.created_at,
                    visibility_scope=VisibilityScope(row.visibility_scope),
                    reactions_aggregate=(
                        json.loads(row.reactions_aggregate)
                        if row.reactions_aggregate and isinstance(row.reactions_aggregate, str)
                        else row.reactions_aggregate
                    ),
                    reply_to_id=row.reply_to_id,
                    thread_id=row.thread_id,
                    has_media=row.has_media,
                    has_links=row.has_links,
                    ingested_at=row.ingested_at,
                    deleted_at=row.deleted_at,
                )
                for row in rows
            ]

    def _get_media_analyses_for_messages(
        self, message_ids: list[str]
    ) -> dict[str, list[dict]]:
        """Batch-fetch media analyses for multiple messages.

        Args:
            message_ids: List of message IDs to query.

        Returns:
            Dictionary mapping message_id to list of media analysis dicts.
        """
        if not message_ids:
            return {}

        result_map: dict[str, list[dict]] = {}

        with self.engine.connect() as conn:
            rows = conn.execute(
                select(media_analysis_table).where(
                    media_analysis_table.c.message_id.in_(message_ids)
                )
            ).fetchall()

            for row in rows:
                entry = {
                    "media_type": row.media_type,
                    "filename": row.filename,
                    "description": row.description,
                    "width": row.width,
                    "height": row.height,
                }
                if row.message_id not in result_map:
                    result_map[row.message_id] = []
                result_map[row.message_id].append(entry)

        return result_map

    def _extract_category(self, topic_key: str) -> str:
        """Extract category from topic key.

        Args:
            topic_key: The topic key string.

        Returns:
            Category string (e.g., "user", "channel").
        """
        parts = topic_key.split(":")
        if parts[0] == "server" and len(parts) >= 3:
            return parts[2]
        return parts[0]

    async def _get_layer_runs(
        self,
        limit: int = 10,
        layer_name: str | None = None,
        since_days: int = 7,
        include_errors: bool = True,
    ) -> list[LayerRun]:
        """Get recent layer runs for self-reflection.

        Retrieves layer run records for operational context in self-reflection.
        Errors provide material for understanding friction in operation.

        Args:
            limit: Maximum number of runs.
            layer_name: Optional filter by layer name.
            since_days: Only include runs from the last N days.
            include_errors: Whether to include runs with errors.

        Returns:
            List of LayerRun objects.
        """
        since = utcnow() - timedelta(days=since_days)

        with self.engine.connect() as conn:
            # Build base query with time filter
            conditions = [layer_runs_table.c.started_at >= since]

            if layer_name:
                conditions.append(layer_runs_table.c.layer_name == layer_name)

            stmt = (
                select(layer_runs_table)
                .where(and_(*conditions))
                .order_by(layer_runs_table.c.started_at.desc())
                .limit(limit)
            )

            rows = conn.execute(stmt).fetchall()

            runs = [
                LayerRun(
                    id=row.id,
                    layer_name=row.layer_name,
                    layer_hash=row.layer_hash,
                    started_at=row.started_at,
                    completed_at=row.completed_at,
                    status=LayerRunStatus(row.status),
                    targets_matched=row.targets_matched,
                    targets_processed=row.targets_processed,
                    targets_skipped=row.targets_skipped,
                    insights_created=row.insights_created,
                    model_profile=row.model_profile,
                    model_provider=row.model_provider,
                    model_name=row.model_name,
                    tokens_input=row.tokens_input,
                    tokens_output=row.tokens_output,
                    tokens_total=row.tokens_total,
                    estimated_cost_usd=row.estimated_cost_usd,
                    errors=row.errors if include_errors else None,
                )
                for row in rows
            ]

            return runs

    async def _insert_layer_run(self, run: LayerRun) -> None:
        """Insert a layer run record.

        Args:
            run: The LayerRun to insert.
        """
        with self.engine.connect() as conn:
            conn.execute(
                layer_runs_table.insert().values(
                    id=run.id,
                    layer_name=run.layer_name,
                    layer_hash=run.layer_hash,
                    started_at=run.started_at,
                    completed_at=run.completed_at,
                    status=run.status.value,
                    targets_matched=run.targets_matched,
                    targets_processed=run.targets_processed,
                    targets_skipped=run.targets_skipped,
                    insights_created=run.insights_created,
                    model_profile=run.model_profile,
                    model_provider=run.model_provider,
                    model_name=run.model_name,
                    tokens_input=run.tokens_input,
                    tokens_output=run.tokens_output,
                    tokens_total=run.tokens_total,
                    estimated_cost_usd=run.estimated_cost_usd,
                    errors=run.errors,
                )
            )
            conn.commit()

        log.debug(
            "layer_run_inserted",
            run_id=run.id,
            layer=run.layer_name,
            status=run.status.value,
        )

    async def _update_layer_run(self, run: LayerRun) -> None:
        """Update a layer run record with final stats.

        Args:
            run: The LayerRun to update.
        """
        with self.engine.connect() as conn:
            conn.execute(
                layer_runs_table.update()
                .where(layer_runs_table.c.id == run.id)
                .values(
                    completed_at=run.completed_at,
                    status=run.status.value,
                    targets_matched=run.targets_matched,
                    targets_processed=run.targets_processed,
                    targets_skipped=run.targets_skipped,
                    insights_created=run.insights_created,
                    model_provider=run.model_provider,
                    model_name=run.model_name,
                    tokens_input=run.tokens_input,
                    tokens_output=run.tokens_output,
                    tokens_total=run.tokens_total,
                    estimated_cost_usd=run.estimated_cost_usd,
                    errors=run.errors,
                )
            )
            conn.commit()

        log.debug(
            "layer_run_updated",
            run_id=run.id,
            layer=run.layer_name,
            status=run.status.value,
        )
