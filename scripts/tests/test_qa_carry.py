#!/usr/bin/env python3
"""v10 AC-12, AC-13: a QA PASS is carried across a base-only update.

A PASS approves the patch over its merge base. When GitHub's "Update branch"
moves a pull request from the reviewed head R to N and the whitespace-sensitive
diff hash over the merge base is the same, the PASS for R decides N. Every other
case denies exactly as before: a different patch, a commit that is not local, a
partial clone, or any FAIL or NEEDS-WORK of the pull request newer than the PASS.

Stdlib only:  python3 -m unittest scripts.tests.test_qa_carry
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import uuid as _uuid
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import receipt_ledger as rl  # noqa: E402

_spec = importlib.util.spec_from_file_location("qa_merge_gate_carry", SCRIPTS / "qa-merge-gate.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

CARRY = SCRIPTS.parent / "registry" / "fixtures" / "CODE.qa-merge-gate" / "carry"


class QaCarryOver(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qa-carry-")
        self._home = (os.environ.get("HOME"), os.environ.get("USERPROFILE"))
        os.environ["HOME"] = os.environ["USERPROFILE"] = self.tmp
        self.sub = Path(self.tmp) / ".claude" / "projects" / "p" / "sess-1" / "subagents"
        self.sub.mkdir(parents=True)
        self.repo = Path(self.tmp) / "repo"
        self.repo.mkdir()
        g = lambda *a: gate._carry_git(self.repo, *a)
        g("init", "-q", "-b", "master")
        gate._carry_commit(self.repo, {"app.py": "def f():\n    return 0\n", "notes.txt": "a\n"}, "base")
        g("checkout", "-q", "-b", "feature")
        self.R = gate._carry_commit(self.repo, {"app.py": "def f():\n    return 1\n"}, "patch")
        g("checkout", "-q", "master")
        gate._carry_commit(self.repo, {"notes.txt": "a\nupstream\n"}, "master moves")
        g("checkout", "-q", "feature")
        g("merge", "-q", "--no-edit", "master")
        self.N = g("rev-parse", "HEAD")
        self.n = 0

    def tearDown(self):
        for key, value in zip(("HOME", "USERPROFILE"), self._home):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def receipt(self, verdict, head, ts, pr="500"):
        self.n += 1
        uid = str(_uuid.uuid4())
        text = f"QA-VERDICT: {verdict}\nQA-SCOPE: PR #{pr}" + (f"\nQA-HEAD: {head}" if head else "")
        tp = self.sub / f"agent-c{self.n}.jsonl"
        tp.write_text(json.dumps({"type": "assistant", "uuid": uid, "parentUuid": str(_uuid.uuid4()),
                                  "sessionId": "sess-1", "timestamp": ts,
                                  "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}) + "\n")
        rl.append_global({"kind": "qa", "verdict": verdict, "scope": f"PR #{pr}", "head": head,
                          "entry_uuid": uid, "agent_type": "Reality Checker", "agent_id": f"c{self.n}",
                          "agent_transcript_path": str(tp)})

    def decide(self, pin=None):
        return rl.qa_decide_for("500", pin or self.N, str(self.repo))

    # ---- AC-12 ----
    def test_a_pure_update_carries_the_pass(self):
        self.receipt("PASS", self.R, "2026-10-01T10:00:00.000Z")
        got = self.decide()
        self.assertEqual(got["verdict"], "PASS")
        self.assertEqual((got["carried_from"], got["carried_to"]), (self.R, self.N))

    def test_an_older_revocation_does_not_stop_the_carry(self):
        self.receipt("NEEDS-WORK", self.R, "2026-10-01T09:00:00.000Z")
        self.receipt("PASS", self.R, "2026-10-01T10:00:00.000Z")
        self.assertEqual(self.decide()["carried_from"], self.R)

    def test_the_carry_fits_inside_the_gate_deadline(self):
        self.receipt("PASS", self.R, "2026-10-01T10:00:00.000Z")
        t = time.monotonic()
        self.assertIsNotNone(self.decide())
        self.assertLess(time.monotonic() - t, gate._LOOKUP_DEADLINE)

    # ---- AC-13 ----
    def test_a_whitespace_only_change_in_the_patch_denies(self):
        self.receipt("PASS", self.R, "2026-10-01T10:00:00.000Z")
        n2 = gate._carry_commit(self.repo, {"app.py": "def f():\n    return 1 \n"}, "space")
        self.assertIsNone(self.decide(n2))

    def test_a_commit_that_is_not_local_denies(self):
        self.receipt("PASS", "0" * 39 + "1", "2026-10-01T10:00:00.000Z")
        self.assertIsNone(self.decide())
        self.receipt("PASS", self.R, "2026-10-01T11:00:00.000Z")
        self.assertIsNone(self.decide("f" * 40))

    def test_a_newer_revocation_of_any_commit_denies(self):
        self.receipt("PASS", self.R, "2026-10-01T10:00:00.000Z")
        self.receipt("NEEDS-WORK", "e" * 40, "2026-10-01T11:00:00.000Z")   # another commit of the PR
        self.assertIsNone(self.decide())

    def test_a_newer_revocation_of_the_reviewed_head_denies(self):
        self.receipt("PASS", self.R, "2026-10-01T10:00:00.000Z")
        self.receipt("FAIL", self.R, "2026-10-01T11:00:00.000Z")
        self.assertIsNone(self.decide())

    def test_a_newer_headless_revocation_denies(self):
        self.receipt("PASS", self.R, "2026-10-01T10:00:00.000Z")
        self.receipt("NEEDS-WORK", "", "2026-10-01T11:00:00.000Z")
        self.assertEqual(self.decide()["verdict"], "NEEDS-WORK")   # names every commit, N included

    def test_a_receipt_naming_the_new_head_decides_without_a_carry(self):
        self.receipt("PASS", self.R, "2026-10-01T10:00:00.000Z")
        self.receipt("NEEDS-WORK", self.N, "2026-10-01T11:00:00.000Z")
        self.assertEqual(self.decide()["verdict"], "NEEDS-WORK")

    def test_a_partial_clone_is_refused(self):
        self.receipt("PASS", self.R, "2026-10-01T10:00:00.000Z")
        gate._carry_git(self.repo, "config", "extensions.partialClone", "origin")
        self.assertIsNone(self.decide())

    def test_no_repository_means_no_carry(self):
        self.receipt("PASS", self.R, "2026-10-01T10:00:00.000Z")
        self.assertIsNone(rl.qa_decide_for("500", self.N, ""))
        self.assertIsNone(rl.qa_decide_for("500", self.N, self.tmp))   # not a repository

    def test_a_pass_for_another_pull_request_is_never_carried(self):
        self.receipt("PASS", self.R, "2026-10-01T10:00:00.000Z", pr="501")
        self.assertIsNone(self.decide())


class CarryFixtures(unittest.TestCase):
    def test_each_violation_is_the_benign_with_one_edit(self):
        benign = json.loads(next(CARRY.glob("benign*.json")).read_text())
        violations = sorted(CARRY.glob("violation*.json"))
        self.assertEqual(len(violations), 3)
        for v in violations:
            data = json.loads(v.read_text())
            changed = [k for k in set(benign) | set(data) if k != "description" and benign.get(k) != data.get(k)]
            self.assertEqual(len(changed), 1, f"{v.name}: {changed}")


if __name__ == "__main__":
    unittest.main()
