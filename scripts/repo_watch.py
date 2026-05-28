#!/usr/bin/env python3
"""repo_watch.py — daily monitor for high-value GitHub repos.

Reads `skills/repo-watch/watchlist.yaml`, fetches HEAD SHA per repo, diffs
against the previous snapshot, classifies the delta as HIGH/LOW/EMPTY signal,
appends to a daily digest, and writes file-based trigger markers for
`/repo-deep-learn` to consume out-of-band.

Workflow lifted from Workflow Architect agent design (2026-05-28):
- Idempotent on same SHA
- File-based trigger handoff (do NOT sync-invoke deep-learn)
- Atomic state writes
- Per-repo error isolation (one bad repo doesn't abort the batch)

Run modes:
    python3 scripts/repo_watch.py                # one full pass (cron mode)
    python3 scripts/repo_watch.py --dry-run      # print what would happen, no writes
    python3 scripts/repo_watch.py --only ECC     # single-repo pass
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

CLAUDE = Path(__file__).resolve().parent.parent
WATCHLIST = CLAUDE / "skills" / "repo-watch" / "watchlist.yaml"
KNOWLEDGE = CLAUDE / "knowledge" / "repo-watch"
STATE_FILE = KNOWLEDGE / "state.json"
TRIGGERS_DIR = KNOWLEDGE / "triggers"
LOCK_FILE = KNOWLEDGE / "state.json.lock"
STALE_LOCK_SEC = 600  # 10 min


def _log(level: str, msg: str) -> None:
    print(f"[{level}] {msg}", flush=True)


def _load_yaml(path: Path) -> dict:
    """Minimal YAML reader (avoid PyYAML dep — supports our flat schema only)."""
    import yaml  # type: ignore[import-untyped]
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _gh_api(endpoint: str, jq: str | None = None, retries: int = 3) -> tuple[int, str]:
    """gh api wrapper with retry. Returns (returncode, stdout-stripped)."""
    cmd = ["gh", "api", endpoint]
    if jq:
        cmd += ["--jq", jq]
    for attempt in range(retries):
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode == 0:
            return 0, p.stdout.strip()
        if p.returncode == 4:  # gh's rate-limit / 5xx exit
            time.sleep(5 * (3 ** attempt))
            continue
        return p.returncode, p.stderr.strip()
    return 1, "retries exhausted"


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _acquire_lock() -> bool:
    """Return True if lock acquired (or stale-stolen). False if active lock held."""
    if LOCK_FILE.exists():
        age = time.time() - LOCK_FILE.stat().st_mtime
        if age < STALE_LOCK_SEC:
            return False
        _log("WARN", f"stale lock found ({int(age)}s old), reclaiming")
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(str(os.getpid()))
    return True


def _release_lock() -> None:
    try:
        LOCK_FILE.unlink()
    except FileNotFoundError:
        pass


def _classify(files: list[dict], signal_paths: list[str], threshold_files: int) -> str:
    """HIGH | LOW | EMPTY based on Workflow Architect's classification rules."""
    if not files:
        return "EMPTY"
    for f in files:
        path = f.get("filename", "")
        for sp in signal_paths:
            sp_norm = sp.rstrip("/")
            if path.startswith(sp_norm + "/") or path == sp_norm:
                return "HIGH"
    if len(files) >= threshold_files:
        return "HIGH"
    return "LOW"


