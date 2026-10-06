#!/usr/bin/env python3
"""quickstart.py — zero-to-alive for a brand-new Octorato user, in one command.

A stranger clones the brain and runs this. No company brain, no sealed worlds, no
config: it checks prerequisites, wires the bin runners, builds the connectome,
wires the Claude Code hooks (merge-hooks.py into ~/.claude/settings.json), points
git at the push guard (core.hooksPath=.githooks), projects Cursor hooks when
present, runs the FAST health check, and ends by writing a first spec that
spec_lint.py accepts. One command after the clone (v10, AC-14 and AC-15).

Where the first spec goes. A newcomer's example must not dirty the public brain
repo, because the next `ai-sync` would publish it. So by default it lands in the
brain's gitignored private layer, `~/.claude/company/docs/specs/<stamp>-first-spec/`,
and quickstart refuses to write it anywhere inside the brain that git does not
ignore. `--project DIR` puts it in your own project instead
(`DIR/docs/specs/<stamp>-first-spec/`), which is where real specs belong. A
second run reuses the existing `*-first-spec` directory instead of adding another.

Exit code: non-zero when a wiring step fails (Claude Code hooks, git hooks path,
first spec). A health-check finding is reported, not fatal, because a fresh clone
legitimately misses optional parts (a private blocklist, optional Python deps).

Going further (your own brain + sealed worlds + multi-machine sync) is a separate,
later step, documented in the README.

Idempotent. Safe to re-run. No network. Writes only under ~/.claude, ~/.local/bin
(the runners), ~/.cursor/hooks.json when Cursor is installed, and --project DIR
when given.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

CLAUDE = Path(__file__).resolve().parent.parent
_COLOR = sys.stdout.isatty() and sys.platform != "win32"


def _c(code, s):
    return f"\033[{code}m{s}\033[0m" if _COLOR else s


def info(s): print(_c("0;32", s))
def warn(s): print(_c("1;33", s))
def err(s):  print(_c("0;31", s))
def step(n, total, s): print(_c("1;36", f"\n[{n}/{total}] {s}"))


def run_script(rel: str, *args) -> bool:
    """Run a brain python script if present. True on success or absent."""
    path = CLAUDE / rel
    if not path.exists():
        warn(f"  (skipped: {rel} not found in this checkout)")
        return True
    code = subprocess.run([sys.executable or "python3", str(path), *args]).returncode
    return code == 0


def _hook_events(path: Path) -> set:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(data, dict):
        return set()
    return {k for k in data if not k.startswith("$")}


def wire_claude_hooks(brain: Path) -> tuple[bool, str]:
    """Project hooks.json into ~/.claude/settings.json through merge-hooks.py,
    then read settings.json back: every event hooks.json declares must be there.
    merge-hooks.py resolves ~/.claude itself, so a checkout anywhere else would
    wire the wrong brain; that case is refused, not guessed."""
    home_brain = Path.home() / ".claude"
    try:
        same = home_brain.resolve() == brain.resolve()
    except OSError:
        same = False
    if not same:
        return False, (f"this checkout is {brain}, but Claude Code loads {home_brain}; "
                       "clone the brain to ~/.claude and re-run")
    want = _hook_events(brain / "hooks.json")
    if not want:
        return False, "hooks.json is missing or declares no hook events"
    script = brain / "scripts" / "merge-hooks.py"
    if not script.is_file():
        return False, "scripts/merge-hooks.py is missing from this checkout"
    if subprocess.run([sys.executable or "python3", str(script)]).returncode != 0:
        return False, "merge-hooks.py exited non-zero"
    settings = brain / "settings.json"
    try:
        have = json.loads(settings.read_text(encoding="utf-8")).get("hooks") or {}
    except (OSError, ValueError, AttributeError):
        return False, f"{settings} is missing or unreadable after merge-hooks.py"
    missing = sorted(want - set(have))
    if missing:
        return False, f"settings.json lacks hook events: {', '.join(missing)}"
    return True, f"{len(have)} hook events wired into {settings}"


def _git(brain: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(brain), *args], capture_output=True, text=True)


def set_git_hooks_path(brain: Path) -> tuple[bool, str]:
    """Point git at the shipped push guard. Without this, .githooks/pre-push never
    runs and a secret can reach the public remote."""
    cur = _git(brain, "config", "--get", "core.hooksPath").stdout.strip()
    if cur != ".githooks":
        cp = _git(brain, "config", "core.hooksPath", ".githooks")
        if cp.returncode != 0:
            return False, f"git config failed: {cp.stderr.strip()}"
        cur = _git(brain, "config", "--get", "core.hooksPath").stdout.strip()
        if cur != ".githooks":
            return False, f"core.hooksPath reads {cur or '(unset)'} after setting it"
    pre_push = brain / ".githooks" / "pre-push"
    if not pre_push.is_file():
        return False, ".githooks/pre-push is missing from this checkout"
    if os.name != "nt" and not os.access(pre_push, os.X_OK):
        return False, ".githooks/pre-push is not executable (chmod +x .githooks/pre-push)"
    return True, "core.hooksPath=.githooks; pre-push present"


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def create_first_spec(brain: Path, project: Path | None, now: datetime | None = None
                      ) -> tuple[bool, str, Path | None]:
    """Write the example spec from templates/spec/ and lint it with spec_lint.py.

    Reuses an existing `*-first-spec` directory, so a re-run adds nothing. Inside
    the brain, the target must be gitignored: an example that git would track is
    an example the next sync would publish."""
    root = project.expanduser() if project is not None else brain / "company"
    specs = root / "docs" / "specs"
    existing = sorted(p for p in specs.glob("*-first-spec") if p.is_dir()) if specs.is_dir() else []
    now = now or datetime.now()
    target = existing[-1] if existing else specs / f"{now.strftime('%Y%m%d%H%M')}-first-spec"
    if _inside(target, brain):
        rel = os.path.relpath(target.resolve(), brain.resolve())
        if _git(brain, "check-ignore", "-q", "--no-index", rel).returncode != 0:
            return False, (f"{target} is inside the brain and git does not ignore it; "
                           "pass --project <your project dir>"), None
    if not existing:
        tdir = brain / "templates" / "spec"
        try:
            target.mkdir(parents=True, exist_ok=False)
            for name in ("feature.md", "plan.md"):
                text = (tdir / f"{name}.template").read_text(encoding="utf-8")
                text = text.replace("{{DATE}}", now.strftime("%Y-%m-%d"))
                text = text.replace("{{SPEC_DIR}}", str(target))
                (target / name).write_text(text, encoding="utf-8")
        except OSError as e:
            return False, f"could not write the first spec: {e}", None
    cp = subprocess.run([sys.executable or "python3", str(brain / "scripts" / "spec_lint.py"),
                         str(target)], capture_output=True, text=True)
    if cp.returncode != 0:
        return False, f"spec_lint.py rejected {target}: {(cp.stdout + cp.stderr).strip()}", target
    return True, f"{target} (spec_lint.py: clean)", target


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Octorato quickstart: one command after the clone.")
    ap.add_argument("--project", type=Path, default=None,
                    help="write the first spec into DIR/docs/specs/ instead of the brain's "
                         "gitignored company/ layer")
    args = ap.parse_args(argv)
    print(_c("1;35", "\n🐙  Octorato quickstart. Let's bring your brain to life.\n"))
    total = 8
    wiring_failures = []

    # 1. Prerequisites
    step(1, total, "Checking prerequisites")
    ok = True
    if sys.version_info < (3, 9):
        err(f"  ✗ Python {sys.version_info.major}.{sys.version_info.minor} found; need 3.9+")
        ok = False
    else:
        info(f"  ✓ Python {sys.version_info.major}.{sys.version_info.minor}")
    if shutil.which("git"):
        info("  ✓ git")
    else:
        err("  ✗ git not found. Install it first.")
        ok = False
    has_claude = bool(shutil.which("claude"))
    cursor_home = Path.home() / ".cursor"
    has_cursor = cursor_home.is_dir()
    if has_claude:
        info("  ✓ Claude Code CLI (`claude`)")
    else:
        warn("  ! Claude Code CLI not on PATH.")
    if has_cursor:
        info(f"  ✓ Cursor runtime detected ({cursor_home})")
    else:
        warn("  ! ~/.cursor not found (Cursor IDE not installed on this machine).")
    if not has_claude and not has_cursor:
        warn("  ! No runtime detected yet. Install Claude Code and/or Cursor:")
        warn("    https://docs.claude.com/claude-code  |  https://cursor.com")
        warn("    Continuing: brain files still wire; you need one runtime to run agents.")
    if not (CLAUDE / "CLAUDE.md").exists():
        err(f"  ✗ This doesn't look like a brain checkout ({CLAUDE}/CLAUDE.md missing).")
        err("    Clone first:  git clone https://github.com/CarlosCaPe/octorato.git ~/.claude")
        return 1
    info(f"  ✓ Brain checkout at {CLAUDE}")
    if not ok:
        err("\nFix the ✗ items above, then re-run. Nothing was changed.")
        return 1

    # 2. Wire the runners
    step(2, total, "Wiring the bin runners (ai-sync / ai-push / ai-pull)")
    run_script("scripts/install-runners.py")

    # 3. Build the connectome
    step(3, total, "Building the connectome (the skill/agent graph)")
    run_script("scripts/generate_neural_map.py")

    # 4. Wire the Claude Code hooks (hooks.json -> settings.json)
    step(4, total, "Wiring the Claude Code hooks (hooks.json → ~/.claude/settings.json)")
    ok, detail = wire_claude_hooks(CLAUDE)
    (info if ok else err)(f"  {'✓' if ok else '✗'} {detail}")
    if not ok:
        wiring_failures.append("Claude Code hooks")

    # 5. Point git at the push guard
    step(5, total, "Enabling the push guard (git core.hooksPath=.githooks)")
    ok, detail = set_git_hooks_path(CLAUDE)
    (info if ok else err)(f"  {'✓' if ok else '✗'} {detail}")
    if not ok:
        wiring_failures.append("git hooks path")

    # 6. Project hooks into Cursor when present
    step(6, total, "Projecting fail-closed hooks → Cursor (no-op if Cursor absent)")
    if has_cursor:
        run_script("scripts/merge-hooks-cursor.py")
    else:
        warn("  (skipped: no ~/.cursor; run merge-hooks-cursor.py after installing Cursor)")

    # 7. Fast health check
    step(7, total, "Running the fast health check (brain_doctor.py --fast)")
    healthy = run_script("scripts/brain_doctor.py", "--fast")

    # 8. First spec
    step(8, total, "Writing your first spec")
    ok, detail, spec_dir = create_first_spec(CLAUDE, args.project)
    (info if ok else err)(f"  {'✓' if ok else '✗'} {detail}")
    if not ok:
        wiring_failures.append("first spec")

    # First-value moment
    print(_c("1;32", "\n" + "─" * 64))
    if wiring_failures:
        err(f"✗ Not wired: {', '.join(wiring_failures)}. See the ✗ lines above, fix, re-run.")
    elif healthy:
        print(_c("1;32", "✓ Your brain is alive."))
    else:
        warn("Brain wired, but the fast health check flagged something. See above; "
             "most items self-heal with `python3 scripts/brain_doctor.py --fix`.")
    print("─" * 64)
    if spec_dir is not None:
        print(f"""
