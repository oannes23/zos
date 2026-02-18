#!/usr/bin/env bash
# recent-changes.sh — Generate a structured summary of recent commits
# for pasting into a Zos instance's context.
#
# Usage: ./recent-changes.sh [count]
#   count: number of commits to show (default: 10)

set -euo pipefail

COUNT="${1:-10}"

echo "# Recent Changes to Zos Codebase"
echo ""
echo "Generated: $(date -u '+%Y-%m-%d %H:%M UTC')"
echo "Branch: $(git rev-parse --abbrev-ref HEAD)"
echo "Latest commit: $(git rev-parse --short HEAD)"
echo ""
echo "---"
echo ""

git log --format='%H %h %aI %s' -n "$COUNT" | while IFS=' ' read -r full_hash short_hash timestamp title_word rest; do
    title="$title_word $rest"
    # Format timestamp: strip the timezone colon for macOS date parsing
    ts_fixed=$(echo "$timestamp" | sed 's/\(.*\):\([0-9][0-9]\)$/\1\2/')
    pretty_date=$(date -j -f '%Y-%m-%dT%H:%M:%S%z' "$ts_fixed" '+%Y-%m-%d %H:%M %Z' 2>/dev/null || echo "$timestamp")

    echo "## $short_hash — $title"
    echo ""
    echo "**Date**: $pretty_date"
    echo ""

    # Get the full commit body (if any, beyond the title)
    body=$(git log --format='%b' -n 1 "$full_hash" | sed '/^$/d' | grep -v '^Co-Authored-By:' || true)
    if [ -n "$body" ]; then
        echo "$body"
        echo ""
    fi

    # Show files changed with stats
    echo "**Files changed**:"
    git diff-tree --no-commit-id -r --stat=80 "$full_hash" | while IFS= read -r line; do
        echo "- $line"
    done
    echo ""

    echo "---"
    echo ""
done
