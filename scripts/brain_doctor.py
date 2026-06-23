#!/usr/bin/env python3
"""Brain Doctor — cross-platform health check for the ~/.claude/ AI-agent brain (octorato).

Read-only by default. `--fix` performs only idempotent repairs. `--json` emits machine-readable results.

Each check yields PASS / WARN / FAIL plus a one-line remediation hint.
Exit code: 0 if no FAIL, 1 if any FAIL. WARN never fails the run.

Cross-platform: pure pathlib + subprocess with explicit args, no bash-isms.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

CLAUDE_DIR = Path(__file__).resolve().parent.parent
HOME = Path.home()

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def detect_python() -> str | None:
    """Resolve a python3/python/py interpreter generically (current first)."""
    if sys.version_info >= (3, 8):
        return sys.executable or "python3"
    for cand in ("python3", "python", "py"):
        path = shutil.which(cand)
        if path:
            return path
    return None


PYTHON = detect_python()


def run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run a subprocess with explicit args; never raises on non-zero."""
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )


def git(*args: str) -> subprocess.CompletedProcess:
    return run(["git", *args], cwd=CLAUDE_DIR)


def resolve_home_relative(value):
    """arms-paths.json values are relative-to-$HOME strings OR arrays of candidates.

    Returns the first existing resolved Path, else None.
    """
    candidates = value if isinstance(value, list) else [value]
    for rel in candidates:
        p = (HOME / rel)
        if p.exists():
            return p
    return None


def read_bytes(p: Path):
    try:
        return p.read_bytes()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Check result object
# ---------------------------------------------------------------------------

class Result:
    def __init__(self, key: str, status: str, message: str, hint: str = ""):
        self.key = key
        self.status = status
        self.message = message
        self.hint = hint

    def to_dict(self):
        return {
            "key": self.key,
            "status": self.status,
            "message": self.message,
            "hint": self.hint,
        }


# ---------------------------------------------------------------------------
# Checks — each returns a Result (or list of Results); wrapped so a crash → FAIL
# ---------------------------------------------------------------------------

def check_repo_identity(fix: bool) -> Result:
    key = "repo-identity"
    if not (CLAUDE_DIR / ".git").exists():
        return Result(key, FAIL, f"{CLAUDE_DIR}/.git missing — not a git repo",
                      "run `git init` and add the octorato origin")
    cp = git("remote", "get-url", "origin")
    if cp.returncode != 0:
        return Result(key, FAIL, "no origin remote configured",
                      "git remote add origin https://github.com/CarlosCaPe/octorato.git")
    url = cp.stdout.strip()
    if "octorato" in url:
        return Result(key, PASS, f"origin → {url}")
    if "dotclaude" in url:
        if fix:
            new_url = url.replace("dotclaude", "octorato")
            fixcp = git("remote", "set-url", "origin", new_url)
            if fixcp.returncode == 0:
                return Result(key, PASS, f"origin rewritten dotclaude→octorato → {new_url}")
            return Result(key, FAIL, f"failed to rewrite origin: {fixcp.stderr.strip()}",
                          "manually: git remote set-url origin <octorato url>")
        return Result(key, FAIL, f"origin points to legacy dotclaude: {url}",
                      "run with --fix to rewrite dotclaude→octorato")
    return Result(key, WARN, f"origin neither octorato nor dotclaude: {url}",
                  "verify origin points to the octorato repo")


def check_sync_clean(fix: bool) -> Result:
    key = "sync-clean"
    status = git("status", "--porcelain")
    if status.returncode != 0:
        return Result(key, FAIL, "git status failed", "ensure CLAUDE_DIR is a valid repo")
    dirty = [ln for ln in status.stdout.splitlines() if ln.strip()]
    # upstream comparison
    up = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if up.returncode != 0:
        msg = f"{len(dirty)} local change(s); no upstream tracking branch"
        return Result(key, WARN, msg, "set upstream: git push -u origin <branch>")
    counts = git("rev-list", "--left-right", "--count", "@{u}...HEAD")
    behind = ahead = 0
    if counts.returncode == 0 and counts.stdout.strip():
        parts = counts.stdout.split()
        if len(parts) == 2:
            behind, ahead = int(parts[0]), int(parts[1])
    detail = f"{len(dirty)} uncommitted, {ahead} ahead, {behind} behind"
    if behind > 0:
        return Result(key, WARN, detail, "git pull (ai-pull) to catch up with upstream")
    return Result(key, PASS, detail)


