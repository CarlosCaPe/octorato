#!/usr/bin/env python3
"""r__posttool__definition-closed: PostToolUse Write|Edit reflex (advisory).

When an entry written to an ARM memory file records that a definition closed
(a closure marker next to a number), remind the agent to find every holder of
the PREVIOUS value by searching for the value, with the exact sweep command and
the arm root already resolved and shell-quoted. The hook cannot know the
previous value, so it never guesses one: the command carries a placeholder the
agent fills in.

Fires only when all of these hold:
  - the tool is Write or Edit and the path is a .md file at any depth under
    <arm root>/.claude/memory/;
  - the path is outside the brain: the live tree, the tree this script runs
    from, and every worktree of the live tree (listed once per firing
    candidate with `git worktree list`, 2 s timeout; when that listing fails
    only the first two are excluded);
  - the NEW text of this call (Edit: new_string, Write: content) has a closure
    marker (English or Spanish) and a number in the same sentence or line. A
    number is an integer of 2+ digits or one written with thousands separators
    (1,438 or 1.438). Dates, ISO datetimes, clock times, and references such
    as #12, PR 12, issue 12, ticket 12 or line 12 are not numbers here, and
    neither is a year (19xx or 20xx) when it is the only number in the
    sentence;
  - this session has not been advised about this file yet.

Advisory only: emits additionalContext, always exits 0, never blocks. Fails
open on unparseable input and on any exception.

State: one file per session, dc-<session id>.json, under
~/.claude/.cache/reflex/definition-closed/, or under the directory named by
OCTO_REFLEX_STATE_DIR when that variable holds an ABSOLUTE path (tests and
manual runs, so a check does not write into the live cache; a relative value
is ignored). The hook writes only files of that name and only over its own
earlier state: a file of that name holding anything else is left untouched,
and a state directory that is a symlink is neither read nor written. In both
cases the advisory is still emitted, so the cost is a repeated advisory.

Limits: state files are never deleted by the hook; remove the directory by
hand to reset. Each file is about 70 bytes per advised path.

What it cannot see: a definition closed in chat and never written to arm
memory; a closure written through Bash, MultiEdit or NotebookEdit; a one-digit
value or a number spelled as a word; a closed value with decimals (0.75,
421.5); a closed value that is itself a year-shaped number standing alone
(2024); a marker and its number in different sentences; a closure phrased with
no listed marker; text past the first 262,144 characters (256 KB of
characters) of one write; a second closure in a file it already advised on in
this session. It also fires on a false positive such as "confirmed 12 rows
loaded", which is why it only advises.

Every quantifier that sits next to another one over whitespace is bounded to
three characters, so a reference written as "PR" plus four or more spaces plus
a number is read as a number.

Stdin:  {"session_id", "tool_name", "tool_input": {"file_path", ...}, ...}
Stdout: {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                "additionalContext": "..."}} or nothing.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

CLAUDE_DIR = Path(__file__).resolve().parent.parent
LIVE_DIR = Path.home() / ".claude"
STATE_ENV = "OCTO_REFLEX_STATE_DIR"
STATE_PREFIX = "dc-"
MAX_SCAN_CHARS = 256 * 1024
WORKTREE_TIMEOUT_S = 2

MARKER_RE = re.compile(
    r"(?<!\w)(closed|confirmed|final|locked|cerrad[oa]|confirmad[oa]|"
    r"definitiv[oa]|queda[ \t]{1,3}en|quedan)(?!\w)", re.IGNORECASE)
NUMBER_RE = re.compile(
    r"(?<![\w.,:#])(?:\d{1,3}(?:[.,]\d{3})+|\d{2,})(?![\w:])(?![.,]\d)")
_MONTH = (r"(?:january|february|march|april|may|june|july|august|september|"
          r"october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|"
          r"nov|dec|enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
          r"septiembre|setiembre|octubre|noviembre|diciembre)")
# Whitespace between tokens is horizontal and bounded (_W, _W0): the text is
# read line by line, and two unbounded runs side by side go quadratic.
_W = r"[ \t]{1,3}"
_W0 = r"[ \t]{0,3}"
DATE_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|z|[+-]\d{2}:?\d{2})?"
    r"|\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b"
    r"|\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b"
    r"|\b\d{1,2}(?:st|nd|rd|th)?" + _W + r"(?:de" + _W + r")?" + _MONTH
    + r"\b\.?(?:,?" + _W + r"(?:de" + _W + r"|del" + _W + r")?\d{4}\b)?"
    r"|\b" + _MONTH + r"\b\.?" + _W + r"\d{1,2}(?:st|nd|rd|th)?\b(?:,?" + _W + r"\d{4}\b)?"
    r"|\b" + _MONTH + r"\b\.?" + _W + r"(?:de" + _W + r"|del" + _W + r")?\d{4}\b",
    re.IGNORECASE)
NOISE_RE = re.compile(
    r"\b(?:prs?|issues?|tickets?|lines?)\b" + _W0 + r"#?" + _W0 + r"\d+"
    r"|#" + _W0 + r"\d+"
    r"|\b\d{1,2}:\d{2}(?::\d{2})?\b",
    re.IGNORECASE)
YEAR_RE = re.compile(r"(?:19|20)\d{2}")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+")


def state_dir() -> Path:
    override = os.environ.get(STATE_ENV)
    if override and os.path.isabs(override):
        return Path(override)
    return LIVE_DIR / ".cache" / "reflex" / "definition-closed"


def _inside(path: str, root) -> bool:
    try:
        base = os.path.normcase(os.path.realpath(str(root)))
    except OSError:
        return False
    return path == base or path.startswith(base.rstrip(os.sep) + os.sep)


def brain_worktrees(live_dir) -> list:
    """Every worktree of the repo at live_dir. Empty on any failure: the caller
    then excludes only the trees it already knows."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        res = subprocess.run(
            ["git", "-C", str(live_dir), "worktree", "list", "--porcelain"],
            env=env, capture_output=True, timeout=WORKTREE_TIMEOUT_S)
    except Exception:
        return []
    if res.returncode != 0:
        return []
    found = []
    for line in res.stdout.split(b"\n"):
        if line.startswith(b"worktree "):
            found.append(os.fsdecode(line[len(b"worktree "):]))
    return found


