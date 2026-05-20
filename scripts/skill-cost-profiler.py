#!/usr/bin/env python3
"""
skill-cost-profiler.py — observability surface 2.

Reads the native Claude Code session JSONL logs that live under
~/.claude/projects/<sanitized-cwd>/<session-uuid>.jsonl, attributes
per-turn `usage` to the Skill tool invocations within that turn, and
emits a ranked table:

  skill_name | invocations | input_tokens | output_tokens | ROI

Attribution is turn-level: every `assistant` event with a Skill tool_use
block attributes its `usage` to that skill name. If a turn invokes M
skills, the usage splits equally. Turns without a Skill tool_use are
bucketed as `__conversation__` (the operator's regular agent chat).

ROI (when trace data is available) = total_tokens / count(diligent
phase_boundary with status=ok across sessions where this skill fired).
Lower is better — fewer tokens per successful 3D Diligent.

Stdlib only — AC-1 of the spec.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

# Shared USD pricing — single source of truth across the FinOps pipeline.
sys.path.insert(0, str(Path(__file__).parent))
from _pricing import tokens_to_usd_simple, format_usd  # noqa: E402

SESSIONS_ROOT = Path.home() / ".claude" / "projects"
TRACES_DIR = Path.home() / ".claude" / "traces"

CONVERSATION_BUCKET = "__conversation__"
UNKNOWN_ARM = "__unknown__"


# ── Helpers ────────────────────────────────────────────


def _arm_from_session_path(session_file: Path) -> str:
    """Extract the arm (client repo) name from a session JSONL file path.

    Claude Code stores session JSONLs under
    ~/.claude/projects/<sanitized-cwd>/<uuid>.jsonl
    where <sanitized-cwd> is the absolute cwd with `/` replaced by `-`.
    Real-world examples we observe:

      -home-<user>                                  → operator's home dir
      -home-<user>--claude                          → brain repo
      -home-<user>-Documents-github-<arm>           → standard arm
      -home-<user>-Documents-github-<arm>-<subdir>  → arm subdir
      -<some-other-prefix>-<arm>                    → non-standard layout

    Heuristic: the arm name is the segment immediately following `github`,
    if present. Underscores in real directory names become hyphens in the
    sanitized path (e.g., `client_x` → `client-x`); we report the
    sanitized form because reversing the transform is ambiguous.

    Returns the arm slug, or the `.claude` brain bucket, or a `home` bucket
    for naked-home sessions, or UNKNOWN_ARM as a final fallback.
    """
    parent = session_file.parent.name
    if not parent.startswith("-"):
        return UNKNOWN_ARM
    # Detect the brain itself (path contains '--claude' segment).
    if "--claude" in parent or parent.endswith("-claude"):
        return ".claude"
    parts = [p for p in parent.split("-") if p]
    # Standard cwd layout: home / <user> / Documents / github / <arm> [/ subdir...]
    if "github" in parts:
        idx = parts.index("github")
        if idx + 1 < len(parts):
            return parts[idx + 1] or UNKNOWN_ARM
    # Naked home or short paths — `-home-<user>` is the operator's tilde.
    if len(parts) <= 2 and parts and parts[0] == "home":
        return "home"
    return UNKNOWN_ARM


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _task_id_for_session(session_uuid: str) -> str:
    return hashlib.sha1(session_uuid.encode("utf-8")).hexdigest()


def _iter_session_files(since: datetime) -> Iterator[Path]:
    if not SESSIONS_ROOT.exists():
        return
    for f in SESSIONS_ROOT.rglob("*.jsonl"):
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if mtime < since:
            continue
        if f.stat().st_size == 0:
            continue
        yield f


def _extract_skills_from_turn(event: dict) -> list[str]:
    msg = event.get("message") or {}
    content = msg.get("content") or []
    out: list[str] = []
    if not isinstance(content, list):
        return out
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use" and block.get("name") == "Skill":
            inp = block.get("input") or {}
            skill = inp.get("skill")
            if isinstance(skill, str) and skill.strip():
                out.append(skill.strip())
    return out


def _usage_from_turn(event: dict) -> tuple[int, int]:
    """Returns (total_input_incl_cache, output_tokens). 0,0 if no usage."""
    msg = event.get("message") or {}
    u = msg.get("usage")
    if not isinstance(u, dict):
        # Some session formats put usage at the top level.
        u = event.get("usage")
    if not isinstance(u, dict):
        return (0, 0)
    in_total = (
        int(u.get("input_tokens", 0) or 0)
        + int(u.get("cache_creation_input_tokens", 0) or 0)
        + int(u.get("cache_read_input_tokens", 0) or 0)
    )
    out_total = int(u.get("output_tokens", 0) or 0)
    return (in_total, out_total)


# ── ROI from trace ─────────────────────────────────────


def _diligent_ok_per_task() -> dict[str, int]:
    """Count phase_boundary records with name=diligent + status=ok per task_id."""
    out: dict[str, int] = defaultdict(int)
    if not TRACES_DIR.exists():
        return out
    for f in sorted(TRACES_DIR.glob("*.jsonl")):
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    rec.get("event") == "phase_boundary"
                    and rec.get("name") == "diligent"
                    and rec.get("status") == "ok"
                ):
                    tid = rec.get("task_id")
                    if isinstance(tid, str):
                        out[tid] += 1
        except OSError:
            continue
    return out


# ── Core aggregation ──────────────────────────────────


def aggregate(days: int) -> tuple[
    dict[str, dict[str, int]],
    dict[str, set[str]],
    dict[str, int],
    dict[str, dict[str, int]],
]:
    """Return (per_skill_stats, per_skill_sessions, diligent_per_task, per_arm_stats).

    per_skill_stats[name] = {invocations, in_tokens, out_tokens}
    per_skill_sessions[name] = set of session UUIDs where the skill fired
    diligent_per_task[task_id] = count of diligent_ok records
    per_arm_stats[arm] = {sessions, turns, in_tokens, out_tokens, cache_read, cache_write}

    FinOps Feature 1: per-arm rollup makes "I have trace data" → "I can
    bill Client A $X for May." Arm is derived from the session-file
    parent directory name (Claude Code's sanitized cwd encoding).
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    per_skill_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"invocations": 0, "in_tokens": 0, "out_tokens": 0}
    )
    per_skill_sessions: dict[str, set[str]] = defaultdict(set)
    per_arm_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "turns": 0,
            "in_tokens": 0,
            "out_tokens": 0,
            "cache_read": 0,
            "cache_write": 0,
        }
    )
    per_arm_sessions: dict[str, set[str]] = defaultdict(set)
    diligent = _diligent_ok_per_task()

    for f in _iter_session_files(since):
        session_uuid = f.stem
        arm = _arm_from_session_path(f)
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") != "assistant":
                    continue
                # Filter on timestamp when present.
                ts_str = event.get("timestamp") or (event.get("message") or {}).get("timestamp")
                if ts_str:
                    ts = _parse_ts(ts_str)
                    if ts is not None and ts < since:
                        continue
                in_tok, out_tok = _usage_from_turn(event)
                if in_tok == 0 and out_tok == 0:
                    continue

                # Per-arm rollup — capture the rich usage breakdown for USD.
                u = (event.get("message") or {}).get("usage") or event.get("usage") or {}
                cache_r = int(u.get("cache_read_input_tokens", 0) or 0)
                cache_w = int(u.get("cache_creation_input_tokens", 0) or 0)
                a = per_arm_stats[arm]
                a["turns"] += 1
                a["in_tokens"] += in_tok
                a["out_tokens"] += out_tok
                a["cache_read"] += cache_r
                a["cache_write"] += cache_w
                per_arm_sessions[arm].add(session_uuid)

                skills = _extract_skills_from_turn(event)
                if not skills:
                    s = per_skill_stats[CONVERSATION_BUCKET]
                    s["invocations"] += 1
                    s["in_tokens"] += in_tok
                    s["out_tokens"] += out_tok
                else:
                    n = len(skills)
                    in_split = in_tok // n
                    out_split = out_tok // n
                    in_remainder = in_tok - in_split * n
                    out_remainder = out_tok - out_split * n
                    for i, name in enumerate(skills):
                        s = per_skill_stats[name]
                        s["invocations"] += 1
                        s["in_tokens"] += in_split + (in_remainder if i == 0 else 0)
                        s["out_tokens"] += out_split + (out_remainder if i == 0 else 0)
                        per_skill_sessions[name].add(session_uuid)
        except OSError:
            continue

    # Attach session counts so the per-arm table can show breadth alongside cost.
    for arm, sessions in per_arm_sessions.items():
        per_arm_stats[arm]["sessions"] = len(sessions)

    return per_skill_stats, per_skill_sessions, diligent, per_arm_stats