def check_interpreter(fix: bool) -> Result:
    key = "interpreter"
    if PYTHON:
        return Result(key, PASS, f"python ≥3.8 resolved: {PYTHON} ({sys.version.split()[0]})")
    return Result(key, FAIL, "no python3/python/py ≥3.8 resolvable",
                  "install Python 3.8+ and ensure it is on PATH")


def check_python_deps(fix: bool) -> Result:
    key = "python-deps"
    req_file = CLAUDE_DIR / "requirements.txt"
    if not req_file.exists():
        return Result(key, WARN, "no requirements.txt at brain root",
                      "create ~/.claude/requirements.txt listing third-party deps")
    required = []
    for line in req_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = line.split("==")[0].split(">=")[0].split("<")[0].split("[")[0].strip()
        if name:
            required.append(name)
    missing = []
    for pkg in required:
        probe = run([PYTHON or "python3", "-c", f"import {pkg}"])
        if probe.returncode != 0:
            missing.append(pkg)
    if not missing:
        return Result(key, PASS, f"all declared deps importable ({', '.join(required)})")
    if fix:
        install = run([PYTHON or "python3", "-m", "pip", "install", "--user",
                       "-r", str(req_file)])
        if install.returncode == 0:
            return Result(key, PASS, f"installed missing deps: {', '.join(missing)}")
        return Result(key, FAIL,
                      f"pip install failed (missing: {', '.join(missing)})",
                      f"run manually: pip install --user -r {req_file}")
    return Result(key, FAIL,
                  f"missing deps: {', '.join(missing)} — heartbeat/connectome will silently degrade",
                  f"pip install --user -r {req_file}  (or rerun with --fix)")


def check_runners_tracked(fix: bool) -> Result:
    key = "runners-tracked"
    bin_dir = HOME / ".local" / "bin"
    names = ["ai-pull", "ai-push", "sync-ai-docs"]
    # On Windows the runners are .cmd/.ps1 thunks, not extensionless POSIX files.
    exts = ["", ".cmd", ".ps1", ".bat"] if os.name == "nt" else [""]

    def resolve_runner(n):
        for ext in exts:
            cand = bin_dir / (n + ext)
            if cand.exists():
                return cand
        return None

    resolved = {n: resolve_runner(n) for n in names}
    missing = [n for n, p in resolved.items() if p is None]
    if missing:
        return Result(key, FAIL, f"missing runner(s): {', '.join(missing)}",
                      "reinstall runners into ~/.local/bin/ (see arm-onboarding skill)")

    untracked = []
    scripts_dir = (CLAUDE_DIR / "scripts").resolve()
    for n in names:
        p = resolved[n]
        try:
            real = p.resolve()
        except Exception:
            real = p
        # Tracked if it's a symlink into scripts/, OR a thunk whose body execs
        # the tracked scripts/ai_sync.py (the octorato-thunk pattern).
        tracked = False
        try:
            real.relative_to(scripts_dir)
            tracked = True
        except ValueError:
            tracked = False
        if not tracked:
            try:
                body = p.read_text(encoding="utf-8", errors="ignore")
                if "octorato-thunk" in body or "scripts/ai_sync.py" in body:
                    tracked = True
            except Exception:
                pass
        if not tracked:
            untracked.append(n)

    if not untracked:
        return Result(key, PASS, "all runners resolve to tracked scripts/")
    return Result(key, WARN,
                  f"runner not version-controlled: {', '.join(untracked)} — fixes won't propagate",
                  "symlink runners to scripts/ai_sync.py or scripts/*.sh so updates flow")


def check_hooks_runtime_sync(fix: bool) -> Result:
    key = "hooks-runtime-sync"
    drift_script = CLAUDE_DIR / "scripts" / "check-hooks-drift.py"
    if not drift_script.exists():
        return Result(key, WARN, "scripts/check-hooks-drift.py not found",
                      "restore the hooks-drift validator")
    cp = run([PYTHON or "python3", str(drift_script)], cwd=CLAUDE_DIR)
    if cp.returncode == 0:
        return Result(key, PASS, "settings.json hooks == validated hooks.json projection")
    detail = (cp.stdout.strip() or cp.stderr.strip() or "drift detected").splitlines()
    msg = detail[-1] if detail else "hooks drift detected"
    return Result(key, FAIL, f"hooks drift: {msg}",
                  "run `python3 scripts/merge-hooks.py` to re-project hooks.json")


