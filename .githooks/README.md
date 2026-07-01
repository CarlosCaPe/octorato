# .githooks/ — pre-push enforcement layer

This directory holds the git hooks that enforce the "Brain Stays Generic" rule
at **push time**, complementing `scripts/check-generic.py` which runs at
**commit time** via the `ai-push` workflow.

## Why two layers

| Layer | Trigger | What it catches |
|---|---|---|
| `scripts/check-generic.py` | `ai-push` (commit-time) | Operator-specific blocklist tokens in staged files + commit message. Soft-fails when the blocklist is missing. |
| `.githooks/pre-push` (this) | every `git push` (push-time) | Universal path denylist + secret-pattern scan + optional blocklist re-check, plus three fail-closed integrity gates (below). Always runs, no soft-fail. |

A plain `git commit && git push` (bypassing `ai-push`) reaches the network if
only `check-generic.py` exists. The pre-push hook is the safety net that fires
regardless of which commit workflow was used.

## The four reasons a push blocks

If your push was rejected, it hit one of these:

1. **Content leak** (path denylist, secret patterns, blocklist tokens): the
   original "Brain Stays Generic" scan described above.
2. **Lineage graph unsound**: `scripts/lineage-doctor.py` found a dangling edge
   or cycle in `connectome/lineage.yaml`. Fix the graph so every seek can be
   trusted, then re-push.
3. **RULE #1 registry gate**: `scripts/brain_doctor.py --registry` declared the
   brain CORRUPT because a rule in `registry/rules.yaml` is not wired (phantom
   script, dead anchor, schema failure). Since v5.5.0 this gate is fail-closed
   on its own inputs too: if `registry/rules.yaml`, `brain_doctor.py`, or a
   working Python is MISSING, the hook exits 1 instead of silently skipping. A
   constitutional gate must never vanish silently.
4. **Capability manifest stale**: `scripts/capability_manifest.py --check`
   found that `docs/CAPABILITIES.md` no longer reflects the live capability set
   (a skill/agent/script/rule/hook changed without regen). Run
   `python3 scripts/capability_manifest.py`, commit the manifest, re-push.

Gates 2 to 4 share the fail-closed stance: a missing gate input (script, graph,
registry, or Python itself) blocks the push, never skips the check.

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
