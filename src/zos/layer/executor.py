"""Pipeline executor for layer execution.

The PipelineExecutor is responsible for orchestrating the execution of
layer pipelines, handling for_each expansion, error recovery, and
budget enforcement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from zos.budget.ledger import TokenLedger
from zos.discord.repository import MessageRepository
from zos.layer.context import PipelineContext
from zos.layer.nodes import create_node
from zos.layer.nodes.base import BaseNode
from zos.layer.schema import LayerDefinition
from zos.logging import get_logger
from zos.salience.repository import SalienceRepository
from zos.topics.topic_key import TopicCategory, TopicKey

if TYPE_CHECKING:
    from zos.budget.models import AllocationPlan
    from zos.config import ZosConfig
    from zos.db import Database
    from zos.llm.client import LLMClient

logger = get_logger("layer.executor")


@dataclass
class ExecutionResult:
    """Result of pipeline execution."""

    success: bool
    run_id: str
    layer_name: str
    targets_processed: int
    targets_skipped: int
    total_tokens: int
    errors: list[str]
    trace: list[dict[str, Any]]
    started_at: datetime
    completed_at: datetime

    @property
    def duration_seconds(self) -> float:
        """Execution duration in seconds."""
        return (self.completed_at - self.started_at).total_seconds()


@dataclass
class PipelineExecutor:
    """Executes layer pipelines.

    The executor handles:
    - Loading and instantiating nodes
    - for_each expansion over targets
    - Budget checking and spending
    - Error handling and partial completion
    - Execution tracing
    """

    db: Database
    llm_client: LLMClient
    config: ZosConfig
    _message_repo: MessageRepository = field(init=False, repr=False)
    _salience_repo: SalienceRepository = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Initialize repositories."""
        self._message_repo = MessageRepository(self.db)
        self._salience_repo = SalienceRepository(self.db)

    async def execute(
        self,
        layer: LayerDefinition,
        allocation_plan: AllocationPlan,
        dry_run: bool = False,
    ) -> ExecutionResult:
        """Execute a layer pipeline.

        Args:
            layer: The layer definition to execute.
            allocation_plan: Budget allocation for this run.
            dry_run: If True, validate only without executing.

        Returns:
            ExecutionResult with details of the execution.
        """
        run_id = allocation_plan.run_id
        started_at = datetime.now(UTC)

        logger.info(f"Starting layer execution: {layer.name} (run_id={run_id})")

        # Create token ledger
        ledger = TokenLedger(self.db)
        if not dry_run:
            ledger.load_plan(allocation_plan)

        # Create base context
        context = PipelineContext(
            run_id=run_id,
            layer_name=layer.name,
            run_start=started_at,
            db=self.db,
            llm_client=self.llm_client,
            message_repo=self._message_repo,
            salience_repo=self._salience_repo,
            token_ledger=ledger,
            model_defaults=layer.model_defaults,
        )

        # Build node instances
        nodes = [create_node(nc) for nc in layer.pipeline.nodes]

        # Resolve targets from allocation plan
        targets = self._resolve_targets(layer, allocation_plan)
        logger.debug(f"Resolved {len(targets)} targets for {layer.name}")

        total_tokens = 0
        targets_processed = 0
        targets_skipped = 0
        errors: list[str] = []

        if layer.pipeline.for_each == "target":
            # Execute pipeline for each target
            target_outputs: list[str] = []

            for topic in targets:
                target_result = await self._execute_for_target(
                    context=context,
                    nodes=nodes,
                    topic=topic,
                    ledger=ledger,
                    layer=layer,
                    dry_run=dry_run,
                )

                total_tokens += target_result["tokens"]
                if target_result["skipped"]:
                    targets_skipped += 1
                else:
                    targets_processed += 1
                errors.extend(target_result["errors"])

                if output := target_result.get("output"):
                    target_outputs.append(output)

            # Store outputs for potential reduce step
            context.set("target_outputs", target_outputs)

        else:
            # Single execution (no for_each)
            single_result = await self._execute_nodes(
                context=context,
                nodes=nodes,
                dry_run=dry_run,
            )
            total_tokens = single_result["tokens"]
            errors = single_result["errors"]
            targets_processed = 1 if single_result["success"] else 0

        completed_at = datetime.now(UTC)

        result = ExecutionResult(
            success=len(errors) == 0,
            run_id=run_id,
            layer_name=layer.name,
            targets_processed=targets_processed,
            targets_skipped=targets_skipped,
            total_tokens=total_tokens,
            errors=errors,
            trace=context.get_trace(),
            started_at=started_at,
            completed_at=completed_at,
        )

        logger.info(
            f"Layer execution completed: {layer.name} "
            f"(processed={targets_processed}, skipped={targets_skipped}, "
            f"tokens={total_tokens}, duration={result.duration_seconds:.2f}s)"
        )

        return result

    async def _execute_for_target(
        self,
        context: PipelineContext,
        nodes: list[BaseNode],
        topic: TopicKey,
        ledger: TokenLedger,
        layer: LayerDefinition,
        dry_run: bool,
    ) -> dict[str, Any]:
        """Execute pipeline for a single target.

        Returns dict with keys: tokens, skipped, errors, output, success
        """
        # Check if topic has any budget
        min_tokens = 100  # Minimum threshold
        if not dry_run and not ledger.can_afford(topic, min_tokens):
            remaining = ledger.get_remaining(topic)
            context.add_trace(
                f"skip_target:{topic.key}",
                success=True,
                skipped=True,
                skip_reason=f"Insufficient budget (remaining={remaining})",
            )
            logger.debug(f"Skipping target {topic.key}: insufficient budget")
            return {"tokens": 0, "skipped": True, "errors": [], "success": True}

        # Fork context for this target
        target_context = context.fork_for_target(topic)

        # Execute nodes
        result = await self._execute_nodes(
            context=target_context,
            nodes=nodes,
            dry_run=dry_run,
        )

        # Apply salience spending if configured
        if not dry_run and result["success"] and layer.salience_rules.spend_per_target > 0:
            self._salience_repo.spend(
                topic_key=topic,
                amount=layer.salience_rules.spend_per_target,
                run_id=context.run_id,
                layer=layer.name,
            )

        result["output"] = target_context.get("llm_output", "")
        result["skipped"] = False
        return result

    async def _execute_nodes(
        self,
        context: PipelineContext,
        nodes: list[BaseNode],
        dry_run: bool,
    ) -> dict[str, Any]:
        """Execute a sequence of nodes.

        Returns dict with keys: tokens, errors, success
        """
        total_tokens = 0
        errors: list[str] = []

        for node in nodes:
            if dry_run:
                # Validate only
                validation_errors = node.validate(context)
                if validation_errors:
                    errors.extend(validation_errors)
                    context.add_trace(
                        node.name,
                        success=False,
                        error="; ".join(validation_errors),
                    )
                    break

                logger.info(f"[DRY-RUN] Would execute: {node.name}")
                context.add_trace(
                    node.name,
                    success=True,
                    skipped=True,
                    skip_reason="Dry run",
                )
                continue

            try:
                result = await node.execute(context)

                context.add_trace(
                    node.name,
                    success=result.success,
                    skipped=result.skipped,
                    skip_reason=result.skip_reason,
                    tokens_used=result.tokens_used,
                    error=result.error,
                )

                total_tokens += result.tokens_used

                if not result.success:
                    errors.append(f"{node.name}: {result.error}")
                    logger.warning(f"Node {node.name} failed: {result.error}")
                    break

            except Exception as e:
                error_msg = f"{node.name}: {str(e)}"
                errors.append(error_msg)
                logger.error(f"Node {node.name} raised exception: {e}")
                context.add_trace(
                    node.name,
                    success=False,
                    error=str(e),
                )
                break

        return {
            "tokens": total_tokens,
            "errors": errors,
            "success": len(errors) == 0,
        }

    def _resolve_targets(
        self,
        layer: LayerDefinition,
        plan: AllocationPlan,
    ) -> list[TopicKey]:
        """Resolve target topics from layer config and allocation plan.

        Filters by:
        - Configured target categories
        - Minimum salience threshold
        - Maximum targets per category
        """
        targets: list[TopicKey] = []

        for cat_name in layer.targets.categories:
            try:
                category = TopicCategory(cat_name)
            except ValueError:
                logger.warning(f"Unknown category in targets: {cat_name}")
                continue

            cat_alloc = plan.category_allocations.get(category)
            if not cat_alloc:
                logger.debug(f"No allocation for category: {category}")
                continue

            category_targets: list[TopicKey] = []

            for topic_alloc in cat_alloc.topic_allocations:
                # Check minimum salience
                if topic_alloc.salience_balance < layer.targets.min_salience:
                    continue

                category_targets.append(topic_alloc.topic_key)

                # Check max targets
                if (
                    layer.targets.max_targets
                    and len(category_targets) >= layer.targets.max_targets
                ):
                    break

            targets.extend(category_targets)

        return targets

    async def validate_layer(
        self,
        layer: LayerDefinition,
    ) -> list[str]:
        """Validate a layer definition without executing.

        Args:
            layer: The layer to validate.

        Returns:
            List of validation error messages.
        """
        errors: list[str] = []

        # Check target categories
        valid_categories = {c.value for c in TopicCategory}
        for cat in layer.targets.categories:
            if cat not in valid_categories:
                errors.append(f"Invalid target category: {cat}")

        # Check node configurations
        for node_config in layer.pipeline.nodes:
            try:
                create_node(node_config)
            except Exception as e:
                errors.append(f"Invalid node config ({node_config.type}): {e}")

        return errors
