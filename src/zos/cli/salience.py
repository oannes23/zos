"""Zos CLI commands."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta

from zos.budget import BudgetAllocator
from zos.config import BudgetConfig, get_config
from zos.db import get_db, init_db
from zos.salience.repository import SalienceRepository
from zos.topics.topic_key import TopicCategory, TopicKey


def cmd_top(args: argparse.Namespace) -> None:
    """Show top topics by salience balance."""
    init_db()
    db = get_db()
    repo = SalienceRepository(db)

    try:
        category = TopicCategory(args.category)
    except ValueError:
        valid = [c.value for c in TopicCategory]
        print(f"Invalid category: {args.category}")
        print(f"Valid categories: {', '.join(valid)}")
        return

    since = None
    if args.since:
        try:
            since = datetime.fromisoformat(args.since).replace(tzinfo=UTC)
        except ValueError:
            print(f"Invalid date format: {args.since}")
            print("Use ISO format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS")
            return

    if args.days:
        since = datetime.now(UTC) - timedelta(days=args.days)

    results = repo.get_top_by_category(category, limit=args.limit, since=since)

    if not results:
        print(f"No salience data for category: {category.value}")
        return

    # Print header
    print(f"\nTop {len(results)} {category.value} topics by salience balance")
    if since:
        print(f"(since {since.strftime('%Y-%m-%d %H:%M:%S')} UTC)")
    print("-" * 60)
    print(f"{'Rank':<6} {'Topic Key':<35} {'Balance':>10}")
    print("-" * 60)

    for i, result in enumerate(results, 1):
        print(f"{i:<6} {result.topic_key:<35} {result.balance:>10.2f}")

    print("-" * 60)


def cmd_balance(args: argparse.Namespace) -> None:
    """Show balance for a specific topic key."""
    init_db()
    db = get_db()
    repo = SalienceRepository(db)

    try:
        topic_key = TopicKey.parse(args.topic_key)
    except ValueError as e:
        print(f"Invalid topic key: {e}")
        print("Format: category:id[:id2[:id3]]")
        print("Examples: user:123, channel:456, dyad:100:200")
        return

    balance = repo.get_balance(topic_key)
    earned = repo.get_total_earned(topic_key)
    spent = repo.get_total_spent(topic_key)

    print(f"\nSalience for {topic_key.key}")
    print("-" * 40)
    print(f"  Earned:  {earned:>10.2f}")
    print(f"  Spent:   {spent:>10.2f}")
    print(f"  Balance: {balance:>10.2f}")
    print("-" * 40)


def cmd_budget_preview(args: argparse.Namespace) -> None:
    """Preview budget allocation without persisting."""
    init_db()
    db = get_db()
    config = get_config()

    # Allow CLI override of total tokens
    budget_config = config.budget
    if args.total_tokens:
        budget_config = BudgetConfig(
            total_tokens_per_run=args.total_tokens,
            per_topic_cap=config.budget.per_topic_cap,
            category_weights=config.budget.category_weights,
        )

    allocator = BudgetAllocator(db, budget_config)

    since = None
    if args.days:
        since = datetime.now(UTC) - timedelta(days=args.days)

    plan = allocator.create_allocation_plan(since=since)

    print("\nBudget Allocation Preview")
    print(f"Run ID: {plan.run_id}")
    print(f"Total Budget: {plan.total_budget:,} tokens")
    print(f"Per-Topic Cap: {plan.per_topic_cap:,} tokens")
    print("=" * 70)

    total_allocated = 0
    for category in TopicCategory:
        cat_alloc = plan.category_allocations.get(category)
        if not cat_alloc:
            continue

        print(f"\n{category.value.upper()} (weight: {cat_alloc.weight}, budget: {cat_alloc.total_tokens:,})")
        print("-" * 50)

        if not cat_alloc.topic_allocations:
            print("  (no topics with salience)")
            continue

        for alloc in cat_alloc.topic_allocations[:10]:  # Top 10
            print(
                f"  {alloc.topic_key.key:<35} "
                f"{alloc.allocated_tokens:>8,} tokens "
                f"({alloc.salience_proportion*100:>5.1f}%)"
            )
            total_allocated += alloc.allocated_tokens

        if len(cat_alloc.topic_allocations) > 10:
            remaining = len(cat_alloc.topic_allocations) - 10
            remaining_tokens = sum(
                a.allocated_tokens for a in cat_alloc.topic_allocations[10:]
            )
            total_allocated += remaining_tokens
            print(f"  ... and {remaining} more topics ({remaining_tokens:,} tokens)")

    print("\n" + "=" * 70)
    print(f"Total Allocated: {total_allocated:,} tokens")
    print(f"Unallocated: {plan.total_budget - total_allocated:,} tokens")


def cmd_llm_test(args: argparse.Namespace) -> None:
    """Test an LLM provider connection."""
    from zos.llm import Message, MessageRole
    from zos.llm.resolver import get_available_providers

    config = get_config()
    if not config.llm:
        print("Error: LLM configuration not found in config")
        print("Add an 'llm' section to your config.yml")
        return

    provider_name = args.provider or config.llm.default_provider
    model = args.model

    # Check if provider is configured
    available = get_available_providers(config.llm)
    if provider_name not in available and provider_name not in config.llm.generic:
        print(f"Error: Provider '{provider_name}' is not configured")
        print(f"Available providers: {', '.join(available) or '(none)'}")
        return

    # Create provider instance
    try:
        if provider_name == "openai":
            from zos.llm.providers.openai import OpenAIProvider

            if not config.llm.openai:
                print("Error: OpenAI provider not configured")
                return
            provider = OpenAIProvider(config.llm.openai)
        elif provider_name == "anthropic":
            from zos.llm.providers.anthropic import AnthropicProvider

            if not config.llm.anthropic:
                print("Error: Anthropic provider not configured")
                return
            provider = AnthropicProvider(config.llm.anthropic)
        elif provider_name == "ollama":
            from zos.llm.providers.ollama import OllamaProvider

            if not config.llm.ollama:
                print("Error: Ollama provider not configured")
                return
            provider = OllamaProvider(config.llm.ollama)
        elif provider_name in config.llm.generic:
            from zos.llm.providers.generic import GenericHTTPProvider

            provider = GenericHTTPProvider(
                config.llm.generic[provider_name],
                provider_name,
            )
        else:
            print(f"Error: Unknown provider '{provider_name}'")
            return
    except Exception as e:
        print(f"Error creating provider: {e}")
        return

    # Build test message
    prompt = args.prompt or "Say hello in exactly 5 words."
    messages = [Message(role=MessageRole.USER, content=prompt)]

    print(f"\nTesting {provider_name} provider...")
    print(f"Model: {model or provider.default_model}")
    print(f"Prompt: {prompt}")
    print("-" * 50)

    async def do_test() -> None:
        try:
            response = await provider.complete(
                messages,
                model=model,
                max_tokens=args.max_tokens,
                temperature=0.7,
            )

            print(f"Response: {response.content}")
            print("-" * 50)
            print(f"Model: {response.model}")
            print(f"Prompt tokens: {response.prompt_tokens}")
            print(f"Completion tokens: {response.completion_tokens}")
            print(f"Total tokens: {response.prompt_tokens + response.completion_tokens}")
            print(f"Finish reason: {response.finish_reason}")

            cost = provider.estimate_cost(
                response.model,
                response.prompt_tokens,
                response.completion_tokens,
            )
            if cost is not None:
                print(f"Estimated cost: ${cost:.6f}")
            else:
                print("Estimated cost: (unknown pricing)")

        except Exception as e:
            print(f"Error: {e}")
        finally:
            if hasattr(provider, "close"):
                await provider.close()

    asyncio.run(do_test())


def cmd_llm_list(_args: argparse.Namespace) -> None:
    """List configured LLM providers."""
    config = get_config()
    if not config.llm:
        print("LLM configuration not found in config")
        return

    print("\nConfigured LLM Providers")
    print("=" * 50)

    default = config.llm.default_provider

    # OpenAI
    status = "✓ configured" if config.llm.openai and config.llm.openai.api_key else "✗ not configured"
    default_marker = " (default)" if default == "openai" else ""
    if config.llm.openai:
        model = config.llm.openai.default_model
        print(f"\nopenai{default_marker}")
        print(f"  Status: {status}")
        print(f"  Default model: {model}")
        print(f"  Base URL: {config.llm.openai.base_url}")
    else:
        print(f"\nopenai{default_marker}: {status}")

    # Anthropic
    status = "✓ configured" if config.llm.anthropic and config.llm.anthropic.api_key else "✗ not configured"
    default_marker = " (default)" if default == "anthropic" else ""
    if config.llm.anthropic:
        model = config.llm.anthropic.default_model
        print(f"\nanthropic{default_marker}")
        print(f"  Status: {status}")
        print(f"  Default model: {model}")
    else:
        print(f"\nanthropic{default_marker}: {status}")

    # Ollama
    status = "✓ configured" if config.llm.ollama else "✗ not configured"
    default_marker = " (default)" if default == "ollama" else ""
    if config.llm.ollama:
        model = config.llm.ollama.default_model
        print(f"\nollama{default_marker}")
        print(f"  Status: {status}")
        print(f"  Default model: {model}")
        print(f"  Base URL: {config.llm.ollama.base_url}")
    else:
        print(f"\nollama{default_marker}: {status}")

    # Generic providers
    if config.llm.generic:
        for name, generic_config in config.llm.generic.items():
            default_marker = " (default)" if default == name else ""
            print(f"\n{name}{default_marker} (generic)")
            print("  Status: ✓ configured")
            print(f"  Default model: {generic_config.default_model}")
            print(f"  Base URL: {generic_config.base_url}")

    print("\n" + "=" * 50)
    if config.llm.default_model:
        print(f"Global default model: {config.llm.default_model}")
    print(f"Default provider: {default}")


def cmd_layer_validate(args: argparse.Namespace) -> None:
    """Validate a layer definition."""
    config = get_config()

    from zos.layer import LayerLoader

    loader = LayerLoader(config.layers_dir)
    errors = loader.validate(args.layer_name)

    if errors:
        print(f"\nValidation FAILED for layer '{args.layer_name}':")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)
    else:
        print(f"\nLayer '{args.layer_name}' is valid.")

        # Show layer summary
        try:
            layer = loader.load(args.layer_name)
            print("\nLayer Summary:")
            print(f"  Name: {layer.name}")
            if layer.description:
                print(f"  Description: {layer.description}")
            if layer.schedule:
                print(f"  Schedule: {layer.schedule}")
            print(f"  Target categories: {', '.join(layer.targets.categories)}")
            print(f"  Pipeline nodes: {len(layer.pipeline.nodes)}")
            if layer.pipeline.for_each:
                print(f"  Execution: for_each {layer.pipeline.for_each}")
        except Exception as e:
            print(f"  (could not load layer details: {e})")


def cmd_layer_list(_args: argparse.Namespace) -> None:
    """List available layers."""
    config = get_config()

    from zos.layer import LayerLoader

    loader = LayerLoader(config.layers_dir)
    layer_names = loader.list_layers()

    if not layer_names:
        print(f"\nNo layers found in {config.layers_dir}")
        return

    print(f"\nAvailable layers in {config.layers_dir}:")
    print("-" * 50)

    for name in sorted(layer_names):
        try:
            layer = loader.load(name)
            desc = layer.description or "(no description)"
            print(f"  {name:<20} {desc}")
        except Exception as e:
            print(f"  {name:<20} (error: {e})")


def cmd_layer_dry_run(args: argparse.Namespace) -> None:
    """Dry-run a layer without making LLM calls."""
    init_db()
    db = get_db()
    config = get_config()

    from zos.budget import BudgetAllocator
    from zos.layer import LayerLoader, PipelineExecutor
    from zos.llm.client import LLMClient

    loader = LayerLoader(config.layers_dir)

    try:
        layer = loader.load(args.layer_name)
    except Exception as e:
        print(f"Error loading layer: {e}")
        sys.exit(1)

    # Create allocation plan
    allocator = BudgetAllocator(db, config.budget)

    since = None
    if args.days:
        since = datetime.now(UTC) - timedelta(days=args.days)

    plan = allocator.create_allocation_plan(since=since)

    # Filter to specific topic if provided
    if args.topic:
        topic = TopicKey.parse(args.topic)
        # Filter plan to just this topic by modifying allocations
        for _cat, cat_alloc in plan.category_allocations.items():
            cat_alloc.topic_allocations = [
                a for a in cat_alloc.topic_allocations if a.topic_key == topic
            ]

    # Create executor with dummy LLM client (won't be used in dry-run)
    # We need a valid LLM config, but it won't make actual calls
    if config.llm:
        llm_client = LLMClient(config.llm, db, config.layers_dir)
    else:
        # Create minimal mock for dry-run
        print("Warning: No LLM config found, dry-run will skip LLM validation")
        llm_client = None

    if llm_client is None:
        print("Error: LLM client required for dry-run (even though no calls are made)")
        sys.exit(1)

    executor = PipelineExecutor(db=db, llm_client=llm_client, config=config)

    async def run() -> None:
        result = await executor.execute(layer, plan, dry_run=True)

        print(f"\nDry-run: {layer.name}")
        print(f"Run ID: {result.run_id}")
        print("-" * 50)
        print(f"Targets: {result.targets_processed} processed, {result.targets_skipped} skipped")
        print(f"Duration: {result.duration_seconds:.2f}s")

        if result.trace:
            print("\nExecution Trace:")
            for entry in result.trace:
                status = "OK" if entry["success"] else "FAIL"
                if entry["skipped"]:
                    status = "SKIP"
                topic_str = f" ({entry['topic']})" if entry.get("topic") else ""
                print(f"  [{status}] {entry['node']}{topic_str}")
                if entry.get("skip_reason"):
                    print(f"         Reason: {entry['skip_reason']}")
                if entry.get("error"):
                    print(f"         Error: {entry['error']}")

        if result.errors:
            print("\nErrors:")
            for error in result.errors:
                print(f"  - {error}")
            sys.exit(1)
        else:
            print("\nDry-run completed successfully.")

    asyncio.run(run())


def cmd_layer_run(args: argparse.Namespace) -> None:
    """Run a layer manually."""
    init_db()
    db = get_db()
    config = get_config()

    from zos.layer import LayerLoader
    from zos.llm.client import LLMClient
    from zos.scheduler.models import TriggerType
    from zos.scheduler.run_manager import RunManager

    # Check for LLM config
    if not config.llm:
        print("Error: LLM configuration required to run layers")
        sys.exit(1)

    loader = LayerLoader(config.layers_dir)
    llm_client = LLMClient(config.llm, db, config.layers_dir)

    # Verify layer exists
    try:
        loader.load(args.layer_name)
    except Exception as e:
        print(f"Error loading layer: {e}")
        sys.exit(1)

    run_manager = RunManager(
        db=db,
        llm_client=llm_client,
        config=config,
        layer_loader=loader,
    )

    async def do_run() -> None:
        print(f"\nRunning layer: {args.layer_name}")
        print("-" * 50)

        result = await run_manager.execute_layer(
            layer_name=args.layer_name,
            triggered_by=TriggerType.MANUAL,
            dry_run=args.dry_run,
        )

        if result is None:
            print("Run skipped: layer is already running")
            return

        print(f"\nRun ID: {result.run_id}")
        print(f"Status: {result.status.value}")
        print(f"Window: {result.window_start.isoformat()} to {result.window_end.isoformat()}")
        print("-" * 50)
        print(f"Targets: {result.targets_processed} processed, {result.targets_skipped} skipped")
        print(f"Tokens used: {result.tokens_used:,}")
        if result.estimated_cost_usd > 0:
            print(f"Estimated cost: ${result.estimated_cost_usd:.4f}")
        if result.duration_seconds:
            print(f"Duration: {result.duration_seconds:.2f}s")

        if result.error_message:
            print(f"\nError: {result.error_message}")
            sys.exit(1)
        else:
            print("\nRun completed successfully.")

    asyncio.run(do_run())


def cmd_runs_list(args: argparse.Namespace) -> None:
    """List runs with optional filters."""
    init_db()
    db = get_db()

    from zos.scheduler.models import RunStatus
    from zos.scheduler.repository import RunRepository

    repo = RunRepository(db)

    status = None
    if args.status:
        try:
            status = RunStatus(args.status)
        except ValueError:
            valid = [s.value for s in RunStatus]
            print(f"Invalid status: {args.status}")
            print(f"Valid statuses: {', '.join(valid)}")
            return

    runs = repo.get_runs(
        layer_name=args.layer,
        status=status,
        limit=args.limit,
    )

    if not runs:
        print("\nNo runs found.")
        return

    print(f"\n{'Run ID':<36} {'Layer':<20} {'Status':<10} {'Started':<20} {'Targets':>8}")
    print("-" * 100)

    for run in runs:
        started = run.started_at.strftime("%Y-%m-%d %H:%M:%S")
        targets = f"{run.targets_processed}/{run.targets_total}"
        print(f"{run.run_id:<36} {run.layer_name:<20} {run.status.value:<10} {started:<20} {targets:>8}")

    print("-" * 100)
    print(f"Showing {len(runs)} runs")


def cmd_runs_show(args: argparse.Namespace) -> None:
    """Show details of a specific run."""
    init_db()
    db = get_db()

    from zos.scheduler.repository import RunRepository

    repo = RunRepository(db)
    run = repo.get_run(args.run_id)

    if run is None:
        print(f"Run not found: {args.run_id}")
        sys.exit(1)

    print(f"\nRun: {run.run_id}")
    print("=" * 60)
    print(f"Layer: {run.layer_name}")
    print(f"Status: {run.status.value}")
    print(f"Triggered by: {run.triggered_by.value}")
    if run.schedule_expression:
        print(f"Schedule: {run.schedule_expression}")
    print()
    print(f"Started: {run.started_at.isoformat()}")
    if run.completed_at:
        print(f"Completed: {run.completed_at.isoformat()}")
        print(f"Duration: {run.duration_seconds:.2f}s")
    print()
    print(f"Window: {run.window_start.isoformat()} to {run.window_end.isoformat()}")
    print()
    print(f"Targets total: {run.targets_total}")
    print(f"Targets processed: {run.targets_processed}")
    print(f"Targets skipped: {run.targets_skipped}")
    print()
    print(f"Tokens used: {run.tokens_used:,}")
    print(f"Estimated cost: ${run.estimated_cost_usd:.4f}")
    print(f"Salience spent: {run.salience_spent:.2f}")

    if run.error_message:
        print()
        print(f"Error: {run.error_message}")

    # Show trace if requested
    if args.trace:
        trace = repo.get_trace(run.run_id)
        if trace:
            print()
            print("Execution Trace:")
            print("-" * 60)
            for entry in trace:
                status = "OK" if entry.success else "FAIL"
                if entry.skipped:
                    status = "SKIP"
                topic_str = f" ({entry.topic_key})" if entry.topic_key else ""
                print(f"  [{status}] {entry.node_name}{topic_str}")
                if entry.skip_reason:
                    print(f"         Reason: {entry.skip_reason}")
                if entry.error:
                    print(f"         Error: {entry.error}")
                if entry.tokens_used > 0:
                    print(f"         Tokens: {entry.tokens_used}")
        else:
            print("\nNo trace entries found.")


def create_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="zos.cli",
        description="Zos CLI tools",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # salience command
    salience_parser = subparsers.add_parser("salience", help="Salience management")
    salience_subparsers = salience_parser.add_subparsers(
        dest="subcommand", help="Salience subcommands"
    )

    # salience top
    top_parser = salience_subparsers.add_parser(
        "top", help="Show top topics by salience"
    )
    top_parser.add_argument(
        "--category",
        "-c",
        required=True,
        help="Topic category (user, channel, user_in_channel, dyad, dyad_in_channel)",
    )
    top_parser.add_argument(
        "--limit", "-l", type=int, default=10, help="Number of results (default: 10)"
    )
    top_parser.add_argument(
        "--since", "-s", help="Only count salience since this date (YYYY-MM-DD)"
    )
    top_parser.add_argument(
        "--days", "-d", type=int, help="Only count salience from last N days"
    )
    top_parser.set_defaults(func=cmd_top)

    # salience balance
    balance_parser = salience_subparsers.add_parser(
        "balance", help="Show balance for a topic"
    )
    balance_parser.add_argument("topic_key", help="Topic key (e.g., user:123)")
    balance_parser.set_defaults(func=cmd_balance)

    # budget command
    budget_parser = subparsers.add_parser("budget", help="Budget allocation")
    budget_subparsers = budget_parser.add_subparsers(
        dest="subcommand", help="Budget subcommands"
    )

    # budget preview
    preview_parser = budget_subparsers.add_parser(
        "preview", help="Preview budget allocation"
    )
    preview_parser.add_argument(
        "--days", "-d", type=int, help="Only consider salience from last N days"
    )
    preview_parser.add_argument(
        "--total-tokens",
        "-t",
        type=int,
        help="Override total token budget (default from config)",
    )
    preview_parser.set_defaults(func=cmd_budget_preview)

    # llm command
    llm_parser = subparsers.add_parser("llm", help="LLM provider management")
    llm_subparsers = llm_parser.add_subparsers(
        dest="subcommand", help="LLM subcommands"
    )

    # llm test
    llm_test_parser = llm_subparsers.add_parser(
        "test", help="Test an LLM provider connection"
    )
    llm_test_parser.add_argument(
        "--provider", "-p", help="Provider to test (default: from config)"
    )
    llm_test_parser.add_argument(
        "--model", "-m", help="Model to use (default: provider default)"
    )
    llm_test_parser.add_argument(
        "--prompt", help="Test prompt to send (default: 'Say hello in exactly 5 words.')"
    )
    llm_test_parser.add_argument(
        "--max-tokens", "-t", type=int, default=100, help="Max tokens (default: 100)"
    )
    llm_test_parser.set_defaults(func=cmd_llm_test)

    # llm list
    llm_list_parser = llm_subparsers.add_parser(
        "list", help="List configured LLM providers"
    )
    llm_list_parser.set_defaults(func=cmd_llm_list)

    # layer command
    layer_parser = subparsers.add_parser("layer", help="Layer management")
    layer_subparsers = layer_parser.add_subparsers(
        dest="subcommand", help="Layer subcommands"
    )

    # layer validate
    layer_validate_parser = layer_subparsers.add_parser(
        "validate", help="Validate a layer definition"
    )
    layer_validate_parser.add_argument("layer_name", help="Layer directory name")
    layer_validate_parser.set_defaults(func=cmd_layer_validate)

    # layer list
    layer_list_parser = layer_subparsers.add_parser(
        "list", help="List available layers"
    )
    layer_list_parser.set_defaults(func=cmd_layer_list)

    # layer dry-run
    layer_dry_run_parser = layer_subparsers.add_parser(
        "dry-run", help="Dry-run a layer without making LLM calls"
    )
    layer_dry_run_parser.add_argument("layer_name", help="Layer to run")
    layer_dry_run_parser.add_argument(
        "--topic", "-t", help="Specific topic to process (e.g., channel:123)"
    )
    layer_dry_run_parser.add_argument(
        "--days", "-d", type=int, help="Only consider salience from last N days"
    )
    layer_dry_run_parser.set_defaults(func=cmd_layer_dry_run)

    # layer run
    layer_run_parser = layer_subparsers.add_parser(
        "run", help="Run a layer manually"
    )
    layer_run_parser.add_argument("layer_name", help="Layer to run")
    layer_run_parser.add_argument(
        "--dry-run", action="store_true", help="Validate without executing"
    )
    layer_run_parser.set_defaults(func=cmd_layer_run)

    # runs command
    runs_parser = subparsers.add_parser("runs", help="Run management")
    runs_subparsers = runs_parser.add_subparsers(
        dest="subcommand", help="Runs subcommands"
    )

    # runs list
    runs_list_parser = runs_subparsers.add_parser(
        "list", help="List runs"
    )
    runs_list_parser.add_argument(
        "--layer", "-l", help="Filter by layer name"
    )
    runs_list_parser.add_argument(
        "--status", "-s", help="Filter by status (pending, running, completed, failed, cancelled)"
    )
    runs_list_parser.add_argument(
        "--limit", "-n", type=int, default=20, help="Maximum runs to show (default: 20)"
    )
    runs_list_parser.set_defaults(func=cmd_runs_list)

    # runs show
    runs_show_parser = runs_subparsers.add_parser(
        "show", help="Show run details"
    )
    runs_show_parser.add_argument("run_id", help="Run ID to show")
    runs_show_parser.add_argument(
        "--trace", "-t", action="store_true", help="Show execution trace"
    )
    runs_show_parser.set_defaults(func=cmd_runs_show)

    return parser


def main() -> None:
    """Run the CLI."""
    parser = create_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    if args.command == "salience" and args.subcommand is None:
        parser.parse_args(["salience", "--help"])
        return

    if args.command == "budget" and args.subcommand is None:
        parser.parse_args(["budget", "--help"])
        return

    if args.command == "llm" and args.subcommand is None:
        parser.parse_args(["llm", "--help"])
        return

    if args.command == "layer" and args.subcommand is None:
        parser.parse_args(["layer", "--help"])
        return

    if args.command == "runs" and args.subcommand is None:
        parser.parse_args(["runs", "--help"])
        return

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()
