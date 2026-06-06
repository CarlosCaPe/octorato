#!/usr/bin/env python3
"""canon-render — propagate canonical FACTS to every subscribed surface.

The content counterpart of harmony-check.py (which governs design VALUES).
A surface subscribes to a fact by embedding a marker span:

    <!--canon:octorato.tagline-->old or stale text<!--/canon-->

canon-render rewrites the inner text to the canonical rendered value from
`content/canon.facts.yaml`. The marker IS the subscription: a file opts in by
carrying one. Idempotent — only writes when a span actually changed.

This GENERALIZES the counts-triad (sync-readme-counts.py + brain-stats.py +
check-stats-drift.py): instead of a count-and-noun regex over README/FAQ, any
fact of any kind flows to any marked surface, and `derived`/`floored` facts
RECOMPUTE from the existing source of truth (brain-stats.py) — converging with
the triad, not forking it.

Reconciliation is typed by `kind`, never averaged:
  asserted -> snap surface to value          (operator is the only editor)
  derived  -> recompute value from `derive`  (cmd + JSON key)
  floored  -> derived, floored to nearest ten, suffixed "+"

Modes:
  (default)        heal every marker in every target file; report writes.
                   Also surfaces any UNMANAGED / UNVERIFIABLE markers on
                   stderr as a non-fatal warning (the operator sees the
                   signal without the run failing). Exit 0 either way.
  --file <path>    heal only one file (for a PostToolUse Write|Edit hook).
  --check          no writes; exit 1 if ANY marker is out of sync (pre-push).
  --audit          no writes; print a drift table; always exit 0.

Soft-fails (exit 0, no error) when the registry is absent, so it is safe to
wire into ai-push before any arm adopts it.
"""
from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import sys
from glob import glob
from pathlib import Path
# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in reports
# survive on Windows shells defaulting to cp1252. Without this, a script
# can do its work correctly and still crash with UnicodeEncodeError when
# printing success. Applied repo-wide by _apply-utf8-reconfigure.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "content" / "canon.facts.yaml"


def _resolve_python() -> str:
    """Pick a Python interpreter that actually runs derive commands.

    `canon.facts.yaml` writes `derive.cmd` as `python3 scripts/...` because that
    is canonical on Linux/CI. On Windows, default PATH puts the Microsoft Store
    `python3.exe` stub ahead of any real interpreter — it exits non-zero on
    every invocation and `_run_derive` then records the fact as UNVERIFIABLE
    and skips it, so `canon-render` prints "already in unison" while silently
    leaving every wiki / README canon marker stale. Detect a working candidate
    once at import time and substitute it into any `python3 ...` derive cmd.
    Falls back to `sys.executable` since this script IS running.
    """
    for cand in ("python3", "python"):
        path = shutil.which(cand)
        if not path:
            continue
        try:
            r = subprocess.run([path, "-c", "import sys"], capture_output=True, timeout=5)
            if r.returncode == 0:
                return path
        except Exception:
            continue
    return sys.executable


_PYTHON = _resolve_python()

# <!--canon:ID-->inner<!--/canon-->  (ID = dotted/kebab word, inner may be empty)
MARKER = re.compile(
    r"<!--\s*canon:([\w.\-]+)\s*-->(.*?)<!--\s*/canon\s*-->",
    re.DOTALL,
)


