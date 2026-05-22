# .githooks/ — pre-push enforcement layer

This directory holds the git hooks that enforce the "Brain Stays Generic" rule
at **push time**, complementing `scripts/check-generic.py` which runs at
**commit time** via the `ai-push` workflow.

## Why two layers

| Layer | Trigger | What it catches |
|---|---|---|
| `scripts/check-generic.py` | `ai-push` (commit-time) | Operator-specific blocklist tokens in staged files + commit message. Soft-fails when the blocklist is missing. |
| `.githooks/pre-push` (this) | every `git push` (push-time) | Universal path denylist + secret-pattern scan + optional blocklist re-check. Always runs, no soft-fail. |

A plain `git commit && git push` (bypassing `ai-push`) reaches the network if
only `check-generic.py` exists. The pre-push hook is the safety net that fires
regardless of which commit workflow was used.

## How to enable

```powershell
cd $HOME\.claude
git config core.hooksPath .githooks
git update-index --chmod=+x .githooks/pre-push   # Windows: mark executable in git
```

On macOS / Linux, also ensure the file is executable on disk:

```bash
chmod +x ~/.claude/.githooks/pre-push
```

## How to verify it's active

```powershell
cd $HOME\.claude
git config --get core.hooksPath        # should print: .githooks
ls .githooks/pre-push                  # file should exist
```

Then attempt to push a deliberately-bad commit (e.g. add a fake `.env` file):

```powershell
echo "FAKE_KEY=sk-1234567890abcdef1234567890abcdef1234567890" > .env
git add .env
git commit -m "test"
git push                                # expect: REFUSED by pre-push
git reset --hard HEAD~1                 # undo the test commit
rm .env
```

## How to bypass (intentional override)

```bash
git push --no-verify
```

Use this **only** when you're certain the policy is too strict for a specific
push. Every `--no-verify` should be considered a small audit event — if it
happens often, the policy needs updating, not bypassing.

## How to edit policy

`push-policy.txt` is committed; everyone working in the brain shares the same
baseline. Add patterns to `[paths]` for file-path denials and `[content]` for
diff-content denials. Patterns are POSIX extended regex.

Operator-private identifiers (real client names, ticket IDs, coworker names)
belong in `company/brain-blocklist.txt` (gitignored). The hook loads them
automatically when present.

## Anti-pattern

Setting `git remote set-url --push origin DO-NOT-PUSH-FROM-*` blocks **all**
pushes including legitimate generic-skill contributions. The hook replaces
this with content-aware filtering: generic content flows, sensitive content
blocks. Don't go back to URL-level guardrails after enabling the hook.
