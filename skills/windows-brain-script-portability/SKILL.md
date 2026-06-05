---
name: windows-brain-script-portability
description: "Two hard-won rules for any Python script in ~/.claude/scripts/ that must run on a Windows brain: (1) `python3` resolves to the Microsoft Store stub by default — depend on the `python3.cmd` shim installed by install-runners.py, never on bare `python3`. (2) ANY script that prints Unicode (✓ ✗ — • → bullet/check/arrow) MUST reconfigure stdout/stderr to UTF-8 at module top — Windows cp1252 consoles crash mid-print otherwise, leaving the script's work half-reported. Use proactively when writing a new brain script, when touching an existing one, or when triaging a Windows-only crash."
metadata:
  type: pattern-reference
  origin: session-learn-extractor — 2026-06-05 after iterating on the same UnicodeEncodeError + python3-stub pair across e5aa67b → install-runners.py → canon-render.py
---

# Windows Brain Script Portability

## When this fires

- About to write a new `~/.claude/scripts/*.py`
- Editing an existing brain script (especially one that prints status, ✓/✗, or any non-ASCII)
- Triaging a Windows-only failure: `UnicodeEncodeError: 'charmap' codec can't encode character ...` or `Python was not found; run without arguments to install from the Microsoft Store`
- Reviewing a PR that adds a hook command to `settings.json`

## Rule 1 — `python3` is a Microsoft Store stub on Windows

`python.org`'s Windows installer ships only `python.exe`. The name `python3` is claimed by an App-Execution-Alias stub at `%LOCALAPPDATA%\Microsoft\WindowsApps\python3.exe` that prints "Python was not found" and exits non-zero.

**Consequences for the brain:**

- Every `python3 ...` line in `settings.json` hooks silently no-ops
- Every `python3 ~/.claude/scripts/...` line in `commands/` fails
- Every `python3 ... | something` pipe in docs misleads new operators

**The fix:** `scripts/install-runners.py` drops `~/.local/bin/python3.cmd` (forwards `%*` to `py -3`) as a thunk that wins PATH order against the stub. Re-run `install-runners.py` on any new Windows brain. This is documented in `docs/architecture/python3-stub-windows-fix.md`.

**What you, the author, must do:** Keep using `python3` in scripts and docs — the shim makes it canonical. Do NOT switch to `python` or `py -3` (breaks POSIX brains).

## Rule 2 — UTF-8 reconfigure is mandatory for any script that prints Unicode

Windows consoles default to `cp1252`. Python's `print()` encodes through whatever the stdout stream says — and the stream defaults to the console encoding. Print a `✓` and you get `UnicodeEncodeError: 'charmap' codec can't encode character '\u2713'`. The crash happens AFTER the script did its actual work but BEFORE reporting success — pure mind-game.

**The canonical block** (must be at module top, after imports, with `sys` in scope):

```python
# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in reports
# survive on Windows shells defaulting to cp1252. Without this, a script
# can do its work correctly and still crash with UnicodeEncodeError when
# printing success.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
```

The `try/except` keeps it portable to non-stream stdio (some embedded contexts) and older Python (`reconfigure` is 3.7+).

`errors="replace"` over `errors="strict"` so a truly-unrepresentable byte degrades to `?` instead of crashing — fail-soft on output beats fail-closed on debug noise.

## Detection

```powershell
# Audit: which brain scripts print Unicode AND lack the guard?
Get-ChildItem ~/.claude/scripts -Filter "*.py" | Where-Object {
  $c = Get-Content $_.FullName -Raw -Encoding UTF8
  ($c -match '[\u2190-\u2BFF\u2010-\u206F]') -and
  ($c -notmatch 'reconfigure\(encoding="utf-8"')
}
```

Expected output as of 2026-06-05: empty. If you see entries, apply Rule 2 to each.

## Anti-patterns

- **Per-script `python3 || python` fallback in commit hooks.** Works for one script, doesn't scale. The shim (Rule 1) fixes ALL 29 settings.json hooks at once.
- **Switching to `python` everywhere to "be safe."** Breaks every POSIX brain. The shim direction is the right one — adapt Windows to the canonical name, not the other way.
- **Replacing `✓` with `OK` to "avoid the issue."** Tempting, but the bug is encoding, not the glyph. UTF-8 reconfigure fixes the cause, not just one symptom.
- **Adding the UTF-8 block AFTER any print statement.** Streams have already been encoded once you've used them; reconfigure must happen FIRST.

## Provenance

The pattern lived implicitly in `e5aa67b` (Windows-portability of pre-push lineage check) for one script. It became canonical on 2026-06-05 after a session sprawled across the same class of problem in `install-runners.py` and `canon-render.py` — when the operator noted "llevas todo el día con ese tema de python, mal gastando tokens en círculo" (you've been on that python topic all day, wasting tokens going in circles), the lesson got promoted from per-script reactive patch to repo-wide preventive sweep. Applied to 54 scripts in one commit, plus this skill written so the next session that touches a `.py` file resolves the question by activation instead of re-discovery.

The meta-lesson — "a fix without a skill is a pisada; a fix with a skill becomes piso" — sits next to `harmonization-over-accretion` and `session-learn-extractor` in the brain's self-improvement loop.