def check_hooks_merge_fresh(fix: bool) -> Result:
    key = "hooks-merge-fresh"
    hooks_json = CLAUDE_DIR / "hooks.json"
    if not hooks_json.exists():
        return Result(key, WARN, "hooks.json absent", "create hooks.json if hooks are used")
    try:
        data = json.loads(hooks_json.read_text(encoding="utf-8"))
    except Exception as e:
        return Result(key, FAIL, f"hooks.json does not parse: {e}", "fix JSON syntax in hooks.json")

    broken = []
    seen = []

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "command" and isinstance(v, str):
                    seen.append(v)
                else:
                    walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)

    for cmd in seen:
        # Extract referenced script paths under ~/.claude. Tokenize on whitespace.
        for tok in cmd.replace('"', " ").replace("'", " ").split():
            candidate = None
            t = tok
            if t.startswith("~/.claude/"):
                candidate = HOME / t[len("~/"):]
            elif "$CLAUDE_DIR/" in t or t.startswith("scripts/") or t.startswith("./scripts/"):
                rel = t.split("$CLAUDE_DIR/")[-1].lstrip("./")
                candidate = CLAUDE_DIR / rel
            elif "/.claude/" in t:
                idx = t.find("/.claude/")
                candidate = HOME / t[idx + len("/.claude/"):]
            if candidate is not None and (
                candidate.suffix in (".py", ".sh", ".js", ".ts", ".mjs") or "/scripts/" in str(candidate)
            ):
                if not candidate.exists():
                    broken.append(str(candidate))

    if broken:
        uniq = sorted(set(broken))
        return Result(key, FAIL, f"{len(uniq)} hooks.json command(s) reference missing file(s): {', '.join(uniq[:5])}",
                      "fix or remove broken command paths in hooks.json")
    return Result(key, PASS, f"all {len(seen)} hooks.json command(s) reference existing files")


def check_leak_guard(fix: bool) -> Result:
    key = "leak-guard"
    cp = git("config", "core.hooksPath")
    hooks_path = cp.stdout.strip() if cp.returncode == 0 else ""
    pre_push = CLAUDE_DIR / ".githooks" / "pre-push"
    pp_exists = pre_push.exists()
    pp_exec = pp_exists and (os.access(str(pre_push), os.X_OK) or os.name == "nt")

    problems = []
    if hooks_path != ".githooks":
        if fix:
            fixcp = git("config", "core.hooksPath", ".githooks")
            if fixcp.returncode == 0:
                hooks_path = ".githooks"
            else:
                problems.append(f"could not set core.hooksPath: {fixcp.stderr.strip()}")
        else:
            problems.append(f"core.hooksPath is '{hooks_path or '(unset)'}', expected '.githooks'")
    if not pp_exists:
        problems.append(".githooks/pre-push missing")
    elif not pp_exec:
        problems.append(".githooks/pre-push not executable")

    if not problems:
        return Result(key, PASS, "core.hooksPath=.githooks; pre-push present & executable")
    hint = "run with --fix to set core.hooksPath .githooks" if hooks_path != ".githooks" \
        else "chmod +x .githooks/pre-push"
    status = FAIL if (not pp_exists or hooks_path != ".githooks") else WARN
    return Result(key, status, "; ".join(problems), hint)