def arm_root(file_path: str, brain_roots=None):
    """The arm root when file_path is a .md file at any depth under
    <arm root>/.claude/memory/ and sits outside the brain roots given, else
    None. Judged on the real path, so a link into an arm memory directory
    resolves to the arm it belongs to."""
    if not file_path:
        return None
    real = os.path.realpath(os.path.expanduser(file_path))
    folded = os.path.normcase(real)
    for root in (brain_roots if brain_roots is not None else (CLAUDE_DIR, LIVE_DIR)):
        if _inside(folded, root):
            return None
    parts = Path(real).parts
    if not parts[-1].lower().endswith(".md"):
        return None
    lowered = [p.lower() for p in parts]
    # The memory directory closest to the file, with at least one part (the
    # arm root) before it and the file after it.
    for i in range(len(parts) - 3, 0, -1):
        if lowered[i] == ".claude" and lowered[i + 1] == "memory":
            return str(Path(*parts[:i]))
    return None


def closure_near_number(text: str) -> bool:
    if not text:
        return False
    for line in text[:MAX_SCAN_CHARS].splitlines():
        if not MARKER_RE.search(line):
            continue
        for sentence in SENTENCE_SPLIT_RE.split(line):
            if not MARKER_RE.search(sentence):
                continue
            rest = NOISE_RE.sub(" ", DATE_RE.sub(" ", sentence))
            numbers = NUMBER_RE.findall(rest)
            if not numbers:
                continue
            if len(numbers) == 1 and YEAR_RE.fullmatch(numbers[0]):
                continue
            return True
    return False


