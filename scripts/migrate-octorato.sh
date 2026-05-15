#!/usr/bin/env bash
# migrate-octorato.sh — One-shot migration after the dotclaude → octorato rebrand (May 2026).
#
# Idempotent. Safe to re-run. Detects if your local ~/.claude/ git origin still
# points to the deleted dotclaude repo, rewrites it to octorato, and pulls.
#
# Run once on every laptop that still has the old origin:
#     bash ~/.claude/scripts/migrate-octorato.sh
#
# If you can't pull because origin is 404, run this:
#     # Replace YOUR_USERNAME with your GitHub username (probably CarlosCaPe)
#     git -C ~/.claude remote set-url origin https://github.com/YOUR_USERNAME/octorato.git
#     bash ~/.claude/scripts/migrate-octorato.sh

set -euo pipefail

BRAIN_DIR="${CLAUDE_DIR:-$HOME/.claude}"

if [[ ! -d "$BRAIN_DIR/.git" ]]; then
    echo "✗ $BRAIN_DIR is not a git repository."
    exit 1
fi

cd "$BRAIN_DIR"

current_origin="$(git remote get-url origin 2>/dev/null || echo '')"
if [[ -z "$current_origin" ]]; then
    echo "  No 'origin' remote configured. Add it manually:"
    echo "    git -C $BRAIN_DIR remote add origin https://github.com/CarlosCaPe/octorato.git"
    exit 1
fi

if [[ "$current_origin" == *"dotclaude"* ]]; then
    new_origin="${current_origin//dotclaude/octorato}"
    echo "  Rebrand detected. Migrating origin:"
    echo "    old: $current_origin"
    echo "    new: $new_origin"
    git remote set-url origin "$new_origin"
    echo "  ✓ origin updated."
else
    echo "  origin already points to: $current_origin"
fi

# Pull to verify the new remote works
echo ""
echo "  Verifying with a fetch..."
if git fetch origin --quiet; then
    echo "  ✓ Fetch successful — the new origin is reachable."
else
    echo "  ✗ Fetch failed. Check your network, gh auth, and that the repo exists."
    exit 1
fi

echo ""
echo "Migration complete. You can now run ai-pull or ai-push normally."