def floor_ten(n: int) -> int:
    """Round DOWN to the nearest ten (152 -> 150, 196 -> 190)."""
    return (n // 10) * 10


def load_registry():
    if not REGISTRY.exists():
        return None
    try:
        import yaml  # PyYAML
    except ImportError:
        print("canon-render: PyYAML not available — skipping (soft-fail)", file=sys.stderr)
        return None
    data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    meta = data.get("meta", {}) or {}
    facts = {f["id"]: f for f in (data.get("facts", []) or [])}
    targets = meta.get("targets", []) or []
    return facts, targets


# Cache derive command results so we run brain-stats.py once, not per-marker.
_DERIVE_CACHE: dict[str, dict] = {}


def _run_derive(cmd: str) -> dict:
    if cmd in _DERIVE_CACHE:
        return _DERIVE_CACHE[cmd]
    import json
    parts = shlex.split(cmd)
    # If the derive command leads with `python3`/`python`, swap to the
    # resolved interpreter so Windows operators with a python3 stub still work.
    if parts and parts[0] in ("python3", "python"):
        parts[0] = _PYTHON
    out = subprocess.run(
        parts, cwd=ROOT, capture_output=True, text=True, timeout=60
    )
    if out.returncode != 0:
        raise RuntimeError(f"derive failed: {cmd}\n{out.stderr.strip()}")
    parsed = json.loads(out.stdout)
    _DERIVE_CACHE[cmd] = parsed
    return parsed


def render(fact: dict) -> str:
    """Return the canonical rendered string for a fact, by kind."""
    kind = fact.get("kind", "asserted")
    if kind == "asserted":
        return str(fact["value"])
    if kind in ("derived", "floored"):
        d = fact.get("derive") or {}
        data = _run_derive(d["cmd"])
        val = data
        for key in str(d["json"]).split("."):
            val = val[key]
        if kind == "floored":
            return f"{floor_ten(int(val))}+"
        return str(val)
    raise ValueError(f"unknown kind '{kind}' for fact '{fact.get('id')}'")


def target_files(targets: list[str]) -> list[Path]:
    seen: list[Path] = []
    for pat in targets:
        for p in sorted(glob(str(ROOT / pat))):
            path = Path(p)
            if path.is_file() and path not in seen:
                seen.append(path)
    return seen


def process_text(text: str, facts: dict, drifts: list, path: Path):
    """Return (new_text, changed_count). Records drifts for reporting."""
    changed = 0

    def _sub(m: re.Match) -> str:
        nonlocal changed
        fid, inner = m.group(1), m.group(2)
        fact = facts.get(fid)
        if fact is None:
            drifts.append((path.name, fid, "UNMANAGED", "(no such fact id)"))
            return m.group(0)
        try:
            canonical = render(fact)
        except Exception as exc:  # derive failure = unverifiable, never write garbage
            drifts.append((path.name, fid, "UNVERIFIABLE", str(exc).splitlines()[0]))
            return m.group(0)
        if inner != canonical:
            drifts.append((path.name, fid, "DRIFT", f"{inner!r} -> {canonical!r}"))
            changed += 1
        return f"<!--canon:{fid}-->{canonical}<!--/canon-->"

    return MARKER.sub(_sub, text), changed


def main() -> int:
    argv = sys.argv[1:]
    check = "--check" in argv
    audit = "--audit" in argv
    one_file = None
    if "--file" in argv:
        i = argv.index("--file")
        one_file = Path(argv[i + 1]).resolve() if i + 1 < len(argv) else None

    reg = load_registry()
    if reg is None:
        print("canon-render: no registry — nothing to do (soft-fail)")
        return 0
    facts, targets = reg

    if one_file is not None:
        files = [one_file] if one_file.exists() else []
    else:
        files = target_files(targets)

    drifts: list = []
    wrote = 0
    write = not (check or audit)
    for path in files:
        before = path.read_text(encoding="utf-8")
        after, changed = process_text(before, facts, drifts, path)
        if changed and after != before:
            if write:
                path.write_text(after, encoding="utf-8")
                wrote += 1
                print(f"canon-render: healed {changed} marker(s) in {path.name}")

    real_drift = [d for d in drifts if d[2] in ("DRIFT", "UNMANAGED", "UNVERIFIABLE")]
    if audit or check:
        if real_drift:
            print(f"canon-render: {len(real_drift)} issue(s)")
            for fname, fid, state, detail in real_drift:
                print(f"  [{state}] {fname} :: canon:{fid}  {detail}")
        else:
            print(f"canon-render: all markers in unison across {len(files)} file(s)")
    elif write:
        # Default mode: surface UNMANAGED / UNVERIFIABLE drifts even when no
        # DRIFT markers needed writing. Previously the script printed "already
        # in unison" while silently leaving every unverifiable marker stale —
        # operator saw green, brain was beige. Treat unverifiable as a warning
        # (stderr, exit 0) so the run completes but the operator gets a signal.
        non_drift_issues = [d for d in drifts if d[2] in ("UNMANAGED", "UNVERIFIABLE")]
        if non_drift_issues:
            print(
                f"canon-render: WARN {len(non_drift_issues)} unresolved marker(s) "
                f"(non-fatal; rerun with --audit for the full table):",
                file=sys.stderr,
            )
            for fname, fid, state, detail in non_drift_issues:
                print(f"  [{state}] {fname} :: canon:{fid}  {detail}", file=sys.stderr)
        if wrote == 0 and not non_drift_issues:
            print(f"canon-render: already in unison across {len(files)} file(s)")
        elif wrote == 0:
            print(f"canon-render: no writes ({len(files)} file(s) scanned; see warnings above)")

    if check and real_drift:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
