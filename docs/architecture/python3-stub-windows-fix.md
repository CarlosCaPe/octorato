# Windows `python3` Stub: Audit + Fix

**Date:** 2026-06-05 (B3 audit fold-in)
**Layer:** brain (`~/.claude/`)
**Status:** fixed via `~/.local/bin/python3.cmd` shim installed by `scripts/install-runners.py`

## The bug

Every Windows brain hook and every `python3 ...` line in `commands/` and
`docs/` silently fails on a fresh Windows install. The reason is upstream
of the brain, it's a Windows-Python packaging quirk, but the consequence
is that the brain runs degraded without telling you.

What happens, step by step:

1. The standard `python.org` installer ships only `python.exe`, not
   `python3.exe`. The name `python3` is unclaimed by the real install.
2. Windows 10/11 ships an **App-Execution-Alias stub** at
   `%LOCALAPPDATA%\Microsoft\WindowsApps\python3.exe` that opens the
   Microsoft Store to "Install Python 3.x". It does NOT run Python.
3. `WindowsApps\` is on every user's PATH by default.
4. Result: `python3 --version` prints "Python was not found; run without
   arguments to install from the Microsoft Store" and exits non-zero.
   `python --version` and `py -3 --version` both work fine.

## Why this matters for the brain

`settings.json` has **29 hook commands** of the form
`python3 ~/.claude/scripts/<script>.py`. On Windows these all hit the
stub:

- PreToolUse / PostToolUse hooks (trace, canon-heal, impact-radius, …)
- UserPromptSubmit / SessionStart hooks (heartbeat, 4d-reminder, …)
- Stop / SessionEnd hooks (cadence-stop, grafo-ledger-check, …)
- PreCompact (session-isolation)

Plus `commands/ai-push.md` step 2b (hooks drift-guard), step 2c (README
count drift-guard, see B2), step 4 (regenerate neural connectome), and
similar in `commands/ai-pull.md`.

A failing hook doesn't fail-closed the prompt. Claude Code just logs
the error and continues, so the operator sees the brain working but
NOT running its hook discipline. That's the "fantasy approval" failure
mode the `reality-checker` agent guards against, applied to the brain
itself.

## The fix

Two parts:

### 1. The runtime fix: `~/.local/bin/python3.cmd`

A 1-line `.cmd` shim that forwards every arg to `py -3` (the Python
Launcher, which IS bundled with every modern Python.org installer):

```cmd
@echo off
rem octorato-thunk
@py -3 %*
```

This file lives in `~/.local/bin/`, which sits at **position 4** on
the user's PATH, before `WindowsApps\` at position 5, so the shim wins
the resolution race. No PATH edit, no new install, no Microsoft Store
popup.

Verification:

```powershell
where.exe python3
# → %USERPROFILE%\.local\bin\python3.cmd
# → %USERPROFILE%\AppData\Local\Microsoft\WindowsApps\python3.exe
python3 --version
# → Python 3.12.10
python3 -c "import sys; print(sys.executable)"
# → %USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe
```

### 2. The install-time fix: `scripts/install-runners.py`

Teach the brain's first-time-setup installer to drop the shim
automatically on Windows. New behavior:

- POSIX: unchanged (no shim needed, `python3` is canonical there).
- Windows: install `python3.cmd` in `~/.local/bin/` before the other
  thunks (`ai-pull.cmd`, `ai-push.cmd`, `sync-ai-docs.cmd`), because
  those thunks themselves call `python3`. Idempotent, re-runs refresh
  the marker-tagged shim in place; backs up any pre-existing standalone
  `python3.cmd` to `python3.cmd.prebrain.bak`.

Result: any new Windows brain install (or any existing one that re-runs
`install-runners.py`) gets the shim automatically.

## Why not a different fix

| Alternative | Why rejected |
|---|---|
| `winget install Python.Python.3` | Doesn't help: installs another Python at a different prefix; still no `python3.exe`. |
| Edit PATH to drop WindowsApps | Breaks other Microsoft Store apps the user may rely on; too invasive. |
| Change every `python3` invocation to `python` | 29 hook commands + tens of doc references; cross-platform regression risk (some Linux distros only ship `python3`, not `python`). |
| Change every `python3` invocation to `py -3` | Same scope; `py` doesn't exist on POSIX so this would break the macOS/Linux brain. |
| Add `python3 || python` fallback everywhere | Works in bash, fragile in cmd.exe / JSON hook strings. Hides the stub failure instead of fixing it. |

The shim is the minimal, surgical, cross-platform-clean fix. POSIX
brains stay untouched. Windows brains get one extra 50-byte file that
makes `python3` mean what every script and doc already assumes it means.

## Side audit: `python.org` install presence

The shim only works if a real Python 3 is installed somewhere `py -3`
can find it. On a brand-new Windows machine with no Python install,
`py -3` errors out too. The brain's `requirements.txt` already documents
the Python install dependency; the first-run UX should be:

```text
1. Install Python 3.11+ from python.org (includes the `py` launcher).
2. Clone octorato to ~/.claude.
3. Run: python -m pip install -r ~/.claude/requirements.txt
4. Run: python ~/.claude/scripts/install-runners.py
   (Note: `python`, not `python3` — bootstrap chicken-and-egg.)
5. Run: ai-pull
```

After step 4, `python3 anything.py` works everywhere, including
inside the `settings.json` hook commands that the brain now executes
on every prompt.

## Detection / re-audit

To check that the shim is working on a Windows brain:

```powershell
python3 ~/.claude/scripts/lineage-doctor.py
# → expect: "✓ sound: no dangling edges, no cycles"

python3 ~/.claude/scripts/check-hooks-drift.py
# → expect: clean exit 0 (or a real drift report, not "Python was not found")
```

If either prints the Microsoft Store stub message, the shim is missing
or shadowed, re-run `python scripts/install-runners.py` and check PATH
order with `where.exe python3` (the `.local/bin` entry should appear
first).