def _roi_for_skill(
    per_skill_stats: dict[str, dict[str, int]],
    per_skill_sessions: dict[str, set[str]],
    diligent_per_task: dict[str, int],
    name: str,
) -> str:
    """Return ROI display string: total_tokens / sum(diligent_ok across this skill's sessions)."""
    stats = per_skill_stats.get(name, {})
    total = stats.get("in_tokens", 0) + stats.get("out_tokens", 0)
    sessions = per_skill_sessions.get(name, set())
    if not sessions or total == 0:
        return "n/a"
    diligent_count = sum(diligent_per_task.get(_task_id_for_session(s), 0) for s in sessions)
    if diligent_count == 0:
        return "n/a"
    return f"{total / diligent_count:,.0f}"


# ── Rendering ──────────────────────────────────────────


def _render_markdown(
    per_skill_stats: dict[str, dict[str, int]],
    per_skill_sessions: dict[str, set[str]],
    diligent_per_task: dict[str, int],
    per_arm_stats: dict[str, dict[str, int]],
    days: int,
) -> str:
    if not per_skill_stats and not per_arm_stats:
        return "_No usage data in window._\n"

    lines: list[str] = []

    # ── Per-arm USD rollup (FinOps Feature 1) ─────────────────────
    if per_arm_stats:
        arm_rows = []
        for arm, stats in per_arm_stats.items():
            usd = tokens_to_usd_simple(
                input_tokens=stats["in_tokens"],
                output_tokens=stats["out_tokens"],
                cache_read=stats.get("cache_read", 0),
                cache_write=stats.get("cache_write", 0),
            )
            total = stats["in_tokens"] + stats["out_tokens"]
            arm_rows.append((arm, stats.get("sessions", 0), stats["turns"], total, usd))
        arm_rows.sort(key=lambda r: r[4], reverse=True)

        lines += [
            f"# Cost by arm (client) — last {days}d",
            "",
            "| Arm | Sessions | Turns | Total tokens | USD (list price) |",
            "|---|---:|---:|---:|---:|",
        ]
        total_usd = 0.0
        for arm, sess, turns, total, usd in arm_rows:
            lines.append(f"| `{arm}` | {sess:,} | {turns:,} | {total:,} | {format_usd(usd)} |")
            total_usd += usd
        lines.append(f"| **TOTAL** |  |  |  | **{format_usd(total_usd)}** |")
        lines += ["", ""]

    # ── Per-skill breakdown (existing surface) ─────────────────────
    rows = []
    for name, stats in per_skill_stats.items():
        total = stats["in_tokens"] + stats["out_tokens"]
        usd = tokens_to_usd_simple(stats["in_tokens"], stats["out_tokens"])
        rows.append(
            (
                name,
                stats["invocations"],
                stats["in_tokens"],
                stats["out_tokens"],
                total,
                usd,
                _roi_for_skill(per_skill_stats, per_skill_sessions, diligent_per_task, name),
            )
        )
    rows.sort(key=lambda r: r[4], reverse=True)  # by total desc

    lines += [
        f"# Skill Cost Profiler — last {days}d",
        "",
        "| Skill | Invocations | Input tokens | Output tokens | Total | USD | Tokens / diligent_ok |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, n, in_t, out_t, total, usd, roi in rows:
        lines.append(
            f"| `{name}` | {n:,} | {in_t:,} | {out_t:,} | {total:,} | {format_usd(usd)} | {roi} |"
        )
    return "\n".join(lines) + "\n"


def _render_json(
    per_skill_stats: dict[str, dict[str, int]],
    per_skill_sessions: dict[str, set[str]],
    diligent_per_task: dict[str, int],
    per_arm_stats: dict[str, dict[str, int]],
) -> str:
    skills_out = []
    for name, stats in per_skill_stats.items():
        total = stats["in_tokens"] + stats["out_tokens"]
        skills_out.append(
            {
                "skill": name,
                "invocations": stats["invocations"],
                "in_tokens": stats["in_tokens"],
                "out_tokens": stats["out_tokens"],
                "total_tokens": total,
                "usd_estimate": tokens_to_usd_simple(stats["in_tokens"], stats["out_tokens"]),
                "sessions": len(per_skill_sessions.get(name, set())),
                "tokens_per_diligent_ok": _roi_for_skill(
                    per_skill_stats, per_skill_sessions, diligent_per_task, name
                ),
            }
        )
    skills_out.sort(key=lambda r: r["total_tokens"], reverse=True)

    arms_out = []
    for arm, stats in per_arm_stats.items():
        usd = tokens_to_usd_simple(
            input_tokens=stats["in_tokens"],
            output_tokens=stats["out_tokens"],
            cache_read=stats.get("cache_read", 0),
            cache_write=stats.get("cache_write", 0),
        )
        arms_out.append(
            {
                "arm": arm,
                "sessions": stats.get("sessions", 0),
                "turns": stats["turns"],
                "in_tokens": stats["in_tokens"],
                "out_tokens": stats["out_tokens"],
                "cache_read": stats.get("cache_read", 0),
                "cache_write": stats.get("cache_write", 0),
                "usd_estimate": usd,
            }
        )
    arms_out.sort(key=lambda r: r["usd_estimate"], reverse=True)

    return json.dumps({"by_skill": skills_out, "by_arm": arms_out}, indent=2) + "\n"


# ── Entry point ────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Skill Cost Profiler — Phase B Port 2.",
    )
    parser.add_argument("--days", type=int, default=30, help="Window in days (default 30).")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of markdown.")
    args = parser.parse_args(argv)

    per_skill_stats, per_skill_sessions, diligent, per_arm_stats = aggregate(args.days)

    if args.json:
        sys.stdout.write(_render_json(per_skill_stats, per_skill_sessions, diligent, per_arm_stats))
    else:
        sys.stdout.write(_render_markdown(per_skill_stats, per_skill_sessions, diligent, per_arm_stats, args.days))
    return 0


if __name__ == "__main__":
    sys.exit(main())