def check_connectome_fresh(fix: bool) -> Result:
    key = "connectome-fresh"
    nm = CLAUDE_DIR / "neural_map.json"
    if not nm.exists():
        if fix:
            gen = CLAUDE_DIR / "scripts" / "generate_neural_map.py"
            if gen.exists():
                run([PYTHON or "python3", str(gen)], cwd=CLAUDE_DIR)
        if not nm.exists():
            return Result(key, FAIL, "neural_map.json missing",
                          "run `python3 scripts/generate_neural_map.py`")
    nm_mtime = nm.stat().st_mtime
    newest = 0.0
    newest_src = None
    for pattern_dir, glob in (("skills", "**/SKILL.md"), ("agents", "**/*.md")):
        base = CLAUDE_DIR / pattern_dir
        if not base.exists():
            continue
        for f in base.glob(glob):
            try:
                m = f.stat().st_mtime
            except Exception:
                continue
            if m > newest:
                newest = m
                newest_src = f
    if newest <= nm_mtime:
        return Result(key, PASS, "neural_map.json newer than all skills/agents sources")
    rel = newest_src.relative_to(CLAUDE_DIR) if newest_src else "?"
    if fix:
        gen = CLAUDE_DIR / "scripts" / "generate_neural_map.py"
        if gen.exists():
            cp = run([PYTHON or "python3", str(gen)], cwd=CLAUDE_DIR)
            if cp.returncode == 0:
                return Result(key, PASS, "neural_map.json regenerated")
            return Result(key, FAIL, f"regeneration failed: {cp.stderr.strip()[:80]}",
                          "run generate_neural_map.py manually")
    return Result(key, WARN, f"neural_map.json stale — {rel} is newer",
                  "run `python3 scripts/generate_neural_map.py` (or --fix)")


def check_arms_config(fix: bool) -> Result:
    key = "arms-config"
    p = CLAUDE_DIR / "company" / "config" / "arms-paths.json"
    if not p.exists():
        return Result(key, WARN, "company/config/arms-paths.json absent (gitignored/optional)",
                      "create it to enable sync-targets checks")
    try:
        json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return Result(key, FAIL, f"arms-paths.json does not parse: {e}", "fix JSON syntax")
    return Result(key, PASS, "arms-paths.json present and valid JSON")


def check_sync_targets(fix: bool) -> list[Result]:
    key = "sync-targets"
    p = CLAUDE_DIR / "company" / "config" / "arms-paths.json"
    if not p.exists():
        return [Result(key, WARN, "arms-paths.json absent — skipping sync-target verification",
                       "create arms-paths.json to enable")]
    try:
        arms = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return [Result(key, FAIL, f"arms-paths.json unreadable: {e}", "fix JSON")]

    results = []
    checked = 0
    for arm, value in arms.items():
        repo = resolve_home_relative(value)
        if repo is None:
            continue  # repo not present on this machine — skip silently
        checked += 1
        source = repo / ".claude" / "CLAUDE.md"
        if not source.exists():
            results.append(Result(f"{key}:{arm}", WARN,
                                  f"{arm}: .claude/CLAUDE.md missing — cannot verify mirrors",
                                  "ensure arm has .claude/CLAUDE.md"))
            continue
        src_bytes = read_bytes(source)
        for mirror_rel in (".github/copilot-instructions.md", ".cursorrules"):
            mirror = repo / mirror_rel
            if not mirror.exists():
                results.append(Result(f"{key}:{arm}", WARN,
                                      f"{arm}: {mirror_rel} missing",
                                      "run sync-ai-docs to regenerate mirror"))
                continue
            if read_bytes(mirror) != src_bytes:
                results.append(Result(f"{key}:{arm}", WARN,
                                      f"{arm}: {mirror_rel} differs from .claude/CLAUDE.md",
                                      "run sync-ai-docs to re-sync mirror"))
        # if both mirrors matched, no per-mirror result emitted; add a PASS marker
        arm_problems = [r for r in results if r.key == f"{key}:{arm}"]
        if not arm_problems:
            results.append(Result(f"{key}:{arm}", PASS, f"{arm}: mirrors in sync"))

    if checked == 0:
        return [Result(key, WARN, "no arm repos resolve on this machine",
                       "clone arm repos or update arms-paths.json")]
    return results


def check_blocklist(fix: bool) -> Result:
    key = "blocklist"
    p = CLAUDE_DIR / "company" / "brain-blocklist.txt"
    if not p.exists():
        return Result(key, WARN, "company/brain-blocklist.txt absent — generic-check soft-fails open",
                      "create brain-blocklist.txt to harden leak prevention")
    return Result(key, PASS, "brain-blocklist.txt present")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def check_finops_enforcement(fix: bool) -> Result:
    key = "finops-enforcement"
    cfg = CLAUDE_DIR / "budgets.yaml"
    if not cfg.exists():
        return Result(key, WARN,
                      "budgets.yaml absent — per-arm budget caps are NOT enforced (FinOps off)",
                      "cp budgets.yaml.example budgets.yaml, then set monthly_usd_cap per arm")
    n = cfg.read_text(errors="ignore").count("monthly_usd_cap")
    return Result(key, PASS, f"FinOps enforcement ON — budgets.yaml present ({n} cap line(s))")