def first_time(session_id, file_path: str, directory: Path) -> bool:
    """True once per session per file. State that cannot be trusted, read or
    written never silences the advisory, and this function never deletes and
    never writes over a file that is not its own earlier state."""
    if os.path.islink(directory):
        return True
    if not isinstance(session_id, str) or not session_id:
        session_id = "no-session"
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)[:120]
    state = directory / f"{STATE_PREFIX}{safe}.json"
    seen = []
    if os.path.lexists(state):
        if os.path.islink(state):
            return True
        try:
            loaded = json.loads(state.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return True
        if not isinstance(loaded, list) or not all(isinstance(s, str) for s in loaded):
            return True
        seen = loaded
    key = os.path.realpath(file_path)
    if key in seen:
        return False
    try:
        directory.mkdir(parents=True, exist_ok=True)
        tmp = state.with_name(state.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(seen + [key]), encoding="utf-8")
        os.replace(tmp, state)  # on failure the temp file stays where it is
    except OSError:
        pass
    return True


def advisory(root: str) -> str:
    return (
        "Definition closed: this memory entry looks like it closes a definition "
        "(a closure marker next to a number). Before updating documents, find "
        "every holder of the previous value by searching for the value itself, "
        "not from memory and not by following links between documents; the "
        "document nobody links to is the one that stays stale. Run: "
        f"python3 ~/.claude/scripts/stale_value_sweep.py --root {shlex.quote(root)} "
        '--old "<previous value>" (replace <previous value> with the value that '
        "was in force before this entry; this hook does not know it). Advisory "
        "only, nothing was blocked.")


def evaluate(raw: str, directory=None, brain_roots=None):
    """The advisory text for this hook event, or None to stay silent.
    brain_roots given (tests) is the whole exclusion list; left out, the live
    tree, this script's tree and the live tree's worktrees are excluded."""
    try:
        event = json.loads(raw or "{}")
    except ValueError:
        return None
    if not isinstance(event, dict):
        return None
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    tool = event.get("tool_name") or ""
    if tool == "Edit":
        text = tool_input.get("new_string")
    elif tool == "Write":
        text = tool_input.get("content")
    else:
        return None
    file_path = tool_input.get("file_path")
    if not isinstance(text, str) or not isinstance(file_path, str):
        return None
    root = arm_root(file_path, brain_roots)
    if root is None or not closure_near_number(text):
        return None
    if brain_roots is None:
        # Asked last: it spawns git, and almost no write gets this far.
        if arm_root(file_path, brain_worktrees(LIVE_DIR)) is None:
            return None
    if not first_time(event.get("session_id"), file_path,
                      directory if directory is not None else state_dir()):
        return None
    return advisory(root)


def main() -> int:
    try:
        message = evaluate(sys.stdin.read())
        if message:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PostToolUse", "additionalContext": message}}))
    except Exception:
        pass
    return 0


def _selftest() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="definition-closed-"))
    failures = []
    try:
        arm = tmp / "arm"
        memory = arm / ".claude" / "memory"
        memory.mkdir(parents=True)
        brain = tmp / "brain"
        (brain / ".claude" / "memory").mkdir(parents=True)
        roots = (brain,)
        state = tmp / "state"
        note = str(memory / "decisions.md")
        counter = [0]

        def event(path, text, tool="Write", session="s1"):
            key = "content" if tool == "Write" else "new_string"
            return json.dumps({"session_id": session, "tool_name": tool,
                               "tool_input": {"file_path": path, key: text}})

        def run(raw):
            return evaluate(raw, directory=state, brain_roots=roots)

        def fresh(text, tool="Write"):
            """The same text on a file this session has not written yet."""
            counter[0] += 1
            return run(event(str(memory / f"case{counter[0]}.md"), text, tool))

        out = run(event(note, "Headcount closed at 438 after the review."))
        expected = f"stale_value_sweep.py --root {os.path.realpath(str(arm))} --old \"<previous value>\""
        if not out or expected not in out:
            failures.append(f"violation did not produce the advisory with the arm root: {out!r}")
        if out and "438" in out:
            failures.append("the advisory guessed a value")
        if run(event(note, "Headcount closed at 438 after the review.")) is not None:
            failures.append("debounce: fired twice for one file in one session")
        if run(event(note, "Headcount closed at 438.", session="s2")) is None:
            failures.append("debounce: a new session stayed silent")

        firing = {
            "Spanish marker on Edit": ("Periodicidad confirmada: queda en 12 periodos.", "Edit"),
            "thousands separator, comma": ("Headcount closed at 1,438.", "Write"),
            "thousands separator, dot": ("Plantilla cerrada en 1.438 personas.", "Write"),
            "number after a date": ("Confirmed on 2026/01/15: headcount 438.", "Write"),
            "number after a reference": ("Closed in PR 12 with headcount 438.", "Write"),
            "number next to a year": ("Headcount for 2026 closed at 438.", "Write"),
            "number after an ISO datetime": ("Confirmed 2026-01-15T10:30:00Z: headcount 438.", "Write"),
        }
        for name, (text, tool) in firing.items():
            if fresh(text, tool) is None:
                failures.append(f"firing input stayed silent: {name}")

        silent_text = {
            "no closure marker": "Headcount might be 438.",
            "marker without a number": "The scope is closed.",
            "one-digit number": "Scope closed at 3.",
            "ISO date": "Confirmed on 2026-01-15.",
            "slash date, year first": "Confirmed on 2026/01/15.",
            "slash date, day first": "Confirmed on 15/01/2026.",
            "English month name": "Confirmed on 15 January 2026.",
            "English month first": "Confirmed on January 15, 2026.",
            "Spanish month name": "Confirmado el 15 de enero de 2026.",
            "hash reference": "Closed by #123.",
            "PR reference": "Closed in PR 123.",
            "issue reference": "Closed, see issue 45.",
            "ticket reference": "Confirmed in Ticket #4521.",
            "line reference": "Confirmed at line 120.",
            "clock time": "Confirmed at 15:30.",
            "ISO datetime, zulu": "Confirmed at 2026-01-15T10:30:00Z.",
            "ISO datetime, offset": "Confirmed at 2026-01-15T10:30:00.123+02:00.",
            "year standing alone": "The plan for 2026 is final.",
            "year of the last century": "Closed since 1998.",
            "decimal": "Ratio confirmed at 0.75.",
            "marker and number in different sentences":
                "The scope is closed. Headcount might be 438.",
        }
        for name, text in silent_text.items():
            if fresh(text) is not None:
                failures.append(f"benign input fired: {name}")

        benign = {
            "non-memory path": event(str(arm / "docs" / "plan.md"), "Headcount closed at 438."),
            "brain memory": event(str(brain / ".claude" / "memory" / "x.md"), "Headcount closed at 438."),
            "non-markdown file": event(str(memory / "h.txt"), "Headcount closed at 438."),
            "memory directory itself named .md": event(str(arm / ".claude" / "memory.md"), "Headcount closed at 438."),
            "other tool": event(str(memory / "i.md"), "Headcount closed at 438.", tool="Read"),
            "malformed JSON": "{not json",
            "empty stdin": "",
            "JSON that is not an object": "[1, 2]",
        }
        for name, raw in benign.items():
            if run(raw) is not None:
                failures.append(f"benign input fired: {name}")

        # Any depth under .claude/memory/ resolves to the same arm root.
        deep = run(event(str(memory / "sub" / "deeper" / "x.md"), "Headcount closed at 438."))
        if not deep or expected not in deep:
            failures.append(f"a memory file in a subdirectory stayed silent: {deep!r}")

        # The arm root is shell-quoted in the command.
        for label, dirname in (("space", "my arm"),
                               ("semicolon and substitution", "arm;touch PWNED $(id)")):
            odd = tmp / dirname
            try:
                (odd / ".claude" / "memory").mkdir(parents=True)
            except OSError:
                continue
            real = os.path.realpath(str(odd))
            got = run(event(str(odd / ".claude" / "memory" / "x.md"), "Headcount closed at 438."))
            if not got or f"--root {shlex.quote(real)} --old" not in got:
                failures.append(f"quoting ({label}): quoted root missing: {got!r}")
            elif f"--root {real} " in got:
                failures.append(f"quoting ({label}): raw root present: {got!r}")
            elif shlex.split(got.split("Run: ", 1)[1].split(" (replace", 1)[0])[3] != real:
                failures.append(f"quoting ({label}): the command does not parse back to the root")

        # A session_id that is not a string is a missing one.
        for bad in (12345, ["a"], None):
            raw = json.dumps({"session_id": bad, "tool_name": "Write", "tool_input": {
                "file_path": str(memory / "nosession.md"), "content": "Headcount closed at 438."}})
            before = (state / "dc-no-session.json").exists()
            got = run(raw)
            if not (state / "dc-no-session.json").exists():
                failures.append(f"session_id {bad!r} did not use the dc-no-session state file")
            if (got is None) != before:
                failures.append(f"session_id {bad!r}: fired={got is not None}, expected {not before}")

        # The hook deletes nothing: old files and files that are not its own
        # survive a firing write, whatever their name or age.
        shared = tmp / "shared"
        shared.mkdir()
        kept = {"settings.json": '{"env": {}}', "hooks.json": '{"hooks": {}}',
                "package.json": '{"name": "x"}', "s9.json": '["not", "ours"]'}
        long_ago = time.time() - 400 * 24 * 3600
        for name, body in kept.items():
            (shared / name).write_text(body, encoding="utf-8")
            os.utime(shared / name, (long_ago, long_ago))
        got = evaluate(event(note, "Headcount closed at 438.", session="s9"),
                       directory=shared, brain_roots=roots)
        if got is None:
            failures.append("shared state directory: the advisory was not emitted")
        for name, body in kept.items():
            if not (shared / name).exists() or (shared / name).read_text(encoding="utf-8") != body:
                failures.append(f"shared state directory: {name} was deleted or rewritten")
        if sorted(os.listdir(shared)) != sorted(list(kept) + ["dc-s9.json"]):
            failures.append(f"shared state directory holds {sorted(os.listdir(shared))}")

        # A file with the hook's own name that is not the hook's own shape is
        # left as it is, and the advisory still goes out, every time.
        foreign = tmp / "foreign"
        foreign.mkdir()
        for body in ('{"keep": "me"}', "not json at all", '[1, 2]'):
            (foreign / "dc-s1.json").write_text(body, encoding="utf-8")
            for _ in range(2):
                got = evaluate(event(note, "Headcount closed at 438."),
                               directory=foreign, brain_roots=roots)
                if got is None:
                    failures.append(f"foreign state file {body!r}: the advisory was silenced")
            if (foreign / "dc-s1.json").read_text(encoding="utf-8") != body:
                failures.append(f"foreign state file {body!r} was overwritten")
        if os.listdir(foreign) != ["dc-s1.json"]:
            failures.append(f"foreign state directory holds {os.listdir(foreign)}")

        # A state directory that is a symlink is neither read nor written.
        target = tmp / "link-target"
        target.mkdir()
        (target / "dc-s1.json").write_text(json.dumps([os.path.realpath(note)]), encoding="utf-8")
        try:
            os.symlink(target, tmp / "linked-state")
            linked_state = True
        except (OSError, NotImplementedError):
            linked_state = False
        if linked_state:
            got = evaluate(event(note, "Headcount closed at 438."),
                           directory=tmp / "linked-state", brain_roots=roots)
            if got is None:
                failures.append("symlinked state directory: state was read (advisory silenced)")
            got = evaluate(event(str(memory / "other.md"), "Headcount closed at 438."),
                           directory=tmp / "linked-state", brain_roots=roots)
            if got is None:
                failures.append("symlinked state directory: the advisory was not emitted")
            if os.listdir(target) != ["dc-s1.json"] or json.loads(
                    (target / "dc-s1.json").read_text(encoding="utf-8")) != [os.path.realpath(note)]:
                failures.append("symlinked state directory: state was written through the link")

        # The scan stops at MAX_SCAN_CHARS characters.
        filler = "plain words only\n"
        pad = filler * (MAX_SCAN_CHARS // len(filler) + 1)
        if closure_near_number(pad + "Headcount closed at 438.\n"):
            failures.append("scan cap: a closure past the cap was read")
        if not closure_near_number(pad[:MAX_SCAN_CHARS - 200] + "\nHeadcount closed at 438.\n"):
            failures.append("scan cap: a closure inside the cap was missed")

        # No input of 100 KB may cost more than a second.
        size = 100 * 1024
        hostile = {
            "marker, reference word, spaces": "closed pr" + " " * size + "x",
            "marker, hash, spaces": "closed #" + " " * size + "x",
            "marker, day number, spaces": "closed 12" + " " * size + "x",
            "marker, month, spaces": "closed january" + " " * size + "x",
            "marker, queda, spaces": "closed queda" + " " * size + "x",
            "long digit run": "closed x" + "1" * size + "x",
            "runs of '1 '": "closed " + "1 " * (size // 2),
            "runs of '1:'": "closed " + "1:" * (size // 2),
            "runs of '12 de '": "closed " + "12 de " * (size // 6),
            "runs of separators": "closed " + ",." * (size // 2),
            "runs of '1,234'": "closed x1" + ",234" * (size // 4) + "x",
            "runs of 'pr '": "closed " + "pr " * (size // 3),
            "runs of sentence ends": "closed " + ". " * (size // 2),
        }
        timings = []
        for name, text in hostile.items():
            started = time.perf_counter()
            closure_near_number(text)
            spent = time.perf_counter() - started
            timings.append((name, spent))
            if spent > 1.0:
                failures.append(f"timing: {name} took {spent:.2f} s at 100 KB")
        if "--timings" in sys.argv:
            for name, spent in timings:
                print(f"  {spent * 1000:8.1f} ms  {name}")

        # The hook body holds no call that deletes a file.
        source = Path(__file__).read_text(encoding="utf-8")
        body = source.split("\ndef _selftest()", 1)[0] + source.split('\nif __name__ == "__main__":', 1)[1]
        deleting = re.findall(r"unlink|os\.remove|rmtree|os\.rmdir|removedirs|send2trash", body)
        if deleting:
            failures.append(f"the hook body carries a delete call: {sorted(set(deleting))}")

        # The state directory follows OCTO_REFLEX_STATE_DIR, absolute paths only.
        saved = os.environ.get(STATE_ENV)
        try:
            os.environ[STATE_ENV] = str(tmp / "env-state")
            if state_dir() != tmp / "env-state":
                failures.append(f"{STATE_ENV} was not honoured")
            default = LIVE_DIR / ".cache" / "reflex" / "definition-closed"
            for relative in ("relative/state", "./state", "~/state", "state"):
                os.environ[STATE_ENV] = relative
                if state_dir() != default:
                    failures.append(f"{STATE_ENV}={relative!r} was followed; only absolute paths count")
        finally:
            if saved is None:
                os.environ.pop(STATE_ENV, None)
            else:
                os.environ[STATE_ENV] = saved

        # Worktrees of the brain are excluded.
        repo = tmp / "repo"
        tree = tmp / "tree"
        repo.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        steps = (["init", "-q"],
                 ["-c", "user.name=selftest", "-c", "user.email=selftest@example.invalid",
                  "commit", "-q", "--allow-empty", "-m", "seed"],
                 ["worktree", "add", "-q", "--detach", str(tree)])
        built = all(subprocess.run(["git", "-C", str(repo), *s], env=env,
                                   capture_output=True, timeout=30).returncode == 0
                    for s in steps)
        if not built:
            failures.append("could not build the worktree fixture")
        else:
            listed = brain_worktrees(repo)
            inside = str(tree / ".claude" / "memory" / "x.md")
            if os.path.realpath(str(tree)) not in [os.path.realpath(w) for w in listed]:
                failures.append(f"the worktree was not listed: {listed}")
            if arm_root(inside, listed) is not None:
                failures.append("a memory path inside a brain worktree was treated as an arm")
            if arm_root(inside, ()) is None:
                failures.append("worktree control: the same path without the list should match")
        if brain_worktrees(tmp / "not-a-repo") != []:
            failures.append("a directory that is not a repo listed worktrees")
    except Exception as exc:  # a selftest that crashes is a failure, not a pass
        failures.append(f"selftest raised {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if failures:
        for f in failures:
            print(f"selftest FAIL: {f}", file=sys.stderr)
        return 1
    print("selftest PASS: advisory on an arm memory closure at any depth, root "
          "shell-quoted, once per session per file, 8 firing and 29 silent "
          "inputs, non-string session id, nothing deleted and no delete call in "
          "the hook body, foreign state file kept, symlinked state dir skipped, "
          "absolute-only state dir override, scan cap pinned, 13 hostile inputs "
          "under 1 s, brain worktrees excluded")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main())
