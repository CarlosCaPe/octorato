#!/usr/bin/env python3
"""lineage-doctor.py — fail-closed integrity check for the surface/derivation graph.

The seek is only trustworthy if the graph is SOUND. A green `SEEK-COMPLETE` over a
rotted index lies — and a confident lie is worse than an honest grep. This validates
connectome/lineage.yaml (+ the private company/ layer if present) and FAILS CLOSED on
a broken index, so the teeth bite truth.

Checks:
  SOUNDNESS  every in-repo path in from/to/appears_in resolves on disk (dangling = ERROR
             — the 'blind where it thinks it sees' rot, e.g. a renamed source).
             off-repo targets (offrepo:true, or label/sentence strings, or <placeholders>)
             are skipped — the graph names them but cannot verify their bytes from here.
  DAG        directed edges (projects_to/generated_by/claim_maps_to) contain no cycle —
             a cycle makes the 'deterministic O(neighbors) seek' loop forever.

Exit 0 = sound (warnings allowed). Exit 1 = broken — blocks push/CI (fail-closed,
unlike check-generic's soft-fail; a rotted public shared index is everyone's bug).

Usage: lineage-doctor.py [--quiet]
"""
import subprocess
import sys
from pathlib import Path

# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in the report
# survive on Windows shells defaulting to cp1252. Without this, the script
# can resolve a sound graph and still crash with UnicodeEncodeError when
# trying to print success.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass  # older Python / non-stream stdio → best-effort fallback

CLAUDE_DIR = Path(__file__).resolve().parent.parent
LINEAGE = CLAUDE_DIR / "connectome" / "lineage.yaml"
PRIVATE = CLAUDE_DIR / "company" / "connectome" / "lineage.yaml"

DIRECTED = {"projects_to", "generated_by", "claim_maps_to"}


def tracked_paths() -> set:
    """Paths git considers part of the repo (sparse-checkout aware).

    A file can be tracked-but-not-materialized when the operator narrowed the
    working tree with `git sparse-checkout`. The graph is still sound — git
    knows the file exists — even though Path.exists() returns False. Without
    this set, a Windows brain with a slim checkout reports false-positive
    'dangling edges' for every wiki/doc page that lives outside the cone.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=CLAUDE_DIR,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return {line.strip() for line in out.splitlines() if line.strip()}
    except Exception:
        return set()  # git unavailable → fall back to filesystem-only semantics


def load():
    edges = []
    for p in (LINEAGE, PRIVATE):
        if not p.exists():
            continue
        try:
            import yaml
            edges.extend((yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("edges") or [])
        except Exception as e:
            print(f"  ✗ cannot parse {p.relative_to(CLAUDE_DIR)}: {e}")
            return None
    return edges


def is_repo_path(s: str) -> bool:
    """True only for clean in-repo relative paths (not labels/sentences/placeholders)."""
    s = s.strip()
    if not s or " " in s or "(" in s or "—" in s or s.startswith("<"):
        return False
    return "/" in s or s.endswith((".md", ".py", ".yaml", ".yml", ".json", ".ts", ".astro", ".svelte"))


def path_resolves(s: str, tracked: set) -> bool:
    """A path resolves if it exists on disk OR git tracks it (handles sparse-checkout).

    Directory entries (trailing slash) resolve if any tracked file lives below.
    """
    if (CLAUDE_DIR / s).exists():
        return True
    norm = s.rstrip("/")
    if norm in tracked:
        return True
    if s.endswith("/") and any(t.startswith(norm + "/") for t in tracked):
        return True
    return False


def main() -> int:
    quiet = "--quiet" in sys.argv
    edges = load()
    if edges is None:
        return 1
    errors, warns = [], []
    tracked = tracked_paths()

    # SOUNDNESS
    for e in edges:
        if e.get("offrepo"):
            continue  # off-repo: named, not verifiable from here
        strings = []
        if e.get("from"):
            strings.append(e["from"])
        strings += [str(x) for x in (e.get("to") or [])]
        strings += [str(x) for x in (e.get("appears_in") or [])]
        for s in strings:
            if is_repo_path(s) and not path_resolves(s, tracked):
                errors.append(f"dangling edge '{e.get('id', '?')}': path does not resolve → {s}")

    # DAG (directed edges only)
    graph = {}
    for e in edges:
        if e.get("kind") in DIRECTED and is_repo_path(e.get("from", "")):
            for t in (e.get("to") or []):
                if is_repo_path(str(t)):
                    graph.setdefault(e["from"], []).append(str(t))
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {}

    def cycle(n):
        color[n] = GRAY
        for m in graph.get(n, []):
            if color.get(m, WHITE) == GRAY:
                return [n, m]
            if color.get(m, WHITE) == WHITE:
                r = cycle(m)
                if r:
                    return [n] + r
        color[n] = BLACK
        return None

    for n in list(graph):
        if color.get(n, WHITE) == WHITE:
            c = cycle(n)
            if c:
                errors.append(f"cycle in directed lineage: {' → '.join(c)}")
                break

    n_edges = len(edges)
    if not quiet:
        print(f"lineage-doctor: {n_edges} edge(s) checked "
              f"({sum(1 for e in edges if e.get('offrepo'))} off-repo skipped)")
        for w in warns:
            print(f"  ⚠ {w}")
    if errors:
        for er in errors:
            print(f"  ✗ {er}", file=sys.stderr)
        print(f"lineage-doctor FAIL: {len(errors)} integrity error(s) — the index is "
              f"unsound; a seek over it would lie.", file=sys.stderr)
        return 1
    if not quiet:
        print("  ✓ sound: no dangling edges, no cycles — the seek can be trusted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
