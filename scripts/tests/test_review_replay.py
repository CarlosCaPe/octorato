#!/usr/bin/env python3
"""Tests for the replay that qualifies an external reviewer (v11 spec
202610141000, phase 4, T20).

  - the tracked Replay_Fixture_Set holds its minimum shape (AC-30)
  - a Held_Out_Set reaches the record only as a hash and counts (AC-31)
  - the doctor fails a machine path, a $HOME path or a blocklist hit (AC-32)
  - three runs of the panel block plus excerpts, parse_panel, unreadable,
    failed and timed-out answers counted against the engine, worst kept (AC-33)
  - the baseline on Fable, Opus only on a quota or credit refusal, with a run
    receipt (AC-34)
  - the bound on the worst of three runs (AC-35)
  - the doctor recomputes every `allowed` pair (AC-36)
  - the fixture directory is on the arming surface (AC-37)
  - the runner and both checks are registered (AC-15)

No live engine is called: every reviewer here is an in-process stub or a stub
executable passed with --cli.

    python3 -m unittest scripts.tests.test_review_replay
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
import brain_doctor  # noqa: E402
import panel_digest as pd  # noqa: E402
import review_replay as rr  # noqa: E402

CASES, _PROBS = rr.load_cases(ROOT / rr.FIXTURES_REL)
GIT_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
GIT_ENV.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")


def answer(case, verdict):
    block = rr.case_message(case).panel_block()
    dg = rr.build_prompt(case)[1]
    body = block.replace(f"PANEL-SHA256: {dg}", "")
    return {"status": "ok", "stdout": f"Checked.\n{body}PANEL-VERDICT: {verdict}\nPANEL-SHA256: {dg}\n"}


def by_prompt(cases):
    return {rr.build_prompt(c)[0]: c for c in cases}


def oracle(cases, wrong=()):
    """A stub reviewer: the expected verdict, flipped for the ids in `wrong`."""
    table = by_prompt(cases)

    def call(prompt):
        c = table[prompt]
        v = c["expected"]
        if c["id"] in wrong:
            v = "PASS" if v == "NEEDS-WORK" else "NEEDS-WORK"
        return answer(c, v)
    return call


def run_counts(caught, fa, nw=40, ok=40):
    return {"needs_work": nw, "caught": caught, "pass": ok, "false_alarms": fa,
            "unparsed": 0, "failed": 0, "timeout": 0, "by_class": {},
            "catch_rate": rr._rate(caught, nw), "false_alarm_rate": rr._rate(fa, ok)}


class FixtureSet(unittest.TestCase):
    def test_ac30_tracked_set_minimum_shape(self):
        self.assertEqual(_PROBS, [])
        self.assertEqual(rr.fixture_problems(CASES), [])
        nw = [c for c in CASES if c["expected"] == "NEEDS-WORK"]
        self.assertGreaterEqual(len(nw), 40)
        self.assertGreaterEqual(sum(1 for c in CASES if c["expected"] == "PASS"), 40)
        for cls in ("wrong-fact", "overstatement"):
            self.assertGreaterEqual(sum(1 for c in nw if c["defect_class"] == cls), 15)

    def test_ac30_shape_check_fails_each_shortfall(self):
        nw = [c for c in CASES if c["expected"] == "NEEDS-WORK"]
        ok = [c for c in CASES if c["expected"] == "PASS"]
        self.assertTrue(rr.fixture_problems(nw[1:] + ok))            # 39 NEEDS-WORK
        self.assertTrue(rr.fixture_problems(nw + ok[1:]))            # 39 PASS
        over = [c for c in nw if c["defect_class"] == "overstatement"]
        self.assertTrue(rr.fixture_problems([c for c in nw if c not in over[6:]] + ok))
        bad = copy.deepcopy(nw[0])
        bad["defect_line"] = "a line the reply does not carry"
        self.assertTrue(rr.fixture_problems([bad] + nw[1:] + ok))
        bad = copy.deepcopy(ok[0])
        bad["excerpts"] = []
        self.assertTrue(rr.fixture_problems(nw + [bad] + ok[1:]))
        bad = copy.deepcopy(ok[0])
        bad["defect_class"] = "wrong-fact"
        self.assertTrue(rr.fixture_problems(nw + [bad] + ok[1:]))

    def test_tree_hash_equals_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "registry" / "replay" / "fixtures"
            shutil.copytree(ROOT / rr.FIXTURES_REL, d)
            (d / "sub").mkdir()
            (d / "sub" / "x.json").write_text("{}\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q", tmp], check=True, env=GIT_ENV)
            subprocess.run(["git", "-C", tmp, "add", "-A"], check=True, env=GIT_ENV)
            subprocess.run(["git", "-C", tmp, "commit", "-qm", "f"], check=True, env=GIT_ENV)
            want = subprocess.run(["git", "-C", tmp, "rev-parse", "HEAD:registry/replay/fixtures"],
                                  capture_output=True, text=True, env=GIT_ENV).stdout.strip()
            self.assertEqual(rr.git_tree_hash(d), want)


class Hygiene(unittest.TestCase):
    """AC-32, through the doctor check."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        shutil.copytree(ROOT / rr.FIXTURES_REL, self.root / rr.FIXTURES_REL)

    def tearDown(self):
        self._tmp.cleanup()

    def check(self, pattern=None):
        return brain_doctor.check_review_replay(False, self.root, pattern or re.compile(r"\bNOHIT\b"))

    def test_ac32_clean_set_passes(self):
        r = self.check()
        self.assertEqual(r.status, brain_doctor.PASS, r.message)

    def test_ac32_absolute_user_path_fails(self):
        p = self.root / rr.FIXTURES_REL / "pass-001.json"
        c = json.loads(p.read_text())
        c["excerpts"][0]["source"] = "/home/someone/build.log"
        p.write_text(json.dumps(c))
        self.assertEqual(self.check().status, brain_doctor.FAIL)

    def test_ac32_home_path_in_a_record_fails(self):
        d = self.root / rr.RECORDS_REL
        d.mkdir(parents=True)
        (d / "codex-x.json").write_text('{"note": "$HOME/.codex"}')
        r = self.check()
        self.assertEqual(r.status, brain_doctor.FAIL)
        self.assertIn("codex-x.json", r.message)

    def test_ac32_blocklist_hit_fails(self):
        r = self.check(re.compile(r"\b(failover)\b", re.IGNORECASE))
        self.assertEqual(r.status, brain_doctor.FAIL)
        self.assertIn("blocklist", r.message)

    def test_ac30_doctor_fails_a_short_set(self):
        for p in sorted((self.root / rr.FIXTURES_REL).glob("nw-over-*.json"))[:6]:
            p.unlink()
        self.assertEqual(self.check().status, brain_doctor.FAIL)


