---
name: hook-profile-gating
description: Runtime gate hooks via OCTO_HOOK_PROFILE (minimal|standard|strict) and OCTO_DISABLED_HOOKS (comma-separated ids) — disable noisy hooks without editing hook files. Use when onboarding a new arm, debugging a runaway hook, or running a low-context session where the full hook stack is overhead. Always-on hooks (leak-guard, secret-scan, hooks-drift) cannot be disabled via env — that's by design. Pattern adopted from affaan-m/ECC.
metadata:
  type: runtime-pattern
  origin: repo-deep-learn — affaan-m/ECC scripts/lib/hook-flags.js (2026-05-28)
---

# Hook Profile Gating

## Why

Hook stack grows over time. Some hooks are non-negotiable (secret-scan, leak-guard); some are nice-to-have (typecheck, tmux-reminder); some get noisy in specific contexts (onboarding a new arm, debugging the brain itself). Editing `settings.json` to disable one is heavy. Env-vars give per-session gating.

## How

Three env vars + one Python helper:

| Var | Values | Default | Effect |
|---|---|---|---|
| `OCTO_HOOK_PROFILE` | `minimal` \| `standard` \| `strict` | `standard` | bulk gate by profile |
| `OCTO_DISABLED_HOOKS` | `id1,id2,...` (comma-separated) | empty | per-hook off-switch |

Profiles:
- **minimal** — only `always_on=True` hooks run (leak-guard, secret-scan, hooks-drift). Fastest. Use when sanity-checking a brain change without firing the world.
- **standard** — default. Everything except `strict_only=True` hooks.
- **strict** — everything, including `strict_only` (slow type-checks, extended security scans).

`OCTO_DISABLED_HOOKS` overrides everything *except* `always_on=True`. You cannot disable the leak-guard via env, ever.

## Helper API

`scripts/lib/hook_flags.py`:

```python
from lib.hook_flags import should_run, profile, is_disabled

# Most common pattern at the top of any hook script:
if not should_run("pre:bash:tmux-reminder"):
    sys.exit(0)

# Always-on:
if not should_run("pre:push:secret-scan", always_on=True):
    sys.exit(0)  # never fires; always returns True

# Strict-only:
if not should_run("post:edit:slow-typecheck", strict_only=True):
    sys.exit(0)

# Read profile directly:
prof = profile()  # 'minimal' | 'standard' | 'strict'
```

## How to port an existing hook

1. Pick a hook id following `<phase>:<event>:<short-name>` (e.g. `pre:bash:tmux-reminder`).
2. Add at the very top of the hook script:
   ```python
   import sys, pathlib
   sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts" / "lib"))
   from hook_flags import should_run
   if not should_run("<your-id>"):
       sys.exit(0)
   ```
3. Decide if it's `always_on` or `strict_only`. Default (neither) = runs in standard+strict, skipped in minimal.
4. Document the id in the hook's docstring + a row in `~/.claude/hooks/README.md`.

Hooks that don't opt in are **always active** — porting is incremental, no flag-day required.

## Examples

```bash
# Onboarding a new arm; minimize noise
export OCTO_HOOK_PROFILE=minimal
ai-pull

# Debugging a specific noisy hook
export OCTO_DISABLED_HOOKS="pre:bash:tmux-reminder,post:edit:typecheck"
ai-push "..."

# Pre-merge strict gate (catches everything before going live)
export OCTO_HOOK_PROFILE=strict
node tests/run-all.js
```

## What NOT to do

- **Don't make leak-guard env-overridable.** It's `always_on=True` for a reason — public brain.
- **Don't gate behavior outside hooks via these env vars.** They're hook-runtime only; for runtime behavior in skills/scripts, use the operator-recall pattern (`load_config()` from a YAML).
- **Don't ship a hook without an id.** Untrackable disabling = bad ops story.

## See also
- [[do-not-ask-to-pause]] — hooks should never prompt the operator; if they need a decision, they're not hooks
- [[dry-run-gate-pattern]] — sibling concept: opt-in for destructive ops, opt-out for hooks via env