def check_lineage_sound(fix: bool) -> Result:
    key = "lineage-sound"
    lineage = CLAUDE_DIR / "connectome" / "lineage.yaml"
    doctor = CLAUDE_DIR / "scripts" / "lineage-doctor.py"
    if not lineage.exists():
        return Result(key, WARN, "connectome/lineage.yaml absent (graph organ not initialized)")
    if not doctor.exists():
        return Result(key, WARN, "scripts/lineage-doctor.py missing")
    cp = run([PYTHON or "python3", str(doctor), "--quiet"], cwd=CLAUDE_DIR)
    if cp.returncode == 0:
        return Result(key, PASS, "lineage graph sound — no dangling edges, no cycles; the seek can be trusted")
    detail = (cp.stderr or cp.stdout or "").strip().splitlines()
    return Result(key, FAIL, "lineage graph UNSOUND — a seek over it would lie",
                  detail[0] if detail else "run `python3 scripts/lineage-doctor.py`")


def check_release_drift(fix: bool) -> Result:
    """News is the brain's marketing reflex: a documented version that was never
    tagged/released = a growth moment (GH release + /dataqbs-news → site/FB) silently
    skipped. Flags when CHANGELOG's top version has no matching git tag — checking the
    remote too, so an un-fetched fresh clone doesn't false-positive on a real release."""
    key = "release-drift"
    changelog = CLAUDE_DIR / "CHANGELOG.md"
    if not changelog.exists():
        return Result(key, WARN, "CHANGELOG.md absent — cannot verify release/news cadence",
                      "create CHANGELOG.md at brain root")
    top_version = None
    for line in changelog.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.startswith("## ") or "unreleased" in line.lower():
            continue
        m = re.search(r"v(\d+\.\d+\.\d+)", line)
        if m:
            top_version = m.group(1)
            break
    if not top_version:
        return Result(key, WARN, "no versioned heading found in CHANGELOG.md",
                      "use `## [date] — vX.Y.Z` headings when cutting a release")
    tags_cp = git("tag", "--list")
    local_tags = set(tags_cp.stdout.split()) if tags_cp.returncode == 0 else set()
    if f"v{top_version}" in local_tags:
        return Result(key, PASS, f"CHANGELOG top v{top_version} has a matching git tag — released")
    # A fresh clone may not have fetched tags. "Released" = the remote tag / GH release
    # exists, not whether this working copy happened to pull it — so fall back to the
    # remote before declaring drift, or the check false-positives on every un-fetched clone.
    try:
        ls = subprocess.run(
            ["git", "ls-remote", "--tags", "origin", f"v{top_version}"],
            cwd=str(CLAUDE_DIR), capture_output=True, text=True, timeout=10,
        )
        if ls.returncode == 0 and f"refs/tags/v{top_version}" in ls.stdout:
            return Result(key, PASS,
                          f"CHANGELOG top v{top_version} released (remote tag exists; "
                          f"not fetched locally — `git fetch --tags` to sync)")
    except (subprocess.TimeoutExpired, OSError):
        pass  # offline — fall through to the local-only verdict below
    return Result(key, WARN,
                  f"CHANGELOG declares v{top_version} but no git tag v{top_version} (local or remote) — "
                  f"release & news never cut (news = top-of-funnel marketing; a major bump with no news = lost reach)",
                  f"gh release create v{top_version} (notes from CHANGELOG); then run /dataqbs-news in the arm")


# ---------------------------------------------------------------------------
# RULE #1 — Registry checks (Wired or Corrupt). docs/architecture/wired-or-corrupt.md
# D0 bootstrap, D1 schema, D2 anchors, D3 per-rule wiring + Coverage Ledger.
# ---------------------------------------------------------------------------

