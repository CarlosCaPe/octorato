#!/usr/bin/env python3
"""external_review.py: receipts for a review run on another engine (v11 phase 4).

THE GAP IT CLOSES
Every receipt the ledger honoured before this was written for a harness
subagent. A review run through `codex exec` or `gemini -p` counted only when a
Claude subagent quoted it, so the receipt belonged to the Claude subagent
(docs/architecture/v11-reply-panel.md, R-05: "independent in context, not in
model"). Spec docs/specs/202610141000-v11-harness-independence-opt-in-tracing,
FR-05 to FR-07, AC-18 to AC-29, AC-37, AC-38, task T19.

WHAT A RECEIPT PROVES, AND NOTHING MORE
A Bash hook pair writes the External_Review_Receipt around one call:

  r__pretool-bash__external-review.py   PreToolUse Bash: parse, check, pending
  r__posttool-bash__external-review.py  PostToolUse Bash: re-check, complete

It is written only when one simple command named a PINNED interpreter and a
PINNED script by their literal absolute paths, with only that engine's
allowlisted arguments (an Accepted_Review_Call); every pinned file of that
engine hashed to its pin before and after the call, with its realpath and the
realpath of every ancestor up to its pin root unchanged; the shell startup and
engine config files hashed to their pins; none of BASH_ENV, ENV, NODE_OPTIONS,
NODE_PATH was set in the hook's environment; and the call took this exact
prompt as one literal argument, asked for this model and produced this exact
output. It proves the hashes of the files it checked, not that the hashed
bytes were the bytes executed, not which model the vendor served, and not
that the modules and config the CLI loads were unchanged. Those residuals are
BOUNDED, not closed: an external receipt never forms a quorum alone and never
clears a send (receipt_ledger.panel_pass_for, g__stop__reply-panel.py), so a
forged external PASS adds at most one vote beside a required harness PASS and
a forged external NEEDS-WORK can only block (AC-38, `receipt_ledger.py
--selftest-external`).

Every other shape of call still runs and never counts: the reflexes never
block and fail open, like r__subagent-stop__qa-receipt.py.

THE PINS (operator-written, per machine, gitignored)
~/.claude/company/config/reviewer-pins.json, on the arming surface. This
module never writes it. `pin-command` prints the command the operator runs in
a terminal; `pin-json` prints the file's content on stdout for that command's
redirect. Template: templates/company/config/reviewer-pins.json.template.

  python3 external_review.py pin-command [--pin-root DIR]   what to pin, and how
  python3 external_review.py pin-json --engine codex --interpreter P --script P
          --engine-path P --pin-root DIR [--engine gemini ...]   the file content
  python3 external_review.py check                          do the pins hold now?
  python3 external_review.py parse '<command>'              is it an Accepted_Review_Call?
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import stat
import sys
from pathlib import Path

# Hook payloads are UTF-8 JSON; the Windows default (cp1252) mangles any
# non-ASCII character before it is read, and the prompt digest would differ.
try:
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

_HERE = Path(__file__).resolve().parent

ENGINES = ("codex", "gemini")
ROLES = ("interpreter", "script", "engine")
# Shell startup files and engine config files, hashed once per machine at pin
# time (absent recorded as null) and compared before and after every call.
STARTUP_FILES = ("~/.bashrc", "~/.bash_profile", "~/.profile")
CONFIG_FILES = {"codex": "~/.codex/config.toml", "gemini": "~/.gemini/settings.json"}
PINNED_FILES = STARTUP_FILES + tuple(CONFIG_FILES[e] for e in ENGINES)
# Each of these, set in the hook's own environment, can make the call load
# code the pins do not cover (a sourced script, a preloaded module).
POISON_ENV = ("BASH_ENV", "ENV", "NODE_OPTIONS", "NODE_PATH")
PINS_REL = ("company", "config", "reviewer-pins.json")
REVIEWERS_REL = ("registry", "reviewers.yaml")

# Raw-text deny list, applied outside single-quoted spans: no redirect of any
# kind (so no heredoc and no here-string), no pipe, list or background
# operator, no expansion, no subshell or group, no raw newline.
_FORBIDDEN = set("<>&|;$`(){}\n\r")
# Unquoted only: a glob, a tilde or a comment would make the argv Bash passes
# differ from the literal tokens compared here (AC-23).
_UNQUOTED_FORBIDDEN = set("*?[~#")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}\Z")
_SHA64 = re.compile(r"[0-9a-f]{64}\Z")


def home() -> str:
    return os.path.expanduser("~")


def pins_path() -> Path:
    return Path(home()).joinpath(".claude", *PINS_REL)


def reviewers_path() -> Path:
    return Path(home()).joinpath(".claude", *REVIEWERS_REL)


def _expand(p: str) -> str:
    return os.path.expanduser(p) if isinstance(p, str) else ""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prompt_digest(prompt: str) -> str:
    """SHA-256 of the prompt argument's bytes, as Bash passes them (UTF-8)."""
    return sha256_bytes(prompt.encode("utf-8", "surrogateescape"))


# ---------------------------------------------------------------------------
# The Accepted_Review_Call parser (AC-20, AC-22, AC-23)
# ---------------------------------------------------------------------------

