"""Zos CLI commands."""

from __future__ import annotations

import argparse
import asyncio
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

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()