YOUR FIRST SPEC:
  {spec_dir}
  Four ideas carry the whole method:
    spec     what must be true, one checkable sentence per criterion (feature.md)
    plan     how, in which steps (plan.md)
    tasks    the plan's numbered lines, each naming the criteria it serves
    verdict  a reviewer that did not write the code decides when it is done
  Read the two files, then ask your assistant to build it.""")
    print("""
TRY IT NOW (the 5-minute proof):
  1. Open a runtime in any folder:
       Claude Code:   claude
       Cursor:        Agent chat (CURSOR_AGENT=1) with this brain loaded
  2. Ask it something real, e.g.:
       "summarize what this repo does and propose one improvement"
  3. Watch what a brain adds on top of a plain agent:
       • a Provenance footer on every answer (Basis / Engine / Touched / Verified)
       • the 2D delegate gate picking the right skill/agent for the task
       • skills loading themselves from this library

WHY THIS, NOT A STOCK EDITOR AGENT:
  Your AI agent forgets who you are and mixes your worlds. An octorato is its
  second brain: memory that lasts, every world sealed from the others, and a
  receipt on every action. One brain for clients, projects, courses, anything
  you keep separate. The difference between a clever assistant and one you can
  trust on real work (and, when a world happens to be a client, bill for).

GOING FURTHER (your own brain + sealed worlds):
  Create your own company brain and sealed "arms" (a client, a project, a
  research topic, a course you're taking), then keep every machine in sync with
  one command:  ai-sync
  Full guide in the README.
""")
    print(_c("1;35", "Welcome aboard. 🐙\n"))
    return 1 if wiring_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
