#!/usr/bin/env python3
"""g__wrap__export-guard.py: start a tracing hook only for an arm that allows export.

The Export_Guard of the v11 tracing spec (AC-09, AC-10, AC-11). Every hook
command of the Tracing_Wrapper plugin calls this script with the upstream hook
command after `--`:

  python3 ~/.claude/scripts/g__wrap__export-guard.py -- <upstream hook argv...>
  python3 g__wrap__export-guard.py --explain        # decide only, reason on stderr
  python3 g__wrap__export-guard.py --selftest [fixture_dir]

The guard reads the hook payload on stdin, finds the session's arm, reads that
arm's Export_Policy (`telemetry.export` in its `arm.json`) and starts the
upstream command ONLY when the policy is exactly `allow`. In every other case
it exits 0 with no output on stdout or stderr and spawns nothing, which every
harness event treats as a no-op (AC-10). The upstream hook is the vendor's
unmodified script; its tree is not patched, the guard decides whether its
process exists at all.

ARM_RESOLUTION, as implemented.

  1. The session's directories are the payload `cwd` (required, absolute) and,
     when the harness exports it, CLAUDE_PROJECT_DIR. Each is resolved to its
     REAL path (os.path.realpath: every symlink, `..` and `.` resolved by the
     filesystem, in that order, the way the kernel walks it), and must be an
     existing directory.
  2. A real path inside a brain resolves to NO arm, whatever arms-paths.json
     says. The brain paths are the real paths of `$HOME/.claude` and of the
     directory this script lives in (its parent's parent). A registered arm
     whose real root is inside a brain is dropped from the registry: a brain
     path never counts as an arm, whichever symlink names it.
  3. The arms are `$HOME/.claude/company/config/arms-paths.json`, read as
     ai_sync.load_arms() reads it: a value is a HOME-relative string or an array
     of candidates, the first candidate that exists wins, else the first. Each
     chosen root is then resolved to its real path.
  4. A directory's arms are every registered real root that contains its real
     path (component-wise, never a string prefix: `arms/a` does not contain
     `arms/ab`). Its arm is the deepest of them.
  5. ALLOW only when: the cwd has an arm; CLAUDE_PROJECT_DIR, when set, has the
     SAME arm (same real root); and that arm and every other registered arm
     containing either directory read `telemetry.export` == "allow". A nested
     arm inside a `deny` arm inherits the deny, because the outer arm's
     commitment covers its whole tree.
  6. The Export_Policy of an arm is read from `<real root>/arm.json`, opened
     with O_NOFOLLOW: a symlinked arm.json is refused, so a deny arm cannot
     borrow another arm's `allow`. It must be a regular file of at most 1 MiB,
     UTF-8, one JSON object, with no repeated key at any level. `telemetry`
     absent, `export` absent (AC-09), or any value but the exact string `allow`
     is deny.

FAIL-CLOSED. Every read or parse error is a deny, never an allow and never a
block: an unreadable stdin, a payload that is not one JSON object, a repeated
payload key, a relative or missing cwd, a cwd that does not exist, an
arms-paths.json that is unreadable, not an object, or holds a value that is
neither a string nor a list of strings, an arm.json that is missing, a
symlink, not a regular file, unreadable, too large or not valid. A deny is
exit 0, silent: a tracing failure never blocks a turn (FR-04).

ON ALLOW the upstream argv runs with the original stdin BYTES and the guard's
own environment, unchanged: nothing is added, removed or overridden, so the
upstream redaction setting is whatever the operator's environment says and the
guard never turns it off (AC-11). The upstream's stdout is DISCARDED and its
exit code is not propagated; its stderr passes through. A tracer has nothing
to say to the harness, and an upstream that printed a `block` decision or
exited 2 would otherwise block the turn it is only meant to observe. The guard
exits 0 whatever the upstream does.

The guard imports nothing from the brain: the only file that decides whether a
trace leaves an arm is this one, and it is on the arming surface
(scripts/g__pretool__arming-surface.py, `g__wrap__*.py`).

NAMED RESIDUALS, deliberately not covered here:
  - The policy is only as good as arm.json. An agent that writes `allow` into
    it through a route the Export_Flip_Gate (g__pretool__export-flip.py) does
    not parse flips the arm; that gate is a speed bump for the honest
    accident, and the plan accepts this residual by name.
  - HOME and CLAUDE_PROJECT_DIR come from the hook's environment. An arm's own
    `.claude/settings.json` is not on the arming surface and can carry an
    `env` block; pointing HOME at a forged brain with a forged arms-paths.json
    makes a deny arm resolve to an allow arm. That is a deliberate act on an
    arm file, the Doctor (T16) is the detector, and the same env block could
    switch the tracer on in any case.
  - A session that starts in an allow arm and reads a deny arm's files by
    absolute path (cwd never moves) is traced as the allow arm it runs in. The
    guard decides by where the session is, not by what it reads.
  - Latency and timeouts of the upstream are T17's measurement, not bounded
    here; the harness hook timeout is the only cap today.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys

for _stream in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

_HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT_BRAIN = os.path.dirname(_HERE)
DEFAULT_FIXTURES = os.path.join("registry", "fixtures", "SECURITY.export-guard")
ARMS_REL = os.path.join("company", "config", "arms-paths.json")
ARM_JSON_MAX = 1 << 20
ALLOW = "allow"


class Deny(Exception):
    """The decision is deny; the message is the reason (only --explain shows it)."""


def _no_dup(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"repeated key {k!r}")
        out[k] = v
    return out


def _loads_object(text: str, what: str) -> dict:
    try:
        obj = json.loads(text, object_pairs_hook=_no_dup)
    except ValueError as exc:
        raise Deny(f"{what} is not valid JSON ({exc})")
    if not isinstance(obj, dict):
        raise Deny(f"{what} is not a JSON object")
    return obj


def _contains(root: str, path: str) -> bool:
    try:
        return os.path.commonpath([root, path]) == root
    except ValueError:  # different drives on Windows
        return False


def _real_dir(path, what: str) -> str:
    if not isinstance(path, str) or not path:
        raise Deny(f"{what} is missing")
    if not os.path.isabs(path):
        raise Deny(f"{what} is not absolute: {path!r}")
    real = os.path.realpath(path)
    if not os.path.isdir(real):
        raise Deny(f"{what} is not an existing directory: {path!r}")
    return real


def brain_paths(home: str) -> list[str]:
    return sorted({os.path.realpath(os.path.join(home, ".claude")),
                   os.path.realpath(SCRIPT_BRAIN)})


def load_arm_roots(home: str, brains: list[str]) -> list[tuple[str, str]]:
    """[(name, real root)] from arms-paths.json; [] when the file is absent."""
    cfg = os.path.join(home, ".claude", ARMS_REL)
    try:
        with open(cfg, "rb") as fh:
            data = fh.read()
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise Deny(f"arms-paths.json unreadable: {exc}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Deny("arms-paths.json is not UTF-8")
    raw = _loads_object(text, "arms-paths.json")
    roots = []
    for name, val in raw.items():
        cands = val if isinstance(val, list) else [val]
        if not cands or not all(isinstance(c, str) and c for c in cands):
            raise Deny(f"arms-paths.json entry {name!r} is not a path or a list of paths")
        chosen = None
        for rel in cands:
            p = os.path.join(home, rel)
            if os.path.exists(p):
                chosen = p
                break
        chosen = chosen or os.path.join(home, cands[0])
        real = os.path.realpath(chosen)
        if not os.path.isdir(real):
            continue  # a root that does not exist contains nothing
        if any(_contains(b, real) for b in brains):
            continue  # a brain path never counts as an arm
        roots.append((name, real))
    return roots


def export_policy(root: str) -> str:
    """'allow' or 'deny' for the arm at `root` (a real path). Never raises."""
    path = os.path.join(root, "arm.json")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    if not getattr(os, "O_NOFOLLOW", 0) and os.path.islink(path):
        return "deny"  # no O_NOFOLLOW on this OS: refuse a link by lstat
    try:
        fd = os.open(path, flags)
    except OSError:
        return "deny"  # missing, a symlink (ELOOP), unreadable: all deny
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > ARM_JSON_MAX:
            return "deny"
        chunks, total = [], 0
        while True:
            b = os.read(fd, 65536)
            if not b:
                break
            total += len(b)
            if total > ARM_JSON_MAX:
                return "deny"
            chunks.append(b)
    except OSError:
        return "deny"
    finally:
        os.close(fd)
    try:
        man = _loads_object(b"".join(chunks).decode("utf-8"), "arm.json")
    except (Deny, UnicodeDecodeError):
        return "deny"
    tel = man.get("telemetry")
    if not isinstance(tel, dict):
        return "deny"  # absent (AC-09) or not an object
    return ALLOW if tel.get("export") == ALLOW else "deny"


def decide(raw: bytes, *, home: str, project_dir: str | None) -> str:
    """Return the arm root whose sessions may export; raise Deny otherwise."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Deny("payload is not UTF-8")
    payload = _loads_object(text, "payload")
    cwd = _real_dir(payload.get("cwd"), "payload cwd")
    dirs = [cwd]
    if project_dir is not None:
        dirs.append(_real_dir(project_dir, "CLAUDE_PROJECT_DIR"))
    brains = brain_paths(home)
    for d in dirs:
        if any(_contains(b, d) for b in brains):
            raise Deny(f"brain session ({d}): a brain path never resolves to an arm")
    roots = load_arm_roots(home, brains)
    if not roots:
        raise Deny("no arm registered")
    session_arm = None
    containing = set()
    for d in dirs:
        hits = [r for _n, r in roots if _contains(r, d)]
        if not hits:
            raise Deny(f"no arm contains {d}")
        deepest = max(hits, key=len)
        if session_arm is None:
            session_arm = deepest
        elif deepest != session_arm:
            raise Deny(f"cwd and CLAUDE_PROJECT_DIR resolve to different arms "
                       f"({session_arm} vs {deepest})")
        containing.update(hits)
    for root in sorted(containing):
        if export_policy(root) != ALLOW:
            raise Deny(f"Export_Policy of the arm at {root} is deny")
    return session_arm


