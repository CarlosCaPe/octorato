#!/usr/bin/env python3
"""harmony-check.py — Octorato Harmony drift checker (the octopus moves as one).

Complement of harmonization-over-accretion: that skill stops you ADDING noise;
this one CONVERGES the values already present into one referenced motion.

One canonical value per property (tokens/canon.json), cited everywhere, copied
nowhere. When a shared numeric token diverges (10 here, 12 there) within an epsilon
band, that is DRIFT → converge to the canonical value. Colors are matched EXACTLY,
never averaged (a load-bearing alert red must not blend into brand red).

  --report  (default)  print the drift table (dry-run)
  --audit              print "DRIFT = N"; exit 1 if N>0  (the Unison Test signal)
  --fix                rewrite DRIFT literals to the canonical value (idempotent;
                       run behind the 4D Gate). Never touches exempt or color lines.

A line annotated  // canon:exempt(reason)  is witnessed, not flagged.
Soft-fail (exit 0) when tokens/canon.json is absent — mirrors check-generic.py.
Zero dependencies (stdlib only).
"""
from __future__ import annotations
import argparse, json, os, re, sys

NUM = re.compile(r"(?<![\w.#-])(\d+(?:\.\d+)?)(px|rem|ms|s)\b")
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
EXEMPT = re.compile(r"canon:exempt\(")
UI_EXT = (".css", ".scss", ".sass", ".less", ".svelte", ".astro", ".tsx", ".jsx", ".vue", ".ts", ".js")
SKIP_DIRS = {"node_modules", ".git", "dist", ".astro", "build", ".cache", ".svelte-kit"}


def find_root(start: str) -> str:
    p = os.path.abspath(start)
    while True:
        if os.path.isfile(os.path.join(p, "tokens", "canon.json")):
            return p
        nxt = os.path.dirname(p)
        if nxt == p:
            return os.path.abspath(start)
        p = nxt


def load_canon(root: str):
    path = os.path.join(root, "tokens", "canon.json")
    if not os.path.isfile(path):
        return None, None, path
    data = json.load(open(path, encoding="utf-8"))
    return data.get("tokens", {}), float(data.get("_epsilon", 1)), path


def nearest(value: float, unit: str, tokens: dict):
    """Return (key, canon_value, distance) for the closest canonical token of same unit."""
    best = None
    for k, t in tokens.items():
        if t.get("unit") != unit:
            continue
        cv = t.get("value")
        if not isinstance(cv, (int, float)):
            continue
        d = abs(value - cv)
        if best is None or d < best[2]:
            best = (k, cv, d)
    return best


def iter_files(paths):
    for p in paths:
        if os.path.isfile(p):
            yield p
        elif os.path.isdir(p):
            for dp, dns, fns in os.walk(p):
                dns[:] = [d for d in dns if d not in SKIP_DIRS]
                for fn in fns:
                    if fn.endswith(UI_EXT):
                        yield os.path.join(dp, fn)


def scan(paths, tokens, eps):
    rows = []  # (file, lineno, raw, unit, value, verdict, canon_key, canon_value)
    canon_colors = {str(t.get("value")).lower() for t in tokens.values() if isinstance(t.get("value"), str)}
    for f in iter_files(paths):
        try:
            lines = open(f, encoding="utf-8", errors="replace").read().splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if EXEMPT.search(line):
                continue
            for m in NUM.finditer(line):
                val, unit = float(m.group(1)), m.group(2)
                near = nearest(val, unit, tokens)
                if near and near[2] == 0:
                    continue  # MATCH — already canonical
                if near and near[2] <= eps:
                    rows.append((f, i, m.group(0), unit, val, "DRIFT", near[0], near[1]))
                else:
                    rows.append((f, i, m.group(0), unit, val, "UNMANAGED", None, None))
            for m in HEX.finditer(line):
                if m.group(0).lower() not in canon_colors:
                    rows.append((f, i, m.group(0), "color", None, "UNMANAGED", None, None))
    return rows


def main():
    ap = argparse.ArgumentParser(description="Octorato Harmony drift checker")
    ap.add_argument("paths", nargs="*", default=["."])
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--fix", action="store_true")
    a = ap.parse_args()
    paths = a.paths or ["."]

    root = find_root(paths[0])
    tokens, eps, cpath = load_canon(root)
    if tokens is None:
        print(f"harmony-check: no canon yet at {cpath} — soft pass (the cell has no genome to read).")
        return 0

    rows = scan(paths, tokens, eps)
    drift = [r for r in rows if r[5] == "DRIFT"]

    if a.audit:
        print(f"DRIFT = {len(drift)}")
        return 1 if drift else 0

    if a.fix:
        by_file = {}
        for r in drift:
            by_file.setdefault(r[0], []).append(r)
        changed = 0
        for f, rs in by_file.items():
            lines = open(f, encoding="utf-8").read().splitlines(keepends=True)
            for (_, ln, raw, unit, val, _, _, cv) in rs:
                target = f"{int(cv) if float(cv).is_integer() else cv}{unit}"
                if lines[ln - 1].count(raw):
                    lines[ln - 1] = lines[ln - 1].replace(raw, target, 1)
                    changed += 1
            open(f, "w", encoding="utf-8").write("".join(lines))
        print(f"harmony-check --fix: converged {changed} drifted literal(s) to canon. Re-run --audit.")
        return 0

    # --report (default)
    if not rows:
        print("harmony-check: DRIFT = 0 — the octopus moves as one. 🐙")
        return 0
    print(f"{'verdict':10} {'value':>8} {'→ canon':>10}  location")
    for (f, ln, raw, unit, val, verdict, ck, cv) in sorted(rows, key=lambda r: (r[5] != 'DRIFT', r[0])):
        tgt = f"{cv}{unit}" if cv is not None else "—"
        print(f"{verdict:10} {raw:>8} {tgt:>10}  {os.path.relpath(f, root)}:{ln}" + (f"  ({ck})" if ck else ""))
    print(f"\nDRIFT = {len(drift)} (within ±{eps}). UNMANAGED = {sum(1 for r in rows if r[5]=='UNMANAGED')} (candidates to canonize).")
    print("Converge with: harmony-check.py --fix   (behind the 4D Gate)")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