def raw_text_problem(command: str) -> str:
    """"" when the raw command text holds none of the forbidden characters
    outside single-quoted spans, else the reason. Double quotes do not hide
    anything: `$` and backtick still expand inside them, and a `'` inside
    double quotes is a literal, not the start of a single-quoted span."""
    if not isinstance(command, str) or not command.strip():
        return "empty command"
    state, i, n = None, 0, len(command)
    while i < n:
        c = command[i]
        if state == "'":
            if c == "'":
                state = None
            i += 1
            continue
        if c in _FORBIDDEN:
            return f"raw {c!r} outside single quotes"
        if state == '"':
            if c == '"':
                state = None
            elif c == "\\" and i + 1 < n:
                i += 1
                if command[i] in _FORBIDDEN:
                    return f"raw {command[i]!r} outside single quotes"
            i += 1
            continue
        if c == "'":
            state = "'"
        elif c == '"':
            state = '"'
        elif c == "\\":
            i += 1
            if i < n and command[i] in _FORBIDDEN:
                return f"raw {command[i]!r} outside single quotes"
        elif c in _UNQUOTED_FORBIDDEN:
            return f"unquoted {c!r}"
        i += 1
    if state:
        return "unterminated quote"
    return ""


def tokens(command: str) -> list:
    """The command split as `shlex.shlex(command, posix=True,
    punctuation_chars=True)` splits it, splitting on whitespace only (the raw
    check already refused every punctuation character) and with no comment
    character (a `#` is refused unquoted). Raises ValueError on bad quoting."""
    lex = shlex.shlex(command, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""
    return list(lex)


def _flag_value(rest: list, i: int):
    return rest[i + 1] if i + 1 < len(rest) else None


def _parse_codex(rest: list) -> tuple:
    """codex: `exec`, then only `--skip-git-repo-check`, `-m|--model NAME`
    and exactly one prompt argument. Returns (model, prompt, index) or raises."""
    if not rest or rest[0] != "exec":
        raise ValueError("codex call does not start with `exec`")
    model, prompt, pidx, seen = None, None, None, set()
    i = 1
    while i < len(rest):
        t = rest[i]
        if t == "--skip-git-repo-check":
            if t in seen:
                raise ValueError(f"repeated {t}")
            seen.add(t)
            i += 1
        elif t in ("-m", "--model"):
            if model is not None:
                raise ValueError("model given twice")
            model = _flag_value(rest, i)
            if model is None or not _MODEL.match(model):
                raise ValueError(f"model name {model!r} is not a plain name")
            i += 2
        elif t.startswith("-"):
            raise ValueError(f"argument {t!r} is outside the codex allowlist")
        else:
            if prompt is not None:
                raise ValueError("more than one prompt argument")
            prompt, pidx = t, i
            i += 1
    if prompt is None:
        raise ValueError("no prompt argument (a stdin prompt is not accepted)")
    return model, prompt, pidx


def _parse_gemini(rest: list) -> tuple:
    """gemini: only `-m|--model NAME` and exactly one `-p|--prompt TEXT`."""
    model, prompt, pidx = None, None, None
    i = 0
    while i < len(rest):
        t = rest[i]
        if t in ("-m", "--model"):
            if model is not None:
                raise ValueError("model given twice")
            model = _flag_value(rest, i)
            if model is None or not _MODEL.match(model):
                raise ValueError(f"model name {model!r} is not a plain name")
            i += 2
        elif t in ("-p", "--prompt"):
            if prompt is not None:
                raise ValueError("prompt given twice")
            prompt = _flag_value(rest, i)
            if prompt is None:
                raise ValueError("-p without a prompt")
            if prompt.startswith("-"):
                raise ValueError("prompt starts with '-'")
            pidx = i + 1
            i += 2
        else:
            raise ValueError(f"argument {t!r} is outside the gemini allowlist")
    if prompt is None:
        raise ValueError("no -p/--prompt argument")
    return model, prompt, pidx


_PARSERS = {"codex": _parse_codex, "gemini": _parse_gemini}


def parse_call(command: str, engines: dict) -> tuple:
    """(call, "") when `command` is an Accepted_Review_Call for one of
    `engines` ({engine: (interpreter path, script path)}), else (None, why).

    call = {engine, interpreter, script, requested_model, prompt,
            prompt_sha256, prompt_index} where prompt_index is the argv index
    of the prompt (argv[0] is the interpreter)."""
    why = raw_text_problem(command)
    if why:
        return None, why
    try:
        toks = tokens(command)
    except ValueError as e:
        return None, f"unparseable: {e}"
    if len(toks) < 2:
        return None, "not an interpreter plus script call"
    hit = None
    for name, pair in (engines or {}).items():
        try:
            interp, script = pair
        except (TypeError, ValueError):
            continue
        if name in _PARSERS and interp and script and toks[0] == interp and toks[1] == script:
            hit = name
            break
    if hit is None:
        return None, "the first two tokens are not a pinned interpreter and script"
    try:
        model, prompt, pidx = _PARSERS[hit](toks[2:])
    except ValueError as e:
        return None, str(e)
    if prompt.startswith("-"):
        return None, "prompt starts with '-'"
    return {"engine": hit, "interpreter": toks[0], "script": toks[1],
            "requested_model": model or "unknown", "prompt": prompt,
            "prompt_sha256": prompt_digest(prompt), "prompt_index": pidx + 2}, ""


# ---------------------------------------------------------------------------
# Hashing and pins (AC-19, AC-20)
# ---------------------------------------------------------------------------

def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_sha256(root: str) -> str:
    """SHA-256 over the sorted (relative path, file SHA-256) pairs of a
    directory, so a rename or a swap inside it changes the hash. A symlink
    inside is recorded by its target text, never followed."""
    pairs = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in list(dirnames) + list(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            st = os.lstat(full)
            if stat.S_ISLNK(st.st_mode):
                pairs.append((rel, "link:" + os.readlink(full)))
            elif stat.S_ISREG(st.st_mode):
                pairs.append((rel, file_sha256(full)))
            elif not stat.S_ISDIR(st.st_mode):
                pairs.append((rel, "special"))
    body = "".join(f"{rel}\0{sha}\n" for rel, sha in sorted(pairs))
    return sha256_bytes(body.encode("utf-8", "surrogateescape"))


def path_sha256(path: str, kind: str) -> str:
    return tree_sha256(path) if kind == "dir" else file_sha256(path)


def optional_file_sha256(path: str):
    """SHA-256 of a file, or None when it does not exist (absent is a value)."""
    p = _expand(path)
    if not os.path.lexists(p):
        return None
    return file_sha256(p)


def _contains(root: str, path: str) -> bool:
    try:
        return os.path.commonpath([root, path]) == root
    except ValueError:
        return False


def _ancestors(path: str, root: str) -> list:
    """Every directory from dirname(path) up to and including root."""
    out, p = [], os.path.dirname(path)
    while True:
        out.append(p)
        if p == root:
            return out
        parent = os.path.dirname(p)
        if parent == p or not _contains(root, parent):
            return out
        p = parent


def entry_problems(entry: dict, home_dir: str | None = None) -> list:
    """AC-19 for one pinned entry: hash, realpath, ancestor prefixes, pin root."""
    home_dir = home_dir or home()
    role = entry.get("role")
    path, real, sha = entry.get("path"), entry.get("realpath"), entry.get("sha256")
    root, kind = entry.get("pin_root"), entry.get("kind", "file")
    label = f"{role} {path}"
    if not all(isinstance(x, str) and x for x in (path, real, sha, root)) \
            or kind not in ("file", "dir"):
        return [f"{label}: pin entry incomplete (path, realpath, sha256, pin_root, kind)"]
    if not (os.path.isabs(path) and os.path.isabs(real) and os.path.isabs(root)):
        return [f"{label}: pinned paths must be absolute"]
    probs = []
    rroot = os.path.realpath(root)
    if rroot != root:
        probs.append(f"{label}: pin root {root} is not its own realpath")
    if root in ("/", home_dir) or rroot in ("/", os.path.realpath(home_dir)):
        probs.append(f"{label}: pin root may be neither $HOME nor /")
    if not (_contains(root, real) and _contains(root, path)):
        probs.append(f"{label}: pin root {root} does not contain the pinned path")
    now_real = os.path.realpath(path)
    if now_real != real:
        probs.append(f"{label}: realpath is {now_real}, pinned {real}")
    for base in (real, path):
        if not _contains(root, base):
            continue
        for anc in _ancestors(base, root):
            if os.path.realpath(anc) != anc:
                probs.append(f"{label}: ancestor {anc} resolves elsewhere")
                break
    if probs:
        return probs
    try:
        if kind == "dir" and not os.path.isdir(real):
            return [f"{label}: pinned directory is missing"]
        if kind == "file" and not os.path.isfile(real):
            return [f"{label}: pinned file is missing"]
        got = path_sha256(real, kind)
    except OSError as e:
        return [f"{label}: unreadable ({type(e).__name__})"]
    if got != sha:
        probs.append(f"{label}: hash differs from its pin")
    return probs


def load_pins(path: Path | None = None):
    """The Reviewer_Pins as a dict, or None when absent or unreadable."""
    p = path or pins_path()
    try:
        with open(p, "rb") as fh:
            data = json.loads(fh.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def engine_paths(pins) -> dict:
    """{engine: (interpreter path, script path)} for every pinned engine."""
    out = {}
    for name, spec in ((pins or {}).get("engines") or {}).items():
        if name not in ENGINES or not isinstance(spec, dict):
            continue
        by = {e.get("role"): e for e in spec.get("entries") or [] if isinstance(e, dict)}
        interp, script = by.get("interpreter"), by.get("script")
        if interp and script and isinstance(interp.get("path"), str) \
                and isinstance(script.get("path"), str):
            out[name] = (interp["path"], script["path"])
    return out


def check_problems(pins, engine: str, env=None, home_dir: str | None = None) -> list:
    """Everything AC-19 and AC-20 require of the environment, for `engine`.
    Empty means the call may be receipted."""
    env = os.environ if env is None else env
    probs = [f"{k} is set in the hook environment" for k in POISON_ENV if k in env]
    spec = ((pins or {}).get("engines") or {}).get(engine)
    if not isinstance(spec, dict):
        return probs + [f"{engine} is not pinned"]
    entries = [e for e in spec.get("entries") or [] if isinstance(e, dict)]
    roles = [e.get("role") for e in entries]
    for role in ROLES:
        if role not in roles:
            probs.append(f"{engine}: no pinned {role}")
    if roles.count("interpreter") != 1 or roles.count("script") != 1:
        probs.append(f"{engine}: exactly one interpreter and one script must be pinned")
    for e in entries:
        probs.extend(entry_problems(e, home_dir))
    files = (pins or {}).get("files")
    if not isinstance(files, dict):
        return probs + ["no startup or config file hashes pinned"]
    for rel in PINNED_FILES:
        if rel not in files:
            probs.append(f"{rel} has no pin")
            continue
        path = os.path.join(home_dir, rel[2:]) if home_dir else _expand(rel)
        try:
            now = None if not os.path.lexists(path) else file_sha256(path)
        except OSError:
            now = "unreadable"
        if now != files[rel]:
            probs.append(f"{rel} differs from its pin (re-pin after a reviewed change)")
    return probs


# ---------------------------------------------------------------------------
# Reviewer_Registry (AC-24, AC-29)
# ---------------------------------------------------------------------------

QUORUM_STATUSES = ("allowed", "not-allowed")


def load_reviewer_registry(path: Path | None = None):
    """(data, problems). Fail closed: anything unreadable is a problem."""
    p = path or reviewers_path()
    try:
        import yaml  # type: ignore[import-not-found]
        data = yaml.safe_load(Path(p).read_text(encoding="utf-8"))
    except Exception as e:
        return None, [f"{Path(p).name} unreadable: {type(e).__name__}"]
    if not isinstance(data, dict):
        return None, [f"{Path(p).name} is not a mapping"]
    probs = []
    revs = data.get("reviewers")
    if not isinstance(revs, dict) or set(revs) - set(ENGINES):
        probs.append(f"`reviewers` must map only {', '.join(ENGINES)}")
    pairs = data.get("pairs")
    if not isinstance(pairs, list):
        probs.append("`pairs` must be a list")
        pairs = []
    for i, pr in enumerate(pairs):
        if not isinstance(pr, dict):
            probs.append(f"pairs[{i}] is not a mapping")
            continue
        if pr.get("engine") not in ENGINES or not isinstance(pr.get("model"), str):
            probs.append(f"pairs[{i}] needs an engine of {', '.join(ENGINES)} and a model")
        if pr.get("status") not in QUORUM_STATUSES:
            probs.append(f"pairs[{i}] status {pr.get('status')!r} is not one of "
                         f"{', '.join(QUORUM_STATUSES)}")
        for k in ("replay_record", "baseline_model"):
            if k not in pr:
                probs.append(f"pairs[{i}] lacks `{k}`")
    return data, probs


def reviewer_allowed(engine: str, model: str, path: Path | None = None) -> bool:
    """True only when the Reviewer_Registry parses cleanly and holds exactly
    one entry for (engine, model) whose status is `allowed`."""
    data, probs = load_reviewer_registry(path)
    if data is None or probs:
        return False
    hits = [p for p in data.get("pairs") or []
            if isinstance(p, dict) and p.get("engine") == engine and p.get("model") == model]
    return len(hits) == 1 and hits[0].get("status") == "allowed"


# ---------------------------------------------------------------------------
# The hook pair (AC-18): shared bodies, so both files stay thin
# ---------------------------------------------------------------------------

def _load_ledger():
    sys.path.insert(0, str(_HERE))
    import receipt_ledger
    return receipt_ledger


def _bash_command(data: dict) -> str:
    if not isinstance(data, dict) or data.get("tool_name") != "Bash":
        return ""
    ti = data.get("tool_input")
    cmd = ti.get("command") if isinstance(ti, dict) else None
    return cmd if isinstance(cmd, str) else ""


def pre_hook(data: dict, env=None) -> dict | None:
    """Append the pending receipt for an Accepted_Review_Call; return it, or
    None when the call is not one (or names no tool_use_id). Never raises."""
    try:
        command = _bash_command(data)
        tid = str(data.get("tool_use_id") or "")
        session = str(data.get("session_id") or "")
        if not command or not tid or not session:
            return None
        pins = load_pins()
        engines = engine_paths(pins)
        if not engines:
            return None
        call, _why = parse_call(command, engines)
        if not call:
            return None
        rl = _load_ledger()
        record = {
            "kind": "external", "state": "pending", "engine": call["engine"],
            "interpreter": call["interpreter"], "script": call["script"],
            "requested_model": call["requested_model"],
            "prompt_sha256": call["prompt_sha256"], "tool_use_id": tid,
            "session_id": session, "agent_id": str(data.get("agent_id") or ""),
            "transcript_path": str(data.get("transcript_path") or ""),
            "cwd": str(data.get("cwd") or ""),
            "pre_problems": check_problems(pins, call["engine"], env),
        }
        rl.append_global(record)
        return record
    except Exception:
        return None


def _exit_and_output(resp) -> tuple:
    """(exit code, stdout) from a Bash tool_response. Claude Code hands a
    dict {stdout, stderr, interrupted, ...} on success; a failed command
    reaches the model as "Error: Exit code N"."""
    if isinstance(resp, dict):
        out = resp.get("stdout")
        out = out if isinstance(out, str) else ""
        if resp.get("interrupted") is True:
            return -1, out
        code = resp.get("exit_code", resp.get("returncode", 0))
        return (code if isinstance(code, int) and not isinstance(code, bool) else -1), out
    if isinstance(resp, str):
        m = re.search(r"Exit code (-?\d+)", resp)
        return (int(m.group(1)) if m else -1), resp
    return -1, ""


def output_path(tool_use_id: str) -> Path:
    rl = _load_ledger()
    return rl.receipts_dir() / "external" / f"{rl._safe(tool_use_id)}.out"


def post_hook(data: dict, env=None) -> dict | None:
    """Complete the pending receipt of this tool_use_id when every check still
    holds; return the complete record, or None. Never raises."""
    try:
        command = _bash_command(data)
        tid = str(data.get("tool_use_id") or "")
        session = str(data.get("session_id") or "")
        if not command or not tid or not session:
            return None
        rl = _load_ledger()
        rows = rl.read_global()
        pend = [r for r in rows if r.get("kind") == "external" and r.get("state") == "pending"
                and r.get("tool_use_id") == tid and r.get("session_id") == session]
        if not pend or any(r.get("state") == "complete" and r.get("tool_use_id") == tid
                           and r.get("kind") == "external" for r in rows):
            return None
        p = pend[-1]
        if p.get("pre_problems") != []:
            return None
        pins = load_pins()
        engines = engine_paths(pins)
        pair = (p.get("interpreter"), p.get("script"))
        if engines.get(p.get("engine")) != pair:
            return None  # re-pinned during the call: the pending row is stale
        call, _why = parse_call(command, {p.get("engine"): pair})
        if not call or call["prompt_sha256"] != p.get("prompt_sha256") \
                or call["requested_model"] != p.get("requested_model"):
            return None
        if check_problems(pins, p["engine"], env):
            return None
        code, out = _exit_and_output(data.get("tool_response"))
        raw = out.encode("utf-8", "surrogateescape")
        dest = output_path(tid)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        with open(tmp, "wb") as fh:
            fh.write(raw)
        os.replace(tmp, dest)
        verdict, digest = rl.parse_panel(out)
        record = {k: v for k, v in p.items() if k not in ("state", "pre_problems", "ts")}
        record.update({
            "state": "complete", "exit_code": code, "output_sha256": sha256_bytes(raw),
            "output_path": str(dest), "panel_verdict": verdict, "panel_digest": digest,
            "qa_verdict": rl.parse_verdict(out)[0],
        })
        rl.append_global(record)
        return record
    except Exception:
        return None


def hook_main(fn) -> int:
    """stdin -> fn(payload). Exit 0 always, print nothing: never blocks."""
    try:
        data = json.loads(sys.stdin.read())
        if isinstance(data, dict):
            fn(data)
    except Exception:
        pass
    return 0


# ---------------------------------------------------------------------------
# Operator CLI: what to pin, and the file content (never written here)
# ---------------------------------------------------------------------------

def _which(name: str) -> str:
    import shutil
    p = shutil.which(name)
    return p or ""


def detect(engine: str) -> dict:
    """Best-effort discovery of the three pinned paths of one engine on this
    machine. Every path is printed for the operator to confirm, never trusted."""
    found = {"engine": engine}
    exe = _which("codex" if engine == "codex" else "gemini")
    if not exe:
        return found
    script = os.path.realpath(exe)
    found["script"] = script
    try:
        with open(script, "rb") as fh:
            first = fh.readline().decode("utf-8", "replace").strip()
    except OSError:
        first = ""
    if first.startswith("#!") and first.endswith("node"):
        node = _which("node")
        if node:
            found["interpreter"] = os.path.realpath(node)
    pkg = os.path.dirname(os.path.dirname(script))
    if engine == "gemini":
        found["engine_path"] = os.path.dirname(script)
    else:
        import glob
        hits = sorted(glob.glob(os.path.join(os.path.dirname(pkg), "codex-*", "vendor", "*",
                                             "bin", "codex"))) + \
            sorted(glob.glob(os.path.join(pkg, "node_modules", "@openai", "codex-*", "vendor",
                                          "*", "bin", "codex")))
        if hits:
            found["engine_path"] = os.path.realpath(hits[0])
    return found


def _common_root(paths: list) -> str:
    try:
        return os.path.commonpath(paths) if paths else ""
    except ValueError:
        return ""


def pin_command(argv: list) -> int:
    root_arg = None
    if "--pin-root" in argv:
        root_arg = argv[argv.index("--pin-root") + 1]
    parts, missing = [], []
    for eng in ENGINES:
        d = detect(eng)
        need = [k for k in ("interpreter", "script", "engine_path") if not d.get(k)]
        if need:
            missing.append(f"{eng}: not found ({', '.join(need)})")
            continue
        root = root_arg or _common_root([d["interpreter"], d["script"], d["engine_path"]])
        if root in ("", "/", home(), os.path.realpath(home())):
            missing.append(f"{eng}: the common ancestor is {root or 'none'}; pass --pin-root "
                           f"with a directory that is neither $HOME nor /")
            continue
        parts.append(f"--engine {eng} --interpreter {shlex.quote(d['interpreter'])} "
                     f"--script {shlex.quote(d['script'])} --engine-path "
                     f"{shlex.quote(d['engine_path'])} --pin-root {shlex.quote(root)}")
    for m in missing:
        print(f"# {m}")
    if not parts:
        print("# nothing to pin on this machine")
        return 1
    me = "~/.claude/scripts/external_review.py"
    print("# Review these paths, then run this in a terminal outside any agent session.")
    print("# The redirect target is on the arming surface: an agent cannot write it.")
    print(f"python3 {me} pin-json {' '.join(parts)} > ~/.claude/{'/'.join(PINS_REL)}")
    return 0


def pin_json(argv: list) -> int:
    """Print the Reviewer_Pins content for the engines named on argv."""
    engines, cur = {}, None
    i = 0
    while i < len(argv):
        k = argv[i]
        v = argv[i + 1] if i + 1 < len(argv) else None
        if v is None:
            print(f"pin-json: {k} needs a value", file=sys.stderr)
            return 2
        if k == "--engine":
            if v not in ENGINES:
                print(f"pin-json: unknown engine {v}", file=sys.stderr)
                return 2
            cur = engines.setdefault(v, {})
        elif k in ("--interpreter", "--script", "--engine-path", "--pin-root") and cur is not None:
            cur[k[2:]] = v
        else:
            print(f"pin-json: unexpected {k}", file=sys.stderr)
            return 2
        i += 2
    out = {"schema": 1, "engines": {}, "files": {}}
    for eng, d in engines.items():
        if set(d) != {"interpreter", "script", "engine-path", "pin-root"}:
            print(f"pin-json: {eng} needs --interpreter --script --engine-path --pin-root",
                  file=sys.stderr)
            return 2
        root = d["pin-root"]
        entries = []
        for role, key in (("interpreter", "interpreter"), ("script", "script"),
                          ("engine", "engine-path")):
            path = d[key]
            if not os.path.isabs(path):
                print(f"pin-json: {path} is not absolute", file=sys.stderr)
                return 2
            kind = "dir" if os.path.isdir(path) else "file"
            real = os.path.realpath(path)
            entries.append({"role": role, "path": path, "realpath": real, "kind": kind,
                            "sha256": path_sha256(real, kind), "pin_root": root})
        for e in entries:
            probs = entry_problems(e)
            if probs:
                print("pin-json: " + "; ".join(probs), file=sys.stderr)
                return 2
        out["engines"][eng] = {"entries": entries}
    for rel in PINNED_FILES:
        out["files"][rel] = optional_file_sha256(rel)
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


def check_cli() -> int:
    pins = load_pins()
    if pins is None:
        print(f"no reviewer pins at {pins_path()}; run `external_review.py pin-command`")
        return 1
    bad = 0
    for eng in sorted(engine_paths(pins)):
        probs = check_problems(pins, eng)
        print(f"{eng}: {'OK' if not probs else 'NO RECEIPT: ' + '; '.join(probs)}")
        bad += bool(probs)
    return 1 if bad else 0


# ---------------------------------------------------------------------------
# Selftest (AC-19 to AC-23): fixtures in registry/fixtures/FLOW.external-review-receipt
# ---------------------------------------------------------------------------

DEFAULT_FIXTURES = os.path.join("registry", "fixtures", "FLOW.external-review-receipt")
PRE_HOOK = "r__pretool-bash__external-review.py"
POST_HOOK = "r__posttool-bash__external-review.py"
# Prompts whose argv bytes Bash must hand over exactly as the parser reads
# them (AC-23), on top of every fixture prompt.
_DIGEST_PROMPTS = (
    "'plain prompt'",
    "\"double quoted, with commas: inside\"",
    "'it'\"'\"'s concatenated'",
    "\"a \\\"quoted\\\" word and a \\\\ backslash\"",
    "'line one\nline two'",
    "'unicode: café über — 日本'",
    "word,with=chars@and%more",
    "'trailing space '",
    "''",
)


def _sandbox_layout(sb: str) -> dict:
    """Fake pinned CLIs inside a temp HOME. The fake `node` is a Python script
    that prints the SHA-256 of every argv element, so Bash itself shows which
    bytes it passed (AC-23)."""
    root = os.path.join(sb, "opt", "nodeprefix")
    p = {"root": root,
         "node": os.path.join(root, "bin", "node"),
         "codex": os.path.join(root, "lib", "node_modules", "@openai", "codex", "bin", "codex.js"),
         "vendor": os.path.join(root, "lib", "node_modules", "@openai", "codex-linux-x64",
                                "vendor", "x86_64-unknown-linux-musl", "bin", "codex"),
         "gemini": os.path.join(root, "lib", "node_modules", "@google", "gemini-cli", "bundle",
                                "gemini.js")}
    p["bundle"] = os.path.dirname(p["gemini"])
    for k in ("node", "codex", "vendor", "gemini"):
        os.makedirs(os.path.dirname(p[k]), exist_ok=True)
    with open(p["node"], "w", encoding="utf-8") as fh:
        fh.write(f"#!{sys.executable}\nimport hashlib, sys\n"
                 "for i, a in enumerate(sys.argv):\n"
                 "    print(f'ARGV-SHA256 {i} ' + hashlib.sha256(a.encode('utf-8', "
                 "'surrogateescape')).hexdigest())\n")
    os.chmod(p["node"], 0o755)
    with open(p["codex"], "w", encoding="utf-8") as fh:
        fh.write("#!/usr/bin/env node\n// launcher\n")
    os.chmod(p["codex"], 0o755)
    with open(p["vendor"], "wb") as fh:
        fh.write(b"\x7fELF fake vendor binary")
    with open(p["gemini"], "w", encoding="utf-8") as fh:
        fh.write("#!/usr/bin/env node\n// gemini\n")
    with open(os.path.join(p["bundle"], "chunk-a.js"), "w", encoding="utf-8") as fh:
        fh.write("export const a = 1;\n")
    for rel, text in (("~/.bashrc", "# rc\n"), ("~/.profile", "# profile\n"),
                      ("~/.codex/config.toml", "model = 'x'\n")):
        full = os.path.join(sb, rel[2:])
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(text)
    return p


def _write_pins(sb: str, p: dict) -> None:
    def ent(role, path, kind="file"):
        real = os.path.realpath(path)
        return {"role": role, "path": path, "realpath": real, "kind": kind,
                "sha256": path_sha256(real, kind), "pin_root": p["root"]}
    pins = {"schema": 1, "engines": {
        "codex": {"entries": [ent("interpreter", p["node"]), ent("script", p["codex"]),
                              ent("engine", p["vendor"])]},
        "gemini": {"entries": [ent("interpreter", p["node"]), ent("script", p["gemini"]),
                               ent("engine", p["bundle"], "dir")]}},
        "files": {}}
    for rel in PINNED_FILES:
        full = os.path.join(sb, rel[2:])
        pins["files"][rel] = file_sha256(full) if os.path.lexists(full) else None
    dest = os.path.join(sb, ".claude", *PINS_REL)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(pins, fh)


def _mutate(sb: str, p: dict, op: str) -> None:
    """One named change to the sandbox, applied after pinning."""
    if op == "edit_codex_script":
        with open(p["codex"], "a", encoding="utf-8") as fh:
            fh.write("// changed\n")
    elif op == "swap_node":
        with open(p["node"], "a", encoding="utf-8") as fh:
            fh.write("# swapped interpreter\n")
    elif op == "swap_vendor":
        with open(p["vendor"], "ab") as fh:
            fh.write(b"swapped")
    elif op == "edit_bundle":
        with open(os.path.join(p["bundle"], "chunk-a.js"), "a", encoding="utf-8") as fh:
            fh.write("export const b = 2;\n")
    elif op == "symlink_codex_copy":
        other = os.path.join(sb, "elsewhere", "codex", "bin")
        os.makedirs(other, exist_ok=True)
        copy = os.path.join(other, "codex.js")
        with open(p["codex"], "rb") as src, open(copy, "wb") as dst:
            dst.write(src.read())
        with open(os.path.join(other, "evil-module.js"), "w", encoding="utf-8") as fh:
            fh.write("// a module beside the copy\n")
        os.remove(p["codex"])
        os.symlink(copy, p["codex"])
    elif op == "edit_bashrc":
        with open(os.path.join(sb, ".bashrc"), "a", encoding="utf-8") as fh:
            fh.write("export NODE_OPTIONS=--require=/tmp/x.js\n")
    elif op == "edit_codex_config":
        with open(os.path.join(sb, ".codex", "config.toml"), "a", encoding="utf-8") as fh:
            fh.write("[model_providers.x]\nbase_url = 'http://127.0.0.1:9'\n")
    elif op == "symlink_parent":
        real = os.path.join(sb, "opt", "realbin")
        os.rename(os.path.join(p["root"], "bin"), real)
        os.symlink(real, os.path.join(p["root"], "bin"))
    else:
        raise ValueError(f"unknown mutation {op!r}")


def _expand_cmd(text: str, p: dict) -> str:
    for k in ("node", "codex", "gemini", "root"):
        text = text.replace("{{" + k.upper() + "}}", p[k])
    return text


def _hook_env(sb: str, extra: dict | None) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in POISON_ENV}
    for k in ("OCTO_MERGE_APPROVE", "OCTO_QA_OK", "OCTO_KERNEL_OPEN"):
        env.pop(k, None)
    env["HOME"] = env["USERPROFILE"] = sb
    env["CLAUDE_SESSION_ID"] = "__selftest__"
    env.update({k: str(v) for k, v in (extra or {}).items()})
    return env


def _run_hook(script: str, payload: dict, env: dict, sb: str) -> None:
    import subprocess
    subprocess.run([sys.executable, str(_HERE / script)], input=json.dumps(payload),
                   capture_output=True, text=True, encoding="utf-8", cwd=sb, env=env,
                   timeout=60)


def _complete_rows(sb: str) -> list:
    path = os.path.join(sb, ".claude", ".cache", "receipts", "global.jsonl")
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for ln in fh:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if r.get("kind") == "external" and r.get("state") == "complete":
                    rows.append(r)
    except OSError:
        pass
    return rows


def _bash_argv_digests(command: str, sb: str) -> dict:
    """Run the command under a clean `bash --noprofile --norc -c` and read the
    argv digests the fake interpreter printed."""
    import subprocess
    env = {"PATH": "/usr/bin:/bin", "HOME": sb}
    cp = subprocess.run(["bash", "--noprofile", "--norc", "-c", command], capture_output=True,
                        text=True, env=env, cwd=sb, timeout=30)
    got = {}
    for ln in cp.stdout.splitlines():
        parts = ln.split()
        if len(parts) == 3 and parts[0] == "ARGV-SHA256":
            got[int(parts[1])] = parts[2]
    return got


def _run_fixture(path: str) -> list:
    import shutil
    import tempfile
    name = os.path.basename(path)
    with open(path, encoding="utf-8") as fh:
        fx = json.load(fh)
    want = int(fx.get("expect_complete", 0))
    sb = os.path.realpath(tempfile.mkdtemp(prefix="external-review-selftest-"))
    fails = []
    try:
        p = _sandbox_layout(sb)
        _write_pins(sb, p)
        for op in fx.get("mutate_before") or []:
            _mutate(sb, p, op)
        command = _expand_cmd(fx["command"], p)
        tid = fx.get("tool_use_id", "toolu_fx_external_1")
        payload = {"session_id": "fx-external", "tool_name": "Bash", "tool_use_id": tid,
                   "tool_input": {"command": command}, "cwd": sb,
                   "transcript_path": os.path.join(sb, ".claude", "projects", "fx",
                                                   "fx-external.jsonl")}
        _run_hook(PRE_HOOK, payload, _hook_env(sb, fx.get("env")), sb)
        for op in fx.get("mutate_during") or []:
            _mutate(sb, p, op)
        post = dict(payload, tool_response={"stdout": fx.get("output", "PANEL-VERDICT: PASS\n"),
                                            "stderr": "", "interrupted": False,
                                            "isImage": False})
        _run_hook(POST_HOOK, post, _hook_env(sb, fx.get("env")), sb)
        rows = _complete_rows(sb)
        if len(rows) != want:
            fails.append(f"{name}: {len(rows)} complete receipt(s), want {want}")
        for k, v in (fx.get("expect_fields") or {}).items():
            if rows and rows[-1].get(k) != v:
                fails.append(f"{name}: {k} is {rows[-1].get(k)!r}, want {v!r}")
        if rows:
            out = os.path.join(sb, ".claude", ".cache", "receipts", "external", f"{tid}.out")
            try:
                with open(out, "rb") as fh:
                    if sha256_bytes(fh.read()) != rows[-1].get("output_sha256"):
                        fails.append(f"{name}: output copy does not hash to the receipt")
            except OSError:
                fails.append(f"{name}: no output copy at {out}")
    finally:
        shutil.rmtree(sb, ignore_errors=True)
    return fails


def _digest_checks(fixture_commands: list) -> list:
    """AC-23: for every prompt, the parser's digest equals the SHA-256 of the
    argv element Bash itself passes."""
    import shutil
    import tempfile
    fails = []
    sb = os.path.realpath(tempfile.mkdtemp(prefix="external-review-argv-"))
    try:
        p = _sandbox_layout(sb)
        engines = {"codex": (p["node"], p["codex"]), "gemini": (p["node"], p["gemini"])}
        cmds = [_expand_cmd(c, p) for c in fixture_commands]
        cmds += [f"{p['node']} {p['codex']} exec -m m1 {q}" for q in _DIGEST_PROMPTS]
        cmds += [f"{p['node']} {p['gemini']} -m m1 -p {q}" for q in _DIGEST_PROMPTS]
        checked, fixed = 0, len(cmds) - len(_DIGEST_PROMPTS) * 2
        for n, cmd in enumerate(cmds):
            call, why = parse_call(cmd, engines)
            if not call:
                if n >= fixed:
                    fails.append(f"AC-23: digest prompt refused by the parser ({why})")
                continue
            got = _bash_argv_digests(cmd, sb)
            checked += 1
            if got.get(call["prompt_index"]) != call["prompt_sha256"]:
                fails.append(f"AC-23: digest of {cmd[-40:]!r} differs from Bash's argv "
                             f"{call['prompt_index']}")
    finally:
        shutil.rmtree(sb, ignore_errors=True)
    return fails


def selftest(fdir: str | None = None) -> int:
    import glob
    fdir = fdir or DEFAULT_FIXTURES
    if not os.path.isabs(fdir):
        fdir = str(_HERE.parent / fdir)
    vio = sorted(glob.glob(os.path.join(fdir, "violation*.json")))
    ben = sorted(glob.glob(os.path.join(fdir, "benign*.json")))
    if not vio or not ben:
        print(f"selftest FAIL: need violation*.json and benign*.json in {fdir}", file=sys.stderr)
        return 1
    fails, cmds = [], []
    for f in vio + ben:
        with open(f, encoding="utf-8") as fh:
            fx = json.load(fh)
        is_v = os.path.basename(f).startswith("violation")
        if is_v and int(fx.get("expect_complete", 0)) != 0:
            fails.append(f"{os.path.basename(f)}: a violation must expect no complete receipt")
        if not is_v and int(fx.get("expect_complete", 0)) != 1:
            fails.append(f"{os.path.basename(f)}: a benign fixture must expect one receipt")
        cmds.append(fx["command"])
        fails.extend(_run_fixture(f))
    fails.extend(_digest_checks(cmds))
    if fails:
        print(f"selftest FAIL: {len(vio)} no-receipt + {len(ben)} receipt "
              f"(external_review vs {os.path.basename(fdir)}): " + "; ".join(fails),
              file=sys.stderr)
        return 1
    print(f"selftest PASS: {len(vio)} no-receipt + {len(ben)} receipt + AC-23 argv digests "
          f"(external_review vs {os.path.basename(fdir)})")
    return 0


def main(argv: list) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip().split("\n\n")[-1])
        return 0
    cmd = argv[0]
    if cmd == "--selftest":
        return selftest(argv[1] if len(argv) > 1 else None)
    if cmd == "pin-command":
        return pin_command(argv[1:])
    if cmd == "pin-json":
        return pin_json(argv[1:])
    if cmd == "check":
        return check_cli()
    if cmd == "parse" and len(argv) == 2:
        call, why = parse_call(argv[1], engine_paths(load_pins()))
        if call:
            call = {k: v for k, v in call.items() if k != "prompt"}
        print(json.dumps(call) if call else f"not an Accepted_Review_Call: {why}")
        return 0 if call else 1
    print(f"unknown command {cmd!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
