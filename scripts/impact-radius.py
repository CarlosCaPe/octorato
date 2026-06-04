#!/usr/bin/env python3
"""impact-radius.py — SEEK the lineage graph; do not SCAN (grep) the repo.

"El grafo es y ya." A grep is a table scan: input-dependent, stochastic,
repo-text-only, blind to off-repo + derived surfaces, and ~100x more tokens than
a seek (measured: ~1737 vs ~16 for one concept). This tool TRAVERSES
connectome/lineage.yaml — a persistent, declared surface/derivation graph — and
returns, deterministically, every surface a touched path/concept impacts,
including off-repo. grep is only a labeled FALLBACK for a concept with no edge
yet (an "unlit neuron"); the fallback writes a candidate to
connectome/lineage.unverified.yaml so the graph grows by use.

Every run emits a one-line machine RECEIPT to the per-turn graph ledger
(~/.claude/.cache/graph-ledger/<session>.jsonl). The Provenance footer's
`Graph:` field MUST quote that receipt verbatim — never model prose.

States:
  SEEK-COMPLETE   — ≥1 lineage edge matched; downstream surfaces returned.
  GREP-FALLBACK   — no edge (unlit neuron); grep ran, candidate filed.
  (SEEK-PARTIAL is produced by the offline lineage-doctor cross-check, not here.)

Usage:
  impact-radius.py "<concept>"        # seek by concept term
  impact-radius.py --file <path>      # seek by a touched file path
"""
import os
import sys
import json
import time
import hashlib
import subprocess
from pathlib import Path

CLAUDE_DIR = Path(__file__).resolve().parent.parent


def _detect_arm_root():
    """Arm-aware seek: when CWD is inside an arm repo that carries its own sealed
    graph (.claude/connectome/lineage.yaml), the seek traverses THAT graph instead
    of the brain's. Walk up to the first repo root (.git); an arm is any such root
    that is not the brain itself. Returns the arm root Path or None (brain mode).
    Arm Isolation holds: one graph per seek, never merged across arms.
    Known limit: a vendored submodule INSIDE an arm stops the walk at the
    inner .git and falls back to brain mode (fail-safe, never cross-graph)."""
    cur = Path.cwd().resolve()
    if cur == CLAUDE_DIR or CLAUDE_DIR in cur.parents:
        return None
    for p in (cur, *cur.parents):
        if (p / ".git").exists():
            if (p / ".claude" / "connectome" / "lineage.yaml").exists():
                return p
            return None  # repo without an arm graph → brain mode (unlit arm)
    return None


ARM_ROOT = _detect_arm_root()
if ARM_ROOT:
    # Arm mode: the arm's sealed graph + optional private layer, both inside the
    # arm repo (never the brain's, never another arm's).
    GRAPH_ROOT = ARM_ROOT
    LINEAGE = ARM_ROOT / ".claude" / "connectome" / "lineage.yaml"
    PRIVATE_LINEAGE = ARM_ROOT / ".claude" / "connectome" / "lineage.private.yaml"
    UNVERIFIED = ARM_ROOT / ".claude" / "connectome" / "lineage.unverified.yaml"
else:
    GRAPH_ROOT = CLAUDE_DIR
    LINEAGE = CLAUDE_DIR / "connectome" / "lineage.yaml"
    # Private layer: arm/CV/client edges that must NOT enter the public brain. Read
    # locally and merged at seek time; gitignored (company/), never committed. This
    # mirrors the brain/arm isolation — the seek sees everything, the repo sees only
    # the generic edges.
    PRIVATE_LINEAGE = CLAUDE_DIR / "company" / "connectome" / "lineage.yaml"
    UNVERIFIED = CLAUDE_DIR / "connectome" / "lineage.unverified.yaml"
LEDGER_DIR = CLAUDE_DIR / ".cache" / "graph-ledger"
# Printed receipts stay generic ("layer=arm"); the arm's name only lands in the
# local gitignored ledger, never in a footer that could reach a public PR.
LAYER_TAG = " layer=arm" if ARM_ROOT else ""