def _process_repo(entry: dict, state: dict, digest_lines: list[str], dry_run: bool) -> None:
    owner, repo = entry["owner"], entry["repo"]
    key = f"{owner}/{repo}"
    threshold_files = int(entry.get("threshold_files", 5))
    signal_paths = entry.get("threshold_signal_paths", [])

    # 2.1 Fetch HEAD
    rc, sha = _gh_api(f"repos/{owner}/{repo}/commits/HEAD", jq=".sha")
    if rc != 0:
        digest_lines.append(f"| {key} | ❌ fetch failed | {sha} |")
        return

    last_sha = state.get(key, {}).get("last_seen_sha")

    # 2.2 Idempotency
    if last_sha == sha:
        digest_lines.append(f"| {key} | ✓ no change | `{sha[:8]}` |")
        return

    # 2.3 Diff vs last_sha (or full snapshot if last_sha missing)
    if last_sha:
        rc, raw = _gh_api(f"repos/{owner}/{repo}/compare/{last_sha}...{sha}", jq=".files")
        if rc != 0:
            _log("WARN", f"{key}: compare failed ({raw}); treating as snapshot baseline")
            files = []
            verdict = "BASELINE"
        else:
            try:
                files = json.loads(raw) if raw else []
            except json.JSONDecodeError:
                files = []
            verdict = _classify(files, signal_paths, threshold_files)
    else:
        # First-ever observation: record baseline, don't classify diff
        verdict = "BASELINE"
        files = []

    # 4. Emission
    short = sha[:8]
    last_short = (last_sha or "—")[:8]
    digest_lines.append(
        f"| {key} | **{verdict}** | `{last_short}` → `{short}` | {len(files)} files |"
    )

    if verdict == "HIGH":
        # Per-file summary
        digest_lines.append("")
        digest_lines.append(f"### {key} — HIGH-SIGNAL details")
        for f in files[:30]:
            status = f.get("status", "")
            digest_lines.append(f"- `{status}` {f.get('filename', '?')}")
        if len(files) > 30:
            digest_lines.append(f"- … and {len(files) - 30} more files")
        digest_lines.append("")

        # Trigger marker for /repo-deep-learn (file-based handoff)
        if not dry_run:
            TRIGGERS_DIR.mkdir(parents=True, exist_ok=True)
            slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", key)
            trigger = TRIGGERS_DIR / f"{slug}-{sha[:12]}.trigger"
            trigger.write_text(json.dumps({
                "repo": key,
                "sha": sha,
                "last_sha": last_sha,
                "files_changed": len(files),
                "detected_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "signal_paths_hit": [
                    f["filename"] for f in files
                    if any(f["filename"].startswith(sp.rstrip("/")) for sp in signal_paths)
                ][:20],
            }, indent=2))
            _log("INFO", f"{key}: trigger written → {trigger.name}")

    # 5. Advance SHA (always — even for LOW, to avoid re-diffing noise forever)
    if not dry_run:
        state[key] = {
            "last_seen_sha": sha,
            "last_verdict": verdict,
            "last_seen_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }


def main() -> int:
    ap = argparse.ArgumentParser(description="Daily watch for high-value GH repos")
    ap.add_argument("--dry-run", action="store_true", help="Print, do not write state/triggers")
    ap.add_argument("--only", help="Filter to a single repo by name (matches owner/repo or repo)")
    args = ap.parse_args()

    if not shutil.which("gh"):
        _log("ERROR", "gh CLI not found — install + authenticate first")
        return 1

    if not WATCHLIST.exists():
        _log("ERROR", f"watchlist missing: {WATCHLIST}")
        return 1

    cfg = _load_yaml(WATCHLIST)
    watchlist = cfg.get("watchlist", [])
    if args.only:
        watchlist = [w for w in watchlist if w["repo"] == args.only or f"{w['owner']}/{w['repo']}" == args.only]
        if not watchlist:
            _log("ERROR", f"--only {args.only} matched no entries")
            return 1

    KNOWLEDGE.mkdir(parents=True, exist_ok=True)
    if not args.dry_run and not _acquire_lock():
        _log("ERROR", "another repo-watch run is active (lock held); aborting")
        return 1

    try:
        # Load state
        if STATE_FILE.exists():
            try:
                state = json.loads(STATE_FILE.read_text())
            except json.JSONDecodeError:
                backup = STATE_FILE.with_suffix(f".corrupt.{int(time.time())}")
                STATE_FILE.rename(backup)
                _log("WARN", f"corrupt state.json → {backup.name}; starting fresh")
                state = {}
        else:
            state = {}

        # Digest
        today = dt.date.today().isoformat()
        digest_path = KNOWLEDGE / f"{today}.md"
        is_new = not digest_path.exists()

        lines: list[str] = []
        if is_new:
            lines.append(f"# repo-watch digest — {today}")
            lines.append("")
            lines.append("| repo | verdict | sha | changes |")
            lines.append("|---|---|---|---|")

        # Per-repo loop
        for entry in watchlist:
            try:
                _process_repo(entry, state, lines, args.dry_run)
            except Exception as e:  # noqa: BLE001 — never abort batch
                _log("ERROR", f"{entry.get('owner')}/{entry.get('repo')}: {e}")
                lines.append(f"| {entry.get('owner')}/{entry.get('repo')} | ❌ exception | {e} |")

        # Footer
        lines.append("")
        lines.append(f"_run at {dt.datetime.now(dt.timezone.utc).isoformat()}_")

        # Persist
        if args.dry_run:
            _log("INFO", "--dry-run: digest preview below\n\n" + "\n".join(lines))
        else:
            mode = "w" if is_new else "a"
            with digest_path.open(mode, encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            _atomic_write(STATE_FILE, json.dumps(state, indent=2))
            _log("INFO", f"digest → {digest_path}")
            _log("INFO", f"state → {STATE_FILE}")

        return 0
    finally:
        if not args.dry_run:
            _release_lock()


if __name__ == "__main__":
    sys.exit(main())