REGISTRY_PATH = CLAUDE_DIR / "registry" / "rules.yaml"
REGISTRY_SCHEMA = CLAUDE_DIR / "registry" / "rules.schema.json"
HOOKS_JSON = CLAUDE_DIR / "hooks.json"
CLAUDE_MD = CLAUDE_DIR / "CLAUDE.md"
CC_EVENTS = {"UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "SessionStart"}


def _rt(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _hooks_index() -> set:
    """(event, matcher, script_basename) tuples from tracked hooks.json."""
    idx = set()
    try:
        data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return idx
    for ev, arr in data.items():
        if ev.startswith("$") or not isinstance(arr, list):
            continue
        for block in arr:
            matcher = block.get("matcher", "*")
            for hk in block.get("hooks", []):
                for tok in hk.get("command", "").replace("\\", " ").split():
                    if tok.endswith(".py"):
                        idx.add((ev, matcher, os.path.basename(tok)))
    return idx


def _resolve_script(name: str) -> Path:
    """canonical_name -> Path. bare .py lives under scripts/; a path is repo-root-relative."""
    return (CLAUDE_DIR / name) if "/" in name else (CLAUDE_DIR / "scripts" / name)


def _claude_anchors() -> list:
    """Anchorable rule lines in CLAUDE.md: ## / ### headings + 'ULTRA RULE' lines."""
    anchors = []
    for ln in _rt(CLAUDE_MD).splitlines():
        s = ln.strip()
        if s.startswith("## ") or s.startswith("### ") or "ULTRA RULE" in s:
            anchors.append(s)
    return anchors


def check_registry(fix: bool) -> list:
    """RULE #1: every registry rule must be wired; unwired = CORRUPT (FAIL)."""
    if not REGISTRY_PATH.exists():
        return [Result("registry-bootstrap", FAIL, "registry/rules.yaml missing",
                       "Phase 0: author registry/rules.yaml")]
    try:
        import yaml
        reg = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        return [Result("registry-bootstrap", FAIL, f"rules.yaml does not load: {e}", "fix YAML syntax")]
    rules = reg.get("rules", []) if isinstance(reg, dict) else []
    out = []

    # D0 bootstrap: pre-push gate present (WARN in Phase 0 until commit lands)
    pp = CLAUDE_DIR / ".githooks" / "pre-push"
    sentinel = pp.exists() and "OCTORATO-WIRE-GATE" in _rt(pp)
    out.append(Result("registry-bootstrap", PASS if sentinel else WARN,
                      f"rules.yaml loads ({len(rules)} rules); pre-push gate "
                      f"{'present' if sentinel else 'NOT wired yet'}",
                      "" if sentinel else "add OCTORATO-WIRE-GATE block to .githooks/pre-push"))

    # D1 schema
    try:
        from jsonschema import Draft202012Validator
        schema = json.loads(REGISTRY_SCHEMA.read_text(encoding="utf-8"))
        errs = sorted(Draft202012Validator(schema).iter_errors(reg), key=lambda e: list(e.path))
        if errs:
            msg = "; ".join(f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errs[:3])
            out.append(Result("registry-schema", FAIL, f"rules.yaml invalid: {msg}",
                              "fix rules.yaml vs rules.schema.json"))
        else:
            out.append(Result("registry-schema", PASS, "rules.yaml valid vs schema"))
    except Exception as e:
        out.append(Result("registry-schema", FAIL, f"schema check crashed: {e}", "pip install jsonschema"))

    # D2 forward anchors + D3 per-rule wiring
    hooks = _hooks_index()
    ctext = _rt(CLAUDE_MD)
    wiring_fail, anchor_fail = [], []
    for r in rules:
        rid = r.get("id", "?")
        anchor = (r.get("source") or {}).get("anchor", "")
        if anchor and anchor not in ctext:
            anchor_fail.append(f"{rid}: anchor '{anchor}' absent")
        for m in r.get("mechanism", []):
            cn = m.get("canonical_name")
            if not cn:
                continue
            if not _resolve_script(cn).exists():
                wiring_fail.append(f"{rid}: {cn} MISSING on disk")
                continue
            fe = m.get("firing_event")
            if fe in CC_EVENTS:
                fm = m.get("firing_matcher") or "*"
                base = os.path.basename(cn)
                hit = any(e == fe and b == base and (mm == fm or fm == "*" or mm == "*")
                          for (e, mm, b) in hooks)
                if not hit:
                    wiring_fail.append(f"{rid}: {base} not in hooks.json at {fe}|{fm}")
    out.append(Result("registry-wiring", FAIL if wiring_fail else PASS,
                      f"all {len(rules)} rules wired (disk + hooks.json)"
                      if not wiring_fail else "; ".join(wiring_fail[:5]),
                      "every mechanism must exist on disk and be in hooks.json"))
    out.append(Result("registry-anchors", FAIL if anchor_fail else PASS,
                      "all rule anchors present in CLAUDE.md"
                      if not anchor_fail else "; ".join(anchor_fail[:4]),
                      "fix source.anchor or restore the CLAUDE.md heading"))

    # D2 reverse: prose anchors with no rule -> WARN (Phase 0 coverage gap, not fail-closed yet)
    covered = {(r.get("source") or {}).get("anchor", "") for r in rules}
    anchors = _claude_anchors()
    uncovered = [a for a in anchors if not any(c and c in a for c in covered)]
    pct = round(100 * (len(anchors) - len(uncovered)) / max(1, len(anchors)))
    out.append(Result("registry-coverage", WARN if uncovered else PASS,
                      f"Coverage {pct}% of CLAUDE.md anchors "
                      f"({len(anchors) - len(uncovered)}/{len(anchors)}); "
                      f"{len(uncovered)} prose anchors unwired (Phase 0)",
                      "Phase 1: backfill uncovered anchors, then flip D2-reverse fail-closed"))
    return out


CHECKS = [
    ("repo-identity", check_repo_identity),
    ("rule-1-registry", check_registry),
    ("sync-clean", check_sync_clean),
    ("interpreter", check_interpreter),
    ("python-deps", check_python_deps),
    ("runners-tracked", check_runners_tracked),
    ("hooks-runtime-sync", check_hooks_runtime_sync),
    ("hooks-merge-fresh", check_hooks_merge_fresh),
    ("leak-guard", check_leak_guard),
    ("connectome-fresh", check_connectome_fresh),
    ("arms-config", check_arms_config),
    ("sync-targets", check_sync_targets),
    ("blocklist", check_blocklist),
    ("finops-enforcement", check_finops_enforcement),
    ("lineage-sound", check_lineage_sound),
    ("release-drift", check_release_drift),
]

STATUS_ICON = {PASS: "✓", WARN: "!", FAIL: "✗"}


def run_all(fix: bool) -> list[Result]:
    results: list[Result] = []
    for key, fn in CHECKS:
        try:
            out = fn(fix)
        except Exception as e:  # one bad check never crashes the run
            results.append(Result(key, FAIL, f"check crashed: {e}", "report this bug"))
            continue
        if isinstance(out, list):
            results.extend(out)
        else:
            results.append(out)
    return results


def render_human(results: list[Result]) -> None:
    print("=" * 60)
    print("🧠 BRAIN DOCTOR")
    print(f"   {CLAUDE_DIR}")
    print("=" * 60)
    width = max((len(r.key) for r in results), default=10)
    for r in results:
        icon = STATUS_ICON.get(r.status, "?")
        print(f"  [{r.status}] {icon} {r.key.ljust(width)}  {r.message}")
        if r.status in (WARN, FAIL) and r.hint:
            print(f"        ↳ fix: {r.hint}")
    p = sum(1 for r in results if r.status == PASS)
    w = sum(1 for r in results if r.status == WARN)
    f = sum(1 for r in results if r.status == FAIL)
    print("-" * 60)
    print(f"  {p} passed, {w} warn, {f} fail")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser(description="Brain Doctor — health check for ~/.claude/ (octorato)")
    ap.add_argument("--fix", action="store_true", help="perform idempotent repairs (opt-in)")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("--registry", action="store_true",
                    help="run ONLY the RULE #1 registry checks (for .githooks/pre-push)")
    args = ap.parse_args()

    results = check_registry(args.fix) if args.registry else run_all(args.fix)
    fails = sum(1 for r in results if r.status == FAIL)

    if args.json:
        warns = sum(1 for r in results if r.status == WARN)
        passes = sum(1 for r in results if r.status == PASS)
        print(json.dumps({
            "claude_dir": str(CLAUDE_DIR),
            "interpreter": PYTHON,
            "summary": {"passed": passes, "warn": warns, "fail": fails},
            "checks": [r.to_dict() for r in results],
        }, indent=2))
    else:
        render_human(results)

    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
