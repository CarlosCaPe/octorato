#!/usr/bin/env python3
"""Tests for the v7 receipt ledger: proves the ANCHORS, not the file.

Each test is a bypass the independent QA demonstrated on the first cut of
v7 (2026-09-05) and that the anchoring must now refuse:

  - a hand-typed seek receipt naming a tool_use that is not a seek (Read,
    `echo list_messages`) is ignored; only a real seek in the turn counts
  - a QA receipt is honored only when its transcript lives under the harness
    projects dir, its LAST assistant text re-parses to PASS, its scope names
    the PR as a whole token (260 never approves 26), and the agent is a QA
    persona; a missing transcript is skipped, not fatal
  - a gate receipt is void when HEAD or the gate tree hash differ, or when
    the gate surfaces carry uncommitted edits

Stdlib only:  python3 -m unittest scripts.tests.test_receipt_ledger
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import receipt_ledger as rl  # noqa: E402


def _tr(path: Path, entries):
    with path.open("w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")


import uuid as _uuid


def _h(entry, sid="fx-session"):
    entry.update({"uuid": str(_uuid.uuid4()), "parentUuid": str(_uuid.uuid4()),
                  "sessionId": sid, "timestamp": "2026-09-05T10:00:00.000Z"})
    return entry


def A(blocks):
    return _h({"type": "assistant", "message": {"role": "assistant", "content": blocks}})


def U(name, inp, tid):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def R(tid):
    return _h({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": "ok"}]}})


class ReceiptLedgerAnchors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="receipts-")
        self._home = os.environ.get("HOME")
        os.environ["HOME"] = self.tmp
        (Path(self.tmp) / ".claude" / "projects" / "p").mkdir(parents=True)

    def tearDown(self):
        os.environ["HOME"] = self._home

    # ---- seek anchoring ----
    def test_seek_receipt_must_name_a_real_seek_tool_use(self):
        tr = Path(self.tmp) / "t.jsonl"
        forged = {"type": "assistant", "message": {"role": "assistant", "content": [U("mcp__whatsapp__list_messages", {"query": "x"}, "f9")]}}
        _tr(tr, [A([U("Read", {"file_path": "/x"}, "r1")]), R("r1"),
                 A([U("Bash", {"command": "echo list_messages"}, "e1")]), R("e1"),
                 A([U("mcp__whatsapp__list_chats", {}, "l1")]), R("l1"),
                 forged,
                 A([U("mcp__whatsapp__list_messages", {"query": "27,180"}, "s1")]), R("s1")])
        for tid in ("r1", "e1", "l1", "f9", "s1", "zz"):
            rl.append_session("s", {"kind": "seek", "tool_use_id": tid, "tool_name": "x"})
        rl.append_session("s", {"kind": "seek", "tool_name": "mcp__whatsapp__list_messages"})  # no id
        hits = rl.seek_receipts_in_turn("s", str(tr))
        self.assertEqual([h["tool_use_id"] for h in hits], ["s1"])

    def test_bash_seek_needs_command_boundary(self):
        self.assertTrue(rl.bash_is_seek("python3 ~/.claude/scripts/query_connectome.py memory \"x\""))
        self.assertTrue(rl.bash_is_seek("cd /tmp && sqlite3 /opt/x/messages.db 'select 1'"))
        self.assertFalse(rl.bash_is_seek("echo list_messages"))
        self.assertFalse(rl.bash_is_seek("grep -rn list_messages ."))
        self.assertFalse(rl.bash_is_seek("git commit -m 'query_connectome.py memory'"))
        # wrappers are peeled; sh -c is expanded
        self.assertTrue(rl.bash_is_seek("nohup timeout 30 python3 ~/.claude/scripts/query_connectome.py memory x"))
        self.assertTrue(rl.bash_is_seek("bash -c 'python3 ~/.claude/scripts/query_connectome.py memory x'"))

    # ---- qa anchoring ----
    def _agent(self, name, text, sid="sess-1", shaped=True):
        d = Path(self.tmp) / ".claude" / "projects" / "p" / sid / "subagents"
        d.mkdir(parents=True, exist_ok=True)
        p = d / name
        mk = (lambda e: _h(e, sid)) if shaped else (lambda e: e)
        _tr(p, [mk({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "working..."}]}}),
                mk({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})])
        return str(p)

    def test_qa_receipt_requires_harness_path_last_pass_and_token_scope(self):
        good = self._agent("agent-a1.jsonl", "review done\nQA-VERDICT: PASS\nQA-SCOPE: PR #260")
        fail_with_pass_word = self._agent("agent-a2.jsonl", "selftest PASS everywhere\nQA-VERDICT: FAIL\nQA-SCOPE: PR #260")
        quoted_first = self._agent("agent-a3.jsonl", "the protocol is `QA-VERDICT: PASS` `QA-SCOPE: PR #999`\n...\nQA-VERDICT: FAIL\nQA-SCOPE: PR #260")
        other_session = self._agent("agent-a4.jsonl", "QA-VERDICT: PASS\nQA-SCOPE: PR #260", sid="sess-2")
        unshaped = self._agent("agent-a5.jsonl", "QA-VERDICT: PASS\nQA-SCOPE: PR #260", shaped=False)
        outside = Path(self.tmp) / "outside.jsonl"
        _tr(outside, [A([{"type": "text", "text": "QA-VERDICT: PASS\nQA-SCOPE: PR #260"}])])
        rec = lambda path, agent="Reality Checker", aid=None: rl.append_global(
            {"kind": "qa", "verdict": "PASS", "scope": "PR #260", "agent_type": agent,
             "agent_id": aid or Path(path).stem.replace("agent-", ""), "agent_transcript_path": path})
        rec(str(outside))                                   # outside harness dir
        rec(fail_with_pass_word)                            # transcript really says FAIL
        rec(quoted_first)                                   # quoted protocol before real FAIL
        rec(good, agent="Explore")                          # not a QA persona
        rec(other_session)                                  # another session's subagent dir
        rec(unshaped)                                       # entries without harness fields
        rec(good, aid="zzz")                                # agent id does not match the file
        rec(str(Path(self.tmp) / ".claude/projects/p/sess-1/subagents/agent-missing.jsonl"))
        self.assertIsNone(rl.qa_pass_for("260", "sess-1"))
        rec(good)
        self.assertIsNotNone(rl.qa_pass_for("260", "sess-1"))
        self.assertIsNone(rl.qa_pass_for("260", "sess-9"))  # wrong session
        self.assertIsNone(rl.qa_pass_for("26", "sess-1"))   # substring never approves
        self.assertIsNone(rl.qa_pass_for("2600", "sess-1"))
        self.assertEqual(rl.parse_verdict("QA-VERDICT: PASS\nQA-SCOPE: PR #1\nQA-VERDICT: FAIL\nQA-SCOPE: PR #2"), ("FAIL", "PR #2"))

    # ---- gate anchoring ----
    def test_gate_receipt_binds_head_and_gate_tree_and_cleanliness(self):
        repo = Path(self.tmp) / "brain"
        (repo / "scripts").mkdir(parents=True); (repo / "registry").mkdir()
        (repo / "scripts" / "g.py").write_text("print(1)\n"); (repo / "registry" / "r.yaml").write_text("a: 1\n")
        (repo / "hooks.json").write_text("{}\n")
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "one"], check=True, env=env)
        head, gates = rl.brain_head(repo), rl.gate_tree_hash(repo)
        self.assertTrue(head and gates and not rl.gate_surfaces_dirty(repo))
        rl.append_global({"kind": "gate-liveness", "ok": True, "head": head, "gates": gates})
        self.assertTrue(rl.gate_receipt_ok(gates))
        (repo / "scripts" / "g.py").write_text("print(2)\n")            # neuter a gate, HEAD unchanged
        self.assertTrue(rl.gate_surfaces_dirty(repo))                   # consumer denies on dirty
        subprocess.run(["git", "-C", str(repo), "update-index", "--assume-unchanged", "scripts/g.py"], check=True, env=env)
        self.assertEqual(subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True, env=env).stdout, "")
        self.assertTrue(rl.gate_surfaces_dirty(repo))                   # porcelain silenced, still dirty
        subprocess.run(["git", "-C", str(repo), "update-index", "--no-assume-unchanged", "scripts/g.py"], check=True, env=env)
        subprocess.run(["git", "-C", str(repo), "commit", "-qam", "two"], check=True, env=env)
        self.assertFalse(rl.gate_receipt_ok(rl.gate_tree_hash(repo)))    # new gate tree, no receipt

    def test_a_git_that_refuses_is_a_finding_and_never_a_clean_tree(self):
        """"git refused" and "clean" must not be the same value.

        QA cycle 3 measured the conflation end to end. `_git` returned "" both when
        git answered nothing and when git FAILED, and empty means clean to every
        consumer, so the ability to make git fail was the ability to forge a clean
        tree. `GIT_TEST_INDEX_THREADS=true` is the exact knob: git parses it as an
        int and rejects it, which kills the two INDEX-reading calls (status,
        ls-files) and leaves the two object-reading ones (ls-tree, rev-parse)
        answering. The name reaches git because `scrubbed_env` keeps `GIT_TEST_*` on
        purpose.

        The tree here is the one that made it exploitable: clean except ONE
        UNTRACKED file under a gate surface. Reading 3 compares HEAD blobs, so it is
        structurally blind to an untracked file, and readings 1 and 2 share the
        index failure mode, so with the knob set NO reading sees it.

        Nothing here asserts against a container that could hold an environment: the
        assertions compare counts and booleans, and a failure message renders only
        those.
        """
        repo = Path(self.tmp) / "refuser"
        (repo / "scripts").mkdir(parents=True); (repo / "registry").mkdir()
        (repo / "scripts" / "g.py").write_text("print(1)\n")
        (repo / "registry" / "r.yaml").write_text("a: 1\n")
        (repo / "hooks.json").write_text("{}\n")
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "one"], check=True, env=env)
        self.assertEqual(len(rl.gate_surfaces_dirty(repo)), 0, "committed tree must read clean")

        (repo / "scripts" / "untracked_gate.py").write_text("print(2)\n")   # never added
        self.assertGreater(len(rl.gate_surfaces_dirty(repo)), 0,
                           "an untracked gate script must be a finding")

        # os.environ is process-wide; restore it or the rest of the suite inherits
        # the knob (the 2026-09-07 HOME-leak class).
        prior = os.environ.get("GIT_TEST_INDEX_THREADS")
        self.addCleanup(lambda: os.environ.__setitem__("GIT_TEST_INDEX_THREADS", prior)
                        if prior is not None else os.environ.pop("GIT_TEST_INDEX_THREADS", None))
        os.environ["GIT_TEST_INDEX_THREADS"] = "true"

        # the knob really does split the readings: index calls fail, object calls do not
        self.assertFalse(rl._git_read(repo, "status", "--porcelain", "--", "scripts")[0],
                         "the knob must make `git status` fail, or this test proves nothing")
        self.assertFalse(rl._git_read(repo, "ls-files", "-v", "--", "scripts")[0],
                         "the knob must make `git ls-files` fail")
        self.assertTrue(rl._git_read(repo, "ls-tree", "-r", "HEAD", "--", "scripts")[0],
                        "`git ls-tree` must still answer, or the failure is not selective")
        self.assertNotEqual(rl.brain_head(repo), "", "`git rev-parse HEAD` must still answer")

        self.assertFalse(rl._git_read(repo, "ls-files", "--others", "--", "scripts")[0],
                         "the knob must make reading 4 fail too; it reads the index as well")

        found = rl.gate_surfaces_dirty(repo)
        self.assertGreater(len(found), 0,
                           "a git that refuses must never read as a clean tree")
        self.assertEqual(sum(1 for f in found if f.startswith("? ")), 3,
                         "every failed reading is a finding: status, ls-files -v, and "
                         "reading 4 (ls-files --others), which the knob kills as well")
        self.assertEqual(len(found), 3,
                         "and NOTHING was measured to differ: this is the tree whose WARN "
                         "used to claim a diff (see brain_doctor.gate_surface_warn)")


def _mkrepo(root: Path, gitignore: str | None = None) -> Path:
    """A throwaway brain-shaped repo: one commit, the three gate surfaces.

    Never the live worktree and never ~/.claude: every mutation in these tests
    happens inside a tempdir the test owns.
    """
    (root / "scripts").mkdir(parents=True)
    (root / "registry").mkdir()
    (root / "scripts" / "g.py").write_text("print(1)\n")
    (root / "registry" / "r.yaml").write_text("a: 1\n")
    (root / "hooks.json").write_text("{}\n")
    if gitignore is not None:
        (root / ".gitignore").write_text(gitignore)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.run(["git", "init", "-q", str(root)], check=True, env=env)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "one"], check=True, env=env)
    return root


class GitThatLiesTest(unittest.TestCase):
    """The sub-class `_git_read` did NOT close: git exits 0 and answers wrong.

    QA cycle 3 fixed the case where git REFUSES (rc != 0), and that was real. It
    left open the case where git LIES: on every route below git exits 0 on all
    four calls, `head` and `gates` both resolve, `gate_surfaces_dirty` answers
    `[]`, and `check_gate_liveness` writes a receipt for a tree carrying an
    uncommitted gate script. Two of the routes need no environment variable at
    all, only one line written into `.git/`.

    Nothing here asserts against a container that could hold an environment: the
    subTest label is a literal string, and every assertion compares finding
    counts and path substrings. A failure message renders those and nothing else.
    """

    PROBE = "scripts/probe_untracked.py"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def _env(self, **kw):
        """Set env keys for the duration of the test and restore them exactly.

        os.environ is process-wide; a HOME left behind breaks the rest of the
        suite (the 2026-09-07 leak class), so every key is restored by name.
        """
        prior = {k: os.environ.get(k) for k in kw}

        def restore():
            for k, v in prior.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.addCleanup(restore)
        for k, v in kw.items():
            os.environ[k] = v

    # --- the five routes, each armed alone, each with its own clean control ---
    def _route_repo_config(self, repo):
        subprocess.run(["git", "-C", str(repo), "config",
                        "status.showUntrackedFiles", "no"], check=True)

    def _route_info_exclude(self, repo):
        (repo / ".git" / "info").mkdir(exist_ok=True)
        (repo / ".git" / "info" / "exclude").write_text(self.PROBE + "\n")

    def _route_xdg(self, repo):
        d = Path(self.tmp) / (repo.name + "-xdg")
        (d / "git").mkdir(parents=True)
        (d / "git" / "config").write_text("[status]\n\tshowUntrackedFiles = no\n")
        self._env(XDG_CONFIG_HOME=str(d))

    def _route_home_status(self, repo):
        d = Path(self.tmp) / (repo.name + "-home")
        d.mkdir(parents=True)
        (d / ".gitconfig").write_text("[status]\n\tshowUntrackedFiles = no\n")
        self._env(HOME=str(d), XDG_CONFIG_HOME=str(d / "xdg"))

    def _route_home_excludes(self, repo):
        d = Path(self.tmp) / (repo.name + "-home2")
        d.mkdir(parents=True)
        (d / "ignore").write_text(self.PROBE + "\n")
        (d / ".gitconfig").write_text("[core]\n\texcludesFile = %s\n" % (d / "ignore"))
        self._env(HOME=str(d), XDG_CONFIG_HOME=str(d / "xdg"))

    ROUTES = ("repo .git/config", ".git/info/exclude", "XDG_CONFIG_HOME",
              "HOME .gitconfig status key", "HOME .gitconfig core.excludesFile")

    def _arm(self, label, repo):
        {"repo .git/config": self._route_repo_config,
         ".git/info/exclude": self._route_info_exclude,
         "XDG_CONFIG_HOME": self._route_xdg,
         "HOME .gitconfig status key": self._route_home_status,
         "HOME .gitconfig core.excludesFile": self._route_home_excludes}[label](repo)

    # Which reading is expected to catch each route. This is set equality, not a
    # count: the `-c` pins (`_git_pins`) are what keep reading 1 honest under the
    # four CONFIG routes, and reading 4 is the only thing that survives the one
    # route no pin can reach (`.git/info/exclude` is a file, not a config key).
    # Assert only "a finding exists" and both mechanisms could carry each other,
    # and reverting either would stay green.
    CAUGHT_BY = {"repo .git/config": "?? ",
                 "XDG_CONFIG_HOME": "?? ",
                 "HOME .gitconfig status key": "?? ",
                 "HOME .gitconfig core.excludesFile": "?? ",
                 ".git/info/exclude": "U "}

    def test_no_config_or_ignore_route_can_hide_an_uncommitted_gate_script(self):
        # positive control FIRST: the file is visible when nothing is armed
        control = _mkrepo(Path(self.tmp) / "control", gitignore="*.pyc\n")
        (control / self.PROBE).write_text("print(2)\n")
        self.assertTrue(any(self.PROBE in f for f in rl.gate_surfaces_dirty(control)),
                        "positive control: an untracked gate script must be visible "
                        "before any route is armed, or the routes prove nothing")

        for i, label in enumerate(self.ROUTES):
            with self.subTest(route=label, tree="dirty"):
                repo = _mkrepo(Path(self.tmp) / ("d%d" % i), gitignore="*.pyc\n")
                (repo / self.PROBE).write_text("print(2)\n")
                self._arm(label, repo)
                found = [f for f in rl.gate_surfaces_dirty(repo) if self.PROBE in f]
                self.assertTrue(found,
                                "route hid an uncommitted gate script")
                self.assertTrue(any(f.startswith(self.CAUGHT_BY[label]) for f in found),
                                "the route must be caught by the reading that is supposed "
                                "to catch it (%r), not incidentally by the other one"
                                % self.CAUGHT_BY[label])
            with self.subTest(route=label, tree="clean"):
                # the SAME route on a genuinely clean tree must stay silent, or the
                # finding is noise and gets waived instead of read
                repo = _mkrepo(Path(self.tmp) / ("c%d" % i), gitignore="*.pyc\n")
                self._arm(label, repo)
                self.assertEqual(rl.gate_surfaces_dirty(repo), [],
                                 "clean control must yield no finding under this route")

    def test_reading_four_suppresses_noise_only_by_committed_rules(self):
        """The noise trade-off, and its number.

        `ls-files --others` with no excludes lists every ignored artifact under the
        gate surfaces: 70 paths on the live brain (`__pycache__`, `*.pyc`,
        generated fixture `*.db`), 36 on a feature worktree. A finding that always
        fires is a finding nobody reads, which fails the same way as no finding at
        all. The filter is the `.gitignore` blob AT HEAD, handed to
        `--exclude-from`, and it takes both numbers to 0 while leaving all five
        routes visible. Drop the filter and this test goes red on noise alone.
        """
        repo = _mkrepo(Path(self.tmp) / "noise", gitignore="*.pyc\n__pycache__/\n")
        (repo / "scripts" / "__pycache__").mkdir()
        (repo / "scripts" / "__pycache__" / "g.cpython-312.pyc").write_bytes(b"\x00")
        self.assertEqual(rl.gate_surfaces_dirty(repo), [],
                         "generated artifacts the COMMITTED .gitignore covers are not "
                         "findings, or the check is noise and gets waived")

    def test_reading_four_ignores_working_tree_ignore_files(self):
        """The filter is a commit, so an uncommitted file cannot widen it.

        `--exclude-per-directory=.gitignore` was measured and rejected here: a
        self-hiding `scripts/.gitignore` holding the probe AND `.gitignore` blinds
        it completely, and it needs no environment and no config key. Reading
        HEAD's blob instead sees both the probe and the ignore file that tried to
        hide it.
        """
        repo = _mkrepo(Path(self.tmp) / "selfhide", gitignore="*.pyc\n__pycache__/\n")
        (repo / "scripts" / "__pycache__").mkdir()
        (repo / "scripts" / "__pycache__" / "g.cpython-312.pyc").write_bytes(b"\x00")
        (repo / self.PROBE).write_text("print(2)\n")
        # both ignore files an attacker can write without a commit, armed together,
        # each hiding itself as well as the probe
        (repo / ".gitignore").write_text("*.pyc\n__pycache__/\n%s\n.gitignore\n" % self.PROBE)
        (repo / "scripts" / ".gitignore").write_text("probe_untracked.py\n.gitignore\n")
        found = rl.gate_surfaces_dirty(repo)
        self.assertTrue(any(self.PROBE in f for f in found),
                        "an edited working-tree .gitignore must not widen the filter")
        self.assertTrue(any("scripts/.gitignore" in f for f in found),
                        "and the self-hiding ignore file must be a finding itself")
        # the generated-noise assertion deliberately lives in the sibling test, not
        # here: two mechanisms (the filter's EXISTENCE, and the filter's SOURCE)
        # should be revertible one at a time and turn exactly one test red each.


if __name__ == "__main__":
    unittest.main()