def run_upstream(argv: list[str], raw: bytes, env: dict | None = None) -> None:
    """Start the upstream hook with the original stdin bytes; never raises."""
    try:
        subprocess.run(argv, input=raw, stdout=subprocess.DEVNULL,
                       env=env if env is not None else dict(os.environ))
    except Exception:
        pass  # a tracing failure never blocks a turn


def guard(raw: bytes, upstream: list[str], *, home: str, project_dir: str | None,
          env: dict | None = None) -> tuple[bool, str]:
    """(spawned, reason). Spawns only on allow."""
    try:
        root = decide(raw, home=home, project_dir=project_dir)
    except Deny as exc:
        return False, str(exc)
    except Exception as exc:  # anything unforeseen is a deny, never an allow
        return False, f"internal error: {type(exc).__name__}: {exc}"
    if not upstream:
        return False, "no upstream command after `--`"
    run_upstream(upstream, raw, env)
    return True, f"allow: arm at {root}"


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--selftest":
        return _selftest(argv[1] if len(argv) > 1 else None)
    explain = bool(argv) and argv[0] == "--explain"
    upstream = argv[argv.index("--") + 1:] if "--" in argv else []
    try:
        raw = sys.stdin.buffer.read()
    except Exception:
        raw = b""
    home = os.path.expanduser("~")
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if explain:
        try:
            root = decide(raw, home=home, project_dir=project_dir)
            sys.stderr.write(f"export-guard: allow: arm at {root}\n")
        except Exception as exc:
            sys.stderr.write(f"export-guard: deny: {exc}\n")
        return 0
    guard(raw, upstream, home=home, project_dir=project_dir)
    return 0


