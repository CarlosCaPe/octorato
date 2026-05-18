#!/usr/bin/env bash
# check-readme-sync.sh — Warn if skills/agents/scripts changed but README didn't.
#
# Called from the pre-commit hook (~/.claude/hooks/git-hooks/pre-commit) AFTER
# the brain-generic check. SOFT block — prompts with a y/N. Not every change
# under skills/ warrants a README update (e.g., a typo fix in a skill body),
# so default-deny + bypass-on-y respects operator judgment.
#
# Bypass options:
#   - Answer 'y' at the prompt
#   - git commit --no-verify (skips ALL pre-commit hooks)
#
# Behavior matrix:
#   No watched-dir changes staged           → silent pass
#   Watched-dir changes + README staged     → silent pass
#   Watched-dir changes + no README + TTY   → prompt
#   Watched-dir changes + no README + NO TTY → warn + pass (don't block automation)

set -e

# Staged files (added, modified, copied, renamed)
STAGED=$(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null || true)

if [[ -z "$STAGED" ]]; then
    exit 0
fi

# Watched dirs — changes here often imply README should be updated
WATCHED_RE='^(skills/|agents/|scripts/)'

# Any staged file in a watched dir?
TOUCHED=$(echo "$STAGED" | grep -E "$WATCHED_RE" || true)
if [[ -z "$TOUCHED" ]]; then
    exit 0
fi

# README.md staged?
README_STAGED=$(echo "$STAGED" | grep -E '^README\.md$' || true)
if [[ -n "$README_STAGED" ]]; then
    exit 0
fi

# Watched-dir changes WITHOUT README change → surface the gap
echo "" >&2
echo "⚠ pre-commit (readme-sync): brain content changed but README.md was not staged." >&2
echo "" >&2
echo "  Staged in watched dirs:" >&2
echo "$TOUCHED" | sed 's/^/    /' >&2
echo "" >&2
echo "  README.md last touched: $(git log -1 --format='%ar (%h)' -- README.md 2>/dev/null || echo 'never')" >&2
echo "" >&2

# Test whether /dev/tty is openable. We use a SUBSHELL (parentheses) to scope
# the redirect — otherwise `exec </dev/tty 2>/dev/null` would persist 2>/dev/null
# for the whole script and silence all later stderr output.
# The subshell tries to open /dev/tty as stdin; if that fails (no controlling
# terminal — CI, automation, ai-push, etc.) it returns non-zero and we pass.
if ! ( exec </dev/tty ) 2>/dev/null; then
    echo "  (no TTY available — proceeding without prompt; treat as intentional)" >&2
    exit 0
fi

# TTY confirmed openable — open it on FD 3 in the parent shell for the read.
exec 3</dev/tty
echo -n "  Proceed without updating README? (y/N) " >&2
read -n 1 -r RESPONSE <&3
exec 3<&-
echo "" >&2
echo "" >&2

if [[ "$RESPONSE" =~ ^[Yy]$ ]]; then
    echo "  ✓ Acknowledged — proceeding without README update." >&2
    exit 0
fi

echo "  ✗ Aborted by operator. Update README.md and re-stage, or use" >&2
echo "    git commit --no-verify to bypass all pre-commit hooks." >&2
exit 1
