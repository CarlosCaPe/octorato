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

        found = rl.gate_surfaces_dirty(repo)
        self.assertGreater(len(found), 0,
                           "a git that refuses must never read as a clean tree")
        self.assertEqual(sum(1 for f in found if f.startswith("? ")), 2,
                         "both failed readings must be reported as findings")


if __name__ == "__main__":
    unittest.main()