# Repo roots the grep fallback may scan (the same surfaces the graph indexes).
SCAN = ["CLAUDE.md", "README.md", "WHITEPAPER.md", "ROADMAP.md", "SHOWCASE.md",
        "CONTRIBUTING.md", "CHANGELOG.md", "skills", "agents", "commands", "docs",
        "scripts", "connectome"]

VERB = {
    "projects_to": "RE-PUBLISH (source→derived copy goes stale)",
    "generated_by": "REGENERATE (do not hand-edit — run the generator)",
    "claim_maps_to": "ADD-FILE-ROW (a claim must map to a running file)",
    "appears_in": "CONVERGE (one value, single-sourced)",
}


def _sha8(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:8]


def load_lineage():
    """Merge the public graph + the private (company/) graph, return (edges, sha8).
    Private edges are read locally and never committed (gitignored) — the seek sees
    them, the public repo never does."""
    edges, parts = [], []
    for path in (LINEAGE, PRIVATE_LINEAGE):
        if not path.exists():
            continue
        raw = path.read_text(encoding="utf-8", errors="replace")
        parts.append(raw)
        try:
            import yaml  # pyyaml is present in the brain (budgets.yaml, watchlist.yaml)
            data = yaml.safe_load(raw) or {}
            edges.extend(data.get("edges") or [])
        except Exception:
            continue
    return edges, (_sha8("\n".join(parts)) if parts else "0000000")


def _matches(target: str, edge: dict) -> bool:
    """Does this edge fire for the given path/concept target?"""
    t = target.strip().lower()
    frm = (edge.get("from") or "").strip().lower()
    if frm:
        if t == frm or t.startswith(frm) or (frm.endswith("/") and t.startswith(frm)):
            return True
        if frm.startswith(t) and t:
            return True
    concept = (edge.get("concept") or "").strip().lower()
    if concept and (t in concept or concept in t) and t:
        return True
    for m in (edge.get("appears_in") or []):
        if t == str(m).strip().lower():
            return True
    return False


def _downstream(target: str, edge: dict):
    """The surfaces this edge says are impacted, given the target."""
    kind = edge.get("kind", "?")
    offrepo = bool(edge.get("offrepo"))
    out = []
    for s in (edge.get("to") or []):
        out.append((str(s), kind, offrepo))
    # appears_in: the OTHER copies plus the single source.
    members = [str(m) for m in (edge.get("appears_in") or [])]
    if members:
        tl = target.strip().lower()
        for m in members:
            if m.strip().lower() != tl:
                out.append((m, kind, offrepo))
        if edge.get("single_source"):
            out.append((f"single-source: {edge['single_source']}", kind, offrepo))
    return out


def seek(target: str):
    edges, sha = load_lineage()
    hits, kinds, edge_ids = [], set(), []
    for e in edges:
        if _matches(target, e):
            edge_ids.append(e.get("id", "?"))
            kinds.add(e.get("kind", "?"))
            for surf, kind, off in _downstream(target, e):
                hits.append({"surface": surf, "kind": kind, "offrepo": off,
                             "verb": VERB.get(kind, "reconcile")})
    return hits, sorted(kinds), edge_ids, sha


