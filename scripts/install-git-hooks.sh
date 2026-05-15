#!/usr/bin/env bash
# install-git-hooks.sh — Install the brain-stays-generic git hooks into ~/.claude/.git/hooks/.
#
# Idempotent. Safe to re-run. Symlinks the tracked hooks in hooks/git-hooks/
# so updates propagate automatically without re-running this script.
#
# Run once per clone:
#   bash ~/.claude/scripts/install-git-hooks.sh

set -euo pipefail

CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"
SRC="$CLAUDE_DIR/hooks/git-hooks"
DST="$CLAUDE_DIR/.git/hooks"

if [[ ! -d "$CLAUDE_DIR/.git" ]]; then
    echo "✗ $CLAUDE_DIR is not a git repository — abort."
    exit 1
fi
if [[ ! -d "$SRC" ]]; then
    echo "✗ $SRC does not exist — run ai-pull first to fetch the hook sources."
    exit 1
fi

mkdir -p "$DST"

for hook in pre-commit commit-msg; do
    src="$SRC/$hook"
    dst="$DST/$hook"
    if [[ ! -f "$src" ]]; then
        echo "⚠ skipping $hook — source not found at $src"
        continue
    fi
    chmod +x "$src"
    # Replace any existing file or symlink at dst with a symlink to the tracked source.
    if [[ -e "$dst" || -L "$dst" ]]; then
        rm -f "$dst"
    fi
    ln -s "$src" "$dst"
    echo "✓ installed $hook → $dst"
done

echo ""
echo "Brain-stays-generic enforcement installed."
echo "Next step: create your blocklist if you haven't:"
echo "  cp $CLAUDE_DIR/templates/company/brain-blocklist.txt.template \\"
echo "     $CLAUDE_DIR/company/brain-blocklist.txt"
echo "  # then edit it to list your arm codes, client names, etc."