class Scoring(unittest.TestCase):
    """AC-33: one case, one answer, three runs."""

    def test_ac33_prompt_is_the_panel_block_plus_excerpts(self):
        c = CASES[0]
        prompt, dg = rr.build_prompt(c)
        block = pd.Message(c["reply"], [], ["operator"], []).panel_block()
        self.assertIn(block, prompt)
        self.assertEqual(dg, pd.digest(c["reply"], [], ["operator"]))
        for e in c["excerpts"]:
            self.assertIn(e["text"], prompt)
            self.assertIn(e["source"], prompt)

    def test_ac33_verdict_read_with_parse_panel_and_bound_to_the_digest(self):
        c = CASES[0]
        dg = rr.build_prompt(c)[1]
        self.assertEqual(rr.judge(answer(c, "NEEDS-WORK")["stdout"], dg), "NEEDS-WORK")
        self.assertEqual(rr.judge("PANEL-VERDICT: PASS\n", dg), "")
        self.assertEqual(rr.judge(f"PANEL-VERDICT: PASS\nPANEL-SHA256: {'0' * 64}\n", dg), "")
        # The last verdict decides, as the ledger reads it.
        self.assertEqual(rr.judge(f"PANEL-VERDICT: PASS\n{answer(c, 'NEEDS-WORK')['stdout']}", dg),
                         "NEEDS-WORK")

    def test_ac33_unreadable_failed_and_timeout_count_against_the_engine(self):
        nw = sum(1 for c in CASES if c["expected"] == "NEEDS-WORK")
        ok = len(CASES) - nw
        for status, stdout in (("ok", "I think it is fine."), ("failed", ""), ("timeout", "")):
            r = rr.run_once(CASES, lambda p, s=status, o=stdout: {"status": s, "stdout": o}, 8)
            self.assertEqual((r["caught"], r["false_alarms"]), (0, ok), status)
            self.assertEqual(r["catch_rate"], 0.0)
            self.assertEqual(r["false_alarm_rate"], 1.0)
        r = rr.run_once(CASES, lambda p: 1 / 0, 4)
        self.assertEqual((r["caught"], r["false_alarms"], r["failed"]), (0, ok, len(CASES)))

    def test_ac33_rates_and_counts(self):
        nws = [c["id"] for c in CASES if c["expected"] == "NEEDS-WORK"][:4]
        oks = [c["id"] for c in CASES if c["expected"] == "PASS"][:2]
        r = rr.run_once(CASES, oracle(CASES, set(nws + oks)), 8)
        self.assertEqual((r["needs_work"], r["caught"], r["pass"], r["false_alarms"]), (40, 36, 40, 2))
        self.assertEqual((r["catch_rate"], r["false_alarm_rate"]), (0.9, 0.05))
        self.assertEqual(sorted(r["missed_ids"]), sorted(nws))

    def test_ac33_three_runs_worst_kept(self):
        nws = [c["id"] for c in CASES if c["expected"] == "NEEDS-WORK"]
        oks = [c["id"] for c in CASES if c["expected"] == "PASS"]
        state = {"n": 0}
        calls = [oracle(CASES), oracle(CASES, set(nws[:3])), oracle(CASES, set(oks[:5]))]

        def call(prompt):
            return calls[min(state["n"] // len(CASES), 2)](prompt)

        def counting(prompt):
            out = call(prompt)
            state["n"] += 1
            return out
        runs = rr.replay(CASES, counting, jobs=1)
        self.assertEqual(len(runs), rr.RUNS)
        self.assertEqual(state["n"], 3 * len(CASES))
        w = rr.worst_of(runs)
        self.assertEqual((w["catch_rate"], w["false_alarm_rate"]), (0.925, 0.125))


STUB = textwrap.dedent('''\
    #!{py}
    import json, os, re, sys
    from pathlib import Path
    argv = sys.argv[1:]
    if argv == ["--version"]:
        print("stub-cli 9.9.9"); sys.exit(0)
    model = argv[argv.index("--model") + 1] if "--model" in argv else argv[argv.index("-m") + 1]
    with open(os.environ["STUB_LOG"], "a") as fh:
        fh.write(model + "\\n")
    if os.environ.get("STUB_REFUSE") == model:
        print("API Error: 429 quota exceeded for this account", file=sys.stderr); sys.exit(1)
    prompt = argv[-1]
    body = re.search(r"PANEL-BODY-BEGIN\\n(.*)\\nPANEL-BODY-END", prompt, re.S).group(1)
    sha = re.search(r"PANEL-SHA256: (\\S+)", prompt).group(1)
    cases = [json.loads(p.read_text()) for p in Path(os.environ["STUB_FIXTURES"]).glob("*.json")]
    c = next(c for c in cases if c["reply"] == body)
    verdict = c["expected"] if os.environ.get("STUB_MODE") != "sloppy" else "PASS"
    print(prompt[prompt.index("PANEL-TO"):prompt.index("PANEL-BODY-END") + 14])
    print("PANEL-VERDICT: " + verdict)
    print("PANEL-SHA256: " + sha)
''')


class RepoCase(unittest.TestCase):
    """A throwaway git repo with the runner committed and the tracked fixtures."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        (self.root / "scripts").mkdir(parents=True)
        shutil.copy2(SCRIPTS / "review_replay.py", self.root / "scripts" / "review_replay.py")
        shutil.copytree(ROOT / rr.FIXTURES_REL, self.root / rr.FIXTURES_REL)
        shutil.copy2(ROOT / rr.REVIEWERS_REL, self.root / rr.REVIEWERS_REL)
        for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "base"]):
            subprocess.run(["git", "-C", str(self.root), *args], check=True, env=GIT_ENV,
                           capture_output=True)
        self.runner_sha = rr.sha256_file(SCRIPTS / "review_replay.py")
        self.tree = rr.git_tree_hash(self.root / rr.FIXTURES_REL)

    def tearDown(self):
        self._tmp.cleanup()

    def write_record(self, rec):
        d = self.root / rr.RECORDS_REL
        d.mkdir(parents=True, exist_ok=True)
        p = d / rr.record_name(rec["engine"], rec["model"])
        p.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return p

    def record(self, role, engine, model, runs, baseline=None):
        return rr.build_record(engine=engine, model=model, role=role, cases=CASES, runs=runs,
                               fixture_tree=self.tree, version="stub 1", reason="test",
                               runner_sha256=self.runner_sha, baseline=baseline)

    def reviewers(self, pairs):
        import yaml
        p = self.root / rr.REVIEWERS_REL
        data = yaml.safe_load(p.read_text())
        data["pairs"] = pairs
        p.write_text(yaml.safe_dump(data), encoding="utf-8")
        return p

    def doctor(self, pairs):
        return brain_doctor.check_reviewer_registry(False, self.reviewers(pairs), self.root)


def pair(model="m1", baseline_model="fable", engine="codex"):
    return {"engine": engine, "model": model, "status": "allowed",
            "replay_record": f"registry/replay/records/{engine}-{model}.json",
            "baseline_model": baseline_model}


class Bound(unittest.TestCase):
    """AC-35, on exact fractions of the worst of three runs."""

    def rec(self, runs):
        return {"runs": runs}

    def test_ac35_edges(self):
        base = self.rec([run_counts(38, 2), run_counts(36, 1), run_counts(37, 3)])  # 0.90 / 0.075
        hold = self.rec([run_counts(40, 0), run_counts(34, 0), run_counts(40, 7)])  # 0.85 / 0.175
        self.assertTrue(rr.bound_holds(hold, base))
        low = self.rec([run_counts(40, 0), run_counts(33, 0), run_counts(40, 0)])   # 0.825
        self.assertFalse(rr.bound_holds(low, base))
        noisy = self.rec([run_counts(40, 0), run_counts(40, 8), run_counts(40, 0)])  # 0.20
        self.assertFalse(rr.bound_holds(noisy, base))
        # The worst run decides, not the mean: two perfect runs do not save one bad one.
        self.assertFalse(rr.bound_holds(
            self.rec([run_counts(40, 0), run_counts(40, 0), run_counts(30, 0)]), base))


class Recompute(RepoCase):
    """AC-35 and AC-36 through the doctor's reviewer-registry check."""

    def setUp(self):
        super().setUp()
        self.base = self.record("baseline", "claude", "fable",
                                [run_counts(38, 2), run_counts(37, 1), run_counts(38, 3)])
        self.write_record(self.base)
        self.cand = self.record("candidate", "codex", "m1",
                                [run_counts(36, 4), run_counts(37, 5), run_counts(36, 4)], self.base)
        self.write_record(self.cand)

    def test_ac36_valid_pair_passes(self):
        r = self.doctor([pair()])
        self.assertEqual(r.status, brain_doctor.PASS, r.message)
        self.assertIn("1 allowed", r.message)

    def test_ac36_allowed_without_a_record_fails(self):
        r = self.doctor([pair(model="m2")])
        self.assertEqual(r.status, brain_doctor.FAIL)
        self.assertIn("codex/m2", r.message)
        bad = pair()
        bad["replay_record"] = "registry/reviewers.yaml"
        self.assertEqual(self.doctor([bad]).status, brain_doctor.FAIL)

    def test_ac35_ac36_outside_the_bound_fails(self):
        cand = self.record("candidate", "codex", "m1",
                           [run_counts(36, 4), run_counts(34, 4), run_counts(36, 4)], self.base)
        self.write_record(cand)
        r = self.doctor([pair()])
        self.assertEqual(r.status, brain_doctor.FAIL)
        self.assertIn("AC-35", r.message)
        cand = self.record("candidate", "codex", "m1",
                           [run_counts(37, 4), run_counts(37, 8), run_counts(37, 4)], self.base)
        self.write_record(cand)
        self.assertEqual(self.doctor([pair()]).status, brain_doctor.FAIL)

    def test_ac36_stored_rates_are_not_trusted(self):
        cand = copy.deepcopy(self.cand)
        cand["runs"][1]["caught"] = 20     # the counts, not the stored rate, decide
        cand["run_receipt"]["runs"] = cand["runs"]
        self.write_record(cand)
        self.assertEqual(self.doctor([pair()]).status, brain_doctor.FAIL)

    def test_ac36_fixture_tree_differs_from_tracked_set_fails(self):
        p = self.root / rr.FIXTURES_REL / "pass-001.json"
        p.write_text(p.read_text().replace("Run 418", "Run 481"))
        r = self.doctor([pair()])
        self.assertEqual(r.status, brain_doctor.FAIL)
        self.assertIn("fixture tree", r.message)

    def test_ac36_baseline_model_change_voids_the_pair(self):
        r = self.doctor([pair(baseline_model="opus")])
        self.assertEqual(r.status, brain_doctor.FAIL)
        # An Opus baseline replaces the Fable one: the Fable-measured pair is void.
        (self.root / rr.RECORDS_REL / "claude-fable.json").unlink()
        self.write_record(self.record("baseline", "claude", "opus",
                                      [run_counts(38, 2), run_counts(37, 1), run_counts(38, 3)]))
        r = self.doctor([pair()])
        self.assertEqual(r.status, brain_doctor.FAIL)
        self.assertIn("baseline model", r.message)

    def test_ac36_baseline_without_run_receipt_fails(self):
        base = copy.deepcopy(self.base)
        del base["run_receipt"]
        self.write_record(base)
        r = self.doctor([pair()])
        self.assertEqual(r.status, brain_doctor.FAIL)
        self.assertIn("run receipt", r.message)

    def test_ac34_ac36_each_run_receipt_field_is_checked(self):
        for field, value in (("model_reason", ""), ("model", "opus"), ("fixture_tree", "0" * 40),
                             ("runs", [run_counts(40, 0)] * 3), ("runner_sha256", "")):
            base = copy.deepcopy(self.base)
            base["run_receipt"][field] = value
            self.write_record(base)
            r = self.doctor([pair()])
            self.assertEqual(r.status, brain_doctor.FAIL, field)
            self.assertIn("run receipt", r.message, field)

    def test_ac36_runner_hash_at_no_commit_fails(self):
        base = copy.deepcopy(self.base)
        base["run_receipt"]["runner_sha256"] = hashlib.sha256(b"a runner never committed").hexdigest()
        self.write_record(base)
        r = self.doctor([pair()])
        self.assertEqual(r.status, brain_doctor.FAIL)
        self.assertIn("committed", r.message)

    def test_ac36_two_baselines_fail(self):
        self.write_record(self.record("baseline", "claude", "opus",
                                      [run_counts(38, 2), run_counts(37, 1), run_counts(38, 3)]))
        self.assertEqual(self.doctor([pair()]).status, brain_doctor.FAIL)

    def test_not_allowed_pairs_need_no_record(self):
        p = pair(model="m9")
        p["status"] = "not-allowed"
        self.assertEqual(self.doctor([p]).status, brain_doctor.PASS)

    def test_ac35_qualify_sets_status_from_the_bound(self):
        self.write_record(self.record("candidate", "gemini", "g1",
                                      [run_counts(30, 0), run_counts(30, 0), run_counts(30, 0)],
                                      self.base))
        got = {(p["engine"], p["model"]): p["status"] for p in rr.qualify(self.root)}
        self.assertEqual(got, {("codex", "m1"): "allowed", ("gemini", "g1"): "not-allowed"})
        rr.write_pairs(self.root / rr.REVIEWERS_REL, rr.qualify(self.root))
        text = (self.root / rr.REVIEWERS_REL).read_text()
        self.assertIn("# Reviewer_Registry", text)    # the comments survive
        r = brain_doctor.check_reviewer_registry(False, self.root / rr.REVIEWERS_REL, self.root)
        self.assertEqual(r.status, brain_doctor.PASS, r.message)


class RunnerEndToEnd(RepoCase):
    """AC-31, AC-33, AC-34 through the CLI with a stub executable."""

    def setUp(self):
        super().setUp()
        self.stub = Path(self._tmp.name) / "stub-cli"
        self.stub.write_text(STUB.format(py=sys.executable), encoding="utf-8")
        self.stub.chmod(0o755)
        self.log = Path(self._tmp.name) / "calls.log"
        self.env = dict(os.environ, STUB_LOG=str(self.log),
                        STUB_FIXTURES=str(self.root / rr.FIXTURES_REL))

    def run_cli(self, *args, **env):
        cp = subprocess.run([sys.executable, str(SCRIPTS / "review_replay.py"), "run",
                             "--root", str(self.root), "--cli", str(self.stub), "--jobs", "8", *args],
                            capture_output=True, text=True, env=dict(self.env, **env), timeout=600)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        return cp

    def load(self, name):
        return json.loads((self.root / rr.RECORDS_REL / name).read_text())

    def test_ac34_baseline_on_fable_with_run_receipt(self):
        self.run_cli("--baseline")
        rec = self.load("claude-fable.json")
        self.assertEqual(rr.record_problems(rec), [])
        self.assertEqual((rec["role"], rec["model"], rec["baseline_model"]), ("baseline", "fable", "fable"))
        rcpt = rec["run_receipt"]
        self.assertEqual(rcpt["runner_sha256"], self.runner_sha)
        self.assertEqual(rcpt["fixture_tree"], self.tree)
        self.assertEqual(rcpt["model"], "fable")
        self.assertEqual(rcpt["runs"], rec["runs"])
        self.assertEqual(len(rec["runs"]), 3)
        self.assertEqual(rec["worst"]["catch_rate"], 1.0)
        self.assertEqual(rec["cli_version"], "stub-cli 9.9.9")
        self.assertEqual(rec["fixture_tree"], self.tree)
        self.assertNotIn("opus", self.log.read_text())
        # 1 probe + 3 runs of 80 cases.
        self.assertEqual(len(self.log.read_text().split()), 1 + 3 * len(CASES))

    def test_ac34_opus_only_when_fable_is_refused_for_quota(self):
        self.run_cli("--baseline", STUB_REFUSE="fable")
        self.assertFalse((self.root / rr.RECORDS_REL / "claude-fable.json").exists())
        rec = self.load("claude-opus.json")
        self.assertEqual(rec["model"], "opus")
        self.assertIn("quota or credits", rec["run_receipt"]["model_reason"])
        self.assertEqual(self.log.read_text().split().count("fable"), 1)

    def test_ac34_a_failure_that_is_not_a_refusal_keeps_fable(self):
        model, reason, _ = rr.choose_baseline_model(
            CASES, lambda m: (lambda p: {"status": "failed", "stdout": "", "stderr": "boom"}))
        self.assertEqual(model, "fable")

    def test_ac33_ac35_candidate_record_names_its_baseline_and_qualifies(self):
        self.run_cli("--baseline")
        self.run_cli("--engine", "codex", "--model", "m1")
        rec = self.load("codex-m1.json")
        self.assertEqual((rec["role"], rec["baseline_model"]), ("candidate", "fable"))
        self.assertTrue(rec["bound"]["holds"])
        self.run_cli("--engine", "gemini", "--model", "g1", STUB_MODE="sloppy")
        sloppy = self.load("gemini-g1.json")
        self.assertEqual((sloppy["worst"]["catch_rate"], sloppy["worst"]["false_alarm_rate"]), (0.0, 0.0))
        self.assertFalse(sloppy["bound"]["holds"])
        statuses = {p["model"]: p["status"] for p in rr.qualify(self.root)}
        self.assertEqual(statuses, {"m1": "allowed", "g1": "not-allowed"})

    def test_ac33_cli_timeout_and_failure_are_read_as_such(self):
        slow = Path(self._tmp.name) / "slow-cli"
        slow.write_text(f"#!{sys.executable}\nimport sys, time\n"
                        "time.sleep(5) if sys.argv[-1] == 'slow' else sys.exit(3)\n", encoding="utf-8")
        slow.chmod(0o755)
        call = rr.cli_caller("codex", str(slow), "m1", 0.5, self._tmp.name)
        self.assertEqual(call("slow")["status"], "timeout")
        self.assertEqual(call("fail")["status"], "failed")

    def test_candidate_needs_a_baseline(self):
        cp = subprocess.run([sys.executable, str(SCRIPTS / "review_replay.py"), "run", "--root",
                             str(self.root), "--cli", str(self.stub), "--engine", "codex",
                             "--model", "m1"], capture_output=True, text=True, env=self.env)
        self.assertEqual(cp.returncode, 2)
        self.assertIn("baseline", cp.stderr)

    def test_ac31_held_out_reaches_the_record_as_hash_and_counts_only(self):
        held = Path(self._tmp.name) / "private-held-out-dir"
        held.mkdir()
        secret = "Held-out reply line that must never reach a record."
        for i, (exp, extra) in enumerate((("PASS", {}), ("NEEDS-WORK", {
                "defect_class": "wrong-fact", "defect_line": secret}))):
            (held / f"h{i}.json").write_text(json.dumps(dict(
                {"id": f"h{i}", "expected": exp, "reply": secret,
                 "excerpts": [{"source": "held/secret-source.txt", "text": "held excerpt"}]}, **extra)))
        self.env["STUB_FIXTURES"] = str(held)
        # The stub reads one directory; point it at a merged copy.
        merged = Path(self._tmp.name) / "merged"
        shutil.copytree(self.root / rr.FIXTURES_REL, merged)
        for p in held.iterdir():
            shutil.copy2(p, merged / p.name)
        self.env["STUB_FIXTURES"] = str(merged)
        self.run_cli("--baseline", "--held-out", str(held))
        raw = (self.root / rr.RECORDS_REL / "claude-fable.json").read_text()
        rec = json.loads(raw)
        ho = rec["held_out"]
        self.assertEqual(ho["tree_sha256"], rr.sha256_tree(held))
        self.assertEqual(ho["counts"], {"needs_work": 1, "pass": 1})
        self.assertEqual(len(ho["runs"]), 3)
        for leak in (secret, "held/secret-source", "h0", "h1", str(held), held.name, "held excerpt"):
            self.assertNotIn(leak, raw)


class ArmingAndRegistration(unittest.TestCase):
    def test_ac37_fixture_dir_is_live_arming(self):
        fdir = ROOT / "registry" / "fixtures" / "ARCHITECTURE.arming-surface"
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("violation_surface_registry_replay_fixture.json",
                         "benign_surface_registry_replay_fixture.json"):
                shutil.copy2(fdir / name, Path(tmp) / name)
            cp = subprocess.run([sys.executable, str(SCRIPTS / "g__pretool__arming-surface.py"),
                                 "--selftest", tmp], capture_output=True, text=True, timeout=600)
            self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])

    def test_ac15_runner_and_checks_registered(self):
        import yaml
        rules = yaml.safe_load((ROOT / "registry" / "rules.yaml").read_text())["rules"]
        names = {m.get("canonical_name") for r in rules for m in r.get("mechanism") or []}
        self.assertIn("review_replay.py", names)
        locators = " ".join(p.get("locator", "") for r in rules for p in r.get("proof") or [])
        self.assertIn('("review-replay", check_review_replay)', locators)
        self.assertIn("scripts/review_replay.py --selftest", locators)
        self.assertIn("review-replay", dict(brain_doctor.CHECKS))

    def test_selftest_passes(self):
        cp = subprocess.run([sys.executable, str(SCRIPTS / "review_replay.py"), "--selftest"],
                            capture_output=True, text=True, cwd=str(ROOT), timeout=600)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