# --- selftest -------------------------------------------------------------------------

_STUB = r"""import os, sys
data = sys.stdin.buffer.read()
with open(sys.argv[1], "wb") as fh:
    fh.write(data)
with open(sys.argv[1] + ".env", "w", encoding="utf-8") as fh:
    fh.write(os.environ.get("EXPORT_GUARD_SELFTEST_MARK", ""))
print('{"decision": "block", "reason": "an upstream stdout the guard must discard"}')
sys.exit(2)
"""


def _selftest(fdir: str | None = None) -> int:
    """Every fixture leg through guard() under a sandbox HOME, with a stub upstream.

    Fixture file (violation*.json: the upstream must NOT be spawned; benign*.json:
    it must be spawned, with the payload bytes and the environment unchanged):
      {"arms_paths": {...} | "arms_paths_raw": "<text>",   -> HOME/.claude/company/config/arms-paths.json
       "files": {"<rel>": <json value> | "<raw text>"},     -> written under HOME
       "dirs": ["<rel>"], "symlinks": [["<link rel>", "<target rel>"]],
       "unreadable": ["<rel>"],                               -> chmod 000 (skipped as root)
       "project_dir": "{{SANDBOX}}/<rel>",                    -> CLAUDE_PROJECT_DIR
       "payload": {...} | "payload_raw": "<text>",
       "_setup": {"expect_reason": "<substring>"}}
    A violation must be refused for the reason it names, so a leg that fails for
    an unrelated reason cannot pass for the case it claims. `{{SANDBOX}}` expands
    to the leg's HOME. CLI legs then run the real argv and stdin path.
    """
    import glob as _glob
    import shutil
    import tempfile

    fdir = fdir or DEFAULT_FIXTURES
    if not os.path.isabs(fdir):
        fdir = os.path.join(SCRIPT_BRAIN, fdir)
    if not os.path.isdir(fdir):
        print(f"selftest FAIL: fixture dir missing: {fdir}", file=sys.stderr)
        return 1
    files = sorted(_glob.glob(os.path.join(fdir, "violation*.json"))) + \
        sorted(_glob.glob(os.path.join(fdir, "benign*.json")))
    names = [os.path.basename(f) for f in files]
    if not any(n.startswith("violation") for n in names) or \
       not any(n.startswith("benign") for n in names):
        print(f"selftest FAIL: need violation*.json and benign*.json in {fdir}",
              file=sys.stderr)
        return 1
    is_root = hasattr(os, "geteuid") and os.geteuid() == 0

    def sub(s: str, sandbox: str) -> str:
        return s.replace("{{SANDBOX}}", sandbox.replace("\\", "/"))

    failures, refused, spawned, skipped = [], 0, 0, []
    for path, name in zip(files, names):
        with open(path, encoding="utf-8") as fh:
            fx = json.load(fh)
        setup = fx.get("_setup") or {}
        if fx.get("unreadable") and (is_root or os.name == "nt"):
            skipped.append(name)
            continue
        sandbox = os.path.realpath(tempfile.mkdtemp(prefix="export-guard-selftest-"))
        try:
            os.makedirs(os.path.join(sandbox, ".claude", "company", "config"))
            for d in fx.get("dirs") or []:
                os.makedirs(os.path.join(sandbox, *d.split("/")), exist_ok=True)
            for rel, content in (fx.get("files") or {}).items():
                fp = os.path.join(sandbox, *rel.split("/"))
                os.makedirs(os.path.dirname(fp), exist_ok=True)
                with open(fp, "w", encoding="utf-8") as fh:
                    fh.write(content if isinstance(content, str) else json.dumps(content))
            cfg = os.path.join(sandbox, ".claude", ARMS_REL)
            if "arms_paths_raw" in fx:
                with open(cfg, "w", encoding="utf-8") as fh:
                    fh.write(fx["arms_paths_raw"])
            elif "arms_paths" in fx:
                with open(cfg, "w", encoding="utf-8") as fh:
                    json.dump(fx["arms_paths"], fh)
            for link, target in fx.get("symlinks") or []:
                lp = os.path.join(sandbox, *link.split("/"))
                tp = os.path.join(sandbox, *target.split("/"))
                os.makedirs(os.path.dirname(lp), exist_ok=True)
                os.symlink(tp, lp, target_is_directory=os.path.isdir(tp))
            for rel in fx.get("unreadable") or []:
                os.chmod(os.path.join(sandbox, *rel.split("/")), 0)
            if "payload_raw" in fx:
                raw = sub(fx["payload_raw"], sandbox).encode("utf-8")
            else:
                raw = sub(json.dumps(fx["payload"]), sandbox).encode("utf-8")
            pd = sub(fx["project_dir"], sandbox) if "project_dir" in fx else None
            stub = os.path.join(sandbox, "stub_upstream.py")
            with open(stub, "w", encoding="utf-8") as fh:
                fh.write(_STUB)
            marker = os.path.join(sandbox, "spawned.bin")
            env = dict(os.environ, EXPORT_GUARD_SELFTEST_MARK="env-" + name)
            did, reason = guard(raw, [sys.executable, stub, marker], home=sandbox,
                                project_dir=pd, env=env)
            really = os.path.exists(marker)
            if did != really:
                failures.append(f"{name}: guard said spawned={did} but the stub "
                                f"{'ran' if really else 'did not run'}")
            elif name.startswith("violation"):
                if really:
                    failures.append(f"{name}: upstream WAS spawned ({reason})")
                else:
                    want = setup.get("expect_reason") or ""
                    if want and want not in reason.replace("\\", "/").replace(sandbox, "{{SANDBOX}}"):
                        failures.append(f"{name}: refused without {want!r}: {reason}")
                    else:
                        refused += 1
            else:
                if not really:
                    failures.append(f"{name}: upstream NOT spawned ({reason})")
                else:
                    with open(marker, "rb") as fh:
                        got = fh.read()
                    with open(marker + ".env", encoding="utf-8") as fh:
                        got_env = fh.read()
                    if got != raw:
                        failures.append(f"{name}: upstream stdin differs from the payload")
                    elif got_env != "env-" + name:
                        failures.append(f"{name}: upstream environment was not passed")
                    else:
                        spawned += 1
        except OSError as exc:
            if fx.get("symlinks") and os.name == "nt":
                skipped.append(name)
            else:
                failures.append(f"{name}: leg raised {type(exc).__name__}: {exc}")
        except Exception as exc:
            failures.append(f"{name}: leg raised {type(exc).__name__}: {exc}")
        finally:
            for rel in fx.get("unreadable") or []:
                try:
                    os.chmod(os.path.join(sandbox, *rel.split("/")), 0o600)
                except OSError:
                    pass
            shutil.rmtree(sandbox, ignore_errors=True)

    # CLI legs: the real argv and stdin path, an allow arm in a sandbox HOME, and a
    # stub that would print a block and exit 2. The guard must print nothing and
    # exit 0 in every one, and spawn only in the last.
    sandbox = os.path.realpath(tempfile.mkdtemp(prefix="export-guard-cli-"))
    try:
        arm = os.path.join(sandbox, "arms", "open")
        os.makedirs(arm)
        os.makedirs(os.path.join(sandbox, ".claude", "company", "config"))
        with open(os.path.join(arm, "arm.json"), "w", encoding="utf-8") as fh:
            json.dump({"kind": "arm", "name": "open", "telemetry": {"export": "allow"}}, fh)
        with open(os.path.join(sandbox, ".claude", ARMS_REL), "w", encoding="utf-8") as fh:
            json.dump({"open": "arms/open"}, fh)
        stub = os.path.join(sandbox, "stub_upstream.py")
        with open(stub, "w", encoding="utf-8") as fh:
            fh.write(_STUB)
        good = json.dumps({"cwd": arm, "hook_event_name": "Stop"}).encode("utf-8")
        cli = [
            ("cli payload not JSON", [], b"{not json", False),
            ("cli payload not UTF-8", [], b"\xff\xfe\x00", False),
            ("cli empty stdin", [], b"", False),
            ("cli allow arm but no upstream after --", None, good, False),
            ("cli --explain never spawns", ["--explain"], good, False),
            ("cli allow arm spawns", [], good, True),
        ]
        env = {k: v for k, v in os.environ.items()
               if k not in ("CLAUDE_PROJECT_DIR", "PYTHONUTF8", "PYTHONIOENCODING")}
        env.update(HOME=sandbox, USERPROFILE=sandbox)
        for i, (label, pre, stdin, must_spawn) in enumerate(cli):
            marker = os.path.join(sandbox, f"cli{i}.bin")
            if pre is None:
                args = ["--"]
            else:
                args = pre + ["--", sys.executable, stub, marker]
            cp = subprocess.run([sys.executable, os.path.abspath(__file__)] + args,
                                input=stdin, capture_output=True, env=env, timeout=60)
            ran = os.path.exists(marker)
            quiet_ok = cp.stdout == b"" and (pre == ["--explain"] or cp.stderr == b"")
            if cp.returncode != 0 or not quiet_ok or ran != must_spawn:
                failures.append(f"{label}: rc={cp.returncode} out={cp.stdout[:80]!r} "
                                f"err={cp.stderr[:80]!r} spawned={ran}")
            elif must_spawn:
                spawned += 1
            else:
                refused += 1
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    if failures:
        print("selftest FAIL: " + "; ".join(failures), file=sys.stderr)
        return 1
    print(f"selftest PASS: {refused} not spawned + {spawned} spawned "
          f"(g__wrap__export-guard.py vs {os.path.basename(fdir)}); every refusal is "
          f"exit 0 with no output, an upstream's stdout and exit 2 never reach the harness")
    if skipped:
        print(f"selftest SKIPPED on this platform: {', '.join(skipped)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except BaseException:
        os._exit(0)  # never block a turn, never start the upstream on an error
