#!/usr/bin/env python3
"""
gap-capture.py — capture 2D-Delegate SELF misses as a gap backlog.

When the delegate gate finds no agent/skill match ("nadie lo hace"), that task
is a capability-gap signal. This records it to ~/.claude/knowledge/gaps.jsonl
(gitignored — task text may carry arm/client context) and counts recurrences.

This is harmonization, NOT accretion: a single miss is noise, so it is only
logged. A gap that recurs >= THRESHOLD times "graduates" — it has earned a
place in the brain and becomes a skill-creator candidate. Build what repeats,
not what merely appeared once.

Usage:
  gap-capture.py "<task description>"   # record one SELF miss (best-effort)
  gap-capture.py --report               # ranked backlog (graduated ones flagged)
"""
import sys
import re
import json
import hashlib
import datetime
from pathlib import Path
from collections import Counter

GAPS = Path(__file__).resolve().parent.parent / "knowledge" / "gaps.jsonl"
THRESHOLD = 3
STOP = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "is",
    "are", "this", "that", "it", "be", "as", "at", "by", "from", "una", "para",
    "los", "las", "del", "con", "que", "por", "como", "the",
}


def norm_key(task: str):
    toks = sorted(
        w for w in re.findall(r"[a-z0-9]+", task.lower())
        if len(w) > 2 and w not in STOP
    )
    key = hashlib.sha1(" ".join(toks).encode("utf-8")).hexdigest()[:12]
    return key


def load():
    if not GAPS.exists():
        return []
    out = []
    for line in GAPS.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def record(task: str) -> int:
    GAPS.parent.mkdir(parents=True, exist_ok=True)
    key = norm_key(task)
    rec = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "task": task.strip()[:300],
        "key": key,
    }
    with GAPS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    count = sum(1 for r in load() if r.get("key") == key)
    if count >= THRESHOLD:
        print(
            f"🔧 GAP graduated: '{task.strip()[:60]}' seen {count}× "
            f"→ candidate for skill-creator (harmonize it in).",
            file=sys.stderr,
        )
    return count


def report():
    recs = load()
    if not recs:
        print("No gaps captured yet — the gate has found a match every time.")
        return
    counts = Counter(r.get("key") for r in recs)
    latest = {r.get("key"): r.get("task", "") for r in recs}
    graduated = sum(1 for c in counts.values() if c >= THRESHOLD)
    print(f"Gap backlog — {len(recs)} misses, {len(counts)} distinct, "
          f"{graduated} graduated (≥{THRESHOLD}×)\n")
    for key, c in counts.most_common():
        flag = "🔧 GRADUATE" if c >= THRESHOLD else "          "
        print(f"{flag}  {c:3d}×  {latest.get(key, '')[:70]}")


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(0)
    if sys.argv[1] == "--report":
        report()
        return
    try:
        record(" ".join(sys.argv[1:]))
    except Exception:
        pass  # never break the caller (the 2D gate)


if __name__ == "__main__":
    main()