def grep_fallback(term: str):
    if ARM_ROOT:
        # Arm mode: the fallback scans the arm's own surfaces only (sealed).
        targets = [str(ARM_ROOT)]
    else:
        targets = [str(CLAUDE_DIR / g) for g in SCAN if (CLAUDE_DIR / g).exists()]
    try:
        out = subprocess.run(
            ["grep", "-rilF", "--include=*.md", "--include=*.py", "--include=*.json",
             "--exclude-dir=.git", "--exclude-dir=node_modules", "--exclude-dir=dist",
             "--exclude-dir=.venv", "--exclude-dir=__pycache__", "--exclude-dir=.next",
             "--", term, *targets],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return []
    files = set()
    for p in out.splitlines():
        p = p.strip()
        if not p:
            continue
        try:
            files.add(Path(p).resolve().relative_to(GRAPH_ROOT).as_posix())
        except ValueError:
            continue
    return sorted(files)


def write_candidate(term: str, hits):
    """Record an unlit-neuron candidate so the graph grows. Generic only —
    a grep can hit an arm path, so we never write absolute/external paths."""
    try:
        UNVERIFIED.parent.mkdir(parents=True, exist_ok=True)
        existing = UNVERIFIED.read_text(encoding="utf-8") if UNVERIFIED.exists() else \
            ("# Auto-filed unlit-neuron candidates (grep fallback). GENERIC ONLY.\n"
             "# Operator promotes candidate -> connectome/lineage.yaml in review.\n"
             "candidates:\n")
        block = [f"  - concept: {json.dumps(term)}", "    grep_hits:"]
        for h in hits:
            block.append(f"      - {h}")
        block += ["    status: unverified", f"    first_seen: {int(time.time())}", ""]
        UNVERIFIED.write_text(existing + "\n".join(block) + "\n", encoding="utf-8")
    except OSError:
        pass


def emit_receipt(line: str, payload: dict):
    """Append the machine receipt to the session AND per-turn ledgers, return the line.
    The per-turn ledger is what the Stop-hook teeth read to know a seek happened THIS turn."""
    try:
        LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        sid = os.environ.get("CLAUDE_SESSION_ID", "adhoc")
        row = json.dumps(payload, ensure_ascii=False) + "\n"
        (LEDGER_DIR / f"{sid}.jsonl").open("a", encoding="utf-8").write(row)
        (LEDGER_DIR / f"{sid}.turn.jsonl").open("a", encoding="utf-8").write(row)
    except OSError:
        pass
    return line


def off_repo_note(hits) -> str:
    if any(h["offrepo"] for h in hits):
        return ("\n⚠ OFF-REPO surfaces in this radius (the seek names them but cannot "
                "verify their bytes from here — reconcile by hand): "
                + ", ".join(h["surface"] for h in hits if h["offrepo"]))
    return ""


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__.strip())
        return 0
    if args[0] == "--file" and len(args) >= 2:
        target = args[1]
    else:
        target = " ".join(args)

    hits, kinds, edge_ids, sha = seek(target)

    if hits:
        line = (f"SEEK-COMPLETE lineage@{sha} hits={len(hits)} "
                f"via {{{','.join(kinds)}}} edges={edge_ids}{LAYER_TAG}")
        emit_receipt(line, {"ts": int(time.time()), "mode": "seek", "target": target,
                            "lineage": sha, "state": "SEEK-COMPLETE",
                            "layer": "arm" if ARM_ROOT else "brain",
                            "edges": edge_ids, "hits": [h["surface"] for h in hits]})
        print(f"🔦 GRAPH SEEK — '{target}' → {len(hits)} impacted surface(s) "
              f"[deterministic, no scan]:")
        for h in hits:
            tag = " (off-repo)" if h["offrepo"] else ""
            print(f"  • {h['surface']}{tag}\n      [{h['kind']}] → {h['verb']}")
        print(off_repo_note(hits))
        print(f"\n📋 RECEIPT (quote verbatim in the Provenance `Graph:` field):\n  {line}")
        return 0

    # No edge — unlit neuron. Fall back to grep, but file the candidate.
    print(f"⚠ UNLIT NEURON — no lineage edge for '{target}'. Falling back to grep "
          f"(scan), and filing a candidate so the graph grows.")
    g = grep_fallback(target)
    write_candidate(target, g)
    line = (f"GREP-FALLBACK(unlit:{target}) lineage@{sha} grep_hits={len(g)} "
            f"→ candidate filed{LAYER_TAG}")
    emit_receipt(line, {"ts": int(time.time()), "mode": "fallback_grep", "target": target,
                        "lineage": sha, "state": "GREP-FALLBACK",
                        "layer": "arm" if ARM_ROOT else "brain", "grep_hits": g})
    for f in g:
        print(f"  {f}")
    print(f"\n📋 RECEIPT:\n  {line}")
    print("\n💡 Add an edge to connectome/lineage.yaml so the next lookup is a seek, not a scan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
