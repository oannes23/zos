"""Salience CLI commands."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

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

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()
