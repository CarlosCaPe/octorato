---
description: Run the brain health-check (octorato self-diagnostics) — repo identity, sync state, hooks, leak-guard, connectome freshness, arm mirror sync.
---

# /brain-doctor

Cross-platform read-only health check for the `~/.claude/` brain (the public `octorato` repo).
Verifies repo identity, git sync state, interpreter, runner version-control, hooks runtime sync,
leak-guard, connectome freshness, and per-arm doc-mirror sync.

## Run

```bash
python3 ~/.claude/scripts/brain_doctor.py
```

## Flags

| Flag | Effect |
|---|---|
| (none) | **Read-only.** Prints `PASS` / `WARN` / `FAIL` per check with a remediation hint. |
| `--fix` | Opt-in. Performs only **idempotent** repairs: rewrite `dotclaude→octorato` origin, set `core.hooksPath .githooks`, regenerate `neural_map.json`. Never destructive. |
| `--json` | Machine-readable output for scripting/CI. |

## Exit codes

- `0` — no `FAIL` (WARN does not fail the run)
- `1` — at least one `FAIL`

Ends with a summary line: `N passed, M warn, K fail`.

## Checks

`repo-identity`, `sync-clean`, `interpreter`, `runners-tracked`, `hooks-runtime-sync`,
`hooks-merge-fresh`, `leak-guard`, `connectome-fresh`, `arms-config`, `sync-targets`, `blocklist`.

Each check is sandboxed — one failing check never crashes the run.
